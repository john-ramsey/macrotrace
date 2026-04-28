import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from dateutil.parser import ParserError


from macrotrace.models.db import Dataset, DatasetDimension
from macrotrace.sources.fred import FredDatasetManager, FRED_TO_PD_OFFSETS

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.fred.fixtures import (
    api_client,
    empty_state,
    db_setup_and_teardown,
    US_CENTRAL,
)


def assert_dimensions_equal(actual: DatasetDimension, expected: dict):
    """Helper to compare DatasetDimension objects with expected values."""
    assert actual.dataset_id == expected["dataset_id"]
    assert actual.dataset_dimension_id == expected["dataset_dimension_id"]
    assert actual.title == expected["title"]
    assert actual.type == expected["type"]
    assert actual.frequency == expected["frequency"]
    assert actual.description == expected["description"]
    assert actual.units == expected["units"]
    assert actual.seasonal_adjustment == expected["seasonal_adjustment"]
    assert actual.valid_from == expected["valid_from"]
    assert actual.valid_to == expected["valid_to"]


def test_initialization(api_client):
    """Test that the FredDatasetManager initializes correctly."""
    dm = FredDatasetManager(api_client=api_client)
    assert dm.api_client == api_client


def test_parse_fred_date_with_date_string(api_client):
    """Test the _parse_date method with a date string."""
    dm = FredDatasetManager(api_client=api_client)
    fred_date_str = "2023-12-31"
    fred_date = dm._parse_date(fred_date_str)
    assert fred_date == US_CENTRAL.localize(datetime(2023, 12, 31))


def test_parse_fred_date_with_datetime_string(api_client):
    """Test the _parse_date method with a datetime string."""
    dm = FredDatasetManager(api_client=api_client)
    fred_date_str = "2023-12-31 14:30:00"
    fred_date = dm._parse_date(fred_date_str)
    assert fred_date == US_CENTRAL.localize(datetime(2023, 12, 31, 14, 30, 0))


def test_parse_fred_date_with_timezone_string(api_client):
    """Test the _parse_date method with a date string containing timezone info."""
    dm = FredDatasetManager(api_client=api_client)
    fred_date_str = "2023-12-31T15:00:00-06:00"
    fred_date = dm._parse_date(fred_date_str)
    # Localize to US_CENTRAL timezone since we are converting
    expected_datetime = US_CENTRAL.localize(datetime(2023, 12, 31, 15, 0, 0))
    assert fred_date == expected_datetime


def test_parse_fred_date_with_ongoing_date(api_client):
    """Test the _parse_date method with a date string indicating ongoing."""
    dm = FredDatasetManager(api_client=api_client)
    fred_date_str = "9999-12-31"
    fred_date = dm._parse_date(fred_date_str)
    assert fred_date is None


def test_parse_fred_date_with_non_overflow_error(api_client):
    """Test the _parse_date method with a non-overflow error string. This should raise a ValueError."""
    dm = FredDatasetManager(api_client=api_client)
    fred_date_str = "invalid-date-string"
    with pytest.raises(ValueError):
        dm._parse_date(fred_date_str)


def test_parse_date_catches_overflow_error(api_client):
    """Test that _parse_date catches OverflowError and returns none."""
    dm = FredDatasetManager(api_client=api_client)
    fred_date_str = "10000-01-01"  # This will cause an OverflowError in datetime

    fred_date = dm._parse_date(fred_date_str)
    assert fred_date is None


def test_parse_date_raises_unexpected_error(api_client):
    """Test that _parse_date raises unexpected errors (parsing for example)."""
    dm = FredDatasetManager(api_client=api_client)
    fred_date_str = "not-a-date"  # This will cause a ParserError in datetime

    with pytest.raises(ParserError):
        dm._parse_date(fred_date_str)


def test_is_new_dimension_new(api_client):
    """Test the _is_new_dimension method with a new dimension."""
    dm = FredDatasetManager(api_client=api_client)
    latest_realtime_start = US_CENTRAL.localize(datetime(2020, 1, 1))
    new_realtime_start = US_CENTRAL.localize(datetime(2021, 1, 1))
    assert dm._is_new_dimension(new_realtime_start, latest_realtime_start) is True


def test_is_new_dimension_not_new(api_client):
    """Test the _is_new_dimension method with a non-new dimension."""
    dm = FredDatasetManager(api_client=api_client)
    latest_realtime_start = US_CENTRAL.localize(datetime(2020, 1, 1))
    old_realtime_start = US_CENTRAL.localize(datetime(2019, 1, 1))
    assert dm._is_new_dimension(old_realtime_start, latest_realtime_start) is False


def test_is_new_dimension_equal(api_client):
    """Test the _is_new_dimension method with a dimension having equal realtime_start."""
    dm = FredDatasetManager(api_client=api_client)
    latest_realtime_start = US_CENTRAL.localize(datetime(2020, 1, 1))
    equal_realtime_start = US_CENTRAL.localize(datetime(2020, 1, 1))
    assert dm._is_new_dimension(equal_realtime_start, latest_realtime_start) is False


def test_new_dimension_frequency_conversion(api_client):
    """Test that frequency conversion from FRED to internal representation works."""
    dm = FredDatasetManager(api_client=api_client)
    fred_frequencies = FRED_TO_PD_OFFSETS.keys()
    expected_conversions = FRED_TO_PD_OFFSETS.values()

    for fred_freq, expected_freq in zip(fred_frequencies, expected_conversions):
        converted_freq = dm._convert_frequency(fred_freq)
        assert converted_freq == expected_freq


def test_new_dimension_frequency_conversion_none(api_client):
    """Test that frequency conversion handles None input."""
    dm = FredDatasetManager(api_client=api_client)
    converted_freq = dm._convert_frequency(None)
    assert converted_freq is None


@patch("macrotrace.sources.fred.FredDatasetManager._get_latest_valid_from")
@patch("macrotrace.sources.fred.FredAPIClient.make_request")
def test_fetch_new_dataset_dimensions_all_new(
    mock_make_request, mock_get_latest_valid_from, api_client, empty_state
):
    """Test the fetch_new_dataset_dimensions method with all new dimensions."""
    state = empty_state

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="FRED")
    state.dataset = dataset
    state.dataset_id = "TEST_DATASET"

    dm = FredDatasetManager(api_client=api_client)

    mock_get_latest_valid_from.return_value = US_CENTRAL.localize(datetime(1970, 1, 1))
    mock_make_request.return_value = {
        "seriess": [
            {
                "id": state.dataset_id,
                "realtime_start": "2019-01-01",
                "realtime_end": "2019-12-31",
                "title": "Test Series",
                "frequency": "Monthly",
                "notes": "Notes for Test Series",
                "units": "Units",
                "seasonal_adjustment": "SA",
            },
            {
                "id": state.dataset_id,
                "realtime_start": "2020-01-01",
                "realtime_end": "9999-12-31",
                "title": "Test Series (Updated)",
                "frequency": "Monthly",
                "notes": "Notes for Test Series",
                "units": "Units (2020)",
                "seasonal_adjustment": "SA",
            },
        ]
    }

    new_dims = dm.fetch_new_dataset_dimensions(state)

    assert len(new_dims) == 2

    assert_dimensions_equal(
        new_dims[0],
        {
            "dataset_id": state.dataset.id,
            "dataset_dimension_id": state.dataset_id,
            "title": "Test Series",
            "type": "numeric",
            "frequency": "MS",
            "description": "Notes for Test Series",
            "units": "Units",
            "seasonal_adjustment": "SA",
            "valid_from": US_CENTRAL.localize(datetime(2019, 1, 1)),
            "valid_to": US_CENTRAL.localize(datetime(2019, 12, 31)),
        },
    )

    assert_dimensions_equal(
        new_dims[1],
        {
            "dataset_id": state.dataset.id,
            "dataset_dimension_id": state.dataset_id,
            "title": "Test Series (Updated)",
            "type": "numeric",
            "frequency": "MS",
            "description": "Notes for Test Series",
            "units": "Units (2020)",
            "seasonal_adjustment": "SA",
            "valid_from": US_CENTRAL.localize(datetime(2020, 1, 1)),
            "valid_to": None,
        },
    )


@patch("macrotrace.sources.fred.FredDatasetManager._get_latest_valid_from")
@patch("macrotrace.sources.fred.FredAPIClient.make_request")
def test_fetch_new_dataset_dimensions_none_new(
    mock_make_request, mock_get_latest_valid_from, api_client, empty_state
):
    """Test the fetch_new_dataset_dimensions method with no new dimensions."""
    state = empty_state

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="FRED")
    state.dataset = dataset
    state.dataset_id = "TEST_DATASET"

    dm = FredDatasetManager(api_client=api_client)

    mock_get_latest_valid_from.return_value = US_CENTRAL.localize(datetime(2021, 1, 1))
    mock_make_request.return_value = {
        "seriess": [
            {
                "id": state.dataset_id,
                "realtime_start": "2019-01-01",
                "realtime_end": "2019-12-31",
                "title": "Test Series",
                "frequency": "Monthly",
                "notes": "Notes for Test Series",
                "units": "Units",
                "seasonal_adjustment": "SA",
            },
            {
                "id": state.dataset_id,
                "realtime_start": "2020-01-01",
                "realtime_end": "9999-12-31",
                "title": "Test Series (Updated)",
                "frequency": "Monthly",
                "notes": "Notes for Test Series",
                "units": "Units (2020)",
                "seasonal_adjustment": "SA",
            },
        ]
    }

    new_dims = dm.fetch_new_dataset_dimensions(state)

    assert len(new_dims) == 0


@patch("macrotrace.sources.fred.FredDatasetManager._get_latest_valid_from")
@patch("macrotrace.sources.fred.FredDatasetManager._get_latest_local_dataset_dimension")
@patch("macrotrace.sources.fred.FredAPIClient.make_request")
def test_fetch_new_dataset_dimensions_some_new(
    mock_make_request,
    mock_get_latest_dimension,
    mock_get_latest_valid_from,
    api_client,
    empty_state,
):
    """
    Test the fetch_new_dataset_dimensions method with some new dimensions.
    I.e. The previous dimension should have its valid_to set, and the new dimension should be added.
    """
    state = empty_state

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="FRED")
    state.dataset = dataset
    state.dataset_id = "TEST_DATASET"

    dm = FredDatasetManager(api_client=api_client)

    # Set the latest realtime_start to match the first dimension
    mock_get_latest_valid_from.return_value = US_CENTRAL.localize(datetime(2019, 1, 1))

    # Create a mock dimension that will be updated
    mock_existing_dimension = MagicMock(spec=DatasetDimension)
    mock_existing_dimension.id = 1
    mock_existing_dimension.valid_from = US_CENTRAL.localize(datetime(2019, 1, 1))
    mock_existing_dimension.valid_to = None
    mock_get_latest_dimension.return_value = mock_existing_dimension

    mock_make_request.return_value = {
        "seriess": [
            {
                "id": state.dataset_id,
                "realtime_start": "2019-01-01",
                "realtime_end": "2019-12-31",  # This should update the existing dimension
                "title": "Test Series",
                "frequency": "Monthly",
                "notes": "Notes for Test Series",
                "units": "Units",
                "seasonal_adjustment": "SA",
            },
            {
                "id": state.dataset_id,
                "realtime_start": "2020-01-01",
                "realtime_end": "9999-12-31",
                "title": "Test Series (Updated)",
                "frequency": "Monthly",
                "notes": "Notes for Test Series",
                "units": "Units (2020)",
                "seasonal_adjustment": "SA",
            },
        ]
    }

    new_dims = dm.fetch_new_dataset_dimensions(state)

    assert len(new_dims) == 1
    assert mock_existing_dimension.valid_to == US_CENTRAL.localize(
        datetime(2019, 12, 31)
    )

    mock_existing_dimension.save.assert_called_once()

    # Verify the new dimension has correct attributes
    assert_dimensions_equal(
        new_dims[0],
        {
            "dataset_id": state.dataset.id,
            "dataset_dimension_id": state.dataset_id,
            "title": "Test Series (Updated)",
            "type": "numeric",
            "frequency": "MS",
            "description": "Notes for Test Series",
            "units": "Units (2020)",
            "seasonal_adjustment": "SA",
            "valid_from": US_CENTRAL.localize(datetime(2020, 1, 1)),
            "valid_to": None,
        },
    )


@patch("macrotrace.sources.fred.FredDatasetManager._get_latest_valid_from")
@patch("macrotrace.sources.fred.FredDatasetManager._get_latest_local_dataset_dimension")
@patch("macrotrace.sources.fred.FredAPIClient.make_request")
def test_fetch_new_dataset_dimensions_is_updated(
    mock_make_request,
    mock_get_latest_dimension,
    mock_get_latest_valid_from,
    api_client,
    empty_state,
):
    """Test that an existing dimension is successfully updated when realtime_end changes."""
    state = empty_state

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="FRED")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    # Create a mock dimension that will be updated
    mock_existing_dimension = MagicMock(spec=DatasetDimension)
    mock_existing_dimension.id = 1
    mock_existing_dimension.valid_from = US_CENTRAL.localize(datetime(2019, 1, 1))
    mock_existing_dimension.valid_to = None

    mock_get_latest_dimension.return_value = mock_existing_dimension
    mock_get_latest_valid_from.return_value = US_CENTRAL.localize(datetime(2019, 1, 1))

    # Mock response that triggers the "is_updated_dimension" path
    mock_make_request.return_value = {
        "seriess": [
            {
                "id": state.dataset_id,
                "realtime_start": "2019-01-01",  # Matches latest_realtime_start
                "realtime_end": "2020-12-31",  # Not None, so it's an update
                "title": "Test Series",
                "frequency": "Monthly",
                "notes": "Notes for Test Series",
                "units": "Units",
                "seasonal_adjustment": "SA",
            }
        ]
    }

    dm = FredDatasetManager(api_client=api_client)
    new_dims = dm.fetch_new_dataset_dimensions(state)

    # No new dimensions should be returned (just an update)
    assert len(new_dims) == 0

    # Verify the existing dimension was updated
    assert mock_existing_dimension.valid_to == US_CENTRAL.localize(
        datetime(2020, 12, 31)
    )
    mock_existing_dimension.save.assert_called_once()


@patch("macrotrace.sources.fred.FredDatasetManager._get_latest_valid_from")
@patch("macrotrace.sources.fred.FredDatasetManager._get_latest_local_dataset_dimension")
@patch("macrotrace.sources.fred.FredAPIClient.make_request")
def test_fetch_new_dataset_dimensions_is_updated_not_found(
    mock_make_request,
    mock_get_latest_dimension,
    mock_get_latest_valid_from,
    api_client,
    empty_state,
):
    """Test that ValueError is raised when updating a dimension that doesn't exist locally."""
    state = empty_state

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="FRED")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    dim = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id=dataset.dataset_id,
        title="Existing Dimension",
        type="numeric",
        frequency="MS",
        description="An existing dimension",
        units="Units",
        seasonal_adjustment="SA",
        valid_from=US_CENTRAL.localize(datetime(2019, 1, 1)),
        valid_to=None,
    )

    mock_get_latest_dimension.return_value = None
    mock_get_latest_valid_from.return_value = US_CENTRAL.localize(datetime(2019, 1, 1))

    # Mock response that triggers the "is_updated_dimension" path
    mock_make_request.return_value = {
        "seriess": [
            {
                "id": state.dataset_id,
                "realtime_start": "2019-01-01",  # Matches latest_realtime_start
                "realtime_end": "2020-12-31",  # Not None, so it's an update
                "title": "Test Series",
                "frequency": "Monthly",
                "notes": "Notes",
                "units": "Units",
                "seasonal_adjustment": "SA",
            }
        ]
    }

    dm = FredDatasetManager(api_client=api_client)

    with pytest.raises(ValueError, match="Latest dimension.*not found"):
        dm.fetch_new_dataset_dimensions(state)
