# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/).

## 0.2.1 — 2026-06-11

- **Docs:** RTDSM is now listed as an available source on the documentation
  homepage — it had been left under "Coming Soon" when 0.2.0 shipped.
- **Docs:** The version selector now shows the `latest` label next to the
  release it points at, and the in-development `dev` build is hidden from
  the selector (it is still reachable directly at `/dev/`).

## 0.2.0 — 2026-06-10

- **Sources:** Added the Federal Reserve Bank of Philadelphia's Real-Time
  Data Set for Macroeconomists (RTDSM) — vintage-aware ingestion of 115 U.S.
  macroeconomic series. Each series is parsed from the published full-history spreadsheet; an optional `series_key={"frequency": "Q" | "M"}` selects the vintage frequency, and a monthly refresh throttle avoids re-downloading the same series
  within a calendar month as requested by the Philadelphia Federal Reserve Bank.
- **Vintage matching:** Added `MTTimeSeries.identify_vintage(...)`, which
  recovers which release(s) an undated block of observations came from by
  comparing it against every stored vintage. Returns a `VintageMatch`
  (`matched`, `is_ambiguous`, `release_date` / `release_dates`) — useful for
  pinning down the vintage behind replication-package data.
- **Time series:** Added `MTTimeSeries.to_series(...)`, the values-only,
  date-indexed pandas `Series` counterpart to `to_dataframe` (supports the
  `default`, `first_difference`, and `pct_change` modes). Exposed
  `VintageMatch` at the package root.

## 0.1.0 — 2026-04-28

First public release.

- **Sources:** vintage-aware ingestion from FRED and ONS, with a local
  SQLite store (`MacroTrace.db`) and shared request cache.
- **Time series:** `MTTimeSeries` with `as_of(...)`, vintage- and
  data-window filtering, `from_dataframe`, and pandas / Darts export.
- **Analysis:** revision metrics, vintage comparison, decomposition
  across vintages, biasedness regression, and revision autocorrelation.
- **Plotting:** Plotly-based vintage, revision, and decomposition plots
  via `MTTimeSeriesPlotter`.
- **CLI / TUI:** `macrotrace ons explorer` and `macrotrace ons tui`
  (the latter via the optional `ons-tui` extra).
