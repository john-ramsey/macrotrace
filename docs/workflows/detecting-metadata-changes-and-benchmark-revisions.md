# Detecting Metadata Changes and Benchmark Revisions

Before comparing vintages, it is worth checking whether the series definition itself changed over time. MacroTrace's `get_historical_metadata()` method gives you a high-level summary of substantive metadata changes across the vintage history.

## Load a FRED Series

For example, using the FRED `CPILFESL` series.

```python
from macrotrace import MTTimeSeries

cpilfesl = MTTimeSeries(
    dataset_id="CPILFESL",
    source="fred",
)

print(cpilfesl)
```

```python
Time Series: CPILFESL (Consumer Price Index for All Urban Consumers: All Items Less Food and Energy in U.S. City Average)
Source: FRED
Units: Index 1982-1984=100
Latest Vintage Date: 2026-03-11
Vintages: 369 available from 1996-12-12 to 2026-03-11
+------------+---------+
| Timestamp  |  Value  |
+------------+---------+
| 2025-05-01 | 326.893 |
| 2025-06-01 | 327.658 |
| 2025-07-01 | 328.682 |
| 2025-08-01 |  329.7  |
| 2025-09-01 | 330.418 |
| 2025-10-01 |         |
| 2025-11-01 | 331.043 |
| 2025-12-01 | 331.814 |
| 2026-01-01 | 332.793 |
| 2026-02-01 | 333.512 |
+------------+---------+
```

## Inspect the Metadata History

`get_historical_metadata()` is intentionally higher level. It only records a new epoch when the substantive metadata changes: title, units, frequency, or seasonal adjustment. The dictionary key is the first vintage date when that substantive definition appeared, while the metadata value reflects the latest vintage within that same epoch.

```python
import pandas as pd

history = cpilfesl.get_historical_metadata()

rows = []
for start_date, metadata in history.items():
    rows.append(
        {
            "epoch_start": start_date.strftime("%Y-%m-%d"),
            "epoch_end": metadata.realtime_end.strftime("%Y-%m-%d")
            if metadata.realtime_end
            else None,
            "title": metadata.title,
            "units": metadata.units,
            "frequency": metadata.frequency,
            "seasonal_adjustment": metadata.seasonal_adjustment,
        }
    )

print(pd.DataFrame(rows))
```

```python
epoch_start  epoch_end                                                                                             title               units frequency seasonal_adjustment
 1996-12-12 2019-08-13                      Consumer Price Index for All Urban Consumers: All Items Less Food and Energy Index 1982-1984=100        MS Seasonally Adjusted
 2019-09-12 2026-03-11 Consumer Price Index for All Urban Consumers: All Items Less Food and Energy in U.S. City Average Index 1982-1984=100        MS Seasonally Adjusted
```

## Interpreting the Metadata History

In this case, `get_historical_metadata()` returns two epochs because the series title changed in September 2019. The units, frequency, and seasonal adjustment stayed the same, but the title was updated to include "in U.S. City Average."

That matters for benchmark revisions because the metadata history and the revision history answer different questions:

- A new metadata epoch tells you that the series definition changed in some substantive way.
- A stable metadata history does not prove that no benchmark revision occurred.

MacroTrace's `generate_vintage_matrix()` still assumes the vintages are comparable. The metadata checks help you evaluate that assumption, but they do not remove the need for researcher judgment.
