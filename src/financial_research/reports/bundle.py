"""Stage, validate and finalize four-file bundles without replacing existing runs."""

import os
import shutil
import tempfile
from pathlib import Path

from financial_research.reports.errors import ReportBundleWriteError
from financial_research.reports.identity import canonical_bytes, sha256
from financial_research.reports.manifest import build_manifest, evidence_artifact
from financial_research.reports.rendering import render_markdown
from financial_research.reports.schemas import ReportFileHashes, ResearchReport
from financial_research.reports.validation import ReportBundleValidator, validate_report


def export_bundle(report: ResearchReport, output_dir: Path = Path("artifacts/reports")) -> Path:
    validate_report(report)
    evidence = evidence_artifact(report)
    markdown = render_markdown(report)
    manifest = build_manifest(report)
    validator = ReportBundleValidator()
    validator.validate(report, markdown, evidence, manifest)
    contents = {
        "report.json": canonical_bytes(report.model_dump(mode="json")) + b"\n",
        "report.md": markdown.encode("utf-8"),
        "evidence.json": canonical_bytes(evidence.model_dump(mode="json")) + b"\n",
    }
    manifest = manifest.model_copy(
        update={
            "file_hashes": ReportFileHashes.model_validate(
                {name: sha256(data) for name, data in contents.items()}
            )
        }
    )
    contents["manifest.json"] = (
        canonical_bytes(manifest.model_dump(mode="json", by_alias=True)) + b"\n"
    )
    staging: Path | None = None
    reserved: Path | None = None
    destination = output_dir / str(report.run_id)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        # Exclusive sibling reservation prevents concurrent writers of the same run.
        reserved_path = output_dir / f".{report.run_id}.lock"
        descriptor = os.open(reserved_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        reserved = reserved_path
        os.close(descriptor)
        if destination.exists() or destination.is_symlink():
            raise ReportBundleWriteError("BUNDLE_ALREADY_EXISTS")
        staging = Path(tempfile.mkdtemp(prefix=f".{report.run_id}.", dir=output_dir))
        for name, data in contents.items():
            (staging / name).write_bytes(data)
        validator.validate_directory(staging)
        # Same-filesystem rename publishes only the fully validated directory.
        staging.rename(destination)
        staging = None
        return destination
    except OSError:
        raise ReportBundleWriteError("BUNDLE_WRITE_FAILED") from None
    finally:
        if staging is not None:
            shutil.rmtree(staging)
        if reserved is not None:
            reserved.unlink()
