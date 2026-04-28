import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from macrotrace.models.db import Dataset, DatasetDimension
from macrotrace.sources.base import DatasetManager

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.base.fixtures import (
    api_client,
    empty_state,
    db_setup_and_teardown,
    UTC,
)


def test_initialization(api_client):
    """Test that DatasetManager initializes correctly with the given API client."""
    dm = DatasetManager(api_client=api_client)
    assert dm.api_client == api_client


@patch("macrotrace.sources.base.Dataset")
def test_fetch_or_create_dataset_definition_create(
    mock_dataset, api_client, empty_state
):
    """Test fetch_or_create_dataset_definition creates a new Dataset if not found."""
    # Mock the query chain to return None (dataset not found)
    mock_query = MagicMock()
    mock_dataset.select.return_value = mock_query
    mock_query.where.return_value = mock_query
    mock_query.first.return_value = None

    mock_created_dataset = MagicMock()
    mock_dataset.create.return_value = mock_created_dataset

    dm = DatasetManager(api_client=api_client)
    result = dm.fetch_or_create_dataset_definition(state=empty_state)

    mock_dataset.select.assert_called_once()
    mock_query.where.assert_called_once()
    mock_query.first.assert_called_once()
    mock_dataset.create.assert_called_once_with(
        dataset_id=empty_state.dataset_id,
        source=empty_state.source,
    )

    assert result == mock_created_dataset


@patch("macrotrace.sources.base.Dataset")
def test_fetch_or_create_dataset_definition_fetch(
    mock_dataset, api_client, empty_state
):
    """Test fetch_or_create_dataset_definition fetches existing Dataset."""
    # Mock the query chain to return an existing dataset
    mock_existing_dataset = MagicMock()
    mock_query = MagicMock()
    mock_dataset.select.return_value = mock_query
    mock_query.where.return_value = mock_query
    mock_query.first.return_value = mock_existing_dataset

    dm = DatasetManager(api_client=api_client)
    result = dm.fetch_or_create_dataset_definition(state=empty_state)

    mock_dataset.select.assert_called_once()
    mock_query.where.assert_called_once()
    mock_query.first.assert_called_once()
    mock_dataset.create.assert_not_called()

    assert result == mock_existing_dataset


def test_fetch_new_dataset_dimensions(api_client, empty_state):
    """Test fetch_new_dataset_dimensions raises NotImplementedError."""
    dm = DatasetManager(api_client=api_client)
    with pytest.raises(NotImplementedError):
        dm.fetch_new_dataset_dimensions(state=empty_state)


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

    dm = DatasetManager(api_client=api_client)
    result = dm._get_all_local_dataset_dimensions(dataset_pk=dataset_pk)

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

    dm = DatasetManager(api_client=api_client)
    result = dm._get_all_local_dataset_dimensions(dataset_pk=dataset.id)

    assert set(result) == {dd1, dd2, dd3}


def test_get_all_local_dataset_dimensions_with_no_dimensions(api_client):
    """Test that _get_all_local_dataset_dimensions returns an empty list when no dimensions exist"""
    # Create a dataset with no dimensions
    dataset = Dataset.create(dataset_id="EMPTY_DATASET", source="test_source")

    dm = DatasetManager(api_client=api_client)
    result = dm._get_all_local_dataset_dimensions(dataset_pk=dataset.id)

    assert result == []


@patch("macrotrace.sources.base.DatasetDimension.select")
def test_get_latest_local_dataset_dimension_query(mock_select, api_client):
    """Test the query in the _get_latest_local_dataset_dimension method."""
    mock_dd = MagicMock()
    mock_dd.id = 5

    mock_query = MagicMock()
    mock_query.where.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.first.return_value = mock_dd
    mock_select.return_value = mock_query

    dataset_pk = 999
    dataset_dimension_id = "test-dim-id"

    dm = DatasetManager(api_client=api_client)
    result = dm._get_latest_local_dataset_dimension(
        dataset_pk=dataset_pk,
        dataset_dimension_id=dataset_dimension_id,
    )

    assert result == mock_dd
    mock_select.assert_called_once()
    mock_query.where.assert_called_once()
    mock_query.order_by.assert_called_once()
    mock_query.first.assert_called_once()


def test_get_latest_local_dataset_dimension_with_db(api_client):
    """Test that _get_latest_local_dataset_dimension returns the latest dataset dimension from the database"""

    # Create a dataset
    dataset = Dataset.create(dataset_id="TEST_DATASET_2", source="test_source")

    # Create multiple dataset dimensions with the same dataset_dimension_id
    dd1 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="DIM_A",
        title="TitleA1",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )
    dd2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="DIM_A",
        title="TitleA2",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 2, 1, tzinfo=UTC),
    )
    dd3 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="DIM_A",
        title="TitleA3",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 3, 1, tzinfo=UTC),
    )

    dm = DatasetManager(api_client=api_client)
    result = dm._get_latest_local_dataset_dimension(
        dataset_pk=dataset.id,
        dataset_dimension_id="DIM_A",
    )

    assert result == dd3


def test_get_latest_local_dataset_dimension_with_no_dimensions(api_client):
    """Test that _get_latest_local_dataset_dimension returns None when no dimensions exist"""

    # Create a dataset with no dimensions
    dataset = Dataset.create(dataset_id="EMPTY_DATASET_2", source="test_source")

    dm = DatasetManager(api_client=api_client)
    result = dm._get_latest_local_dataset_dimension(
        dataset_pk=dataset.id,
        dataset_dimension_id="NON_EXISTENT_DIM",
    )

    assert result is None


@patch("macrotrace.sources.base.DatasetManager._get_all_local_dataset_dimensions")
def test_get_latest_valid_from_with_dimensions(
    mock_get_all_local_dataset_dimensions, api_client
):
    """Test that _get_latest_valid_from returns the latest valid_from from non-time dimensions"""
    dataset_pk = 999

    dim_non_time_1 = MagicMock()
    dim_non_time_1.type = "text"
    dim_non_time_1.valid_from = datetime(2021, 6, 1, tzinfo=UTC)

    dim_non_time_2 = MagicMock()
    dim_non_time_2.type = "category"
    dim_non_time_2.valid_from = datetime(2022, 3, 1, tzinfo=UTC)

    # Mock to return the dimensions
    mock_get_all_local_dataset_dimensions.return_value = [
        dim_non_time_1,
        dim_non_time_2,
    ]

    dm = DatasetManager(api_client=api_client)
    result = dm._get_latest_valid_from(dataset_pk=dataset_pk)

    assert result == datetime(2022, 3, 1, tzinfo=UTC)


@patch("macrotrace.sources.base.DatasetManager._get_all_local_dataset_dimensions")
def test_get_latest_valid_from_with_no_dimensions(
    mock_get_all_local_dataset_dimensions, api_client
):
    """Test that _get_latest_valid_from returns the default date when no dimensions exist"""
    dataset_pk = 999

    # Mock to return an empty list (no dimensions)
    mock_get_all_local_dataset_dimensions.return_value = []

    dm = DatasetManager(api_client=api_client)
    result = dm._get_latest_valid_from(dataset_pk=dataset_pk)

    assert result == datetime(1800, 1, 1, tzinfo=UTC)
