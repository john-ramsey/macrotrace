# Utilizing Your Own Data with MacroTrace

## Overview

While MacroTrace provides built-in support for various economic data sources like FRED and ONS, you can also analyze your own datasets using MacroTrace's `from_dataframe()` method. This allows you to leverage MacroTrace's revision analysis tools on custom data.

## Required Data Structure

To use your own data with MacroTrace, you need to prepare a pandas DataFrame with the following three required columns:

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | datetime | The observation date/time for each data point |
| `value` | numeric | The observed value at that timestamp |
| `release_date` | datetime | The date when this observation was released/published |

### Creating a Time Series from DataFrame

```python
import pandas as pd
from macrotrace import MTTimeSeries

# Example: Create a DataFrame with your data
df = pd.DataFrame({
    'timestamp': ['2024-01-01', '2024-02-01', '2024-03-01', '2024-01-01', '2024-02-01'],
    'value': [100.0, 105.0, 110.0, 99.5, 104.8],
    'release_date': ['2024-01-15', '2024-02-15', '2024-03-15', '2024-02-15', '2024-03-15']
})

# Create MTTimeSeries from the DataFrame
ts = MTTimeSeries.from_dataframe(
    df=df,
    dataset_id='MY_CUSTOM_SERIES',
    title='My Custom Economic Indicator',
    units='Index (Base=100)',
    frequency='MS',
    seasonal_adjustment='Not Seasonally Adjusted'
)
```
### Optional Parameters

When creating a time series from a DataFrame, you can provide optional metadata:

- **`title`**: A descriptive title for your series (defaults to `dataset_id`)
- **`units`**: The units of measurement (defaults to "Units")
- **`frequency`**: The frequency of observations denoted by a valid pandas offset alias (e.g., "MS", "QS", "AS"). If not provided, it will be inferred from the timestamps
- **`seasonal_adjustment`**: Description of seasonal adjustment method applied, if any

Including this metadata helps ensure clarity in visualizations.

### Timezone Handling

**Important**: Both `timestamp` and `release_date` columns should be timezone-aware datetime objects. If your data lacks timezone information:

- MacroTrace will automatically assume **UTC** timezone
- You'll see a warning message in the logs
- To avoid this, explicitly set timezones when creating your DataFrame:

```python
import pandas as pd

df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize('UTC')
df['release_date'] = pd.to_datetime(df['release_date']).dt.tz_localize('UTC')
```

Or for a specific timezone:

```python
df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize('America/New_York')
```

## Using Your Custom Time Series

Once created, your custom time series has access to all MacroTrace analysis methods:

```python
# Access historical vintages
vintage_2024_02 = ts.as_of('2024-02-15')

# Generate vintage matrix
vintage_matrix = ts.generate_vintage_matrix()

# Plot revisions
ts.plot.revision_histogram()

# Compare vintages
ts.plot.timeseries_comparison(
    vintage_dates=['2024-01-15', '2024-02-15', '2024-03-15'],
    chart_type='line'
)

# Assess revision success
flags, success_rate = ts.assess_revision_success()
print(f"Revision success rate: {success_rate:.2%}")
```

## Example: Loading from CSV

```python
import pandas as pd
from macrotrace import MTTimeSeries

# Load your data from CSV
df = pd.read_csv('my_data.csv')

# Ensure proper data types
df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize('UTC')
df['release_date'] = pd.to_datetime(df['release_date']).dt.tz_localize('UTC')
df['value'] = pd.to_numeric(df['value'])

# Create time series
ts = MTTimeSeries.from_dataframe(
    df=df,
    dataset_id='CUSTOM_GDP',
    title='Custom GDP Estimates',
    units='Billions of Dollars',
    frequency='Quarterly',
    seasonal_adjustment='Seasonally Adjusted at Annual Rate'
)

# Analyze
print(ts)
```

## Troubleshooting

### ValueError: DataFrame must contain columns

- Ensure your DataFrame has exactly these column names: `timestamp`, `value`, and `release_date`. Column names are case-sensitive.

### Timezone Warnings

- Add timezone information to your datetime columns using `pd.to_datetime().dt.tz_localize()` as shown above. The program will default to UTC if no timezone is provided, but it's best to be explicit.

### ValueError: Not enough observations to infer frequency

- Provide the `frequency` parameter explicitly when calling `from_dataframe()`, or ensure you have at least 2 observations with regular intervals.

### Empty Vintage Chain

- Ensure your `release_date` values vary. If all observations have the same release date, only one vintage will be created.
