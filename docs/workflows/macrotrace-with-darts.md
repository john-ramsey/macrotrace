# MacroTrace with Darts

MacroTrace can hand a stored vintage directly to [Darts](https://unit8co.github.io/darts/) so you can use forecasting and decomposition tools without manually reshaping the data first.

## Convert a MacroTrace Series to a Darts TimeSeries

```python
import pandas as pd
from macrotrace import MTTimeSeries

payems = MTTimeSeries(
    dataset_id="PAYEMS",
    source="fred",
)

darts_ts = payems.to_darts_timeseries()
```

At this point you have a standard Darts `TimeSeries` for that period of time, but it still came from a MacroTrace vintage-aware workflow.


## Run a Simple Forecast

Once the series is in Darts format, you can use any Darts model that fits your workflow. Here is a simple `NaiveDrift` example:

```python
from darts.models import NaiveDrift

model = NaiveDrift()
model.fit(darts_ts)
forecast = model.predict(3)

forecast.to_dataframe()
```

```python
 timestamp       value
2026-03-01 158589.0077
2026-04-01 158712.0153
2026-05-01 158835.0230
```

This is a good starting point when you want MacroTrace to handle the data retrieval and vintage management, and Darts to handle downstream forecasting work.
