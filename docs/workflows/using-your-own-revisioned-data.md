# Using Your Own Revisioned Data

You can use MacroTrace with your own revisioned data as long as you provide three columns: `timestamp`, `value`, and `release_date`. This is useful for hand-collected releases, archived spreadsheets, internal forecasts, or data from sources MacroTrace does not yet support directly.

## Create a Small Revisioned Dataset

The example below builds a simple three-observation series with multiple releases. Notice that the timestamps are explicitly timezone-aware.

```python
import pandas as pd
from macrotrace import MTTimeSeries

df = pd.DataFrame(
    {
        "timestamp": [
            "2024-01-01", "2024-01-01", "2024-01-01",
            "2024-02-01", "2024-02-01", "2024-02-01",
            "2024-03-01", "2024-03-01", "2024-03-01",
        ],
        "value": [100.0, 99.8, 99.9, 101.2, 101.0, 101.1, 101.9, 102.4, 102.6],
        "release_date": [
            "2024-01-15", "2024-02-15", "2024-03-15",
            "2024-02-15", "2024-03-15", "2024-04-15",
            "2024-03-15", "2024-04-15", "2024-05-15",
        ],
    }
)

df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
df["release_date"] = pd.to_datetime(df["release_date"], utc=True)

custom = MTTimeSeries.from_dataframe(
    df=df,
    dataset_id="CUSTOM_CPI",
    title="Custom CPI Example",
    units="Index (2024=100)",
    frequency="MS",
    seasonal_adjustment="Not Seasonally Adjusted",
)

print(custom)
```

```python
Time Series: CUSTOM_CPI (Custom CPI Example)
Source: USER
Units: Index (2024=100)
Latest Vintage Date: 2024-05-15
Vintages: 4 available from 2024-01-15 to 2024-05-15
+------------+-------+
| Timestamp  | Value |
+------------+-------+
| 2024-03-01 | 102.6 |
+------------+-------+
```

## Build the Vintage Matrix

```python
vintage_matrix = custom.generate_vintage_matrix()
print(vintage_matrix)
```

```python
release_date               2024-01-15 00:00:00+00:00  2024-02-15 00:00:00+00:00  2024-03-15 00:00:00+00:00  2024-04-15 00:00:00+00:00  2024-05-15 00:00:00+00:00
timestamp
2024-01-01 00:00:00+00:00                      100.0                       99.8                       99.9                        NaN                        NaN
2024-02-01 00:00:00+00:00                        NaN                      101.2                      101.0                      101.1                        NaN
2024-03-01 00:00:00+00:00                        NaN                        NaN                      101.9                      102.4                      102.6
```

## Find the First Release of Each Observation

```python
print(custom.return_first_vintages())
```

```python
                timestamp        first_vintage_date  value
2024-01-01 00:00:00+00:00 2024-01-15 00:00:00+00:00  100.0
2024-02-01 00:00:00+00:00 2024-02-15 00:00:00+00:00  101.2
2024-03-01 00:00:00+00:00 2024-03-15 00:00:00+00:00  101.9
```

## Compute a Simple Revision Measure

For a small custom dataset, one straightforward measure is the difference between the latest stored value and the first release.

```python
first = custom.return_first_vintages().rename(columns={"value": "first_value"})
latest = custom.analysis.select_vintage_by_index(
    "latest",
    include_vintage_date=False,
).rename(columns={"value": "latest_value"})

metric = first.merge(latest, on="timestamp")
metric["final_minus_first"] = metric["latest_value"] - metric["first_value"]

print(metric[["timestamp", "final_minus_first"]].set_index("timestamp"))
```

```python
                           final_minus_first
timestamp
2024-01-01 00:00:00+00:00               -0.1
2024-02-01 00:00:00+00:00               -0.1
2024-03-01 00:00:00+00:00                0.7
```
