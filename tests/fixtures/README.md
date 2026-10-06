# Offline fixtures

All JSON values and filing/accession dates here are **synthetic**, including NVDA
values. They exercise provider-shaped normalization and PIT semantics; they are
not SEC evidence, investment inputs, or artifacts copied from Quant research.

The compact daily chart contains 70 monotonically dated sessions with alternating
price changes. Weekends and 2025-05-26 are absent. One ten-metric filing becomes
available 2025-05-23; a revenue revision filed that day becomes available 2025-05-27.
A revenue alias tests deterministic per-filing concept priority. The exchange
calendar is deliberately limited to these observed sessions, not a general market
holiday calendar. `nvda_expected.json` freezes the selected business outputs.

`fiscal_observations.json` adds explicit, synthetic issuer fiscal labels for
Stage 2 flow/stock and quarterly/annual comparisons. The examples intentionally
use fiscal year labels distinct from calendar years. Prior-year comparative facts
are disclosed in a synthetic 2025 filing and are available only on that filing's
next observed session. No values or fiscal labels are evidence of actual NVDA
financial statements. The two absent canonical metrics exercise UNAVAILABLE.
