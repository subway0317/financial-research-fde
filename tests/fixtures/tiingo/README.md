# Tiingo EOD semantic fixtures

These are selected required response fields from the authorized live forensics
retrieved on 2026-10-07. No credentials, headers or request URLs are stored.
Metadata retains only ticker and the observed NASDAQ exchangeCode. Prices retain
date, raw/adjusted OHLCV, splitFactor and divCash, on the vendor retrieval vintage.

| Fixture | Requested interval | Rows | Purpose |
| --- | --- | ---: | --- |
| nflx_split.json | 2025-11-10 through 2025-11-21 | 10 | Forward 10-for-1 split, adjusted trading 2025-11-17 |
| tlry_reverse.json | 2025-11-26 through 2025-12-05 | 7 | Reverse 1-for-10 split, adjusted trading 2025-12-02 |
| aapl_dividend.json | 2026-08-03 through 2026-08-21 | 15 | Observed divCash event 2026-08-10; price adjustment, unchanged volume |
| nvda_730.json | 2024-06-30 through 2026-06-30 | 501 | 730 calendar days, eight observed dividends; first session 2024-07-01 |

The row counts belong to these fixtures, not a universal provider acceptance rule.
Reverse-split event references: [Tilray issuer disclosure](https://ir.tilray.com/node/14781/html)
and [Nasdaq corporate-action notice](https://www.nasdaqtrader.com/TraderNews.aspx?id=eca2025-641).
Reverse-split adjusted volume is an integer; the pre-event samples differ from
raw volume divided by ten by less than one share. The adapter preserves vendor
adjVolume and does not apply its own rounding, split factor or dividend factor.

These fixtures establish regression cases, not an archived historical as-of price
vintage or a complete independent exchange calendar. Tiingo's daily date component
is a session label; local timezone conversion would incorrectly shift it backward.
