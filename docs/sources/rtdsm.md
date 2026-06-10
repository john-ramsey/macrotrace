# Real-Time Data Set for Macroeconomists (RTDSM)

## Overview

The **Real-Time Data Set for Macroeconomists (RTDSM)** is a collection of vintages of U.S. macroeconomic data maintained by the Federal Reserve Bank of Philadelphia. RTDSM is a heavily used source in economic research for studying data revisions and for building real-time analyses, and it is based on the work of Croushore and Stark (2001).

RTDSM has no API. The Philadelphia Fed publishes one spreadsheet per series containing the complete history of every vintage. MacroTrace downloads those spreadsheets and stores each vintage in the same data model used by the other sources, so RTDSM series behave like any other MacroTrace time series.

## Data Provider

- **Maintained by**: Federal Reserve Bank of Philadelphia
- **Website**: [https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-for-macroeconomists)
- **Data Access**: Free, no API key required
- **Update cadence**: All files are refreshed at the end of each month

## How MacroTrace Accesses RTDSM

Because there is no API, MacroTrace downloads the published "full time series history" spreadsheet for a series and parses every vintage from it. You do not need to keep the Excel files on disk: the data is read into memory and written to the local database. If you would like to keep a copy of the source spreadsheets, you can provide a directory (see [Saving the source spreadsheets](#saving-the-source-spreadsheets-optional)).

## RTDSM Data Structure

Each RTDSM series is identified by a short uppercase `dataset_id` (for example `ROUTPUT` for Real GNP/GDP, `RCON` for Real Personal Consumption Expenditures, `RUC` for the Unemployment Rate). These dataset IDs can be found on the [Philadelphia Fed's website](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-full-time-series-history) and are listed in `macrotrace.sources.rtdsm.RTDSM_CATALOG`.

A single series can be published at more than one vintage frequency. The `series_key` selects which vintage frequency to load:

- `{"frequency": "Q"}` loads the quarterly vintages of the series.
- `{"frequency": "M"}` loads the monthly vintages of the series.

The vintage frequency (how often a new snapshot is published) is independent of the data frequency (how often the underlying series is observed). For example, `RCON` is quarterly data that is published as both quarterly vintages and monthly vintages. The data frequency is fixed per series and is determined automatically, so you only ever choose the vintage frequency.

## Loading Data

```python
from macrotrace import MTTimeSeries

# Quarterly vintages of Real GNP/GDP
routput = MTTimeSeries(
    dataset_id="ROUTPUT",
    source="RTDSM",
    series_key={"frequency": "Q"},
)
```

The `frequency` key is optional. If you omit it, MacroTrace uses the series' only vintage frequency when there is just one, and defaults to quarterly when a series offers both.

```python
# EMPLOY only has monthly vintages, so this loads the monthly vintages
employ = MTTimeSeries(dataset_id="EMPLOY", source="RTDSM")
```

For reliable round trips (loading the same series again later without re-fetching), pass the `frequency` key explicitly so the stored series key and the requested series key always match.

## Choosing the Vintage Frequency

Not every series offers both vintage frequencies. If you request a frequency a series does not provide, MacroTrace raises a clear error that lists what is available.

```python
# DIV provides only quarterly vintages
MTTimeSeries(dataset_id="DIV", source="RTDSM", series_key={"frequency": "M"})
# ValueError: RTDSM series DIV does not offer M-frequency vintages. Available: Q.
```

Within a single database, load a given series at one vintage frequency. The quarterly and monthly vintages of the same series overlap (the mid-quarter monthly vintage is the same snapshot as the quarterly vintage, with identical values), so a series is best kept to one vintage frequency per database.

## Finding Series Mnemonics

Browse the full list of series and download pages here:

- [Real-Time Data Set: Full Time Series History](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-full-time-series-history)

The mnemonic shown on each series page is the `dataset_id`. A few commonly used series:

| Mnemonic | Series | Data frequency | Vintage frequencies |
|----------|--------|----------------|---------------------|
| ROUTPUT | Real GNP/GDP | Quarterly | Q, M |
| NOUTPUT | Nominal GNP/GDP | Quarterly | Q, M |
| RCON | Real Personal Consumption Expenditures | Quarterly | Q, M |
| RUC | Unemployment Rate | Monthly | Q |
| EMPLOY | Nonfarm Payroll Employment | Monthly | M |
| CPI | Consumer Price Index | Monthly | Q |
| M1 | M1 Money Stock | Monthly | Q |
| M2 | M2 Money Stock | Monthly | Q |

The complete set of supported series is available in code as `macrotrace.sources.rtdsm.RTDSM_CATALOG`, which maps each mnemonic to its title, data frequency, and available vintage frequencies:

```python
from macrotrace.sources.rtdsm import RTDSM_CATALOG

print(len(RTDSM_CATALOG))            # 115
print(RTDSM_CATALOG["ROUTPUT"])      # title, data_freq, vintage_freqs
```

## Monthly Refresh Behavior

RTDSM spreadsheets are refreshed only at the beginning of each month, so MacroTrace will not re-download a series from the Philadelphia Fed more than once per calendar month. After the first load in a month, subsequent loads of the same series are served from the local request cache without contacting the provider's website, no matter how many times you load it. At the start of the next month the file is fetched again.

This behavior relies on the request cache, which is enabled by default. If you need to force a fresh download within the same month, delete the request cache file (`MacroTraceRequestCache.sqlite` by default, or the path given by the `MACROTRACE_CACHE` environment variable).

## Saving the Source Spreadsheets (Optional)

If you want to keep a copy of the downloaded Excel files, use the `RTDSMUpdateManager` directly with an `excel_dir`. It ingests the data into the database (and writes the spreadsheet to `excel_dir`); you can then read the series back through `MTTimeSeries`:

```python
from macrotrace.sources.rtdsm import RTDSMUpdateManager
from macrotrace import MTTimeSeries

# Download, save the spreadsheet, and store every vintage
RTDSMUpdateManager(
    dataset_id="ROUTPUT",
    series_key={"frequency": "Q"},
    excel_dir="./rtdsm_files",
).update()

# Read the stored data back without re-fetching
routput = MTTimeSeries(
    dataset_id="ROUTPUT",
    source="RTDSM",
    series_key={"frequency": "Q"},
    update_prior_to_load=False,
)
```

## Troubleshooting

### Unknown series

```
ValueError: Unknown RTDSM series 'XYZ'. See macrotrace.sources.rtdsm.RTDSM_CATALOG ...
```

**Solution**: Use a supported uppercase mnemonic. Check `macrotrace.sources.rtdsm.RTDSM_CATALOG` or the [full series list](https://www.philadelphiafed.org/surveys-and-data/real-time-data-research/real-time-data-set-full-time-series-history).

### Frequency not available

```
ValueError: RTDSM series DIV does not offer M-frequency vintages. Available: Q.
```

**Solution**: Request a vintage frequency the series provides, or omit the `frequency` key to use the default.
