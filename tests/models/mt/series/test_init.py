import os
import pytest
from unittest.mock import MagicMock, patch
import pandas as pd

from macrotrace.models.db import Observation, Release, Dataset, Series
from macrotrace.models.mt.time_series import VALID_SOURCES
from macrotrace.sources.base import UpdateManager
from tests.models.mt.utils import *
from macrotrace.models.db import DatasetDimension, SeriesDimensionFilter


def test_set_valid_source(empty_timeseries):
    """Test that MTTimeSeries._set_source sets valid sources correctly"""
    for source in VALID_SOURCES:
        empty_timeseries._set_source(source)
        assert empty_timeseries.source == source.upper()


def test_set_invalid_source(empty_timeseries):
    """Test that MTTimeSeries._set_source raises ValueError for invalid sources"""
    with pytest.raises(ValueError):
        empty_timeseries._set_source("INVALID_SOURCE")


def test_clean_date_none(empty_timeseries):
    """Test that MTTimeSeries._clean_date returns None when given None"""
    dt = empty_timeseries._clean_date(None)
    assert dt is None


def test_clean_date_str_ntz(empty_timeseries):
    """Test that MTTimeSeries._clean_date cleans a date string with no timezone correctly and sets UTC"""
    dt = empty_timeseries._clean_date("2023-05-15")
    assert dt == datetime(2023, 5, 15, tzinfo=UTC)


def test_clean_date_str_tz(empty_timeseries):
    """Test that MTTimeSeries._clean_date cleans a date string with timezone correctly"""
    dt = empty_timeseries._clean_date("2023-05-15T12:00:00+08:00")
    assert dt == datetime(2023, 5, 15, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))


def test_clean_date_datetime_with_tz(empty_timeseries):
    """Test that MTTimeSeries._clean_date cleans a datetime object correctly"""
    dt = datetime(2023, 5, 15, tzinfo=UTC)
    cleaned_dt = empty_timeseries._clean_date(dt)
    assert cleaned_dt == dt


def test_clean_date_datetime_no_tz(empty_timeseries):
    """Test that MTTimeSeries._clean_date cleans a datetime object with no timezone correctly and sets UTC"""
    dt = datetime(2023, 5, 15)
    cleaned_dt = empty_timeseries._clean_date(dt)
    assert cleaned_dt.tzinfo == timezone.utc


def test_clean_date_invalid_type(empty_timeseries):
    """Test that MTTimeSeries._clean_date raises TypeError for invalid input types"""
    with pytest.raises(TypeError):
        empty_timeseries._clean_date(12345)  # Invalid type


def test_get_valid_dimension_from_date(empty_timeseries):
    """Test that the MTTimeSeries._get_valid_dimension_from_date gets the valid dimension from a date correctly"""

    dim1 = MagicMock()
    dim1.valid_from = datetime(2020, 1, 1, tzinfo=UTC)
    dim1.valid_to = datetime(2021, 1, 1, tzinfo=UTC)

    dim2 = MagicMock()
    dim2.valid_from = datetime(2021, 1, 2, tzinfo=UTC)
    dim2.valid_to = datetime(2022, 1, 1, tzinfo=UTC)

    dim3 = MagicMock()
    dim3.valid_from = datetime(2022, 1, 2, tzinfo=UTC)
    dim3.valid_to = None  # ongoing

    dimensions = [
        dim1,
        dim2,
        dim3,
    ]

    as_of_date = datetime(2021, 6, 1, tzinfo=UTC)
    valid_dim = empty_timeseries._get_valid_dimension_from_date(dimensions, as_of_date)
    assert valid_dim == dim2


def test_get_valid_dimension_from_date_ongoing(empty_timeseries):
    """Test that the MTTimeSeries._get_valid_dimension_from_date gets the valid dimension for an ongoing dimension correctly"""

    dim1 = MagicMock()
    dim1.valid_from = datetime(2020, 1, 1, tzinfo=UTC)
    dim1.valid_to = datetime(2021, 1, 1, tzinfo=UTC)

    dim2 = MagicMock()
    dim2.valid_from = datetime(2021, 1, 2, tzinfo=UTC)
    dim2.valid_to = None  # ongoing

    dimensions = [
        dim1,
        dim2,
    ]

    as_of_date = datetime(2023, 6, 1, tzinfo=UTC)
    valid_dim = empty_timeseries._get_valid_dimension_from_date(dimensions, as_of_date)
    assert valid_dim == dim2


def test_get_valid_dimension_from_date_no_match(empty_timeseries):
    """Test that the MTTimeSeries raises a ValueError when no valid dimension is found"""

    dim1 = MagicMock()
    dim1.valid_from = datetime(2020, 1, 1, tzinfo=UTC)
    dim1.valid_to = datetime(2020, 12, 31, tzinfo=UTC)

    dim2 = MagicMock()
    dim2.valid_from = datetime(2021, 1, 1, tzinfo=UTC)
    dim2.valid_to = datetime(2021, 12, 31, tzinfo=UTC)
    dimensions = [
        dim1,
        dim2,
    ]

    with pytest.raises(ValueError):
        as_of_date = datetime(2022, 1, 1, tzinfo=UTC)
        empty_timeseries._get_valid_dimension_from_date(dimensions, as_of_date)


def test_strip_empty_observations_start(empty_timeseries):
    """Test that the MTTimeSeries._strip_empty_observations() removes observations with None values at the start"""

    obs1 = MagicMock()
    obs1.value = None
    obs2 = MagicMock()
    obs2.value = None
    obs3 = MagicMock()
    obs3.value = 10
    obs4 = MagicMock()
    obs4.value = 20

    observations = [obs1, obs2, obs3, obs4]
    cleaned_observations = empty_timeseries._strip_empty_observations(observations)
    assert cleaned_observations == [obs3, obs4]


def test_strip_empty_observations_end(empty_timeseries):
    """Test that the MTTimeSeries._strip_empty_observations() removes observations with None values at the end"""

    obs1 = MagicMock()
    obs1.value = 10
    obs2 = MagicMock()
    obs2.value = 20
    obs3 = MagicMock()
    obs3.value = None
    obs4 = MagicMock()
    obs4.value = None

    observations = [obs1, obs2, obs3, obs4]
    cleaned_observations = empty_timeseries._strip_empty_observations(observations)
    assert cleaned_observations == [obs1, obs2]


def test_get_observations_for_release(empty_timeseries):
    """Test that the MTTimeSeries._get_observations_for_release() retrieves observations correctly"""

    dataset = Dataset.create(dataset_id="TEST", source=VALID_SOURCES[0])
    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )
    series = Series.create(dataset=dataset, series_key={})

    obs1 = Observation.create(
        series=series,
        release=release,
        value=100,
        observation_timestamp=datetime(2022, 12, 31, tzinfo=UTC),
    )
    obs2 = Observation.create(
        series=series,
        release=release,
        value=200,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )
    obs3 = Observation.create(
        series=series,
        release=release,
        value=300,
        observation_timestamp=datetime(2023, 1, 2, tzinfo=UTC),
    )

    observations = empty_timeseries._get_observations_for_release(release.id)
    assert len(observations) == 3
    obs_values = [obs.value for obs in observations]
    assert obs_values == [100, 200, 300]


def test_get_observations_for_release_strip_start(empty_timeseries):
    """Test that the MTTimeSeries._get_observations_for_release() strips None values at the start"""

    dataset = Dataset.create(dataset_id="TEST", source=VALID_SOURCES[0])
    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )
    series = Series.create(dataset=dataset, series_key={})

    obs1 = Observation.create(
        series=series,
        release=release,
        value=None,
        observation_timestamp=datetime(2022, 12, 30, tzinfo=UTC),
    )
    obs2 = Observation.create(
        series=series,
        release=release,
        value=None,
        observation_timestamp=datetime(2022, 12, 31, tzinfo=UTC),
    )
    obs3 = Observation.create(
        series=series,
        release=release,
        value=300,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    observations = empty_timeseries._get_observations_for_release(release.id)
    assert len(observations) == 1
    assert observations[0].value == 300


def test_get_observations_for_release_strip_end(empty_timeseries):
    """Test that the MTTimeSeries._get_observations_for_release() strips None values at the end"""

    dataset = Dataset.create(dataset_id="TEST", source=VALID_SOURCES[0])
    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )
    series = Series.create(dataset=dataset, series_key={})

    obs1 = Observation.create(
        series=series,
        release=release,
        value=100,
        observation_timestamp=datetime(2022, 12, 30, tzinfo=UTC),
    )
    obs2 = Observation.create(
        series=series,
        release=release,
        value=None,
        observation_timestamp=datetime(2022, 12, 31, tzinfo=UTC),
    )
    obs3 = Observation.create(
        series=series,
        release=release,
        value=None,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    observations = empty_timeseries._get_observations_for_release(release.id)
    assert len(observations) == 1
    assert observations[0].value == 100


def test_get_update_manager_success(empty_timeseries):
    """Test that the MTTimeSeries._get_update_manager() returns an UpdateManager instance for each valid source"""
    valid_sources = VALID_SOURCES.copy()
    valid_sources.remove("USER")  # USER source does not have an UpdateManager

    # Set the env var for FRED API key to avoid errors
    os.environ["FRED_API_KEY"] = "test_api_key"

    for source in valid_sources:
        empty_timeseries.source = source
        update_manager = empty_timeseries._get_update_manager()

        assert isinstance(update_manager, UpdateManager)


def test_get_update_manager_invalid_source(empty_timeseries):
    """Test that the MTTimeSeries._get_update_manager() raises an AssertionError for an invalid source"""
    empty_timeseries.source = "INVALID_SOURCE"
    with pytest.raises(AssertionError):
        empty_timeseries._get_update_manager()


def test_fetch_or_load_state_calls_update(empty_timeseries):
    """Test that the MTTimeSeries._fetch_or_load_state() calls update_manager.update() when update_prior_to_load is True"""

    mock_update_manager = MagicMock(spec=UpdateManager)
    _ = empty_timeseries._fetch_or_load_state(
        mock_update_manager, update_prior_to_load=True
    )

    # Assert that we called update_manager.update()
    mock_update_manager.update.assert_called_once()


def test_fetch_or_load_state_does_not_call_update(empty_timeseries):
    """Test that the MTTimeSeries._fetch_or_load_state() does not call update_manager.update() when update_prior_to_load is False"""

    mock_update_manager = MagicMock(spec=UpdateManager)
    empty_timeseries._load_state_from_db = MagicMock(return_value="local-state")

    state = empty_timeseries._fetch_or_load_state(
        mock_update_manager,
        update_prior_to_load=False,
    )

    mock_update_manager.update.assert_not_called()
    empty_timeseries._load_state_from_db.assert_called_once_with()
    assert state == "local-state"


@patch("macrotrace.models.mt.time_series.Release")
def test_get_releases_query(mock_release_model, empty_timeseries):
    """Test the query in the MTTimeSeries._get_releases() method constructs the correct query chain."""

    mock_order_by_result = MagicMock()
    mock_where_result = MagicMock()
    mock_where_result.order_by.return_value = mock_order_by_result

    mock_select_result = MagicMock()
    mock_select_result.where.return_value = mock_where_result

    mock_release_model.select.return_value = mock_select_result

    dataset_pk = 999

    result = empty_timeseries._get_releases(dataset_pk=dataset_pk)

    # Verify the query chain was constructed correctly
    mock_release_model.select.assert_called_once()
    mock_select_result.where.assert_called_once()
    mock_where_result.order_by.assert_called_once()
    assert result == mock_order_by_result


def test_get_releases_with_db(empty_timeseries):
    """Test that the MTTimeSeries._get_releases() pulls releases from the database correctly"""

    dataset = Dataset.create(dataset_id="TEST", source="TEST")

    release1 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )
    release2 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 2, 1, tzinfo=UTC),
    )

    releases_query = empty_timeseries._get_releases(dataset_pk=dataset.id)

    releases = list(releases_query.execute())

    assert len(releases) == 2
    assert releases[0].release_date == datetime(2023, 1, 1, tzinfo=UTC)
    assert releases[1].release_date == datetime(2023, 2, 1, tzinfo=UTC)


def test_get_releases_filters_by_vintage_window(empty_timeseries):
    """Test that the MTTimeSeries._get_releases() respects vintage date filters."""

    dataset = Dataset.create(dataset_id="TEST_FILTERED", source="TEST")

    Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )
    Release.create(
        dataset=dataset,
        release_date=datetime(2023, 2, 1, tzinfo=UTC),
    )
    Release.create(
        dataset=dataset,
        release_date=datetime(2023, 3, 1, tzinfo=UTC),
    )

    empty_timeseries.vintage_start_date = datetime(2023, 2, 1, tzinfo=UTC)
    empty_timeseries.vintage_end_date = datetime(2023, 2, 28, tzinfo=UTC)

    releases_query = empty_timeseries._get_releases(dataset_pk=dataset.id)
    releases = list(releases_query.execute())

    assert len(releases) == 1
    assert releases[0].release_date == datetime(2023, 2, 1, tzinfo=UTC)


def test_get_release_with_no_releases(empty_timeseries):
    """Test that the MTTimeSeries._get_releases() returns an empty list when there are no releases for the dataset"""

    dataset = Dataset.create(dataset_id="TEST_NO_RELEASES", source="TEST")

    releases_query = empty_timeseries._get_releases(dataset_pk=dataset.id)

    releases = list(releases_query.execute())

    assert len(releases) == 0


@patch("macrotrace.models.mt.time_series.DatasetDimension")
def test_get_series_dimension_from_key_query(mock_dataset_dimension, empty_timeseries):
    """Test the query in the MTTimeSeries._get_series_dimension_from_key() method constructs the correct query chain."""

    # Mock the state object
    mock_state = MagicMock()
    mock_state.dataset.id = 1
    mock_state.series.id = 2

    # Set up the mock query chain
    mock_dim = MagicMock()
    mock_dim.dataset_dimension_id = "dimension-1"

    mock_where_result = MagicMock()
    # Mock needs to be iterable multiple times (for the set comprehension and list())
    mock_where_result.__iter__ = lambda self: iter([mock_dim])

    mock_join_result = MagicMock()
    mock_join_result.where.return_value = mock_where_result

    mock_select_result = MagicMock()
    mock_select_result.join.return_value = mock_join_result

    mock_dataset_dimension.select.return_value = mock_select_result

    result = empty_timeseries._get_series_dimension_from_key(mock_state)

    # Verify the query chain was constructed correctly
    mock_dataset_dimension.select.assert_called_once()
    mock_select_result.join.assert_called_once()
    mock_join_result.where.assert_called_once()
    assert result == [mock_dim]


def test_get_series_dimension_from_key_with_db(empty_timeseries):
    """Test that the MTTimeSeries._get_series_dimension_from_key() retrieves dimensions from the database correctly"""

    # Create test data
    dataset = Dataset.create(dataset_id="TEST", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    # Create a dataset dimension
    unfiltered_dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="test-dimension-1",
        title="Test Dimension 1",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    filtered_dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="test-dimension-2",
        title="Test Dimension 2",
        type="text",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    dimension_filter = SeriesDimensionFilter.create(
        series=series,
        dimension=filtered_dimension,
        value="exclude-me",
    )

    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    dimensions = empty_timeseries._get_series_dimension_from_key(mock_state)

    # Verify that only the unfiltered dimension is returned
    assert len(dimensions) == 1
    assert (
        dimensions[0].dataset_dimension_id == unfiltered_dimension.dataset_dimension_id
    )


def test_get_series_dimension_from_key_no_match(empty_timeseries):
    """Test that the MTTimeSeries._get_series_dimension_from_key() raises ValueError when no dimensions match"""
    # Create test data but with filters that exclude the dimension
    dataset = Dataset.create(dataset_id="TEST_NO_MATCH", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="test-dimension-1",
        title="Test Dimension 1",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    # Create a filter that will exclude this dimension
    SeriesDimensionFilter.create(
        series=series,
        dimension=dimension,
        value=1,
    )

    # Create mock state
    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    # Should raise ValueError because no dimensions match (the filter excludes it)
    with pytest.raises(ValueError, match="did not uniquely identify"):
        empty_timeseries._get_series_dimension_from_key(mock_state)


def test_get_series_dimension_from_key_duplicate_match(empty_timeseries):
    """Test that the MTTimeSeries._get_series_dimension_from_key() raises ValueError when more dimensions match or don't have a filter"""
    # Create test data but with filters that exclude the dimension
    dataset = Dataset.create(dataset_id="TEST_NO_MATCH", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="test-dimension-1",
        title="Test Dimension 1",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    dimension2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="test-dimension-2",
        title="Test Dimension 2",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    # Create mock state
    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    # Should raise ValueError because multiple dimensions match (no filters to exclude)
    with pytest.raises(ValueError, match="did not uniquely identify"):
        empty_timeseries._get_series_dimension_from_key(mock_state)


def test_load_from_dataframe():
    """Test that MTTimeSeries can be initialized from a Pandas DataFrame and contains the correct data"""
    df = pd.read_csv("tests/assets/mt/time_series/from_dataframe.csv")

    args = {
        "df": df,
        "dataset_id": "TEST_DF",
        "title": "Test Time Series from DataFrame",
        "units": "Index",
        "frequency": "MS",
        "seasonal_adjustment": "Seasonally Adjusted",
    }

    expected_vintage_info = [
        {"release_date": "2020-01-26", "n_obs": 972, "obs_sum": 86560444},
        {"release_date": "2021-01-26", "n_obs": 984, "obs_sum": 88255373},
        {"release_date": "2022-01-26", "n_obs": 996, "obs_sum": 90008745},
        {"release_date": "2023-01-26", "n_obs": 1008, "obs_sum": 91831543},
        {"release_date": "2024-01-26", "n_obs": 1020, "obs_sum": 93714693},
        {"release_date": "2025-01-26", "n_obs": 1032, "obs_sum": 95615545},
    ]

    ts = MTTimeSeries.from_dataframe(**args)

    # TS Checks
    assert ts.dataset_id == args["dataset_id"]
    assert ts.source == "USER"
    assert len(ts.current_observations) == 1044
    assert len(ts.vintages) == len(expected_vintage_info)
    assert sum(obs.value for obs in ts.current_observations) == 97518620
    assert ts.current_observations[0].timestamp == datetime(1939, 1, 1, tzinfo=UTC)
    assert ts.current_observations[-1].timestamp == datetime(2025, 12, 1, tzinfo=UTC)

    # Metadata checks
    assert ts.metadata.title == args["title"]
    assert ts.metadata.units == args["units"]
    assert ts.metadata.frequency == args["frequency"]
    assert ts.metadata.seasonal_adjustment == args["seasonal_adjustment"]

    # Vintage checks
    for i, v in enumerate(ts.vintages):
        expected_info = expected_vintage_info[i]
        assert v.release_date.strftime("%Y-%m-%d") == expected_info["release_date"]
        assert len(v.current_observations) == expected_info["n_obs"]
        assert len(v.vintages) == i


def test_load_dataframe_ntz_check(caplog):
    """Test that MTTimeSeries.from_dataframe logs a warning when timestamps lack timezone info"""
    df = pd.read_csv("tests/assets/mt/time_series/from_dataframe.csv")

    MTTimeSeries.from_dataframe(
        df=df,
        dataset_id="TEST_DF",
    )

    assert "Timestamp column has no timezone information. Assuming UTC." in caplog.text
    assert (
        "Release date column has no timezone information. Assuming UTC." in caplog.text
    )


def test_load_dataframe_with_tz():
    """Test that MTTimeSeries.from_dataframe handles timestamps with timezone info correctly"""
    df = pd.read_csv("tests/assets/mt/time_series/from_dataframe_with_tz.csv")

    ts = MTTimeSeries.from_dataframe(
        df=df,
        dataset_id="TEST_DF",
    )

    # Check that timestamps have Pacific timezone info
    assert ts.current_observations[0].timestamp.tzinfo == timezone(timedelta(hours=-8))
    assert ts.current_observations[-1].timestamp.tzinfo == timezone(timedelta(hours=-8))

    for v in ts.vintages:
        assert v.release_date.tzinfo == timezone(timedelta(hours=-8))
        assert v.current_observations[0].timestamp.tzinfo == timezone(
            timedelta(hours=-8)
        )


def test_load_dataframe_missing_column():
    """Test that MTTimeSeries.from_dataframe raises a ValueError when required columns are missing"""
    df = pd.read_csv("tests/assets/mt/time_series/from_dataframe.csv")

    for col in ["timestamp", "value", "release_date"]:
        df_dropped_col = df.drop(columns=[col])
        with pytest.raises(ValueError, match=f"Missing.*{col}"):
            MTTimeSeries.from_dataframe(
                df=df_dropped_col,
                dataset_id="TEST_DF",
            )


def test_init_with_valid_parameters():
    """Test that MTTimeSeries.__init__ properly initializes with valid parameters and loads data"""
    # Create test data in database
    dataset = Dataset.create(dataset_id="GDP", source="FRED")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="GDP",
        units="Billions of Dollars",
        frequency="QS",
        seasonal_adjustment="Seasonally Adjusted",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release1 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )

    release2 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 2, 1, tzinfo=UTC),
    )

    # Create observations
    for i, release in enumerate([release1, release2]):
        for j in range(3):
            Observation.create(
                series=series,
                release=release,
                value=100 + i * 10 + j,
                observation_timestamp=datetime(2022, 1 + j, 1, tzinfo=UTC),
            )

    ts = MTTimeSeries(
        dataset_id="GDP",
        source="FRED",
        update_prior_to_load=False,
    )

    # Verify attributes were set correctly
    assert ts.dataset_id == "GDP"
    assert ts.source == "FRED"
    assert ts.series_key == {}
    assert len(ts.current_observations) == 3
    assert len(ts.vintages) == 1
    assert ts.release_date == datetime(2023, 2, 1, tzinfo=UTC)
    assert ts.metadata.title == "GDP"
    assert ts.metadata.units == "Billions of Dollars"


def test_init_filters_observations_by_data_dates():
    """Test that MTTimeSeries.__init__ properly filters observations using data_start_date and data_end_date"""
    dataset = Dataset.create(dataset_id="TEST", source="FRED")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test",
        units="Units",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 6, 1, tzinfo=UTC),
    )

    # Create observations spanning several months
    for i in range(6):
        Observation.create(
            series=series,
            release=release,
            value=100 + i,
            observation_timestamp=datetime(2023, 1 + i, 1, tzinfo=UTC),
        )

    ts = MTTimeSeries(
        dataset_id="TEST",
        source="FRED",
        data_start_date=datetime(2023, 2, 1, tzinfo=UTC),
        data_end_date=datetime(2023, 4, 1, tzinfo=UTC),
        update_prior_to_load=False,
    )

    # Should only have observations from Feb to Apr (3 observations)
    assert len(ts.current_observations) == 3
    assert ts.current_observations[0].timestamp == datetime(2023, 2, 1, tzinfo=UTC)
    assert ts.current_observations[-1].timestamp == datetime(2023, 4, 1, tzinfo=UTC)


def test_init_filters_vintages_by_vintage_dates():
    """Test that MTTimeSeries.__init__ only returns vintages inside the requested window."""
    dataset = Dataset.create(dataset_id="TEST_VINTAGE", source="FRED")
    series = Series.create(dataset=dataset, series_key={})

    DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test",
        units="Units",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release1 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )
    release2 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 2, 1, tzinfo=UTC),
    )

    Observation.create(
        series=series,
        release=release1,
        value=100,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )
    Observation.create(
        series=series,
        release=release2,
        value=200,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    ts = MTTimeSeries(
        dataset_id="TEST_VINTAGE",
        source="FRED",
        vintage_start_date=datetime(2023, 2, 1, tzinfo=UTC),
        update_prior_to_load=False,
    )

    assert ts.release_date == datetime(2023, 2, 1, tzinfo=UTC)
    assert len(ts.vintages) == 0
    assert len(ts.current_observations) == 1
    assert ts.current_observations[0].value == 200


def test_init_raises_window_specific_error_when_no_vintages_in_window():
    """Test that MTTimeSeries.__init__ raises a clear error when no vintages match the requested window."""
    dataset = Dataset.create(dataset_id="TEST_WINDOW", source="FRED")
    series = Series.create(dataset=dataset, series_key={})

    DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test",
        units="Units",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )

    Observation.create(
        series=series,
        release=release,
        value=100,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(
        ValueError,
        match="No vintages available for dataset TEST_WINDOW",
    ):
        MTTimeSeries(
            dataset_id="TEST_WINDOW",
            source="FRED",
            vintage_start_date=datetime(2023, 2, 1, tzinfo=UTC),
            update_prior_to_load=False,
        )


def test_init_raises_error_when_no_data_found():
    """Test that MTTimeSeries.__init__ raises ValueError when no data is found"""
    dataset = Dataset.create(dataset_id="EMPTY", source="FRED")
    series = Series.create(dataset=dataset, series_key={})

    with pytest.raises(
        ValueError,
        match="Series key {} did not uniquely identify a single dataset dimension. Found 0 unique dimensions.",
    ):
        MTTimeSeries(
            dataset_id="EMPTY",
            source="FRED",
            update_prior_to_load=False,
        )


@patch(
    "macrotrace.models.mt.time_series.MTTimeSeries._get_update_manager",
    side_effect=AssertionError("Local-only loads should not create an update manager"),
)
def test_init_local_fred_load_does_not_require_api_key(
    mock_get_update_manager, monkeypatch
):
    """Test that local-only FRED loads succeed without an API key when data is already local."""
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    dataset = Dataset.create(dataset_id="PAYEMS", source="FRED")
    series = Series.create(dataset=dataset, series_key={})

    DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="date",
        title="Observation Date",
        units="Thousands of Persons",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 6, tzinfo=UTC),
    )
    Observation.create(
        series=series,
        release=release,
        value=100.0,
        observation_timestamp=datetime(2022, 12, 1, tzinfo=UTC),
    )

    ts = MTTimeSeries(
        dataset_id="PAYEMS",
        source="FRED",
        update_prior_to_load=False,
    )

    assert ts.release_date == datetime(2023, 1, 6, tzinfo=UTC)
    assert len(ts.current_observations) == 1
    mock_get_update_manager.assert_not_called()


@patch(
    "macrotrace.models.mt.time_series.MTTimeSeries._get_update_manager",
    side_effect=AssertionError("Local-only loads should not create an update manager"),
)
def test_init_local_ons_load_does_not_create_update_manager(mock_get_update_manager):
    """Test that local-only ONS loads use only the local database."""
    series_key = {"geography": "K02000001"}
    dataset = Dataset.create(
        dataset_id="gdp-to-four-decimal-places",
        source="ONS",
    )
    series = Series.create(dataset=dataset, series_key=series_key)

    DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="date",
        title="Date",
        units="Index",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )
    geography_dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="geography",
        title="Geography",
        units=None,
        frequency=None,
        type="text",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )
    SeriesDimensionFilter.create(
        series=series,
        dimension=geography_dimension,
        value="K02000001",
    )

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 13, tzinfo=UTC),
    )
    Observation.create(
        series=series,
        release=release,
        value=101.2,
        observation_timestamp=datetime(2022, 12, 1, tzinfo=UTC),
    )

    ts = MTTimeSeries(
        dataset_id="gdp-to-four-decimal-places",
        source="ONS",
        series_key=series_key,
        update_prior_to_load=False,
    )

    assert ts.release_date == datetime(2023, 1, 13, tzinfo=UTC)
    assert len(ts.current_observations) == 1
    assert ts.current_observations[0].value == 101.2
    mock_get_update_manager.assert_not_called()


def test_load_vintages_from_releases_single_release():
    """Test that _load_vintages_from_releases correctly loads a single release"""
    dataset = Dataset.create(dataset_id="TEST", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test Series",
        units="Units",
        frequency="D",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )

    Observation.create(
        series=series,
        release=release,
        value=100,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    empty_ts = MTTimeSeries.__new__(MTTimeSeries)
    empty_ts.dataset_id = "TEST"
    empty_ts.source = "TEST"
    empty_ts.series_key = {}
    empty_ts.data_start_date = None
    empty_ts.data_end_date = None
    empty_ts.vintage_start_date = None
    empty_ts.vintage_end_date = None

    vintages = empty_ts._load_vintages_from_releases(mock_state)

    assert len(vintages) == 1
    assert vintages[0].release_date == datetime(2023, 1, 1, tzinfo=UTC)
    assert len(vintages[0].current_observations) == 1
    assert vintages[0].vintages == []


def test_load_vintages_from_releases_multiple_releases():
    """Test that _load_vintages_from_releases correctly builds vintage chain from multiple releases"""
    dataset = Dataset.create(dataset_id="TEST", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test Series",
        units="Units",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    # Create 3 releases
    releases = []
    for i in range(3):
        release = Release.create(
            dataset=dataset,
            release_date=datetime(2023, i + 1, 1, tzinfo=UTC),
        )
        releases.append(release)

        # Each release has observations
        for j in range(i + 1):  # Growing number of observations
            Observation.create(
                series=series,
                release=release,
                value=100 + i * 10 + j,
                observation_timestamp=datetime(2023, j + 1, 1, tzinfo=UTC),
            )

    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    empty_ts = MTTimeSeries.__new__(MTTimeSeries)
    empty_ts.dataset_id = "TEST"
    empty_ts.source = "TEST"
    empty_ts.series_key = {}
    empty_ts.data_start_date = None
    empty_ts.data_end_date = None
    empty_ts.vintage_start_date = None
    empty_ts.vintage_end_date = None

    vintages = empty_ts._load_vintages_from_releases(mock_state)

    # Should have 3 vintages
    assert len(vintages) == 3

    # First vintage has no prior vintages
    assert len(vintages[0].vintages) == 0
    assert len(vintages[0].current_observations) == 1

    # Second vintage has 1 prior vintage
    assert len(vintages[1].vintages) == 1
    assert len(vintages[1].current_observations) == 2

    # Third vintage has 2 prior vintages
    assert len(vintages[2].vintages) == 2
    assert len(vintages[2].current_observations) == 3


def test_load_vintages_from_releases_skips_empty_releases():
    """Test that _load_vintages_from_releases skips releases without observations"""
    dataset = Dataset.create(dataset_id="TEST", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test Series",
        units="Units",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    # Create 3 releases but only add observations to 2 of them
    release1 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )

    release2_empty = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 2, 1, tzinfo=UTC),
    )

    release3 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 3, 1, tzinfo=UTC),
    )

    # Add observations only to release1 and release3
    Observation.create(
        series=series,
        release=release1,
        value=100,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    Observation.create(
        series=series,
        release=release3,
        value=200,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    empty_ts = MTTimeSeries.__new__(MTTimeSeries)
    empty_ts.dataset_id = "TEST"
    empty_ts.source = "TEST"
    empty_ts.series_key = {}
    empty_ts.data_start_date = None
    empty_ts.data_end_date = None
    empty_ts.vintage_start_date = None
    empty_ts.vintage_end_date = None

    vintages = empty_ts._load_vintages_from_releases(mock_state)

    # Should only have 2 vintages (release2 skipped)
    assert len(vintages) == 2
    assert vintages[0].release_date == datetime(2023, 1, 1, tzinfo=UTC)
    assert vintages[1].release_date == datetime(2023, 3, 1, tzinfo=UTC)


def test_load_vintages_from_releases_raises_on_no_data():
    """Test that _load_vintages_from_releases raises ValueError when no releases have observations"""
    dataset = Dataset.create(dataset_id="EMPTY", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Empty Series",
        units="Units",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    # Create a release but don't add any observations
    Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )

    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    empty_ts = MTTimeSeries.__new__(MTTimeSeries)
    empty_ts.dataset_id = "EMPTY"
    empty_ts.source = "TEST"
    empty_ts.series_key = {}
    empty_ts.data_start_date = None
    empty_ts.data_end_date = None
    empty_ts.vintage_start_date = None
    empty_ts.vintage_end_date = None

    with pytest.raises(ValueError, match="No time series data found"):
        empty_ts._load_vintages_from_releases(mock_state)


def test_build_vintage_for_release_success():
    """Test that _build_vintage_for_release correctly builds a vintage from a release"""
    dataset = Dataset.create(dataset_id="TEST", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test Series",
        units="Billions",
        frequency="QS",
        seasonal_adjustment="SA",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )

    obs = Observation.create(
        series=series,
        release=release,
        value=150.5,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    empty_ts = MTTimeSeries.__new__(MTTimeSeries)
    empty_ts.dataset_id = "TEST"
    empty_ts.source = "TEST"
    empty_ts.series_key = {}
    empty_ts.data_start_date = None
    empty_ts.data_end_date = None

    vintage = empty_ts._build_vintage_for_release(
        release=release,
        series_dimensions=[dimension],
        time_series_list=[],
        state=mock_state,
    )

    assert vintage is not None
    assert vintage.release_date == datetime(2023, 1, 1, tzinfo=UTC)
    assert len(vintage.current_observations) == 1
    assert vintage.current_observations[0].value == 150.5
    assert vintage.metadata.title == "Test Series"
    assert vintage.metadata.units == "Billions"
    assert vintage.metadata.frequency == "QS"
    assert vintage.metadata.seasonal_adjustment == "SA"


def test_build_vintage_for_release_returns_none_when_no_observations():
    """Test that _build_vintage_for_release returns None when release has no observations"""
    dataset = Dataset.create(dataset_id="TEST", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test Series",
        units="Units",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
    )

    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    empty_ts = MTTimeSeries.__new__(MTTimeSeries)
    empty_ts.dataset_id = "TEST"
    empty_ts.source = "TEST"
    empty_ts.series_key = {}
    empty_ts.data_start_date = None
    empty_ts.data_end_date = None

    vintage = empty_ts._build_vintage_for_release(
        release=release,
        series_dimensions=[dimension],
        time_series_list=[],
        state=mock_state,
    )

    assert vintage is None


def test_build_vintage_for_release_includes_prior_vintages():
    """Test that _build_vintage_for_release correctly includes prior vintages in the chain"""
    dataset = Dataset.create(dataset_id="TEST", source="TEST")
    series = Series.create(dataset=dataset, series_key={})

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim-1",
        title="Test Series",
        units="Units",
        frequency="MS",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 2, 1, tzinfo=UTC),
    )

    Observation.create(
        series=series,
        release=release,
        value=200,
        observation_timestamp=datetime(2023, 1, 1, tzinfo=UTC),
    )

    # Create a mock prior vintage
    mock_prior_vintage = MagicMock()
    mock_prior_vintage.release_date = datetime(2023, 1, 1, tzinfo=UTC)

    mock_state = MagicMock()
    mock_state.dataset = dataset
    mock_state.series = series

    empty_ts = MTTimeSeries.__new__(MTTimeSeries)
    empty_ts.dataset_id = "TEST"
    empty_ts.source = "TEST"
    empty_ts.series_key = {}
    empty_ts.data_start_date = None
    empty_ts.data_end_date = None

    vintage = empty_ts._build_vintage_for_release(
        release=release,
        series_dimensions=[dimension],
        time_series_list=[mock_prior_vintage],
        state=mock_state,
    )

    assert vintage is not None
    assert len(vintage.vintages) == 1
    assert vintage.vintages[0] == mock_prior_vintage


def test_describe_vintage_window_both_bounds(empty_timeseries):
    """Both start and end produce a 'between ... and ...' description."""
    empty_timeseries.vintage_start_date = datetime(2024, 1, 1, tzinfo=UTC)
    empty_timeseries.vintage_end_date = datetime(2024, 6, 30, tzinfo=UTC)
    assert (
        empty_timeseries._describe_vintage_window()
        == "between 2024-01-01 and 2024-06-30"
    )


def test_describe_vintage_window_start_only(empty_timeseries):
    """A start-only window renders as 'on or after'."""
    empty_timeseries.vintage_start_date = datetime(2024, 1, 1, tzinfo=UTC)
    empty_timeseries.vintage_end_date = None
    assert empty_timeseries._describe_vintage_window() == "on or after 2024-01-01"


def test_describe_vintage_window_end_only(empty_timeseries):
    """An end-only window renders as 'on or before'."""
    empty_timeseries.vintage_start_date = None
    empty_timeseries.vintage_end_date = datetime(2024, 6, 30, tzinfo=UTC)
    assert empty_timeseries._describe_vintage_window() == "on or before 2024-06-30"


def test_describe_vintage_window_no_bounds(empty_timeseries):
    """No bounds render as the catch-all message."""
    empty_timeseries.vintage_start_date = None
    empty_timeseries.vintage_end_date = None
    assert empty_timeseries._describe_vintage_window() == "for all vintages"


def test_load_state_from_db_raises_when_dataset_missing(empty_timeseries):
    """_load_state_from_db raises ValueError when no dataset row exists."""
    empty_timeseries.dataset_id = "MISSING"
    empty_timeseries.source = "FRED"

    with pytest.raises(ValueError, match="No locally stored dataset found"):
        empty_timeseries._load_state_from_db()


def test_load_state_from_db_raises_when_series_missing(empty_timeseries):
    """_load_state_from_db raises ValueError when the series row is missing."""
    Dataset.create(dataset_id="HAS_DATASET", source="FRED")

    empty_timeseries.dataset_id = "HAS_DATASET"
    empty_timeseries.source = "FRED"
    empty_timeseries.series_key = {"unknown": "key"}

    with pytest.raises(ValueError, match="No locally stored series found"):
        empty_timeseries._load_state_from_db()


def test_fetch_or_load_state_requires_updater_when_refreshing(empty_timeseries):
    """_fetch_or_load_state raises if asked to refresh without an updater."""
    with pytest.raises(ValueError, match="Update manager is required"):
        empty_timeseries._fetch_or_load_state(None, update_prior_to_load=True)
