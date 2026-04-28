# Reproducible Research / Frozen Snapshots

When reviewing academic projects, the goal is not to download the latest vintage data, but rather reload the same data which was used in the paper. MacroTrace supports this by storing fetched data locally in `MacroTrace.db`. This can be published alongside code and notebooks to allow others to load the same snapshot of data without needing to fetch from the source again.

## Step 1: Fetch and Store the Data Once

On the first run, load the series as normal. MacroTrace will fetch the data, store it locally, and build the vintage history.

```python
from macrotrace import MTTimeSeries

payems = MTTimeSeries(
    dataset_id="PAYEMS",
    source="fred",
)
```

## Step 2: Reload the Same Snapshot Later

Once the series is stored locally (in `MacroTrace.db`), you can reopen it without refreshing from the source.

```python
from macrotrace import MTTimeSeries

frozen_payems = MTTimeSeries(
    dataset_id="PAYEMS",
    source="fred",
    update_prior_to_load=False, # This tells MacroTrace to load from the local database without fetching new data
)

print(f"Latest vintage date: {frozen_payems.release_date:%Y-%m-%d}")
```

```python
Latest vintage date: 2026-03-06
```

## A Practical Workflow for Replication

For a paper or appendix, a practical workflow is:

1. Fetch the series once and note the latest vintage date.
2. Keep the resulting `MacroTrace.db` file with your project files.
3. In replication scripts, load the series with `update_prior_to_load=False`.
4. Refresh ***only*** when you deliberately move to a newer snapshot.

This is especially useful when you want coauthors, referees, or future-you to work from exactly the same stored vintages rather than silently pulling newer revisions.
