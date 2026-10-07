"""Bilingual Markdown rendered exclusively from the validated public projection."""

from financial_research.public_research.schemas import PublicResearchReport
from financial_research.reports.rendering import HEADINGS, _cell
from financial_research.reports.schemas import ReportSectionID, ReportStatus
from financial_research.schemas.agent import ResponseLanguage


def render_public_markdown(report: PublicResearchReport) -> str:
    chinese = report.language == ResponseLanguage.CHINESE

    def label(english: str, chinese_text: str) -> str:
        return chinese_text if chinese else english

    aliases = {entry.canonical_id: entry.display_alias for entry in report.evidence_appendix}
    calc_aliases = {
        entry.canonical_id: entry.display_alias for entry in report.calculation_appendix
    }
    lines = [
        "# " + label("Equity Research Report", "股票研究报告"),
        "",
        f"**{report.ticker} · {report.as_of_date}**",
        "",
        f"{label('Report Status', '报告状态')}: **{report.status}**  ",
        f"{label('Research Quality', '研究质量')}: **{report.quality_status}**  ",
        f"{label('Synthesis Readiness', '综合就绪状态')}: **{report.synthesis_readiness}**",
    ]
    if report.quality.issues:
        lines.extend(("", "**" + label("Quality diagnostics", "质量诊断") + "**"))
        lines.extend(
            f"- {issue.severity}: {issue.code}: {issue.message}" for issue in report.quality.issues
        )
    for section in report.sections:
        key = section.section_id
        lines.extend(("", "## " + HEADINGS[key][int(chinese)], ""))
        if key == ReportSectionID.SCOPE:
            lines.extend(
                (
                    label(
                        "Research is restricted to information available under the existing "
                        "point-in-time rules as of the requested date.",
                        "本研究仅使用按照现有时点（PIT）规则，在指定研究日期之前已经可获得的信息。",
                    ),
                    "",
                    f"{label('As-of date', '研究日期')}: {report.as_of_date}  ",
                    f"{label('Workflow', '工作流程')}: "
                    f"BROAD_RESEARCH / {report.selected_skill_id}  ",
                    label(
                        "Filing dates and availability dates are distinct. Fundamental "
                        "availability uses the first observed trading session after filing.",
                        "申报日期与可用日期分别记录；基本面数据在申报后的首个已观察交易日可用。",
                    ),
                )
            )
        for claim in section.claims:
            citations = "".join(f"[{aliases[key]}]" for key in claim.evidence_ids)
            citations += "".join(
                f"[{calc_aliases[key]}]" for key in claim.evidence_ids if key in calc_aliases
            )
            lines.append(f"- {claim.statement} {citations}")
        if key == ReportSectionID.QUALITY:
            lines.append(f"{label('Quality', '质量')}: {report.quality_status}")
            lines.extend(
                f"- {issue.severity}: {issue.code}: {issue.message}"
                for issue in report.quality.issues
            )
            if report.status == ReportStatus.BLOCKED:
                lines.extend(("", "### " + label("Blocking Reasons", "阻塞原因"), ""))
                lines.extend(f"- {reason}" for reason in report.blocking_reasons)
        elif key == ReportSectionID.LIMITATIONS:
            lines.extend(f"- {limitation}" for limitation in report.limitations)
        elif key == ReportSectionID.EVIDENCE:
            lines.append(
                label(
                    "Aliases are presentation references; canonical IDs remain authoritative. "
                    "— means metadata was not supplied.",
                    "别名仅用于展示，规范 ID 保持不变。— 表示未提供相应元数据。",
                )
            )
            for entry in report.evidence_appendix:
                ref = entry.evidence
                lines.extend(
                    (
                        "",
                        f"### {entry.display_alias}",
                        "",
                        "| " + label("Field | Value", "字段 | 值") + " |",
                        "| --- | --- |",
                    )
                )
                for field, value in (
                    ("canonical_id", entry.canonical_id),
                    ("kind", ref.kind),
                    ("disclosure", ref.disclosure),
                    ("observation_count", ref.observation_count),
                    ("input_range_start", ref.input_range_start),
                    ("input_range_end", ref.input_range_end),
                    ("internal_input_digest", ref.internal_input_digest),
                    ("metric", ref.metric),
                    ("value", ref.value),
                    ("unit", ref.unit),
                    ("date", ref.date),
                    ("period_start", ref.period_start),
                    ("period_end", ref.period_end),
                    ("provider", ref.provider),
                    ("source_reference", ref.source_reference),
                    ("filed_at", ref.filed_at),
                    ("available_date", ref.available_date),
                    ("data_vintage", ref.data_vintage),
                    ("transformation", "; ".join(ref.transformation)),
                ):
                    lines.append(f"| {field} | {_cell(value)} |")
        elif key == ReportSectionID.CALCULATIONS:
            for calculation_entry in report.calculation_appendix:
                calc = calculation_entry.provenance
                lines.extend(("", f"### {calculation_entry.display_alias}", ""))
                for calc_field, calc_value in (
                    ("canonical_id", calculation_entry.canonical_id),
                    ("operation", calc.calculation_name),
                    ("formula", calc.formula),
                    ("metric", calc.metric),
                    ("methodology", calc.methodology),
                    ("input_count", calc.input_summary.input_count),
                    ("withheld_market_input_count", calc.input_summary.withheld_market_input_count),
                    ("input_range_start", calc.input_summary.input_range_start),
                    ("input_range_end", calc.input_summary.input_range_end),
                    ("input_kind", calc.input_summary.input_kind),
                    ("input_metrics", "; ".join(calc.input_summary.input_metrics)),
                    ("internal_input_digest", calc.input_summary.internal_input_digest),
                    ("result", calculation_entry.result),
                    ("unit", calculation_entry.result_unit),
                    ("date", calculation_entry.date),
                    ("period_start", calculation_entry.period_start),
                    ("period_end", calculation_entry.period_end),
                    ("result_evidence", f"[{aliases[calculation_entry.canonical_id]}]"),
                ):
                    lines.append(f"- {calc_field}: {_cell(calc_value)}")
                lines.append("- inputs:")
                lines.extend(
                    f"  - [{alias}] `{key}`"
                    for key, alias in zip(
                        calc.input_evidence_ids,
                        calculation_entry.input_display_aliases,
                        strict=True,
                    )
                )
                lines.extend(f"- parameter: {p.name} = {_cell(p.value)}" for p in calc.parameters)
        elif key == ReportSectionID.AUDIT:
            runtime = report.runtime_metadata
            for audit_field, audit_value in (
                ("report_version", report.report_version),
                ("projection_version", report.projection_version),
                ("integrity_scope", report.integrity_scope),
                ("report_id", report.report_id),
                ("run_id", report.run_id),
                ("ticker", report.ticker),
                ("as_of_date", report.as_of_date),
                ("language", report.language),
                ("selected_skill_id", report.selected_skill_id),
                ("plan_version", runtime.plan_version),
                ("planner_used", "false"),
                ("planner_call_count", runtime.planner_call_count),
                ("synthesis_call_count", runtime.synthesis_call_count),
                ("repair_count", runtime.repair_count),
                ("claim_count", sum(len(section.claims) for section in report.sections)),
                ("evidence_count", len(report.evidence_appendix)),
                ("calculation_count", len(report.calculation_appendix)),
                ("provider", runtime.provider),
                ("model", runtime.model),
                ("synthesis_prompt_version", runtime.synthesis_prompt_version),
                ("report_compiler_version", runtime.report_compiler_version),
                ("created_at", runtime.created_at.isoformat()),
                ("internal_research_semantic_hash", report.integrity.semantic_hash),
            ):
                lines.append(f"- {audit_field}: {_cell(audit_value)}")
    return "\n".join(lines) + "\n"
