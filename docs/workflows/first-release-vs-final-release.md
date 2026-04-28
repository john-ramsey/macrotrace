# First Release vs Final Release

Many empirical projects need a concrete definition of the "initial estimate" and the "latest available estimate". MacroTrace gives you both directly from the vintage chain.

## Build the First-Release and Latest Series

`return_first_vintages()` returns the first stored value for each observation. `select_vintage_by_index(vintage_index="latest")` returns the latest non-missing value for each observation.

```python
from macrotrace import MTTimeSeries

payems = MTTimeSeries(
    dataset_id="PAYEMS",
    source="fred",
)

first = payems.return_first_vintages().rename(columns={"value": "first_value"})
latest = payems.analysis.select_vintage_by_index(
    vintage_index="latest",
    include_vintage_date=True,
    dropna=True,
).rename(
    columns={
        "value": "latest_value",
        "vintage_date": "latest_vintage_date",
    }
)

comparison = first.merge(latest, on="timestamp", how="inner")
comparison["timestamp"] = comparison["timestamp"].dt.strftime("%Y-%m-%d")
comparison["first_vintage_date"] = comparison["first_vintage_date"].dt.strftime("%Y-%m-%d")
comparison["latest_vintage_date"] = comparison["latest_vintage_date"].dt.strftime("%Y-%m-%d")

print(comparison.tail(6))
```

```python
 timestamp first_vintage_date  first_value  latest_value latest_vintage_date
2025-09-01         2025-11-20     159626.0      158548.0          2026-03-06
2025-10-01         2025-12-16     159488.0      158408.0          2026-03-06
2025-11-01         2025-12-16     159552.0      158449.0          2026-03-06
2025-12-01         2026-01-09     159526.0      158432.0          2026-03-06
2026-01-01         2026-02-11     158627.0      158558.0          2026-03-06
2026-02-01         2026-03-06     158466.0      158466.0          2026-03-06
```

This gives you a clean way to operationalize two common research concepts:

- The **first release** is the first vintage date on which an observation appears.
- The **latest release** is the latest stored value for that same observation.

With these two series in hand, you can measure revision size, compare initial releases with later data, or evaluate whether conclusions depend on using real-time or revised data.
