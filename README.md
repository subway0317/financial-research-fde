# Financial Research FDE

Financial Research FDE Platform provides reliable financial data, daily point-in-time
(PIT) selection, deterministic calculations, structured provenance, data quality,
and reproducible research contexts. FDE Stage 1 — Deterministic Research Core builds a typed `ResearchContext` from
an explicit ticker and as-of date. FDE Stage 2 — Research Tools & API Layer adds
five deterministic research tools and a thin, typed, stateless FastAPI transport.
FDE Stage 3 — Research Skills & Controlled Orchestration composes those tools into
four reusable domain workflows and one quality-gated equity evidence package.

This project is **not a demonstrated alpha-generating stock predictor**. Earlier
Quant research found no robust multi-year predictive signal from Relative Market +
OLS/Ridge, and no robust incremental predictive value from the registered PIT
fundamentals. Those negative results stand. Relative SMA here is a representation
choice, not a predictive-performance claim.

## Setup and verification

Requires Python **>=3.12**. Local verification used the existing Python **3.14.4**
virtual environment. CI is configured for Python 3.12 and 3.14. Stage 1 CI passed
at `39893f0`; Stage 2 CI passed at `1adcc82`. Stage 3 changes are validated locally;
the workflow executes on GitHub after the user creates a checkpoint.

On a new machine:

```bash
git clone git@github.com:subway0317/financial-research-fde.git
cd financial-research-fde
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
mypy src/financial_research
```

For the existing development environment, activate `.venv` and install; do not
recreate it. `pyproject.toml` is the center for dependencies and tooling. Runtime
uses Pydantic, HTTPX, FastAPI and uvicorn; calculations use Python's standard library. No
Poetry, Conda, uv, dataframe contract or database server is required.

The default test suite is fully offline. Tests use small synthetic JSON fixtures
and `httpx.MockTransport`, and an autouse fixture blocks socket connections. NVDA
is the verified end-to-end fixture target; a second ticker verifies generic core
behavior. All fixture values/filings are synthetic and documented in
[tests/fixtures/README.md](tests/fixtures/README.md).

The `live` marker is excluded by default (`-m "not live"`).
`tests/live/test_nvda_smoke.py` is a separate opt-in real-provider smoke; see the
Stage 2 live instructions below. CI uses the offline default.

## Capability architecture

```text
External source
  -> providers (transport + source normalization)
  -> schemas (validated canonical contracts)
  -> company / market / fundamentals services
  -> research.ResearchContextBuilder
  -> ResearchContext + structured quality + provenance
  -> tools (purpose-specific typed results, evidence and calculations)
  -> api (FastAPI transport only)
```

The Python workflow direction is **core → tools → skills → future agent**.
The existing API remains a transport over tools; Stage 3 adds no HTTP endpoints.

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
provenance, five deterministic research tools, typed FastAPI endpoints, five
registered research skills, shared-context orchestration, evidence packages,
offline tests, opt-in live smokes and CI configuration.

Not implemented: LLM or model SDKs, agent orchestration, UI frameworks, reports,
RAG, vector stores, news, sentiment, transcripts, predictive/walk-forward modeling,
portfolios, trading, real-time feeds, authentication or cloud deployment.

Live availability is reported separately by the explicit Stage 2 smoke path.
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
semantics. Stage 3 workflows are documented below; no Stage 4 agent is included.


## Stage 2 tools and direct Python use

Tools have no FastAPI imports, HTTP request objects, or provider-specific parsing.
Core modules do not import tools or API. The API delegates to `ResearchTools`,
which accepts a replaceable context builder. Pure functions also accept an
already-built `ResearchContext` for composing several tools from one acquisition.

| Tool | Purpose |
| --- | --- |
| `get_company_snapshot` | Identity, latest observed close, 5/20/60-session market windows, relative SMA and latest registered source facts |
| `analyze_fundamental_trends` | Registered metric universe (or requested subset), legal YoY comparisons and structured unavailability |
| `compare_periods` | One metric, `latest_vs_prior_year_comparable`, using the same comparison engine as trends |
| `summarize_market_behavior` | Observed-session close-to-close return, non-annualized daily volatility, OHLC extrema and latest relative SMA |
| `inspect_research_quality` | Existing Stage 1 status/issues, objective ages, available/missing metrics and structured provenance |

```python
from datetime import date

from financial_research.config import ResearchConfig
from financial_research.research.live import LiveContextBuilder
from financial_research.tools import ResearchTools

tools = ResearchTools(LiveContextBuilder(ResearchConfig.from_env()))
result = tools.analyze_fundamental_trends(
    ticker="NVDA", as_of_date=date(2026, 6, 30), metrics=["revenue", "net_income"]
)
```

To reuse one context, call `analyze_fundamental_trends(context, metrics=[...])`,
`get_company_snapshot(context)`, or another exported pure function. Neither path
requires the API package. `normalized_business_json()` excludes only request/build/
retrieval timestamps, preserving business dates, vintages, evidence IDs and formulas.

### Financial comparison rules

The canonical registry exposes `metric_kind`: six FLOW and four STOCK metrics.
Optional `FiscalPeriod` metadata requires explicit ANNUAL or QUARTERLY frequency,
fiscal year, quarter when quarterly, and a source reference. Existing Stage 1
facts without these labels remain valid. Absence means `UNVERIFIED_FISCAL_PERIOD`,
not a guessed quarter. Flow duration guards support 70–110 inclusive days for
quarters and 330–400 for annual periods; stub periods/YTD remain unsupported.

The shared engine selects the greatest legal period end, then ANNUAL before
QUARTERLY at the same endpoint, and the latest legally available filing vintage
within that exact duration. Unlabeled competing durations produce structured
unavailability. Conflicting latest filing values are invalid. YoY requires the
same frequency and fiscal quarter (when applicable), fiscal year exactly one
less, compatible durations (difference at most 14 days), and period-end spacing
330–400 days. It never substitutes another quarter, a sequential comparison,
an annual fact for a quarter, or a future filing. Revision selection never
rewrites the underlying source history.

The Stage 2 live composition enables optional SEC submissions metadata enrichment.
SEC `fy/fp` describe filing context and cannot label all comparative facts. A
label is accepted only when companyfacts end/filed/form match that accession's
submissions report date/filing date/form, and duration agrees with its frequency.
Only metadata archives overlapping the explicit filing scope are fetched (maximum
20). Original filing facts can establish prior-year labels; later comparative
rows are not relabeled using the later filing's year. YTD rows and annual-report
standalone Q4 flows without explicit quarterly labels remain unlabeled. There is
no fiscal/calendar-frame conversion or YTD-to-quarter aggregation. The default
Stage 1 SEC adapter behavior remains unchanged unless enrichment bounds are supplied.

For a legal pair, `absolute_change = current - prior`. When prior is positive,
`percentage_change = (current - prior) / prior`, as a **fraction**, not multiplied
by 100. A zero or negative prior gives null percentage and `NOT_MEANINGFUL` while
retaining absolute change. Decimal arithmetic uses sufficient precision for exact
subtraction and at least 50 digits for ratios. Direction is only INCREASED,
DECREASED, UNCHANGED, or UNAVAILABLE. There are no investment judgments or signals.

An unregistered requested metric raises `UnsupportedMetricError`; a registered
metric without a legal current/prior pair returns a typed UNAVAILABLE result and
reason. Metric lists must be nonempty and unique when supplied.

### Evidence and calculation provenance

`EvidenceReference` distinguishes SOURCE_FACT and COMPUTATION. IDs are content
hashes of source identity/value/vintage or calculation/formula/input IDs/parameters,
excluding volatile retrieval timestamps. Every successful derived calculation
records its formula, parameters and input evidence IDs. Source references include
financial periods/filing availability or market session dates. All calculation
input IDs resolve to source evidence included in that result. Ratios, changes,
returns, volatility, extrema, relative SMA and objective ages have calculation
provenance; unavailable values do not acquire fabricated calculations.

### Market windows and freshness

Lookback is an integer **2–504 observed closes**, not calendar days. A complete
N-close window contains **N−1 simple returns**. Cumulative return is
`last_close / first_close - 1`; realized volatility is sample standard deviation
of those returns, ddof=1 and non-annualized, explicitly exposed as
`realized_volatility_daily` with `annualized=false`. Two closes permit a return
but cannot provide sample volatility. Insufficient N-close history yields a
structured unavailable window; partial history is counted but not used as if
complete. Latest relative SMA reuses Stage 1 feature values and can refer to a
longer history than the descriptive window. OHLC extrema use adjusted high/low.
The configured 730-day core history does not guarantee 504 observed sessions.

Quality preserves Stage 1's status, severity and market freshness rule. Age fields
are calendar-day differences from the explicit as-of date. Fundamental age alone
never causes a new 90-day staleness warning. A FAIL context blocks financial
calculations; the quality inspector can expose existing FAIL diagnostics. Future
market/fundamental information is always a PIT integrity error.

## Stage 2 API

Export an explicitly chosen SEC contact User-Agent, then start:

```bash
export SEC_USER_AGENT="Your Organization your-name your-email@example.com"
uvicorn financial_research.api.app:app --reload
```

Swagger: **http://127.0.0.1:8000/docs**. OpenAPI: `/openapi.json`.
`GET /health` returns process liveness independently of SEC/Yahoo availability.
Importing the default `app` and accessing health/docs performs no provider requests.
Each research request owns and closes its provider clients; only configuration/
factory references persist. There are no caches, database/user sessions, queues,
background jobs or authentication. `create_app(tools_factory=...)` and the
`get_research_tools` dependency support offline injection.

| Endpoint | Additional request fields |
| --- | --- |
| `POST /v1/research/company-snapshot` | None |
| `POST /v1/research/fundamental-trends` | Optional `metrics` |
| `POST /v1/research/compare-periods` | `metric`, optional `comparison` (only `latest_vs_prior_year_comparable`) |
| `POST /v1/research/market-behavior` | Optional `lookback_sessions`, default 60 |
| `POST /v1/research/quality` | None |

Every request requires canonicalizable `ticker` and ISO date `as_of_date`.
Dates must be YYYY-MM-DD; numeric timestamps, datetime strings and invalid dates
are rejected. Lookback rejects booleans, strings and out-of-range integers.

```bash
curl -X POST http://127.0.0.1:8000/v1/research/company-snapshot \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"NVDA","as_of_date":"2026-06-30"}'
curl -X POST http://127.0.0.1:8000/v1/research/fundamental-trends \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"NVDA","as_of_date":"2026-06-30","metrics":["revenue","net_income"]}'
curl -X POST http://127.0.0.1:8000/v1/research/compare-periods \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"NVDA","as_of_date":"2026-06-30","metric":"revenue","comparison":"latest_vs_prior_year_comparable"}'
curl -X POST http://127.0.0.1:8000/v1/research/market-behavior \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"NVDA","as_of_date":"2026-06-30","lookback_sessions":60}'
curl -X POST http://127.0.0.1:8000/v1/research/quality \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"NVDA","as_of_date":"2026-06-30"}'
```

Research responses contain `request_id` (new server-generated UUID4),
`schema_version`, aware UTC `generated_at`, typed `data`, `quality`, and
`limitations`. `X-Request-ID` matches the body ID. Runtime metadata is separate
from deterministic business content. There is no public raw ResearchContext,
chat, prediction, signal or report endpoint. Routes contain no financial calculations.

| Error | HTTP status / stable code |
| --- | --- |
| Unknown ticker | 404 / UNKNOWN_TICKER |
| Malformed request | 422 / REQUEST_VALIDATION_ERROR |
| Unregistered metric | 422 / UNSUPPORTED_METRIC |
| Invalid canonical data | 422 / DATA_VALIDATION_ERROR |
| Required history missing | 422 / INSUFFICIENT_HISTORY |
| Provider transport failure | 502 / PROVIDER_ERROR |
| PIT integrity failure | 500 / PIT_VIOLATION |
| Missing live provider configuration | 503 / CONFIGURATION_ERROR |
| Unexpected internal exception | 500 / INTERNAL_ERROR |

Errors expose only stable code, sanitized message and request ID, never raw
exception/provider payload, traceback, filesystem path or secrets. Standard
logging includes request ID, endpoint, ticker, as-of date, tool name, execution
duration and result quality. Internal errors remain failures, not fallback results.

## Stage 2 offline and live validation

```bash
pytest
ruff check .
ruff format --check .
mypy src/financial_research
python -m pip check
git diff --check
```

Default pytest includes Stage 1, tool and API regression tests and excludes live.
CI runs these offline tests and static checks on Python 3.12 / 3.14. API tests
exercise all endpoints, errors, OpenAPI and docs with injected fixture contexts.
Some restrictive execution sandboxes block local socketpair wakeups required by
ASGI/thread bridges; run checks in a normal local shell in that case. The test
suite's external socket/DNS guard must remain enabled.

The live path is explicit and uses **real** SEC/Yahoo requests:

```bash
export LIVE_AS_OF_DATE="2026-06-30"
pytest -m live tests/live/test_nvda_smoke.py -s
python -m financial_research.tools.smoke --ticker NVDA --as-of-date 2026-06-30
```

It resolves company, fetches market and companyfacts/submissions data, builds a
PIT context, then exercises company snapshot and fundamental trends. Assertions
check typed shape, ticker/CIK, nonempty market, legal dates, quality and tool
integration, not exact changing financial values. Smoke status is PASS, EXTERNAL
BLOCKED for identifiable HTTP access/rate/outage or transport failures, or FAILED
for validation/integrity/unclassified implementation errors. CLI exit codes are
0/2/1 respectively. The pytest live test fails on any non-PASS status and prints
the classification; external blocks are never skipped, mocked or called PASS.
Missing SEC_USER_AGENT is configuration failure, not a provider outage. Contact
identity must be explicitly supplied for live requests; the application does not
read Git identity or send it automatically.

Offline correctness and live availability are separate validation dimensions.
Live prices/companyfacts still use retrieved snapshots and may change; historical
vintage warnings, SEC concept/period limitations, and observed-calendar freshness
limits remain visible. Stage 2 adds no LLM, agent, valuation/predictive engine,
database, UI, deployment or investment-signal capability.

## Stage 3: tools, skills and the future agent

A **Tool** supplies an atomic deterministic computation or analysis, such as
period comparison or a descriptive market window. A **Skill** organizes those
existing results through a fixed domain workflow with typed inputs/outputs,
explicit evidence and quality behavior. A future **Agent** may understand user
intent, choose skills, ask for clarification and synthesize natural language.
**Stage 3 does not contain an LLM Agent or perform synthesis.**

Core and tools never import skills. Skills never import FastAPI or LLM SDKs.
Financial calculations, PIT filtering, comparable-period rules and data-quality
rules stay in Stage 1/2. No new dependencies, external accounts, API keys, OAuth,
extensions or external services are required. Live execution reuses the existing
SEC/Yahoo-compatible composition and its explicitly supplied SEC User-Agent.

### Registered skills and contracts

| Skill ID | Fixed purpose | Input / output contract |
| --- | --- | --- |
| `company_overview` | Organize identity, latest market state, standard windows and registered source facts | `SkillInput` / `CompanyOverviewResult` |
| `fundamental_analysis` | Organize legal comparable-period trends without repeating primitive comparisons | `FundamentalAnalysisInput` / `FundamentalAnalysisResult` |
| `market_analysis` | Organize descriptive market window and relative SMA evidence | `MarketAnalysisInput` / `MarketAnalysisResult` |
| `research_quality_audit` | Organize authoritative issues, ages, missing metrics and provenance | `SkillInput` / `ResearchQualityAuditResult` |
| `equity_research` | Execute the four domain skills and assemble an evidence package | `EquityResearchInput` / `ResearchEvidencePackage` |

Every skill definition has a stable ID, version `1.0`, name, objective description,
required tools, input/output schema references and capabilities. The composite
also declares its required subskills. `SkillRegistry.register`, `.get` and `.list`
use explicit in-process registration; listing is ordered by ID. Duplicate IDs
raise `DataValidationError`; unknown lookup raises `KeyError`. There is no discovery,
remote registry, marketplace or downloaded plugin code.

```python
from datetime import date

from financial_research.skills import create_skill_registry

registry = create_skill_registry()
skill = registry.get("equity_research")
result = skill.run(ticker="NVDA", as_of_date=date(2026, 6, 30))
print(result.model_dump_json(indent=2))
```

`create_skill_registry(builder=...)` injects an offline or alternative context
builder. For explicit metric/window options, use the typed concrete skill:

```python
from financial_research.skills import EquityResearchSkill, SkillExecutionContext

# context is an already-built Stage 1 ResearchContext.
execution = SkillExecutionContext(
    ticker=context.ticker,
    as_of_date=context.as_of_date,
    research_context=context,
)
package = EquityResearchSkill().run_from_context(
    execution, metrics=["revenue", "net_income"], lookback_sessions=60
)
print(package.metadata.status, package.synthesis_readiness)
```

Input schemas reject malformed contracts before execution. A supported metric
without comparable data yields UNAVAILABLE; a requested unregistered metric
produces a sanitized FAILED execution before provider work. Comparison and
market definitions are exactly the Stage 2 definitions documented above.

### Shared execution and controlled workflow

One standalone `.run` creates a UUID4 execution ID and builds one ResearchContext.
One composite run shares that same context across every subskill and tool. The
execution holds typed, temporary tool results, never persistent or global caches.
Repeated identical tool requests reuse results. The market skill reuses snapshot
windows for 5/20/60 sessions; other requested windows use the existing Stage 2
window helper while retaining cached relative SMA evidence. Standalone market
analysis calls the complete market tool. Trends do not call `compare_periods`
again for each metric.

The fixed order is context acquisition/reuse → quality gate → company overview →
fundamental analysis → market analysis → quality audit → evidence merge → package
assembly. Quality FAIL stops financial work; only quality diagnostics are then
assembled. Other critical failures stop subsequent normal subskills. Evidence
integrity failures return a failed package without publishing the suspect index.

`SkillExecutionContext` is owned by one logical run. Create a fresh execution for
another run; its context cannot be replaced after binding. No cross-run data cache
is supplied, and the configured history still does not guarantee 504 sessions or
all fiscal comparison pairs. An injected builder remains responsible for supplying
the canonical Stage 1 context and authoritative quality report.

### Status, quality and synthesis readiness

Execution status and data quality remain separate:

| SkillStatus | Meaning |
| --- | --- |
| `SUCCESS` | Core workflow and required evidence completed |
| `PARTIAL` | Core purpose completed; some supporting metrics, windows or SMA/volatility evidence is unavailable |
| `UNAVAILABLE` | Legal data is insufficient for the skill's core purpose |
| `FAILED` | Provider, PIT, canonical validation, critical quality, integrity or unexpected execution failure |

Company overview requires identity and current market state; unavailable registered
fundamentals or standard windows are supporting gaps. Fundamental analysis requires
at least one legal comparison among requested metrics. Market analysis requires its
complete requested close window; volatility/SMA may be supporting gaps. A quality
audit can complete successfully while faithfully reporting warnings/missing metrics;
an authoritative FAIL instead gives FAILED and retains critical diagnostics.

The composite requires all four sections, current market state, at least one legal
fundamental comparison and a complete requested market window. Any failed subskill
means FAILED; any core unavailable subskill means UNAVAILABLE. Supporting gaps mean
PARTIAL. Missing percentage change for a zero/negative base preserves a valid
absolute comparison and its existing limitation rather than changing data quality.

| Condition | SynthesisReadiness |
| --- | --- |
| Successful, sufficient evidence; quality PASS; no limitations | `READY` |
| Sufficient core evidence with warnings, supporting gaps or limitations | `READY_WITH_WARNINGS` |
| FAILED or insufficient core evidence | `NOT_READY` |

PASS_WITH_WARNINGS is preserved and can accompany SUCCESS or PARTIAL. Fundamental
age never adds a second staleness rule. Readiness is permission metadata for a
future synthesis layer, not synthesized text or an investment judgment.

### ResearchEvidencePackage and trace

Identity, as-of date, UUID4 execution ID, generation timestamp, skill version,
overall status, quality and sanitized error metadata live in the typed `metadata`
field. The package additionally contains the four structured sections, subskill
metadata, `synthesis_readiness`, `evidence_index`, calculation provenance,
limitations and `execution_trace`, with schema version `1.0`.

`evidence_index` maps existing Stage 2 evidence IDs to their original typed
`EvidenceReference`. Sections and metric summaries reference IDs rather than
copying full evidence collections. Same ID/same content deduplicates; same ID/
different content raises `EvidenceIntegrityError`. Conflicting calculation
provenance also fails. Every computation and input reference must resolve.
Formulas, parameters and source vintage remain intact. Limitations are preserved,
deduplicated and sorted. Stage 3 generates no second evidence identity system.

Trace steps contain only sequence, action type, target, status, quality status,
safe error code and optional duration. They record context acquisition, tool calls/
reuse, subskill completion, quality gate, evidence merge and package assembly.
There are no reasoning, chain-of-thought, thesis or free-form thought fields.
Skill exceptions remain FAILED with safe metadata; raw provider messages and
credentials are not serialized. Logs include execution ID, skill and status/code.

`normalized_business_json()` excludes execution/request IDs, build/retrieval
timestamps and timing fields (`duration_ms`, `started_at`, `completed_at`). Fixed
fixtures/input/version produce identical statuses, source vintage, evidence IDs,
calculation provenance, sorted limitations and trace actions/targets/statuses.
Changing retrieved live snapshots remains a real business-vintage difference.

### Stage 3 verification and live composite smoke

Use the existing offline validation commands above. Tests cover contracts, registry,
domain composition, all status/readiness branches, gates, failures, evidence
deduplication/collisions/reference resolution, deterministic output and trace,
dependency direction, and counters proving one composite context/provider cycle.
All Stage 1/2 tests, API/OpenAPI contracts and live infrastructure remain included.
CI still runs offline tests and static checks on Python 3.12/3.14; live remains
excluded by default.

With the existing, explicitly supplied `SEC_USER_AGENT`:

```bash
export LIVE_AS_OF_DATE="2026-06-30"
pytest -m live tests/live/test_nvda_equity_skill_smoke.py -s
python -m financial_research.skills.smoke --ticker NVDA --as-of-date 2026-06-30
```

This opt-in path builds one live context and exercises all four subskills and the
composite. It checks typed shape, legal dates, context count, sections, evidence
integrity and preserved limitations without volatile exact-value assertions.
The summary reports smoke status separately from SkillStatus, readiness and data
quality: a legitimate data-unavailable result remains UNAVAILABLE/NOT_READY.
Provider access/rate/outage/transport blocks are classified EXTERNAL BLOCKED;
validation/integrity/execution failures are FAILED. The pytest smoke fails rather
than skips on non-PASS. CLI exit codes remain PASS=0, EXTERNAL BLOCKED=2, FAILED=1.

Source concept/period coverage, observed-calendar freshness and retrieved historical
vintage limitations remain unchanged. Stage 3 adds no LLM SDK, agent, routing,
natural-language report/thesis, recommendations, valuation, prediction, portfolio,
database, persistent sessions, authentication, UI, deployment or remote marketplace.
