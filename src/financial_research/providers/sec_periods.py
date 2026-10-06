"""Conservative SEC fiscal labels corroborated by a filing's report date.

Companyfacts fy/fp label the filing context, not every comparative fact. Only
primary report-date facts receive that filing's labels. Historical comparative
rows and YTD durations remain unlabeled; no calendar-frame-to-fiscal conversion.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from financial_research.exceptions import DataValidationError
from financial_research.providers.http import JsonResponse, JsonTransport
from financial_research.schemas.periods import FiscalPeriod, PeriodFrequency


@dataclass(frozen=True)
class FilingMetadata:
    report_date: date
    filed_at: date
    form: str
    source_reference: str
    data_vintage: str


def filing_metadata(
    transport: JsonTransport, cik: str, start: date, end: date
) -> dict[str, FilingMetadata]:
    response = transport.get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    try:
        if str(response.payload["cik"]).zfill(10) != cik:
            raise ValueError("submissions CIK mismatch")
        filings = response.payload["filings"]
        records = _filing_rows(filings["recent"], response, start, end)
        files = filings.get("files", [])
        if not isinstance(files, list):
            raise ValueError("invalid submissions archive index")
        # Retrieve only archives overlapping the explicit requested filing scope.
        relevant = []
        for archive in files:
            first = date.fromisoformat(archive["filingFrom"])
            last = date.fromisoformat(archive["filingTo"])
            if first > last:
                raise ValueError("invalid submissions archive chronology")
            if first <= end and last >= start:
                name = archive["name"]
                if not re.fullmatch(rf"CIK{cik}-submissions-[0-9]+\.json", name):
                    raise ValueError("invalid submissions archive filename")
                relevant.append(name)
        if len(relevant) > 20:
            raise ValueError("filing scope requires more than 20 metadata archives")
        for name in sorted(set(relevant)):
            archived = transport.get(f"https://data.sec.gov/submissions/{name}")
            for accession, record in _filing_rows(archived.payload, archived, start, end).items():
                previous = records.get(accession)
                if previous and (previous.report_date, previous.filed_at, previous.form) != (
                    record.report_date,
                    record.filed_at,
                    record.form,
                ):
                    raise ValueError("conflicting submission metadata for one accession")
                records.setdefault(accession, record)
        return records
    except (KeyError, TypeError, ValueError) as exc:
        raise DataValidationError("SEC submissions failed fiscal metadata normalization") from exc


def _filing_rows(
    payload: dict[str, Any], response: JsonResponse, start: date, end: date
) -> dict[str, FilingMetadata]:
    columns = [payload[key] for key in ("accessionNumber", "reportDate", "filingDate", "form")]
    if (
        any(not isinstance(column, list) for column in columns)
        or len({len(column) for column in columns}) != 1
    ):
        raise ValueError("invalid submissions column lengths")
    records: dict[str, FilingMetadata] = {}
    for accession, report, filed, form in zip(*columns, strict=True):
        filed_at = date.fromisoformat(filed)
        if not start <= filed_at <= end or form not in {"10-Q", "10-K", "10-Q/A", "10-K/A"}:
            continue
        if not report:
            continue  # Explicitly absent report dates cannot establish a fiscal label.
        report_date = date.fromisoformat(report)
        if report_date > filed_at:
            raise ValueError("submission report date exceeds filing date")
        record = FilingMetadata(
            report_date=report_date,
            filed_at=filed_at,
            form=form,
            source_reference=f"{response.provenance.source_reference}#{accession}",
            data_vintage=response.provenance.data_vintage,
        )
        previous = records.get(accession)
        if previous is not None and previous != record:
            raise ValueError("conflicting submission metadata")
        records[accession] = record
    return records


def corroborated_period(
    row: dict[str, Any], filings: dict[str, FilingMetadata]
) -> FiscalPeriod | None:
    filing = filings.get(row["accn"])
    if filing is None or (
        date.fromisoformat(row["end"]) != filing.report_date
        or date.fromisoformat(row["filed"]) != filing.filed_at
        or row["form"] != filing.form
    ):
        return None
    year, label = row.get("fy"), row.get("fp")
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
        return None
    if label == "FY" and filing.form in {"10-K", "10-K/A"}:
        frequency, quarter, bounds = PeriodFrequency.ANNUAL, None, (330, 400)
    elif label in {"Q1", "Q2", "Q3", "Q4"} and filing.form in {"10-Q", "10-Q/A"}:
        frequency, quarter, bounds = PeriodFrequency.QUARTERLY, int(label[1]), (70, 110)
    else:
        return None
    if row.get("start") is not None:
        duration = (filing.report_date - date.fromisoformat(row["start"])).days + 1
        if not bounds[0] <= duration <= bounds[1]:
            return None
    return FiscalPeriod(
        frequency=frequency,
        fiscal_year=year,
        fiscal_quarter=quarter,
        source_reference=f"{filing.source_reference};vintage={filing.data_vintage}",
    )
