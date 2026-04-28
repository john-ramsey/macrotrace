import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from fixtures import api_client, empty_state, UTC, db_setup_and_teardown

from macrotrace.models.db import Dataset, Release, DatasetDimension
from macrotrace.sources.base import ReleaseManager


def test_initialization(api_client):
    """Test that ReleaseManager initializes correctly with the given API client."""
    rm = ReleaseManager(api_client=api_client)
    assert rm.api_client == api_client


def test_fetch_new_releases(api_client, empty_state):
    """Test that fetch_new_releases method returns a NotImplementedError."""
    rm = ReleaseManager(api_client=api_client)

    with pytest.raises(NotImplementedError):
        rm.fetch_new_releases(state=empty_state)


def test_fetch_new_release_dimensions(api_client, empty_state):
    """Test that fetch_new_release_dimensions method returns a NotImplementedError."""
    rm = ReleaseManager(api_client=api_client)

    with pytest.raises(NotImplementedError):
        rm.fetch_new_release_dimensions(state=empty_state)


@patch("macrotrace.sources.base.Release.select")
def test_get_all_releases_in_db_query(mock_select, api_client):
    """Test that _get_current_releases_in_db method's query"""
    mock_release1 = MagicMock()
    mock_release2 = MagicMock()
    mock_release1.release_date = "2025-01-01"
    mock_release2.release_date = "2025-02-01"

    mock_query = MagicMock()
    mock_query.where.return_value = [mock_release1, mock_release2]
    mock_select.return_value = mock_query

    dataset_pk = 999

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_current_releases_in_db(dataset_pk=dataset_pk)

    assert result == ["2025-01-01", "2025-02-01"]
    mock_select.assert_called_once()
    mock_query.where.assert_called_once()


def test_get_all_releases_in_db_with_db(api_client):
    """Test that _get_current_releases_in_db returns all release dates from the database"""

    # Create a dataset
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")

    # Create multiple releases with different dates
    Release.create(dataset=dataset, release_date=datetime(2024, 1, 15, tzinfo=UTC))
    Release.create(dataset=dataset, release_date=datetime(2025, 3, 20, tzinfo=UTC))
    Release.create(dataset=dataset, release_date=datetime(2024, 12, 10, tzinfo=UTC))

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_current_releases_in_db(dataset_pk=dataset.id)

    expected_dates = [
        datetime(2024, 1, 15, tzinfo=UTC),
        datetime(2025, 3, 20, tzinfo=UTC),
        datetime(2024, 12, 10, tzinfo=UTC),
    ]

    assert set(result) == set(expected_dates)
    assert isinstance(result, list)


def test_get_all_releases_in_db_with_no_releases(api_client):
    """Test that _get_current_releases_in_db returns an empty list when no releases exist"""
    # Create a dataset with no releases
    dataset = Dataset.create(dataset_id="EMPTY_DATASET", source="test_source")

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_current_releases_in_db(dataset_pk=dataset.id)

    assert result == []


@patch("macrotrace.sources.base.Release.select")
def test_get_latest_local_release_date_query(mock_select, api_client):
    """Test that _get_latest_local_release_date method's query"""

    latest_date = datetime(2025, 3, 15)

    mock_query = MagicMock()
    mock_query.where.return_value.scalar.return_value = latest_date
    mock_select.return_value = mock_query

    dataset_pk = 999

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_latest_local_release_date(dataset_pk=dataset_pk)

    assert result == latest_date
    mock_select.assert_called_once()
    mock_query.where.assert_called_once()


def test_get_latest_local_release_date_with_db(api_client):
    """Test that _get_latest_local_release_date returns the maximum release date from the database"""

    # Create a dataset
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")

    # Create multiple releases with different dates
    Release.create(dataset=dataset, release_date=datetime(2024, 1, 15, tzinfo=UTC))
    Release.create(dataset=dataset, release_date=datetime(2025, 3, 20, tzinfo=UTC))
    Release.create(dataset=dataset, release_date=datetime(2024, 12, 10, tzinfo=UTC))

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_latest_local_release_date(dataset_pk=dataset.id)

    assert result == datetime(2025, 3, 20, tzinfo=UTC)


def test_get_latest_local_release_date_with_no_releases(api_client):
    """Test that _get_latest_local_release_date returns datetime(1800, 1, 1, tzinfo=UTC) when no releases exist"""
    # Create a dataset with no releases
    dataset = Dataset.create(dataset_id="EMPTY_DATASET", source="test_source")

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_latest_local_release_date(dataset_pk=dataset.id)

    assert result == datetime(1800, 1, 1, tzinfo=UTC)


@patch("macrotrace.sources.base.DatasetDimension.select")
def test_get_all_local_dataset_dimensions_query(mock_select, api_client):
    """Test the query in the _get_all_local_dataset_dimensions method."""
    mock_dd1 = MagicMock()
    mock_dd2 = MagicMock()
    mock_dd1.id = 1
    mock_dd2.id = 2

    mock_query = MagicMock()
    mock_query.where.return_value = [mock_dd1, mock_dd2]
    mock_select.return_value = mock_query

    dataset_pk = 999

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_all_local_dataset_dimensions(dataset_pk=dataset_pk)

    assert result == [mock_dd1, mock_dd2]
    mock_select.assert_called_once()
    mock_query.where.assert_called_once()


def test_get_all_local_dataset_dimensions_with_db(api_client):
    """Test that _get_all_local_dataset_dimensions returns all dataset dimensions from the database"""

    # Create a dataset
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")

    # Create multiple dataset dimensions
    dd1 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="DIM1",
        title="Title1",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )
    dd2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="DIM2",
        title="Title2",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 2, tzinfo=UTC),
    )
    dd3 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="DIM3",
        title="Title3",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 3, tzinfo=UTC),
    )

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_all_local_dataset_dimensions(dataset_pk=dataset.id)

    assert set(result) == {dd1, dd2, dd3}


def test_get_all_local_dataset_dimensions_with_no_dimensions(api_client):
    """Test that _get_all_local_dataset_dimensions returns an empty list when no dimensions exist"""
    # Create a dataset with no dimensions
    dataset = Dataset.create(dataset_id="EMPTY_DATASET", source="test_source")

    rm = ReleaseManager(api_client=api_client)
    result = rm._get_all_local_dataset_dimensions(dataset_pk=dataset.id)

    assert result == []


def test_is_new_release_success():
    """Test the _is_new_release method of ReleaseManager."""
    rm = ReleaseManager(api_client=None)

    current_release_dates = [
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 2, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
    ]

    # Test a new release date not in current releases
    new_date = datetime(2024, 4, 1, tzinfo=UTC)
    assert rm._is_new_release(new_date, current_release_dates) is True


def test_is_new_release_fail():
    """Test the _is_new_release method of ReleaseManager for existing release."""
    rm = ReleaseManager(api_client=None)

    current_release_dates = [
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2024, 2, 1, tzinfo=UTC),
        datetime(2024, 3, 1, tzinfo=UTC),
    ]

    # Test a release date that already exists
    existing_date = datetime(2024, 2, 1, tzinfo=UTC)
    assert rm._is_new_release(existing_date, current_release_dates) is False


def test_is_wanted_release_success():
    """Test the _is_wanted_release method of ReleaseManager."""
    rm = ReleaseManager(api_client=None)

    # Test a release date within the specified range
    release_date = datetime(2024, 6, 15, tzinfo=UTC)
    start_date = datetime(2024, 1, 1, tzinfo=UTC)
    end_date = datetime(2024, 12, 31, tzinfo=UTC)

    assert rm._is_wanted_release(release_date, start_date, end_date) is True


def test_is_wanted_release_fail_after_end():
    """Test the _is_wanted_release method of ReleaseManager for out-of-range release (after end date)."""
    rm = ReleaseManager(api_client=None)

    # Test a release date outside the specified range
    release_date = datetime(2025, 1, 15, tzinfo=UTC)
    start_date = datetime(2024, 1, 1, tzinfo=UTC)
    end_date = datetime(2024, 12, 31, tzinfo=UTC)

    assert rm._is_wanted_release(release_date, start_date, end_date) is False


def test_is_wanted_release_fail_before_start():
    """Test the _is_wanted_release method of ReleaseManager for out-of-range release (before start date)."""
    rm = ReleaseManager(api_client=None)

    # Test a release date outside the specified range
    release_date = datetime(2023, 12, 15, tzinfo=UTC)
    start_date = datetime(2024, 1, 1, tzinfo=UTC)
    end_date = datetime(2024, 12, 31, tzinfo=UTC)

    assert rm._is_wanted_release(release_date, start_date, end_date) is False


def test_get_api_start_date_no_start_date():
    """
    Test the _get_api_start_date method of ReleaseManager when:
        - There is no release start date.

    The default earliest date should be returned.
    """
    rm = ReleaseManager(api_client=None)
    dataset_pk = 999

    release_start_date = None

    api_start_date = rm._get_api_start_date(
        dataset_pk=dataset_pk,
        release_start_date=release_start_date,
    )
    assert api_start_date == datetime(1800, 1, 1, tzinfo=UTC)


@patch("macrotrace.sources.base.ReleaseManager._get_latest_local_release_date")
def test_get_api_start_date_with_start_date(mock_get_latest_local_release_date):
    """
    Test the _get_api_start_date method of ReleaseManager when:
        - There is a release start date.

    The minimum of the release start date and latest local release date should be returned.
    """
    rm = ReleaseManager(api_client=None)

    dataset_pk = 999
    release_start_date = datetime(2024, 6, 15, tzinfo=UTC)

    mock_get_latest_local_release_date.return_value = datetime(2024, 12, 31, tzinfo=UTC)

    api_start_date = rm._get_api_start_date(
        dataset_pk=dataset_pk,
        release_start_date=release_start_date,
    )
    assert api_start_date == datetime(2024, 6, 15, tzinfo=UTC)


@patch("macrotrace.sources.base.ReleaseManager._get_latest_local_release_date")
def test_get_api_start_date_with_start_date_after_latest(
    mock_get_latest_local_release_date,
):
    """
    Test the _get_api_start_date method of ReleaseManager when:
        - There is a release start date that is after the latest local release date.

    The latest local release date should be returned.
    """
    rm = ReleaseManager(api_client=None)

    dataset_pk = 999
    release_start_date = datetime(2025, 1, 1, tzinfo=UTC)

    mock_get_latest_local_release_date.return_value = datetime(2024, 12, 31, tzinfo=UTC)

    api_start_date = rm._get_api_start_date(
        dataset_pk=dataset_pk,
        release_start_date=release_start_date,
    )
    assert api_start_date == datetime(2024, 12, 31, tzinfo=UTC)
