import pytest
from datetime import datetime, timedelta, timezone
from typing import List

from peewee import SqliteDatabase
import pytz

from macrotrace.models import MTTimeSeries, MTObservation, MTSeriesMetadata
from macrotrace.models.db import (
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
)

SAMPLE_START_DATE = datetime(2024, 12, 1, tzinfo=timezone.utc)
SAMPLE_END_DATE = datetime(2024, 12, 14, tzinfo=timezone.utc)
SAMPLE_STARTING_VALUE = 100.0
ASC = True

SAMPLE_DATASET_ID = "TEST"
SAMPLE_DATASET_SOURCE = "TEST_SOURCE"
SAMPLE_DATASET_UNITS = "Billions of Dollars"
SAMPLE_DATASET_FREQUENCY = "D"
SAMPLE_TITLE = "Gross TEST Product"
SAMPLE_SEASONAL_ADJUSTMENT = "Seasonally Adjusted"

db = SqliteDatabase(":memory:")
UTC = pytz.timezone("UTC")


# Note that importing db_setup_and_teardown fixture within test .py files sets up and tears down the database for each test automatically
@pytest.fixture(scope="function", autouse=True)
def db_setup_and_teardown():
    # Bind models to test DB
    models = [
        Dataset,
        DatasetDimension,
        Release,
        ReleaseDimension,
        Series,
        SeriesDimensionFilter,
        Observation,
    ]
    db.bind(models, bind_refs=False, bind_backrefs=False)
    db.connect(reuse_if_open=True)
    db.create_tables(models)

    yield

    db.drop_tables(models)
    db.close()


def make_observations(
    start_datetime: datetime,
    end_datetime: datetime,
    start_value: float,
    ascending=True,
    revision_window_days=None,
) -> list[MTObservation]:
    """
    Makes a list of MTObservation objects for a range of dates.
    The values either grow or shrink by one per day depending on the `ascending` flag.

    Example:
        start = datetime.today() - timedelta(days=4)
        end = datetime.today()
        make_observations(start, end, 100.0, ascending=True) Provides us with...
        [
            MTObservation(timestamp=start,         value=100.0, release_date=start + 1 day),
            MTObservation(timestamp=start + 1 day, value=101.0, release_date=start + 2 days),
            MTObservation(timestamp=start + 2 day, value=102.0, release_date=start + 3 days),
            MTObservation(timestamp=start + 3 day, value=103.0, release_date=start + 4 days),
            MTObservation(timestamp=end,           value=104.0, release_date=end + 1 day)
        ]

    Args:
        start_datetime (datetime): The starting datetime for observations.
        end_datetime (datetime): The ending datetime for observations.
        start_value (float): The starting value for the observations.
        ascending (bool): Whether the values should ascend or descend.
        revision_window_days (int, optional): The number of days after which revisions occur. Defaults to None.
            None means no revisions for the series.

    Returns:
        list[MTObservation]: A list of MTObservation objects.
    """
    observations = []
    current_date = start_datetime
    day_offset = 0
    release_date = end_datetime + timedelta(days=1)

    while current_date <= end_datetime:
        # Calculate base value
        final_value = start_value + (day_offset if ascending else -day_offset)

        # If we are provided a revision window, calculate the revision
        if revision_window_days is not None:
            # Calculate revision if observation is older than revision window
            days_since_observation = (release_date - current_date).days
            if days_since_observation > revision_window_days:
                revision_days = min(
                    days_since_observation - revision_window_days, revision_window_days
                )
                revision_amount = revision_days * (1 if ascending else -1)
                final_value += revision_amount

        observations.append(
            MTObservation(
                timestamp=current_date,
                value=final_value,
                release_date=release_date,
            )
        )
        current_date += timedelta(days=1)
        day_offset += 1

    return observations


def make_vintages(
    start_datetime: datetime,
    end_datetime: datetime,
    start_value: float,
    ascending=True,
    revision_window_days=None,
) -> List[MTTimeSeries]:
    """
    Creates a list of MTTimeSeries objects for a range of dates with observations up until each release date.
    Utilizes the make_observations function to generate the current observations.

    Example:
        start = datetime.today() - timedelta(days=4)
        end = datetime.today()
        make_vintages(start, end, 100.0, ascending=True) Provides us with...
        [
            MTTimeSeries(
                dataset_id="id",
                source="source",
                release_date=start,
                current_observations=[observations from start to start],
                vintages=[]
            ),
            MTTimeSeries(
                dataset_id="id",
                source="source",
                release_date=start + 1 day,
                current_observations=[observations from start to start + 1 day],
                vintages=[previous vintage]
            )...
        ]

    Args:
        start_datetime (datetime): The starting datetime for the vintage range.
        end_datetime (datetime): The ending datetime for the vintage range.
        start_value (float): The starting value for the observations.
        ascending (bool): Whether the values should ascend or descend.
        revision_window_days (int, optional): The number of days after which revisions occur. Defaults to None.
            None means no revisions for the series.

    Returns:
        List[MTTimeSeries]: A list of MTTimeSeries objects.
    """
    time_series_list = []
    current_observation_date = start_datetime

    while current_observation_date <= end_datetime:
        time_series_list.append(
            MTTimeSeries._from_data(
                dataset_id="TEST",
                release_date=current_observation_date + timedelta(days=1),
                current_observations=make_observations(
                    start_datetime,
                    current_observation_date,
                    start_value=start_value,
                    ascending=ascending,
                    revision_window_days=revision_window_days,
                ),
                # Recall each vintage contains all prior vintages
                # Shallow copy to avoid mutating prior vintages
                vintages=time_series_list[:],
                source="TEST_SOURCE",
                frequency="D",
                seasonal_adjustment="Seasonally Adjusted",
                units="Billions of Dollars",
                title="Gross TEST Product",
            ),
        )
        current_observation_date += timedelta(days=1)

    return time_series_list


def sample_observations(revision_window_days=None):
    return make_observations(
        SAMPLE_START_DATE,
        SAMPLE_END_DATE + timedelta(days=1),
        SAMPLE_STARTING_VALUE,
        ascending=ASC,
        revision_window_days=revision_window_days,
    )


def sample_vintages(revision_window_days=None):
    return make_vintages(
        SAMPLE_START_DATE,
        SAMPLE_END_DATE,
        SAMPLE_STARTING_VALUE,
        ascending=ASC,
        revision_window_days=revision_window_days,
    )


@pytest.fixture()
def empty_timeseries():
    """Used for testing methods"""

    ts = MTTimeSeries._from_data(
        dataset_id="TEST",
        source="TEST_SOURCE",
        release_date=datetime.today(),
        current_observations=[],
        vintages=[],
        frequency="D",
        seasonal_adjustment="Seasonally Adjusted",
        units="Billions of Dollars",
        title="Gross TEST Product",
    )

    ts.data_end_date = None
    ts.data_start_date = None
    ts.vintage_start_date = None
    ts.vintage_end_date = None
    ts.series_key = None

    return ts


@pytest.fixture
def sample_time_series():
    observations = sample_observations()
    vintages = sample_vintages()

    ts = MTTimeSeries._from_data(
        dataset_id=SAMPLE_DATASET_ID,
        release_date=SAMPLE_END_DATE + timedelta(days=2),
        current_observations=observations,
        vintages=vintages,
        source=SAMPLE_DATASET_SOURCE,
        units=SAMPLE_DATASET_UNITS,
        frequency=SAMPLE_DATASET_FREQUENCY,
        title=SAMPLE_TITLE,
        seasonal_adjustment=SAMPLE_SEASONAL_ADJUSTMENT,
    )
    return ts


@pytest.fixture
def sample_time_series_with_revisions():
    observations = sample_observations(revision_window_days=3)
    vintages = sample_vintages(revision_window_days=3)

    ts = MTTimeSeries._from_data(
        dataset_id=SAMPLE_DATASET_ID,
        release_date=SAMPLE_END_DATE + timedelta(days=2),
        current_observations=observations,
        vintages=vintages,
        source=SAMPLE_DATASET_SOURCE,
        units=SAMPLE_DATASET_UNITS,
        frequency=SAMPLE_DATASET_FREQUENCY,
        title=SAMPLE_TITLE,
        seasonal_adjustment=SAMPLE_SEASONAL_ADJUSTMENT,
    )
    return ts
