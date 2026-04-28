# Revision Diagnostics for Researchers

Once you have a vintage chain, MacroTrace can help answer several common research questions:

- Did revisions usually move the series toward the final value?
- Do early releases look biased relative to later releases?
- How large are revisions relative to forecast errors?
- How different are selected vintages from one another?

The examples below use the FRED `PAYEMS` series.

## Revision Success

`assess_revision_success()` implements the idea that a successful revision moves the series closer to the final value.

```python
from macrotrace import MTTimeSeries

payems = MTTimeSeries(
    dataset_id="PAYEMS",
    source="fred",
)

_, success_rate = payems.analysis.assess_revision_success()
print(round(float(success_rate), 4))
```

```python
0.6391
```

In this snapshot, about 63.9% of assessed revisions moved the series closer to the final value.

## Biasedness Regression

`revision_biasedness_regression()` compares one vintage with another using the standard regression setup from the revisions literature.

```python
print(payems.analysis.revision_biasedness_regression(1, "latest"))
```

```python
+---------------+-----------+---------+---------+--------+--------------+---------------+
|     Param     | Estimate  | Std Err | t (H0)  | p (H0) | CI Low (95%) | CI High (95%) |
+---------------+-----------+---------+---------+--------+--------------+---------------+
| alpha (const) | 672.8463* | 47.5250 | 14.1577 | 0.0000 |   579.5908   |   766.1017    |
|   beta (x)    |  0.9958*  | 0.0005  | -8.8276 | 0.0000 |    0.9949    |    0.9968     |
+---------------+-----------+---------+---------+--------+--------------+---------------+
```

Here, the first vintage is the independent variable and the latest vintage is the dependent variable. The closer `alpha` is to zero and `beta` is to one, the closer the early vintage is to an unbiased predictor of the later one.

## Revision Uncertainty

`revision_uncertainty()` compares revision variability with rolling forecast errors from a forecast model. The example below uses the lightweight `Naive` model.

```python
uncertainty = payems.analysis.revision_uncertainty(
    forecast_method="Naive",
    min_train_size=24,
)
print(uncertainty)
```

```python
{'std_dev_forecast_errors': 707.847, 'std_dev_revisions': 613.0383, 'ratio': 0.8661}
```

The `ratio` compares the standard deviation of revisions with the standard deviation of forecast errors. A ratio below one means revisions were smaller than forecast errors in this sample.

## Vintage Comparison

`vintage_comparison()` summarizes how a chosen set of vintages differ from one another across several revision statistics. Unlike the diagnostics above, which sweep the full vintage chain, here you pick the vintages you care about and decide how to pair them up.

The main arguments for the method are:
- `vintage_dates`: the vintages you want to compare. Each requested date is resolved through `as_of()` to the nearest release at or before that date, so you can hand it any calendar date. If two requested dates resolve to the same release, the duplicates collapse and a warning is logged.
- `mode` (default `"growth"`): in `"growth"` mode each vintage is converted to within-vintage period-over-period growth rates before comparison, so metrics describe revisions to the *growth rate*. In `"levels"` mode the raw level values are compared and metrics describe revisions to the *level*.
- `strategy`: `"sequential"` walks pairwise (v1→v2, v2→v3), `"final"` compares each earlier vintage against the most recent vintage in the request, and `"all"` compares every pair.

```python
from datetime import datetime, timezone

comparison = payems.analysis.vintage_comparison(
    vintage_dates=[
        datetime(2024, 3, 15, tzinfo=timezone.utc),
        datetime(2025, 3, 15, tzinfo=timezone.utc),
        datetime(2026, 3, 15, tzinfo=timezone.utc),
    ],
    strategy="final",
)
print(list(comparison.comparison.keys()))
```

```python
['vintage_2024-03-08T00:00:00-06:00_to_2026-03-06T00:00:00-06:00',
 'vintage_2025-03-07T00:00:00-06:00_to_2026-03-06T00:00:00-06:00']
```

The keys reflect the *resolved* release dates, not the calendar dates that were requested. Here, each mid-March date was resolved back to that month's PAYEMS release (issued the first Friday of the month), so the labels show what was actually compared.

```python
pair_key = "vintage_2024-03-08T00:00:00-06:00_to_2026-03-06T00:00:00-06:00"
print(comparison.comparison[pair_key])
```

Numeric values below are shown rounded to four decimals for readability.

```python
{'bias': 0.0,
 'relative_bias': 0.0022,
 'dispersion': 0.0,
 'relative_dispersion': 0.0078,
 'largest_upward_revision': -0.0006,
 'largest_downward_revision': 0.0009,
 'standard_deviation_of_revisions_difference': 0.0001,
 'counts': {'upward': 196, 'downward': 207, 'no_change': 618},
 'directional_misses_trend': 0.0029}
```

For the 2024-03-08 vs 2026-03-06 pair, growth-rate revisions are roughly symmetric (196 up, 207 down, 618 unchanged out of 1,021 timestamps). The largest single upward revision moved the growth rate by about 0.06 percentage points (`-0.0006` under the Young sign convention) and the largest downward revision by about 0.09 percentage points. Only 0.29% of timestamps disagreed about whether the series rose or fell between the two vintages.

Switch `strategy` or `mode` to slice the same vintages a different way. In levels mode, the same pair looks like:

```python
levels = payems.analysis.vintage_comparison(
    vintage_dates=[
        datetime(2024, 3, 15, tzinfo=timezone.utc),
        datetime(2025, 3, 15, tzinfo=timezone.utc),
        datetime(2026, 3, 15, tzinfo=timezone.utc),
    ],
    strategy="final",
    mode="levels",
)
print(levels.comparison[pair_key])
```

```python
{'bias': 2.8131,
 'relative_bias': 0.0,
 'dispersion': 5.5587,
 'relative_dispersion': 0.0001,
 'largest_upward_revision': -88.0,
 'largest_downward_revision': 570.0,
 'standard_deviation_of_revisions_difference': 33.895,
 'counts': {'upward': 178, 'downward': 193, 'no_change': 651},
 'directional_misses_sign': 0.0,
 'directional_misses_trend': 0.0029}
```

In levels mode, `bias` and `dispersion` are in the units of the underlying series (thousands of persons, for PAYEMS), and an extra `directional_misses_sign` measure reports the share of timestamps where the level itself crosses zero between vintages. PAYEMS never goes negative, so it stays at `0.0`.

This is a compact way to compare selected vintages without inspecting the full vintage matrix by hand.
