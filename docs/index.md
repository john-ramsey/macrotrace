# MacroTrace

A Python package for tracking and analyzing macroeconomic data revisions and their impact on economic analysis.

## What is MacroTrace?

MacroTrace helps researchers and analysts understand how macroeconomic data evolves over time through revisions. MacroTrace provides easy access to these **vintages**, snapshots of data as it appeared at specific points in time. Economic indicators like GDP, unemployment, and inflation are frequently revised as new information becomes available. These revisions can significantly impact economic analysis, forecasting, and policy decisions.

MacroTrace provides tools for:

- **Collecting** real-time data vintages from multiple sources
- **Analyzing** patterns and impacts of data revisions
- **Tracking** how economic indicators change over time with revisions

## Why MacroTrace?

Often times in economic analysis, the most recent data release is used without considering how previous estimates have changed. However, revisions can alter the interpretation of economic conditions.

For example, the United States Non-Farm Payroll is reported monthly by the Bureau of Labor Statistics (BLS). Each month, the initial estimate is released, followed by subsequent revisions in later months as more complete data is collected. Consider the period over period change for US Non-Farm Payroll in August of 2011:
- First released in September 2011: +0 Jobs MoM (July to August)
- Revised in October 2011: +57k Jobs MoM
- Revised in November 2011: +104k Jobs MoM

Each of these is a different vintage of the same data point which tells a different story about the economy at that time. MacroTrace allows you to collect and analyze these vintages to understand how data revisions impact economic analysis.

Until now, there has been no easy way to collect and analyze these vintages. MacroTrace fills this gap by providing a comprehensive framework for working with macroeconomic data revisions.

## Key Features

### Multi-Source Data Collection
Automated collection from major economic data providers:

- **[FRED](sources/fred.md)** (Federal Reserve Economic Data)
- **[ONS](sources/ons.md)** (Office for National Statistics)

Coming Soon:

- **[RTDSM](sources/rtdsm.md)** (Real-Time Data Set for Macroeconomists)

### Revision Tracking
Maintain complete history of how each data point changes across releases, enabling analysis of:

- Revision patterns and magnitudes
- Impact on economic analysis
- Vintage comparison
- Real-time vs. final data differences

### Efficient Database Management
Built on Peewee ORM & SQLite for:

- Fast local storage and retrieval
- Easy replicability / replication package generation
- Extensible data models

### Analysis Tools
Integrated tools for revision analysis and visualization including:

- Export data to pandas DataFrames for in-depth analysis.
- Visualization of revision patterns over time with Plotly.
- Forecasting and uncertainty measurement tools with Darts.

## Install from PyPI

```bash
pip install macrotrace
```

## Quick Example

```python
from macrotrace import MTTimeSeries

# Fetch US Payrolls time series from FRED
payems_series = MTTimeSeries(
    dataset_id="PAYEMS",
    source="fred"
)

# View a snapshot of the data
print(payems_series)
```

The above code fetches the Total Nonfarm Payrolls series from FRED and prints a snapshot of the data, including its revision history.

*Printing the object provides the following preview:*

```python
Time Series: PAYEMS (All Employees, Total Nonfarm)
Source: FRED
Units: Thousands of Persons
Latest Vintage Date: 2025-12-16
Vintages: 71 available from 2020-01-10 to 2025-12-16
+------------+----------+
| Timestamp  |  Value   |
+------------+----------+
| 2025-02-01 | 159155.0 |
| 2025-03-01 | 159275.0 |
| 2025-04-01 | 159433.0 |
| 2025-05-01 | 159452.0 |
| 2025-06-01 | 159439.0 |
| 2025-07-01 | 159511.0 |
| 2025-08-01 | 159485.0 |
| 2025-09-01 | 159593.0 |
| 2025-10-01 | 159488.0 |
| 2025-11-01 | 159552.0 |
+------------+----------+
```

## Project Status

This package is part of ongoing PhD research on macroeconomic data revisions. It is actively developed and tested.

## Next Steps

- [Installation Guide](getting-started/installation.md) - Get MacroTrace installed
- [Quick Start](getting-started/quickstart.md) - Start using MacroTrace in minutes
- [Overview](guide/overview.md) - Learn about core concepts and features
- [API Reference](api/macrotrace/time_series.md) - Detailed API documentation
