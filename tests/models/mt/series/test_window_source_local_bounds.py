import datetime as dt

import pytest
import pytz

from macrotrace.models.db import (
    Dataset,
    DatasetDimension,
    Observation,
    Release,
    Series,
)
from macrotrace.models.mt.time_series import MTTimeSeries
from tests.models.mt.utils import *  # noqa: F401,F403

CENTRAL = pytz.timezone("America/Chicago")
UTC_TZ = dt.timezone.utc

JAN_RELEASE = CENTRAL.localize(dt.datetime(2018, 1, 17))  # CST, -06:00
FEB_RELEASE = CENTRAL.localize(dt.datetime(2018, 2, 15))  # CST, -06:00
MAR_RELEASE = CENTRAL.localize(dt.datetime(2018, 3, 16))  # CDT, -05:00
# A UTC-midnight stamp on the next day guards the end bound against
# off-by-one inclusion past the requested day.
NEXT_DAY_UTC_RELEASE = dt.datetime(2018, 3, 17, tzinfo=UTC_TZ)

OBSERVATION_MONTHS = [
    CENTRAL.localize(dt.datetime(2017, 11, 1)),
    CENTRAL.localize(dt.datetime(2017, 12, 1)),
    CENTRAL.localize(dt.datetime(2018, 1, 1)),
    CENTRAL.localize(dt.datetime(2018, 2, 1)),
]


@pytest.fixture
def central_stamped_dataset():
    """Seed a FRED-shaped dataset whose stamps sit at midnight US Central."""
    dataset = Dataset.create(source="FRED", dataset_id="WINDOWED")
    series = Series.create(dataset=dataset, series_key={})
    DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="WINDOWED",
        title="Windowed",
        type="text",
        frequency="MS",
        units="Index",
        seasonal_adjustment=None,
        valid_from=dt.datetime(2000, 1, 1, tzinfo=UTC_TZ),
        valid_to=None,
    )

    releases = [JAN_RELEASE, FEB_RELEASE, MAR_RELEASE, NEXT_DAY_UTC_RELEASE]
    for i, release_date in enumerate(releases):
        release = Release.create(dataset=dataset, release_date=release_date)
        # Each release carries one more month of history, ending with the
        # 2018-02-01 print first published in the 2018-03-16 release.
        for timestamp in OBSERVATION_MONTHS[: i + 2]:
            Observation.create(
                series=series,
                release=release,
                observation_timestamp=timestamp,
                value=100.0 + i,
            )


def load_windowed(**kwargs):
    return MTTimeSeries(
        dataset_id="WINDOWED",
        source="FRED",
        update_prior_to_load=False,
        **kwargs,
    )


def test_vintage_end_date_includes_same_day_source_local_release(
    central_stamped_dataset,
):
    ts = load_windowed(vintage_end_date="2018-03-16")
    release_dates = [v.release_date for v in ts._vintages_including_current_series]

    assert MAR_RELEASE in release_dates  # the regression
    assert NEXT_DAY_UTC_RELEASE not in release_dates  # nothing past the day


def test_vintage_end_date_aware_instant_still_compares_exactly(
    central_stamped_dataset,
):
    # Midnight UTC precedes the 05:00 UTC Central-midnight stamp, so an
    # explicit aware instant keeps excluding the same-day release.
    ts = load_windowed(vintage_end_date=dt.datetime(2018, 3, 16, tzinfo=UTC_TZ))

    assert ts.release_date == FEB_RELEASE


def test_vintage_window_single_calendar_day(central_stamped_dataset):
    ts = load_windowed(vintage_start_date="2018-03-16", vintage_end_date="2018-03-16")
    release_dates = [v.release_date for v in ts._vintages_including_current_series]

    assert release_dates == [MAR_RELEASE]


def test_data_end_date_includes_same_day_source_local_observation(
    central_stamped_dataset,
):
    ts = load_windowed(
        vintage_start_date="2018-03-16",
        vintage_end_date="2018-03-16",
        data_end_date="2018-02-01",
    )
    timestamps = [obs.timestamp for obs in ts.current_observations]

    assert OBSERVATION_MONTHS[-1] in timestamps  # the 2018-02-01 print survives


def test_data_window_aware_instants_still_compare_exactly(central_stamped_dataset):
    # Midnight UTC precedes the Central-midnight observation stamp (06:00 UTC
    # under CST), so an explicit aware instant keeps excluding the same-day print.
    ts = load_windowed(
        vintage_start_date="2018-03-16",
        vintage_end_date="2018-03-16",
        data_end_date=dt.datetime(2018, 2, 1, tzinfo=UTC_TZ),
    )
    timestamps = [obs.timestamp for obs in ts.current_observations]

    assert OBSERVATION_MONTHS[-1] not in timestamps
