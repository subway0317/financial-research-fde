# Financial Research FDE

Financial Research FDE Platform provides reliable financial data, daily point-in-time
(PIT) selection, deterministic calculations, structured provenance, data quality,
and reproducible research contexts. FDE Stage 1 — Deterministic Research Core takes
an explicit ticker and as-of date and builds a typed `ResearchContext`.

This project is **not a demonstrated alpha-generating stock predictor**. Earlier
Quant research found no robust multi-year predictive signal from Relative Market +
OLS/Ridge, and no robust incremental predictive value from the registered PIT
fundamentals. Those negative results stand. Relative SMA here is a representation
choice, not a predictive-performance claim.

## Setup and verification

Requires Python **>=3.12**. Local verification used the existing Python **3.14.4**
virtual environment. CI is configured for Python 3.12 and 3.14; CI execution itself
is verified by GitHub after a push, not by this local implementation.

On a new machine:

```bash
git clone git@github.com:subway0317/financial-research-fde.git
cd financial-research-fde
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src/financial_research
```

For the existing development environment, activate `.venv` and install; do not
recreate it. `pyproject.toml` is the center for dependencies and tooling. Runtime
uses only Pydantic and HTTPX; calculations use Python's standard library. No
Poetry, Conda, uv, dataframe contract or database server is required.

The default test suite is fully offline. Tests use small synthetic JSON fixtures
and `httpx.MockTransport`, and an autouse fixture blocks socket connections. NVDA
is the verified end-to-end fixture target; a second ticker verifies generic core
behavior. All fixture values/filings are synthetic and documented in
[tests/fixtures/README.md](tests/fixtures/README.md).

There are **no live smoke tests** in this release. The `live` marker is registered
and excluded by default (`-m "not live"`). Future live tests must be explicitly
opted into with `pytest -m live`; CI uses the offline default.

## Capability architecture

```text
External source
  -> providers (transport + source normalization)
  -> schemas (validated canonical contracts)
  -> company / market / fundamentals services
  -> research.ResearchContextBuilder
  -> ResearchContext + structured quality + provenance
```

- `schemas/`: frozen Pydantic models, extra fields forbidden, finite required
  numeric values, timezone-aware acquisition timestamps, OHLC/period validation.
- `providers/base.py`: structural protocols returning canonical models. SEC/Yahoo
  JSON exists only inside provider adapters. A replacement provider implements
  the same protocols; services and features do not change.
- `company/service.py`: resolves canonical ticker and stable ten-digit CIK.
- `market/`: validated daily market data and the seven registered features.
- `fundamentals/`: provider-independent metric registry, pure PIT engine and
  canonical fundamental service.
- `quality/checks.py`: deterministic diagnostics; no imputation or chronology repair.
- `research/context.py`: orchestration and provenance assembly; no source parsing.

`providers/http.py`, `sec_concepts.py`, `sec_facts.py`, and `schemas/base.py` are
small supporting modules separating transport, alias mapping, normalization and
shared validation. There are no stage-numbered runtime modules. Neither source
code nor fixtures import or read the old Quant repository.

## Building a research context

Services and providers are explicit dependencies. The builder has no implicit
network provider, credentials or global state. An offline caller can inject
providers that return canonical schemas; integration tests exercise real adapters
against provider-shaped fixtures.

The following is an **opt-in live network example** (not needed to run tests):

```bash
export SEC_USER_AGENT="Your Organization your-name your-email@example.com"
```

```python
from datetime import date

from financial_research.company.service import CompanyService
from financial_research.config import ResearchConfig
from financial_research.fundamentals.service import FundamentalService
from financial_research.market.service import MarketService
from financial_research.providers.market import YahooMarketProvider
from financial_research.providers.sec import SECProvider
from financial_research.research import ResearchContextBuilder

config = ResearchConfig.from_env()
if not config.sec_user_agent:
    raise RuntimeError("Set SEC_USER_AGENT with your organization and contact email")

sec = SECProvider(user_agent=config.sec_user_agent, timeout=config.http_timeout_seconds)
market = YahooMarketProvider(timeout=config.http_timeout_seconds)
try:
    builder = ResearchContextBuilder(
        company_service=CompanyService(sec),
        market_service=MarketService(market),
        fundamental_service=FundamentalService(sec),
        config=config,
    )
    context = builder.build(ticker="NVDA", as_of_date=date(2026, 6, 30))
    print(context.quality.status)
    print(context.model_dump_json(indent=2))
finally:
    market.close()
    sec.close()
```

`ResearchConfig.from_env()` reads the explicitly exported environment variables;
`.env.example` is a template, not an automatically loaded configuration file.
Client ownership is explicit: adapters close clients they create, while callers
close injected HTTPX clients. Logs use standard `logging` for requests,
normalization, builds and quality results, without raw payloads or credentials.

## Daily PIT semantics

`as_of_date` means research state **at the end of that calendar date**:

- Market observations must be on/before that date. On weekends, the latest
  preceding observed session supplies the latest market state.
- `period_end`, `filed_at`, and `available_date` are independent fields.
- `filed_at` is the SEC filing **calendar date**, not an intraday timestamp.
- Availability is the first **observed trading session strictly after** filing
  date, including when a filing was submitted before the market close.
- Selected fundamental observations must have `available_date <= as_of_date`.
- No wall clock decides availability, selection, market freshness or features.
  Current time supplies only `generated_at`, `retrieved_at`, and transport pacing.

The pure PIT engine downloads nothing. It uses an explicit observed-session
calendar with coverage bounds. A filing before those bounds cannot be assigned to
the first session artificially. Filings outside the configured history are
recorded as `HISTORICAL_OUT_OF_SCOPE`; filings with no post-filing session yet are
recorded as `PIT_EXCLUDED`. These are expected input-history exclusions (INFO),
not hidden violations in an already selected context.

History starts at `as_of_date - market_lookback_days` (default **730 calendar days**)
and ends at `as_of_date`. Fundamentals are limited by filing date to this coverage.
Older periods reported in an in-scope filing remain source facts. Availability
uses the ticker's observed market sessions, not a guessed weekday/holiday
calendar. Suspensions and missing provider sessions can delay inferred availability;
Stage 1 does not establish a complete independent exchange calendar.

Future bars returned to a market service raise `PITViolationError`. Future
availability in an already selected context is ERROR/FAIL, and the context schema
rejects a PASS status that conceals it. Provider failures propagate; malformed
source data raises `DataValidationError` without fallback or zero filling.

## Registered calculations

All features use the same uniformly adjusted close series. Windows count
**observed sessions** and include the current session.

| Feature | Frozen definition |
| --- | --- |
| `simple_return` | `close[t] / close[t-1] - 1` |
| `log_return` | `log(close[t] / close[t-1])` |
| `rolling_volatility_20` | sample standard deviation of the last 20 simple returns, ddof=1, not annualized |
| `rolling_volatility_60` | sample standard deviation of the last 60 simple returns, ddof=1, not annualized |
| `close_to_sma_5` | `close / mean(last 5 closes) - 1` |
| `close_to_sma_20` | `close / mean(last 20 closes) - 1` |
| `close_to_sma_60` | `close / mean(last 60 closes) - 1` |

The first return and insufficient warm-up windows are `null`, never zero. The
60-return volatility requires **61 closes**. Insufficient latest rolling history
produces a warning. Duplicate or unsorted market dates are rejected, never sorted
or deduplicated silently.

Yahoo-compatible normalization multiplies **every OHLC value** by `adjclose/close`
and declares `SPLIT_AND_DIVIDEND_ADJUSTED`. Reported share volume is unchanged.
Missing required fields or adjusted close fail normalization. Current provider
adjustment vintages may reflect subsequent corporate actions: Stage 1 enforces
observation-date cutoffs but **does not establish an archived historical as-of
price vintage**. `RETRIEVED_MARKET_VINTAGE` records that limitation as a warning.

## Registered fundamentals and source resolution

Ten metrics are registered with USD units and duration/instant semantics:
`revenue`, `gross_profit`, `operating_income`, `net_income`,
`operating_cash_flow`, `capital_expenditures`, `cash_and_equivalents`,
`total_assets`, `total_liabilities`, `stockholders_equity`.

Source mappings live in `providers/sec_concepts.py`, separate from the canonical
registry. For revenue, the explicit priority is
`RevenueFromContractWithCustomerExcludingAssessedTax`, then `Revenues`, then
`SalesRevenueNet`. Priority applies **within the same period and accession**;
otherwise a newer tag could erase older filing evidence. Other metrics use one
registered concept. Unsupported tags, currencies and forms are not guessed.

Identical redundant source rows are consolidated with diagnostic records.
Different alias values use the registered priority and produce a warning.
Conflicting duplicates **within any individual concept** fail normalization.
Different periods, year-to-date durations and amendments remain distinct facts;
no quarterly conversion, TTM roll-up, latest-value selection, YoY or margin is
invented. A revised filing becomes available only on its own next session and
never replaces the earlier vintage retroactively. Capital expenditures mean
reported payments for property, plant and equipment (positive outflow).

Stage 1 supports SEC **us-gaap**, **USD**, and **10-Q/10-K plus amendments**. IFRS,
issuer-specific extension concepts and unsupported forms remain outside scope.
Missing legally available registered metrics produce explicit warnings.

## Provenance, reproducibility and quality

`ResearchContext` schema version `1.0` includes company, observations, feature
rows, adjustment metadata, selected fundamentals, provenance and a quality report.
Financial source values use Decimal; JSON serializes them as strings.

Provenance contains provider, source type/reference, aware retrieval timestamp,
content-based data vintage (SHA-256 for downloaded payloads), and transformations.
Fundamental source records additionally preserve period, filing and accession.
Source facts and computed results have different typed `SourceType` values.
Concept names can appear in source evidence/transformation descriptions; the
business contract uses canonical metric names exclusively.

`normalized_business_json()` removes only `generated_at` and `retrieved_at`,
retaining content hashes, data vintage, transformation and business dates. Fixed
fixtures + ticker + as-of date yield identical normalized content. Different
live provider snapshots can legitimately differ and are not disguised as the same
vintage. Snapshot retrieval itself is not an archived historical database.

Quality status is `PASS`, `PASS_WITH_WARNINGS`, or `FAIL`, derived from issues:
ERROR always means FAIL; WARNING means PASS_WITH_WARNINGS unless there is ERROR.
Checks cover required fields, finite numbers, OHLC, duplicate sessions/canonical
facts, chronology, availability/session consistency, future information, freshness,
rolling history, units, metric support and feature/date alignment. Identical
canonical duplicates warn; conflicting duplicates fail. Market freshness uses
calendar-day distance from the explicit as-of date (default **7 days**), so normal
weekends do not cause errors.

Current SEC company metadata is reference identity, not a historical security
master: `CURRENT_COMPANY_REFERENCE` warns on that limitation. SEC's directory does
not establish reporting currency, which is preserved as unknown (`None`) with an
explicit warning. Thus even a sound fixture context can be PASS_WITH_WARNINGS.
A Stage 1 verification PASS means the implementation meets its defined scope;
it does not imply that every live context's data-quality status is PASS.

Public exceptions derive from `FinancialResearchError`: `UnknownTickerError`,
`ProviderError`, `DataValidationError`, `PITViolationError`,
`InsufficientHistoryError`, and `UnsupportedMetricError`. A quality FAIL is a
reviewable diagnostic context, not approval to use it as a valid research input.

## Scope and limits

Implemented: typed research core, SEC company/fundamental adapter, Yahoo-compatible
market adapter, frozen deterministic features, daily PIT, structured quality,
provenance, offline tests and CI configuration.

Not implemented: LLM or model SDKs, agent orchestration, API/UI frameworks, reports,
RAG, vector stores, news, sentiment, transcripts, predictive/walk-forward modeling,
portfolios, trading, real-time feeds, authentication or cloud deployment.

Live provider availability has not been smoke-tested in this implementation.
Yahoo's chart endpoint is an external compatibility interface and may reject or
change responses. SEC may throttle/reject access; the adapter requires an identified
User-Agent and paces sequential requests to at most approximately nine per second
per adapter. It does not coordinate limits across processes and is intended for
small sequential workflows. There are no automatic retries/fallbacks or durable
snapshot cache. Reproducibility is proven for frozen fixtures, not changing live
snapshots. CI versions are configured; only Python 3.14.4 was run locally.

The adapters use the [SEC EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [SEC developer access guidance](https://www.sec.gov/about/developer-resources).
Future work must preserve this independent core and these daily PIT/feature
semantics. No Stage 2 implementation is included.
