"""
Regression tests for FRED timezone handling.

Background
----------
Earlier versions of ``macrotrace/sources/fred.py`` localised parsed FRED dates
with the broken pytz idiom ``datetime(...).replace(tzinfo=US_CENTRAL)``. When a
``pytz`` zone is bound via ``tzinfo=`` directly (instead of via
``US_CENTRAL.localize(...)``) pytz applies its *first* historical entry for the
zone, which for ``America/Chicago`` is Local Mean Time (LMT) at -05:50:36 — not
CST/CDT. The resulting datetimes were ~9 minutes off true CST midnight, which
silently rolled observation timestamps to the previous day after a downstream
``tz_convert`` + ``normalize`` (the symptom that surfaced in the
``6_1_revision_dynamics`` notebook, where December PAYEMS observations
appeared as ``2021-11-30 -06:00`` instead of ``2021-12-01 -06:00``).

These tests pin the offset of every FRED-localised datetime to a real Chicago
offset (-05:00 CDT or -06:00 CST) so the LMT regression cannot return.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest

from macrotrace.models.db import Dataset, Release, Series
from macrotrace.sources.base import UpdateState
from macrotrace.sources.fred import (
    FredDatasetManager,
    FredObservationManager,
    FredReleaseManager,
)

# Note: importing db_setup_and_teardown wires the in-memory test DB for each test.
from tests.sources.fred.fixtures import (
    api_client,
    db_setup_and_teardown,
    empty_state,
    US_CENTRAL,
)

LMT_OFFSET = timedelta(hours=-5, minutes=-50, seconds=-36)
CST_OFFSET = timedelta(hours=-6)
CDT_OFFSET = timedelta(hours=-5)


def _assert_real_chicago_offset(dt: datetime) -> None:
    """Fail if ``dt`` is in pytz LMT (-05:50:36) instead of real CST/CDT."""
    assert dt.tzinfo is not None, f"expected tz-aware datetime, got naive {dt!r}"
    offset = dt.utcoffset()
    assert offset != LMT_OFFSET, (
        f"datetime {dt!r} is in pytz LMT (-05:50:36) — this is the "
        "`.replace(tzinfo=US_CENTRAL)` regression. Use US_CENTRAL.localize() instead."
    )
    assert offset in (CST_OFFSET, CDT_OFFSET), (
        f"datetime {dt!r} has unexpected offset {offset}; "
        f"expected CST ({CST_OFFSET}) or CDT ({CDT_OFFSET})."
    )


@pytest.mark.parametrize(
    "date_str,expected_offset",
    [
        ("2023-01-15", CST_OFFSET),  # mid-January, CST
        ("2023-07-15", CDT_OFFSET),  # mid-July, CDT
        # DST transitions happen at 02:00 local time, so midnight on the
        # transition day is still in the *previous* offset.
        ("2023-03-12", CST_OFFSET),  # 2023 DST starts March 12 at 02:00
        ("2023-11-05", CDT_OFFSET),  # 2023 DST ends November 5 at 02:00
        ("2023-03-13", CDT_OFFSET),  # day after DST start — fully CDT
        ("2023-11-06", CST_OFFSET),  # day after DST end — fully CST
    ],
)
def test_parse_date_uses_real_chicago_offset(api_client, date_str, expected_offset):
    """_parse_date must localise naive date strings to real CST/CDT, not LMT."""
    dm = FredDatasetManager(api_client=api_client)
    parsed = dm._parse_date(date_str)
    _assert_real_chicago_offset(parsed)
    assert parsed.utcoffset() == expected_offset


@pytest.mark.parametrize(
    "naive_dt,expected_offset",
    [
        (datetime(2020, 1, 1), CST_OFFSET),
        (datetime(2020, 7, 1), CDT_OFFSET),
        (datetime(2020, 3, 8, 3, 0, 0), CDT_OFFSET),  # just after DST start
        (datetime(2020, 11, 1, 1, 30, 0), CST_OFFSET),  # 2020 DST ends Nov 1
    ],
)
def test_ensure_us_central_uses_real_chicago_offset(
    api_client, naive_dt, expected_offset
):
    """_ensure_us_central must localise naive datetimes to real CST/CDT, not LMT."""
    rm = FredReleaseManager(api_client=api_client)
    converted = rm._ensure_us_central(naive_dt)
    _assert_real_chicago_offset(converted)
    assert converted.utcoffset() == expected_offset


def test_fetch_new_releases_localises_release_dates_correctly(api_client, empty_state):
    """
    Release dates returned from fetch_new_releases must be in real CST/CDT.
    Pre-fix, every release_date was LMT; downstream code computing
    ``release_date.tz_convert("UTC")`` would drift by 9 minutes per release.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="FRED")
    state.dataset = dataset

    api_client.make_request = MagicMock(
        return_value={
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "vintage_dates": [
                "2023-01-15",  # CST
                "2023-07-15",  # CDT
                "2023-12-01",  # CST
            ],
        }
    )

    rm = FredReleaseManager(api_client=api_client)
    new_releases = rm.fetch_new_releases(state)

    assert len(new_releases) == 3
    expected_offsets = [CST_OFFSET, CDT_OFFSET, CST_OFFSET]
    for release, expected_offset in zip(new_releases, expected_offsets):
        _assert_real_chicago_offset(release.release_date)
        assert release.release_date.utcoffset() == expected_offset


@pytest.mark.parametrize(
    "key,expected_offset",
    [
        ("PAYEMS_20210712", CDT_OFFSET),
        ("PAYEMS_20211201", CST_OFFSET),
        ("PAYEMS_19960401", CST_OFFSET),  # 1996 DST started April 7
    ],
)
def test_clean_vintage_str_date_uses_real_chicago_offset(
    api_client, key, expected_offset
):
    """_clean_vintage_str_date must localise to real CST/CDT, not LMT."""
    om = FredObservationManager(api_client=api_client)
    cleaned = om._clean_vintage_str_date(key)
    _assert_real_chicago_offset(cleaned)
    assert cleaned.utcoffset() == expected_offset


def test_create_new_observations_localises_observation_timestamps(
    api_client, empty_state
):
    """
    The observation_timestamp on every persisted Observation must be in real
    CST/CDT. This is the most important assertion: it is the field that
    surfaces in MTTimeSeries / analysis.select_vintage_by_index() and
    triggered the original notebook bug.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="PAYEMS", source="FRED")
    state.dataset = dataset

    release_dec = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2021, 12, 3))
    )
    release_jul = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2021, 7, 2))
    )

    series = Series.create(dataset=dataset, series_key={})
    state.series = series

    # FRED returns one row per timestamp; values keyed by "{series}_YYYYMMDD".
    # The two cases below straddle DST so we exercise both CST and CDT.
    obs_data = [
        # December 2021 PAYEMS observation, released Dec 3 2021 (CST).
        {"date": "2021-12-01", "PAYEMS_20211203": 158_000.0},
        # June 2021 PAYEMS observation, released Jul 2 2021 (CDT).
        {"date": "2021-06-01", "PAYEMS_20210702": 152_000.0},
    ]
    release_dates_to_id = {
        release_dec.release_date: release_dec.id,
        release_jul.release_date: release_jul.id,
    }

    om = FredObservationManager(api_client=api_client)
    new_observations = om._create_new_observations(state, obs_data, release_dates_to_id)

    assert len(new_observations) == 2
    for obs in new_observations:
        _assert_real_chicago_offset(obs.observation_timestamp)

    by_value = {o.value: o for o in new_observations}
    assert by_value[158_000.0].observation_timestamp.utcoffset() == CST_OFFSET
    assert by_value[152_000.0].observation_timestamp.utcoffset() == CDT_OFFSET


# Notebook reproduction: tz_convert + normalize must not roll back the day.
@pytest.mark.parametrize(
    "iso_date",
    [
        "2021-12-01",  # December (CST) — was the original failing case
        "2020-03-01",  # March 2020 (CST until Mar 8) — leap year edge
        "1996-04-01",  # April 1996 (CST until Apr 7) — pre-2007 DST rules
        "2021-01-01",  # January (CST)
        "1994-11-01",  # November (CST)
        "2021-07-01",  # July (CDT) — control case
        "2021-11-01",  # early November (still CDT in 2021)
    ],
)
def test_observation_timestamp_survives_tz_convert_normalize_roundtrip(
    api_client, empty_state, iso_date
):
    """
    Mimic the notebook pipeline that exposed the bug:

        pd.to_datetime(ts, utc=True).dt.tz_convert("America/Chicago").dt.normalize()

    With the LMT bug, December/January/etc dates rolled back one day (e.g.
    2021-12-01 -> 2021-11-30). After the fix, the calendar date must be
    preserved through the round trip for every month of the year.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="PAYEMS", source="FRED")
    state.dataset = dataset

    release = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2030, 1, 1))
    )
    series = Series.create(dataset=dataset, series_key={})
    state.series = series

    release_key = f"PAYEMS_{release.release_date.strftime('%Y%m%d')}"
    obs_data = [{"date": iso_date, release_key: 100.0}]

    om = FredObservationManager(api_client=api_client)
    [obs] = om._create_new_observations(
        state, obs_data, {release.release_date: release.id}
    )

    _assert_real_chicago_offset(obs.observation_timestamp)

    # The notebook round trip:
    series = pd.Series([obs.observation_timestamp])
    normalized = (
        pd.to_datetime(series, utc=True).dt.tz_convert(US_CENTRAL).dt.normalize()
    )

    expected = datetime.strptime(iso_date, "%Y-%m-%d").date()
    assert normalized.iloc[0].date() == expected, (
        f"calendar date drifted after tz_convert+normalize: "
        f"{iso_date} -> {normalized.iloc[0]}"
    )
