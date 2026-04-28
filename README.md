# MacroTrace

MacroTrace is a Python library for collecting, storing, and analyzing macroeconomic
time-series vintages. It is designed for research workflows where the revision
history matters just as much as the latest published value.

Instead of treating a series as a single final dataset, MacroTrace helps you work
with the sequence of releases that were available in real time. This makes it
easier to study data revisions, reproduce historical analyses, and compare what was
known at different publication dates.

## Features

- Fetch vintage-aware macroeconomic time series from FRED and ONS
- Store releases locally in SQLite for reproducible, offline-friendly workflows
- Retrieve series as they were known on a specific date with `as_of(...)`
- Filter both vintage windows and data windows when loading a series
- Export to pandas DataFrames and Darts `TimeSeries` objects
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
