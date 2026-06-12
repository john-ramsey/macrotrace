# MacroTrace

[![PyPI version](https://img.shields.io/pypi/v/macrotrace.svg)](https://pypi.org/project/macrotrace/)
[![Python versions](https://img.shields.io/pypi/pyversions/macrotrace.svg)](https://pypi.org/project/macrotrace/)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![CI](https://github.com/john-ramsey/macrotrace/actions/workflows/ci.yml/badge.svg)](https://github.com/john-ramsey/macrotrace/actions/workflows/ci.yml)
[![Docs](https://github.com/john-ramsey/macrotrace/actions/workflows/docs.yml/badge.svg)](https://john-ramsey.github.io/macrotrace/)

MacroTrace is a Python library for collecting, storing, and analyzing macroeconomic
time-series vintages. It is designed for research workflows where the revision
history matters just as much as the latest published value.

**Documentation:** <https://john-ramsey.github.io/macrotrace/>

Instead of treating a series as a single final dataset, MacroTrace helps you work
with the sequence of releases that were available in real time. This makes it
easier to study data revisions, reproduce historical analyses, and compare what was
known at different publication dates.

## Features

- Fetch vintage-aware macroeconomic time series from FRED, ONS, and the Philadelphia Fed's Real-Time Data Set (RTDSM)
- Store releases locally in SQLite for reproducible, offline-friendly workflows
- Retrieve series as they were known on a specific date with `as_of(...)`
- Filter both vintage windows and data windows when loading a series
- Recover which release an undated block of data came from with `identify_vintage(...)`
- Export to pandas DataFrames or Series and Darts `TimeSeries` objects
- Plot vintages and revision comparisons with built-in Plotly tooling

## Installation

Install the package from PyPI:

```bash
pip install macrotrace
```

Install the optional ONS Textual interface:

```bash
pip install "macrotrace[ons-tui]"
```

## Requirements

- Python 3.11+
- A FRED API key for FRED-backed series

Set your FRED API key before loading FRED series:

```bash
export FRED_API_KEY="your_api_key_here"
```

## Quick Start

```python
from macrotrace import MTTimeSeries

payems = MTTimeSeries(
    dataset_id="PAYEMS",
    source="FRED",
)

print(payems)

july_2020 = payems.as_of("2020-07-15")
df = july_2020.to_dataframe()
```

MacroTrace stores fetched releases in a local SQLite database named
`MacroTrace.db`, making repeated loads faster and keeping vintage histories
available for later analysis.

For multi-dimensional datasets such as ONS releases, provide a `series_key` to
select a specific slice of the dataset:

```python
from macrotrace import MTTimeSeries

gdp = MTTimeSeries(
    dataset_id="gdp-to-four-decimal-places",
    source="ONS",
    series_key={
        "geography": "K02000001",
        "unofficialstandardindustrialclassification": "A--T",
    },
)
```

The Philadelphia Fed's Real-Time Data Set (RTDSM) needs no API key. Use the
series mnemonic as the `dataset_id` and select the vintage frequency with the
`series_key`:

```python
from macrotrace import MTTimeSeries

routput = MTTimeSeries(
    dataset_id="ROUTPUT",
    source="RTDSM",
    series_key={"frequency": "Q"},
)
```

See the [RTDSM source guide](docs/sources/rtdsm.md) for the full list of series
and details on vintage frequencies.

### Identifying an Unknown Vintage

If you have a block of observations with no release date attached — for
example, a series lifted from a replication package — `identify_vintage`
compares it against every stored vintage and reports which release(s) it is
consistent with:

```python
from macrotrace import MTTimeSeries

routput = MTTimeSeries(
    dataset_id="ROUTPUT",
    source="RTDSM",
    series_key={"frequency": "Q"},
)

# `unknown` is a date-indexed pandas Series whose vintage you want to recover
match = routput.identify_vintage(unknown)

if match.is_ambiguous:
    print(f"Ambiguous — consistent with {len(match.release_dates)} vintages")
elif match.matched:
    print(f"Matches the {match.release_date.date()} vintage")
else:
    print(f"No matching vintage found (failed on: {match.failure_reason})")
```

## Command-Line Tools

MacroTrace includes command-line tools for exploring ONS datasets:

```bash
macrotrace ons explorer
```

If you installed the optional TUI extra, you can also run:

```bash
macrotrace ons tui
```

## Development

For local development, we use `uv` for dependency management and environment
execution.

Install the project with the development, docs, and optional TUI dependencies:

```bash
uv sync --extra ons-tui --group dev --group docs
```

Run tests inside the managed environment with:

```bash
uv run pytest
```

Code formatting is handled with `black`:

```bash
uv run black .
```

## Project Status

MacroTrace is under active development as part of a PhD research project on
macroeconomic data revisions.

## License

MacroTrace is licensed under the GNU General Public License v3.0 or later
(`GPL-3.0-or-later`).
