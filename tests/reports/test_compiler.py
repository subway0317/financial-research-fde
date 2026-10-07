from datetime import timedelta
from uuid import uuid4

import pytest

from financial_research.reports.compiler import ReportCompiler
from financial_research.reports.errors import ReportCompilationError, ReportIntegrityError
from financial_research.reports.identity import semantic_hash
from financial_research.reports.rendering import render_markdown
from financial_research.reports.schemas import ReportIntegrity
from financial_research.reports.service import ReportWorkflowService
from financial_research.reports.validation import validate_report
from financial_research.schemas.tools import CalculationProvenance

from .conftest import REQUEST


def compile_answer(answer, report):
    return ReportCompiler().compile(
        answer,
        run_id=report.run_id,
        created_at=report.runtime_metadata.created_at,
        provider="fake",
        model="scripted",
    )


def rehash(report):
    digest = semantic_hash(report)
    return report.model_copy(
        update={"report_id": f"report:{digest}", "integrity": ReportIntegrity(semantic_hash=digest)}
    )


def test_claims_limitations_provenance_are_lossless_and_compiler_does_no_work(report_run):
    response, answer, llm, builder = report_run
    before = answer.model_dump_json()
    report = compile_answer(answer, response.report)
    claims = tuple(claim for section in report.sections for claim in section.claims)
    assert {claim.claim_id: claim for claim in claims} == {
        claim.claim_id: claim for claim in answer.claims
    }
    assert "Revenue increased from 100 to 150." in render_markdown(report)
    assert report.limitations == answer.limitations and report.quality == answer.quality
    assert report.blocking_reasons == answer.unavailable_context
    for entry in report.evidence_appendix:
        assert entry.evidence == answer.citations[entry.canonical_id]
    for entry in report.calculation_appendix:
        assert entry.provenance in answer.calculation_provenance
        assert entry.result == answer.citations[entry.canonical_id].value
    assert answer.model_dump_json() == before
    assert llm.call_count == builder.calls == 1
    assert report == response.report
    assert render_markdown(report) == response.markdown


def test_report_semantic_id_excludes_run_timestamps_tokens_latency_trace(report_run):
    response, answer, _, _ = report_run
    first = response.report
    usage = answer.llm_usage[0].model_copy(
        update={"latency_ms": 999, "input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200}
    )
    changed = answer.model_copy(update={"llm_usage": (usage,)})
    second = ReportCompiler().compile(
        changed,
        run_id=uuid4(),
        created_at=first.runtime_metadata.created_at + timedelta(days=1),
        provider="fake",
        model="scripted",
    )
    assert second.report_id == first.report_id and second.integrity == first.integrity
    assert second.run_id != first.run_id and second.runtime_metadata != first.runtime_metadata
    assert semantic_hash(second) == semantic_hash(first)


@pytest.mark.parametrize(
    "changed_field", ["statement", "evidence", "limitations", "quality", "language"]
)
def test_semantic_content_changes_report_id(report_run, changed_field):
    response, answer, _, _ = report_run
    if changed_field == "statement":
        claim = answer.claims[0].model_copy(
            update={"statement": "The supplied identifier remains NVDA."}
        )
        answer = answer.model_copy(update={"claims": (claim, *answer.claims[1:])})
    elif changed_field == "evidence":
        key = answer.claims[0].evidence_ids[0]
        refs = {
            **answer.citations,
            key: answer.citations[key].model_copy(update={"data_vintage": "different-vintage"}),
        }
        answer = answer.model_copy(update={"citations": refs})
    elif changed_field == "limitations":
        answer = answer.model_copy(
            update={"limitations": (*answer.limitations, "NEW_CANONICAL_LIMITATION")}
        )
    elif changed_field == "quality":
        issue = answer.quality.issues[0].model_copy(
            update={"message": "Different canonical diagnostic."}
        )
        answer = answer.model_copy(
            update={
                "quality": answer.quality.model_copy(
                    update={"issues": (issue, *answer.quality.issues[1:])}
                )
            }
        )
    else:
        # The compiler preserves statements; production language validation lives in Agent.
        answer = answer.model_copy(update={"response_language": "CHINESE"})
    assert compile_answer(answer, response.report).report_id != response.report.report_id


def test_canonical_alias_mapping_ignores_input_dictionary_order(report_run):
    response, answer, _, _ = report_run
    reordered = answer.model_copy(
        update={
            "citations": dict(reversed(list(answer.citations.items()))),
            "calculation_provenance": tuple(reversed(answer.calculation_provenance)),
        }
    )
    assert compile_answer(reordered, response.report) == response.report
    assert [entry.canonical_id for entry in response.report.evidence_appendix] == sorted(
        entry.canonical_id for entry in response.report.evidence_appendix
    )
    assert len(response.report.evidence_appendix) < len(answer.citations)


@pytest.mark.parametrize("language", ["ENGLISH", "CHINESE"])
def test_all_fixed_bilingual_headings_and_claims_preserved(report_agent_factory, language):
    agent, _, _ = report_agent_factory()
    response = ReportWorkflowService(agent).run(
        REQUEST.model_copy(update={"response_language": language})
    )
    headings = (
        [
            "股票研究报告",
            "研究范围",
            "公司概况",
            "基本面",
            "市场表现",
            "数据质量",
            "限制",
            "证据附录",
            "计算附录",
            "审计信息",
        ]
        if language == "CHINESE"
        else [
            "Equity Research Report",
            "Research Scope",
            "Company",
            "Fundamentals",
            "Market Behavior",
            "Data Quality",
            "Limitations",
            "Evidence Appendix",
            "Calculation Appendix",
            "Audit Metadata",
        ]
    )
    positions = [response.markdown.index("# " + headings[0])]
    positions.extend(response.markdown.index("## " + heading) for heading in headings[1:])
    assert positions == sorted(positions)
    for claim in agent.last_answer.claims:
        assert claim.statement in response.markdown
    for limitation in agent.last_answer.limitations:
        assert limitation in response.markdown
    assert "filed_at" in response.markdown and "available_date" in response.markdown
    assert "data_vintage" in response.markdown and "provider" in response.markdown


@pytest.mark.parametrize(
    "kind",
    ["missing_calc", "missing_input", "wrong_evidence_id", "duplicate_calc", "planned_answer"],
)
def test_compiler_rejects_invalid_validated_looking_inputs(report_run, kind):
    response, answer, _, _ = report_run
    cited = next(
        claim.evidence_ids[0] for claim in answer.claims if claim.claim_type == "COMPUTED_FACT"
    )
    if kind == "missing_calc":
        answer = answer.model_copy(
            update={
                "calculation_provenance": tuple(
                    calc for calc in answer.calculation_provenance if calc.evidence_id != cited
                )
            }
        )
    elif kind == "duplicate_calc":
        answer = answer.model_copy(
            update={
                "calculation_provenance": (
                    *answer.calculation_provenance,
                    answer.calculation_provenance[0],
                )
            }
        )
    elif kind == "missing_input":
        calc = next(calc for calc in answer.calculation_provenance if calc.evidence_id == cited)
        answer = answer.model_copy(
            update={
                "citations": {
                    key: ref
                    for key, ref in answer.citations.items()
                    if key != calc.input_evidence_ids[0]
                }
            }
        )
    elif kind == "wrong_evidence_id":
        refs = {
            **answer.citations,
            cited: answer.citations[cited].model_copy(update={"evidence_id": "wrong-id"}),
        }
        answer = answer.model_copy(update={"citations": refs})
    else:
        answer = answer.model_copy(update={"planner_prompt_version": "stage5-planner-v1"})
    with pytest.raises((ReportCompilationError, ReportIntegrityError)):
        compile_answer(answer, response.report)


def test_report_validator_rejects_future_pit_evidence_even_after_rehash(report_run):
    report = report_run[0].report
    original = next(
        entry for entry in report.evidence_appendix if entry.evidence.kind == "SOURCE_FACT"
    )
    replacement = original.model_copy(
        update={
            "evidence": original.evidence.model_copy(
                update={"available_date": report.as_of_date + timedelta(days=1)}
            )
        }
    )
    changed = report.model_copy(
        update={
            "evidence_appendix": tuple(
                replacement if entry == original else entry for entry in report.evidence_appendix
            )
        }
    )
    with pytest.raises(ReportIntegrityError, match="PIT_VIOLATION"):
        validate_report(rehash(changed))


def test_validator_rejects_claim_id_alias_and_input_corruption(report_run):
    report = report_run[0].report
    section = next(s for s in report.sections if s.claims)
    duplicate = section.model_copy(update={"claims": (*section.claims, section.claims[0])})
    bad_claims = report.model_copy(
        update={"sections": tuple(duplicate if s == section else s for s in report.sections)}
    )
    entry = report.evidence_appendix[0].model_copy(update={"display_alias": "E999"})
    bad_alias = report.model_copy(
        update={"evidence_appendix": (entry, *report.evidence_appendix[1:])}
    )
    calc = report.calculation_appendix[0].model_copy(update={"input_display_aliases": ("E999",)})
    bad_inputs = report.model_copy(
        update={"calculation_appendix": (calc, *report.calculation_appendix[1:])}
    )
    for invalid in (bad_claims, bad_alias, bad_inputs):
        with pytest.raises(ReportIntegrityError):
            validate_report(rehash(invalid))


def test_compiler_displays_existing_result_without_recalculating(report_run):
    response, answer, _, _ = report_run
    key = next(
        claim.evidence_ids[0] for claim in answer.claims if claim.claim_type == "COMPUTED_FACT"
    )
    ref = answer.citations[key].model_copy(update={"value": "777.123456789"})
    changed = answer.model_copy(update={"citations": {**answer.citations, key: ref}})
    report = compile_answer(changed, response.report)
    entry = next(entry for entry in report.calculation_appendix if entry.canonical_id == key)
    assert entry.result == "777.123456789"
    assert "777.123456789" in render_markdown(report)


def test_transitive_computation_inputs_are_included_without_financial_arithmetic(report_run):
    response, answer, _, _ = report_run
    child = next(
        claim.evidence_ids[0] for claim in answer.claims if claim.claim_type == "COMPUTED_FACT"
    )
    parent = "computation:fixture-parent"
    ref = answer.citations[child].model_copy(update={"evidence_id": parent, "value": "123456"})
    provenance = CalculationProvenance(
        evidence_id=parent,
        calculation_name="fixture-operation",
        formula="fixture: already computed",
        input_evidence_ids=(child,),
    )
    claim = next(claim for claim in answer.claims if claim.claim_type == "COMPUTED_FACT")
    changed_claim = claim.model_copy(update={"evidence_ids": (parent,)})
    changed = answer.model_copy(
        update={
            "citations": {**answer.citations, parent: ref},
            "calculation_provenance": (*answer.calculation_provenance, provenance),
            "claims": tuple(
                changed_claim if original == claim else original for original in answer.claims
            ),
        }
    )
    report = compile_answer(changed, response.report)
    assert {entry.canonical_id for entry in report.calculation_appendix} == {parent, child}
    parent_entry = next(
        entry for entry in report.calculation_appendix if entry.canonical_id == parent
    )
    child_entry = next(entry for entry in report.evidence_appendix if entry.canonical_id == child)
    assert parent_entry.input_display_aliases == (child_entry.display_alias,)
    assert parent_entry.result == "123456"


def test_cyclic_computation_input_is_rejected_with_typed_error(report_run):
    response, answer, _, _ = report_run
    key = next(
        claim.evidence_ids[0] for claim in answer.claims if claim.claim_type == "COMPUTED_FACT"
    )
    original = next(calc for calc in answer.calculation_provenance if calc.evidence_id == key)
    bad = original.model_copy(update={"input_evidence_ids": (key,)})
    changed = answer.model_copy(
        update={
            "calculation_provenance": tuple(
                bad if calc == original else calc for calc in answer.calculation_provenance
            )
        }
    )
    with pytest.raises(ReportIntegrityError, match="CYCLIC_CALCULATION"):
        compile_answer(changed, response.report)
