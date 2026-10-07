import json
from pathlib import Path

import pytest

from financial_research.reports.bundle import export_bundle
from financial_research.reports.cli import main
from financial_research.reports.errors import ReportBundleWriteError, ReportIntegrityError
from financial_research.reports.identity import sha256
from financial_research.reports.rendering import render_markdown
from financial_research.reports.schemas import ResearchReport
from financial_research.reports.service import ReportWorkflowService
from financial_research.reports.validation import ReportBundleValidator

from .conftest import REQUEST


def test_export_four_files_hashes_rebuild_and_duplicate_failure(report_run, tmp_path):
    report = report_run[0].report
    path = export_bundle(report, tmp_path)
    before = {f.name: f.read_bytes() for f in path.iterdir()}
    assert set(before) == {"report.json", "report.md", "evidence.json", "manifest.json"}
    manifest = json.loads(before["manifest.json"])
    assert manifest["file_hashes"] == {
        name: sha256(data) for name, data in before.items() if name != "manifest.json"
    }
    parsed = ReportBundleValidator().validate_directory(path)
    assert parsed == ResearchReport.model_validate_json(before["report.json"]) == report
    assert render_markdown(parsed).encode() == before["report.md"]
    with pytest.raises(ReportBundleWriteError, match="BUNDLE_ALREADY_EXISTS"):
        export_bundle(report, tmp_path)
    assert before == {f.name: f.read_bytes() for f in path.iterdir()}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("name", ["report.json", "report.md", "evidence.json", "manifest.json"])
def test_corrupt_bundle_files_cannot_pass_integrity(report_run, tmp_path, name):
    path = export_bundle(report_run[0].report, tmp_path)
    file = path / name
    if name == "report.md":
        file.write_text(file.read_text() + "\nUnsupported new report claim [E999][C999].\n")
    else:
        data = json.loads(file.read_text())
        data["report_id"] = "report:" + "1" * 64
        file.write_text(json.dumps(data))
    with pytest.raises(ReportIntegrityError):
        ReportBundleValidator().validate_directory(path)


def test_even_harmless_whitespace_tampering_breaks_file_hash(report_run, tmp_path):
    path = export_bundle(report_run[0].report, tmp_path)
    with (path / "report.json").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ReportIntegrityError, match="FILE_HASH_MISMATCH"):
        ReportBundleValidator().validate_directory(path)


def test_failed_staging_validation_removes_partial_output(report_run, tmp_path, monkeypatch):
    def fail(*args):
        raise ReportIntegrityError("TEST_VALIDATION_FAILURE")

    monkeypatch.setattr(ReportBundleValidator, "validate_directory", fail)
    with pytest.raises(ReportIntegrityError, match="TEST_VALIDATION_FAILURE"):
        export_bundle(report_run[0].report, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_failed_file_write_is_typed_and_leaves_no_bundle(report_run, tmp_path, monkeypatch):
    original = Path.write_bytes

    def fail_evidence(path, data):
        if path.name == "evidence.json":
            raise OSError("__PRIVATE_PATH_SECRET__")
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_evidence)
    with pytest.raises(ReportBundleWriteError, match="BUNDLE_WRITE_FAILED") as failure:
        export_bundle(report_run[0].report, tmp_path)
    assert "__PRIVATE_PATH_SECRET__" not in str(failure.value)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("blocked", [False, True])
def test_cli_normal_and_blocked_outputs_valid_bundle(
    report_agent_factory, nvda_context, tmp_path, capsys, blocked
):
    agent, llm, _ = report_agent_factory(context=nvda_context if blocked else None)
    code = main(
        [
            "--ticker",
            "NVDA",
            "--as-of-date",
            "2025-05-25",
            "--language",
            "ENGLISH",
            "--output-dir",
            str(tmp_path),
        ],
        service=ReportWorkflowService(agent),
    )
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    report = ReportBundleValidator().validate_directory(Path(output["bundle_path"]))
    assert report.status == ("BLOCKED" if blocked else "COMPLETED_WITH_WARNINGS")
    assert output["planner_calls"] == 0 and llm.call_count == (0 if blocked else 1)
    assert output["bundle_integrity"] == "PASS"


def test_security_sentinels_absent_from_all_files_and_cli(
    report_agent_factory,
    provider_payloads,
    fixture_builder,
    fiscal_context,
    tmp_path,
    monkeypatch,
    capsys,
):
    secret, contact, raw = "__KEY_SENTINEL__", "__CONTACT_SENTINEL__", "__RAW_PROVIDER_SENTINEL__"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("SEC_USER_AGENT", contact)
    monkeypatch.setenv("ENV_CONTENT_SENTINEL", "__ENV_SENTINEL__")
    # These dictionaries are consumed by real provider adapters in the inherited fixture.
    for payload in provider_payloads.values():
        payload["raw_only_secret"] = raw
    (tmp_path / ".env").write_text("PRIVATE_ENV=__ENV_SENTINEL__")
    rebuilt = fixture_builder.build(ticker=REQUEST.ticker, as_of_date=REQUEST.as_of_date)
    context = fiscal_context.model_copy(
        update={"company": rebuilt.company, "market": rebuilt.market}
    )
    agent, _, _ = report_agent_factory(context=context)
    assert (
        main(
            [
                "--ticker",
                "NVDA",
                "--as-of-date",
                str(REQUEST.as_of_date),
                "--output-dir",
                str(tmp_path),
            ],
            service=ReportWorkflowService(agent),
        )
        == 0
    )
    out = capsys.readouterr()
    path = Path(json.loads(out.out)["bundle_path"])
    all_text = out.out + out.err + "".join(file.read_text() for file in path.iterdir())
    for forbidden in (
        secret,
        contact,
        raw,
        "__ENV_SENTINEL__",
        "OPENAI_API_KEY",
        "SEC_USER_AGENT",
        "system_prompt",
        "user_payload",
        "chain_of_thought",
    ):
        assert forbidden not in all_text


def test_cli_sanitizes_domain_errors(report_agent_factory, tmp_path, capsys, monkeypatch):
    agent, _, _ = report_agent_factory()
    service = ReportWorkflowService(agent)

    def fail(request):
        raise ReportIntegrityError("__SECRET_MESSAGE__")

    monkeypatch.setattr(service, "run", fail)
    assert main(["--ticker", "NVDA", "--as-of-date", str(REQUEST.as_of_date)], service=service) == 1
    out = capsys.readouterr()
    assert "__SECRET_MESSAGE__" not in out.err and "ReportIntegrityError" in out.err
