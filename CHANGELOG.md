# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [SemVer](https://semver.org/).

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
