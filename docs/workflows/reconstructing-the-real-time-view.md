# Reconstructing the Real-Time View

One of the most common real-time data questions is: what did this series look like at the time? Macrotrace provides an `as_of()` method to reconstruct the vintage available on any historical date. This is a critical starting point for replication work, as it allows researchers to understand what data was actually available to forecasters, policymakers, and analysts at the time they were making decisions.

## Load the Series

We will use the FRED `PAYEMS` series, which tracks total nonfarm payroll employment in the United States.

```python
from macrotrace import MTTimeSeries

payems = MTTimeSeries(
    dataset_id="PAYEMS",
    source="fred",
)
```

## Recover the Vintage Available on a Historical Date

The `as_of()` method returns the most recent vintage available on or before the date you choose.

```python
from datetime import datetime, timezone

realtime_payems = payems.as_of(
    datetime(2020, 7, 15, tzinfo=timezone.utc)
)
print(realtime_payems)
```

```python
Time Series: PAYEMS (All Employees, Total Nonfarm)
Source: FRED
Units: Thousands of Persons
Latest Vintage Date: 2020-07-02
Vintages: 785 available from 1955-05-06 to 2020-07-02
+------------+----------+
| Timestamp  |  Value   |
+------------+----------+
| 2019-09-01 | 151368.0 |
| 2019-10-01 | 151553.0 |
| 2019-11-01 | 151814.0 |
| 2019-12-01 | 151998.0 |
| 2020-01-01 | 152212.0 |
| 2020-02-01 | 152463.0 |
| 2020-03-01 | 151090.0 |
| 2020-04-01 | 130303.0 |
| 2020-05-01 | 133002.0 |
| 2020-06-01 | 137802.0 |
+------------+----------+
```
