"""Canonical UTF-8 serialization and semantic identity, without runtime fields."""

import hashlib
import json

from financial_research.reports.schemas import ResearchReport


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def semantic_hash(report: ResearchReport) -> str:
    return sha256(
        canonical_bytes(
            report.model_dump(
                mode="json", exclude={"report_id", "run_id", "runtime_metadata", "integrity"}
            )
        )
    )
