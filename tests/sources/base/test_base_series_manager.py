import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from macrotrace.sources.base import SeriesManager
from macrotrace.models.db import (
    Dataset,
    Series,
    SeriesDimensionFilter,
    DatasetDimension,
)

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from fixtures import api_client, empty_state, UTC, db_setup_and_teardown


def test_initialization(api_client):
    """Test that SeriesManager initializes correctly with the given API client."""
    sm = SeriesManager(api_client=api_client)
    assert sm.api_client == api_client


@patch("macrotrace.sources.base.Series.select")
def test_fetch_or_create_series_definition_query(mock_select, api_client, empty_state):
    """Test that fetch_or_create_series_definition method's query is correct."""
    # Mock a dataset with id for the state
    mock_dataset = MagicMock()
    mock_dataset.id = 1
    empty_state.dataset = mock_dataset
    empty_state.series_key = {"dim1": "value1"}

    # Mock the query chain to return an existing series
    mock_existing_series = MagicMock()
    mock_query = MagicMock()
    mock_query.where.return_value = mock_query
    mock_query.first.return_value = mock_existing_series
    mock_select.return_value = mock_query

    sm = SeriesManager(api_client=api_client)
    result = sm.fetch_or_create_series_definition(state=empty_state)

    mock_select.assert_called_once()
    assert mock_query.where.call_count == 2
    mock_query.first.assert_called_once()

    assert result == mock_existing_series


def test_fetch_or_create_series_definition_create_with_db(api_client, empty_state):
    """Test that fetch_or_create_series_definition creates a new Series if not found in DB."""

    # Create a dataset
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")

    sm = SeriesManager(api_client=api_client)
    state = empty_state
    state.dataset = dataset

    series = sm.fetch_or_create_series_definition(state=state)
    assert series.dataset.id == dataset.id


def test_fetch_or_create_series_definition_fetch_with_db(api_client, empty_state):
    """Test that fetch_or_create_series_definition fetches existing Series from DB."""

    # Create a dataset
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")

    # Create a series
    series_key = {"dim1": "value1"}
    existing_series = Series.create(dataset=dataset, series_key=series_key)

    sm = SeriesManager(api_client=api_client)
    state = empty_state
    state.dataset = dataset
    state.series_key = series_key

    fetched_series = sm.fetch_or_create_series_definition(state=state)
    assert fetched_series.id == existing_series.id


@patch("macrotrace.sources.base.SeriesDimensionFilter.select")
def test_get_series_dimension_filters_query(mock_select, api_client):
    """Test that _get_series_dimension_filters method's query is correct."""
    mock_filter1 = MagicMock()
    mock_filter2 = MagicMock()

    mock_query = MagicMock()
    mock_query.join.return_value = mock_query
    mock_query.where.return_value = mock_query
    mock_query.objects.return_value = [mock_filter1, mock_filter2]
    mock_select.return_value = mock_query

    sm = SeriesManager(api_client=api_client)
    result = sm._get_series_dimension_filters(series_pk=999)

    mock_select.assert_called_once()
    mock_query.join.assert_called_once()
    mock_query.where.assert_called_once()
    mock_query.objects.assert_called_once()

    assert result == [mock_filter1, mock_filter2]


def test_get_series_dimension_filters_with_db(api_client):
    """Test that _get_series_dimension_filters returns all series dimension filters from the database"""

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")
    series = Series.create(
        dataset=dataset, series_key={"dim1": "value1", "dim2": "value2"}
    )

    # Main dim which we are not filtering on
    dataset_dim0 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim0",
        title="Main Dimension 0",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    dataset_dim1 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim1",
        title="Dimension 1",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )
    dataset_dim2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim2",
        title="Dimension 2",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    sdf1 = SeriesDimensionFilter.create(
        series=series, dimension=dataset_dim1, value="value1"
    )
    sdf2 = SeriesDimensionFilter.create(
        series=series, dimension=dataset_dim2, value="value2"
    )

    sm = SeriesManager(api_client=api_client)
    result = sm._get_series_dimension_filters(series_pk=series.id)

    assert len(result) == 2
    result_pairs = {(f.dataset_dimension_id, f.value) for f in result}
    assert result_pairs == {("dim1", "value1"), ("dim2", "value2")}


def test_get_series_dimension_filters_with_no_filters(api_client):
    """Test that _get_series_dimension_filters returns an empty list when no filters exist"""

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")
    series = Series.create(dataset=dataset, series_key={})

    sm = SeriesManager(api_client=api_client)
    result = sm._get_series_dimension_filters(series_pk=series.id)

    assert result == []


def test_fetch_new_series_dimension_filters_no_new(api_client):
    """Test that fetch_new_series_dimension_filters doesn't create filters that already exist"""
    state = empty_state

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")
    series = Series.create(
        dataset=dataset, series_key={"dim1": "value1", "dim2": "value2"}
    )

    # Main dim which we are not filtering on
    dataset_dim0 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim0",
        title="Main Dimension 0",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )
    dataset_dim1 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim1",
        title="Dimension 1",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )
    dataset_dim2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim2",
        title="Dimension 2",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    sdf1 = SeriesDimensionFilter.create(
        series=series, dimension=dataset_dim1, value="value1"
    )
    sdf2 = SeriesDimensionFilter.create(
        series=series, dimension=dataset_dim2, value="value2"
    )

    sm = SeriesManager(api_client=api_client)
    state.series = series
    state.series_key = {"dim1": "value1", "dim2": "value2"}

    filters = sm.fetch_new_series_dimension_filters(state=state)

    assert filters == []


def test_fetch_new_series_dimension_filters_all_new(api_client, empty_state):
    """Test that fetch_new_series_dimension_filters creates all new filters when none exist"""
    state = empty_state
    series_key = {"dim1": "value1", "dim2": "value2"}

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")
    series = Series.create(dataset=dataset, series_key=series_key)

    # Main dim which we are not filtering on
    dataset_dim0 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim0",
        title="Main Dimension 0",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    dataset_dim1 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim1",
        title="Dimension 1",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    dataset_dim2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim2",
        title="Dimension 2",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    sm = SeriesManager(api_client=api_client)
    state.dataset = dataset
    state.series = series
    state.series_key = series_key

    filters = sm.fetch_new_series_dimension_filters(state=state)

    assert len(filters) == 2
    filter_pairs = {(f.dimension.dataset_dimension_id, f.value) for f in filters}
    assert filter_pairs == {("dim1", "value1"), ("dim2", "value2")}


def test_fetch_new_series_dimension_filters_some_new(api_client, empty_state):
    """Test that fetch_new_series_dimension_filters creates only new filters when some exist"""
    state = empty_state
    series_key = {"dim1": "value1", "dim2": "value2"}

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")
    series = Series.create(dataset=dataset, series_key=series_key)

    # Main dim which we are not filtering on
    dataset_dim0 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim0",
        title="Main Dimension 0",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    dataset_dim1 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim1",
        title="Dimension 1",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    dataset_dim2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim2",
        title="Dimension 2",
        type="text",
        frequency="MS",
        valid_from=datetime(2024, 1, 1, tzinfo=UTC),
    )

    # Create existing filter for dim1, not dim2
    sdf1 = SeriesDimensionFilter.create(
        series=series, dimension=dataset_dim1, value="value1"
    )

    sm = SeriesManager(api_client=api_client)
    state.dataset = dataset
    state.series = series
    state.series_key = series_key

    filters = sm.fetch_new_series_dimension_filters(state=state)

    assert len(filters) == 1
    filter_pair = (filters[0].dimension.dataset_dimension_id, filters[0].value)
    assert filter_pair == ("dim2", "value2")


def test_fetch_new_series_dimension_filters_no_filters(api_client, empty_state):
    """Test that fetch_new_series_dimension_filters returns an empty list when no filters are in state"""
    state = empty_state

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="test_source")
    series = Series.create(dataset=dataset, series_key={})

    sm = SeriesManager(api_client=api_client)
    state.series = series
    state.series_key = {}

    filters = sm.fetch_new_series_dimension_filters(state=state)

    assert filters == []
