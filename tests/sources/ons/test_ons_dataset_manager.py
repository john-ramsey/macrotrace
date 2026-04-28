import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from macrotrace.models.db import Dataset, DatasetDimension, Release, Series
from macrotrace.sources.ons import ONSDatasetManager

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.ons.fixtures import (
    api_client,
    empty_state,
    db_setup_and_teardown,
    UTC,
)


def test_initialization(api_client):
    """
    Test that the ONSDatasetManager initializes correctly with the provided API client.
    """
    dm = ONSDatasetManager(api_client)

    assert dm.api_client == api_client


@patch("macrotrace.sources.ons.ONSAPIClient.make_request")
def test_series_is_timeseries_returns_true(api_client):
    """
    Test the _series_is_timeseries method of ONSDatasetManager returns True when the series is a time series.
    """
    dm = ONSDatasetManager(api_client)

    mock_response = [
        {"edition": "time-series"},
        {"edition": "other-edition"},
    ]
    api_client.make_request = MagicMock(return_value={"items": mock_response})

    is_timeseries = dm._series_is_timeseries(dataset_id="TEST_DATASET")

    assert is_timeseries is True


@patch("macrotrace.sources.ons.ONSAPIClient.make_paginated_request")
def test_series_is_timeseries_returns_false(api_client):
    """
    Test the _series_is_timeseries method of ONSDatasetManager returns False when the series is not a time series.
    """
    dm = ONSDatasetManager(api_client)

    mock_response = [
        {"edition": "other-edition-1"},
        {"edition": "other-edition-2"},
    ]
    api_client.make_paginated_request = MagicMock(return_value=mock_response)

    is_timeseries = dm._series_is_timeseries(dataset_id="TEST_DATASET")

    assert is_timeseries is False


@patch("macrotrace.sources.ons.ONSDatasetManager._series_is_timeseries")
@patch("macrotrace.sources.ons.Dataset.select")
def test_fetch_dataset_definition_query(
    mock_dataset_select, mock_is_timeseries, api_client, empty_state
):
    """
    Test that _fetch_dataset_definition correctly fetches and creates a dataset definition.
    """
    state = empty_state
    state.dataset_id = "TEST_DATASET"
    mock_is_timeseries.return_value = True

    mock_query = MagicMock()
    mock_query.where.return_value.scalar.return_value = None
    mock_dataset_select.return_value = mock_query

    dm = ONSDatasetManager(api_client)
    dm._fetch_dataset_definition(state)

    mock_dataset_select.assert_called_once()
    mock_query.where.assert_called_once()


def test_fetch_dataset_definition_existing_dataset(api_client, empty_state):
    """
    Test that _fetch_dataset_definition returns existing dataset definition.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset_id = dataset.dataset_id
    state.source = dataset.source

    dm = ONSDatasetManager(api_client)
    fetched_dataset = dm._fetch_dataset_definition(state)

    assert fetched_dataset.id == dataset.id


def test_fetch_dataset_definition_nonexistent_dataset(api_client, empty_state):
    """
    Test that _fetch_dataset_definition returns None when dataset definition does not exist.
    """
    state = empty_state
    state.dataset_id = "NONEXISTENT_DATASET"
    state.source = "ONS"

    dm = ONSDatasetManager(api_client)
    fetched_dataset = dm._fetch_dataset_definition(state)

    assert fetched_dataset is None


@patch("macrotrace.sources.ons.ONSDatasetManager._series_is_timeseries")
def test_fetch_or_create_dataset_definition_not_timeseries(
    mock_is_timeseries, api_client, empty_state
):
    """
    Test that fetch_or_create_dataset_definition raises AssertionError when the series is not a time series.
    """
    state = empty_state
    state.dataset_id = "TEST_DATASET"
    mock_is_timeseries.return_value = False

    dm = ONSDatasetManager(api_client)

    with pytest.raises(AssertionError) as exc_info:
        dm.fetch_or_create_dataset_definition(state)
        assert (
            str(exc_info.value) == f"Dataset {state.dataset_id} is not a time series."
        )


@patch("macrotrace.sources.ons.ONSDatasetManager._series_is_timeseries")
@patch("macrotrace.sources.ons.ONSDatasetManager._fetch_dataset_definition")
def test_fetch_or_create_dataset_definition_creates_dataset(
    mock_fetch_dataset, mock_is_timeseries, api_client, empty_state
):
    """
    Test that fetch_or_create_dataset_definition creates a new dataset definition when it does not exist.
    """
    state = empty_state
    state.dataset_id = "TEST_DATASET"
    state.source = "ONS"

    mock_is_timeseries.return_value = True
    mock_fetch_dataset.return_value = None

    dm = ONSDatasetManager(api_client)
    dataset = dm.fetch_or_create_dataset_definition(state)

    db_dataset = Dataset.get(
        (Dataset.dataset_id == state.dataset_id) & (Dataset.source == state.source)
    )
    assert db_dataset.id == dataset.id
    assert db_dataset.dataset_id == dataset.dataset_id
    assert db_dataset.source == dataset.source


@patch("macrotrace.sources.ons.ONSDatasetManager._series_is_timeseries")
@patch("macrotrace.sources.ons.ONSDatasetManager._fetch_dataset_definition")
def test_fetch_or_create_dataset_definition_returns_existing_dataset(
    mock_fetch_dataset, mock_is_timeseries, api_client, empty_state
):
    """
    Test that fetch_or_create_dataset_definition returns existing dataset definition when it exists.
    """
    state = empty_state
    state.dataset_id = "TEST_DATASET"
    state.source = "ONS"

    existing_dataset = Dataset.create(dataset_id=state.dataset_id, source=state.source)

    mock_is_timeseries.return_value = True
    mock_fetch_dataset.return_value = existing_dataset

    dm = ONSDatasetManager(api_client)
    dataset = dm.fetch_or_create_dataset_definition(state)

    assert dataset.id == existing_dataset.id
    assert dataset.dataset_id == existing_dataset.dataset_id
    assert dataset.source == existing_dataset.source


def test_track_dimension_appearances_across_releases(api_client, empty_state):
    """
    Test that _track_dimension_appearances_across_releases correctly tracks dimension appearances across releases.
    Note that the 'time' dimension should be excluded from the results.
    """
    state = empty_state
    state.dataset_id = "TEST_DATASET"

    release1 = MagicMock()
    release1.release_date = "2023-01-01"
    release1.additional_metadata = {
        "dimensions": [
            # Note that time should not be present in the final output
            {"name": "time"},
            {"name": "dim1"},
            {"name": "dim2"},
        ]
    }

    release2 = MagicMock()
    release2.release_date = "2023-06-01"
    release2.additional_metadata = {
        "dimensions": [
            {"name": "time"},
            {"name": "dim1"},
            {"name": "dim2"},
            {"name": "dim3"},
        ]
    }

    release3 = MagicMock()
    release3.release_date = "2023-09-01"
    release3.additional_metadata = {
        "dimensions": [
            {"name": "time"},
            {"name": "dim1"},
            {"name": "dim3"},
        ]
    }

    state.new_releases = [release1, release2, release3]

    dm = ONSDatasetManager(api_client)
    dimension_appearances = dm._track_dimension_appearances_across_releases(state)

    expected_appearances = {
        "dim1": {
            "releases": ["2023-01-01", "2023-06-01", "2023-09-01"],
            "metadata": {"name": "dim1"},
        },
        "dim2": {
            "releases": ["2023-01-01", "2023-06-01"],
            "metadata": {"name": "dim2"},
        },
        "dim3": {
            "releases": ["2023-06-01", "2023-09-01"],
            "metadata": {"name": "dim3"},
        },
    }

    assert dimension_appearances == expected_appearances


def test_determine_dimension_validity_period_active(api_client):
    """
    Test that _determine_dimension_validity_period correctly determines the validity period of an active dimension.
    """
    dm = ONSDatasetManager(api_client)

    dimension_release_dates = [
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2023, 6, 1, tzinfo=UTC),
        datetime(2023, 9, 1, tzinfo=UTC),
    ]
    latest_release_date = datetime(2023, 9, 1, tzinfo=UTC)

    valid_from, valid_to = dm._determine_dimension_validity_period(
        dimension_release_dates, latest_release_date
    )

    assert valid_from == datetime(2023, 1, 1, tzinfo=UTC)
    assert valid_to is None


def test_determine_dimension_validity_period_discontinued(api_client):
    """
    Test that _determine_dimension_validity_period correctly determines the validity period of a discontinued dimension.
    """
    dm = ONSDatasetManager(api_client)

    dimension_release_dates = [
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2023, 6, 1, tzinfo=UTC),
        datetime(2023, 9, 1, tzinfo=UTC),
    ]
    latest_release_date = datetime(2023, 12, 1, tzinfo=UTC)

    valid_from, valid_to = dm._determine_dimension_validity_period(
        dimension_release_dates, latest_release_date
    )

    assert valid_from == datetime(2023, 1, 1, tzinfo=UTC)
    assert valid_to == datetime(2023, 9, 1, tzinfo=UTC)


def test_construct_dataset_dimension(api_client, empty_state):
    """
    Test that _construct_dataset_dimension correctly creates a dataset dimension.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    dm = ONSDatasetManager(api_client)

    dimension_metadata = {
        "name": "test_dimension",
    }
    valid_from = datetime(2023, 1, 1, tzinfo=UTC)
    valid_to = datetime(2023, 12, 31, tzinfo=UTC)

    dimension = dm._construct_dataset_dimension(
        state=state,
        dimension_name=dimension_metadata["name"],
        dim_meta=dimension_metadata,
        valid_from=valid_from,
        valid_to=valid_to,
    )

    assert dimension.title == "test_dimension"
    assert dimension.type == "text"
    assert dimension.valid_from == valid_from
    assert dimension.valid_to == valid_to


def test_update_existing_dimension_validity_period_needs_update(
    api_client, empty_state
):
    """
    Test that _update_existing_dimension_validity_period correctly updates the valid_to and valid_from of an existing dimension.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    dm = ONSDatasetManager(api_client)

    last_appearance = datetime(2023, 9, 1, tzinfo=UTC)
    original_valid_from = datetime(2023, 2, 1, tzinfo=UTC)
    earliest_appearance = datetime(2023, 1, 1, tzinfo=UTC)
    latest_release_date = datetime(2023, 12, 1, tzinfo=UTC)

    existing_dimension = dm._construct_dataset_dimension(
        state=state,
        dimension_name="test_dimension",
        dim_meta={"name": "test_dimension"},
        valid_from=original_valid_from,
        valid_to=None,
    )
    existing_dimension.save(force_insert=True)

    assert (
        DatasetDimension.get(DatasetDimension.id == existing_dimension.id) is not None
    )

    dm._update_existing_dimension_validity_period(
        dimension=existing_dimension,
        earliest_appearance=earliest_appearance,
        last_appearance=last_appearance,
        latest_release_date=latest_release_date,
    )

    updated_dimension = DatasetDimension.get(
        DatasetDimension.id == existing_dimension.id
    )

    assert updated_dimension.valid_to == last_appearance
    assert updated_dimension.valid_from == earliest_appearance


def test_update_existing_dimension_validity_period_no_update_needed(
    api_client, empty_state
):
    """
    Test that _update_existing_dimension_validity_period does not update the existing dimension when no update is needed.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    dm = ONSDatasetManager(api_client)

    last_appearance = datetime(2023, 9, 1, tzinfo=UTC)
    earliest_appearance = datetime(2023, 1, 1, tzinfo=UTC)
    latest_release_date = datetime(2023, 12, 1, tzinfo=UTC)

    existing_dimension = dm._construct_dataset_dimension(
        state=state,
        dimension_name="test_dimension",
        dim_meta={"name": "test_dimension"},
        valid_from=earliest_appearance,
        valid_to=last_appearance,
    )
    existing_dimension.save(force_insert=True)

    assert (
        DatasetDimension.get(DatasetDimension.id == existing_dimension.id) is not None
    )

    dm._update_existing_dimension_validity_period(
        dimension=existing_dimension,
        earliest_appearance=earliest_appearance,
        last_appearance=last_appearance,
        latest_release_date=latest_release_date,
    )

    updated_dimension = DatasetDimension.get(
        DatasetDimension.id == existing_dimension.id
    )

    assert updated_dimension.valid_from == earliest_appearance
    assert updated_dimension.valid_to == last_appearance


def test_update_existing_dimension_validity_period_no_valid_to(api_client, empty_state):
    """
    Test that _update_existing_dimension_validity_period does not update the valid_to of an existing dimension when valid_to is None.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    dm = ONSDatasetManager(api_client)
    last_appearance = datetime(2023, 12, 1, tzinfo=UTC)
    earliest_appearance = datetime(2023, 1, 1, tzinfo=UTC)
    latest_release_date = datetime(2023, 12, 1, tzinfo=UTC)

    existing_dimension = dm._construct_dataset_dimension(
        state=state,
        dimension_name="test_dimension",
        dim_meta={"name": "test_dimension"},
        valid_from=earliest_appearance,
        valid_to=None,
    )
    existing_dimension.save(force_insert=True)

    assert (
        DatasetDimension.get(DatasetDimension.id == existing_dimension.id) is not None
    )

    dm._update_existing_dimension_validity_period(
        dimension=existing_dimension,
        earliest_appearance=earliest_appearance,
        last_appearance=last_appearance,
        latest_release_date=latest_release_date,
    )

    updated_dimension = DatasetDimension.get(
        DatasetDimension.id == existing_dimension.id
    )

    assert updated_dimension.valid_to is None


@patch("macrotrace.sources.ons.ONSAPIClient.make_request")
def test_fetch_initial_dataset_dimension(mock_make_request, api_client, empty_state):
    """Test fetching the initial dataset dimension from the mock response."""
    state = empty_state

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    mock_make_request.return_value = {
        "title": "intial_dimension",
        "release_frequency": "Monthly",
        "description": "Initial dimension description",
        "unit_of_measure": "Units",
    }
    freq = "MS"

    first_release_date = datetime(2023, 1, 1, tzinfo=UTC)

    dm = ONSDatasetManager(api_client)
    dimension = dm._fetch_initial_dataset_dimension(
        state, first_release_date, freq=freq
    )

    assert dimension.dataset == state.dataset
    assert dimension.dataset_dimension_id == state.dataset_id
    assert dimension.title == mock_make_request.return_value["title"]
    assert dimension.type == "numeric"
    assert dimension.frequency == freq
    assert dimension.description == mock_make_request.return_value["description"]
    assert dimension.units == mock_make_request.return_value["unit_of_measure"]
    assert dimension.valid_from == first_release_date


def test_should_get_initial_dimension_true(api_client):
    """
    Test that _should_get_initial_dimension returns True when there are no existing dimensions.
    """
    dim1 = MagicMock()
    dim1.dataset_dimension_id = "dim1"

    dim2 = MagicMock()
    dim2.dataset_dimension_id = "dim2"

    current_dims = [dim1, dim2]
    series_key = {
        "dim1": "value1",
        "dim2": "value2",
    }

    dm = ONSDatasetManager(api_client)

    should_get = dm._should_get_initial_dimension(
        current_dimensions=current_dims, dataset_id="initial"
    )

    assert should_get is True


def test_should_get_initial_dimension_false(api_client):
    """
    Test that _should_get_initial_dimension returns False when all dimensions are present in the series key.
    """
    initial = MagicMock()
    initial.dataset_dimension_id = "initial"

    dim1 = MagicMock()
    dim1.dataset_dimension_id = "dim1"
    current_dims = [initial, dim1]
    series_key = {
        "dim1": "value1",
    }

    dm = ONSDatasetManager(api_client)

    should_get = dm._should_get_initial_dimension(
        current_dimensions=current_dims, dataset_id="initial"
    )

    assert should_get is False


@patch("macrotrace.sources.ons.ONSDatasetManager._should_get_initial_dimension")
def test_fetch_new_dataset_dimensions_full_flow(
    mock_should_get_initial_dimension, api_client, empty_state
):
    """
    Test that fetch_new_dataset_dimensions correctly fetches new dataset dimensions. Initial dimension is already present.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    state.series = Series.create(
        dataset=dataset,
        series_key={},
    )

    # Create the Initial dimension
    initial_dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="TEST_DATASET",
        title="initial",
        type="numeric",
        valid_from=datetime(2023, 1, 1, tzinfo=UTC),
    )

    release1 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "time"},
                {"name": "dim1"},
                {"name": "dim2"},
            ]
        },
    )
    release2 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 6, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "time"},
                {"name": "dim1"},
                {"name": "dim2"},
                {"name": "dim3"},
            ]
        },
    )
    release3 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 9, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "time"},
                {"name": "dim1"},
                {"name": "dim3"},
            ]
        },
    )
    state.new_releases = [release1, release2, release3]

    # We already made the initial dimension above
    mock_should_get_initial_dimension.return_value = False

    dm = ONSDatasetManager(api_client)

    new_dimensions = dm.fetch_new_dataset_dimensions(state)

    assert len(new_dimensions) == 3
    dim_names = {dim.title for dim in new_dimensions}
    assert dim_names == {"dim1", "dim2", "dim3"}
    for dim in new_dimensions:
        if dim.title == "dim1":
            assert dim.valid_from == datetime(2023, 1, 1, tzinfo=UTC)
            assert dim.valid_to is None
        elif dim.title == "dim2":
            assert dim.valid_from == datetime(2023, 1, 1, tzinfo=UTC)
            assert dim.valid_to == datetime(2023, 6, 1, tzinfo=UTC)
        elif dim.title == "dim3":
            assert dim.valid_from == datetime(2023, 6, 1, tzinfo=UTC)
            assert dim.valid_to is None


@patch("macrotrace.sources.ons.ONSDatasetManager._fetch_initial_dataset_dimension")
@patch("macrotrace.sources.ons.ONSDatasetManager._should_get_initial_dimension")
def test_fetch_new_dataset_dimensions_no_initial_dimension_fetch(
    mock_should_get_initial_dimension,
    mock_fetch_initial_dimension,
    api_client,
    empty_state,
):
    """
    Test that fetch_new_dataset_dimensions correctly fetches the initial dataset dimension when _should_get_initial_dimension returns True.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    state.series = Series.create(
        dataset=dataset,
        series_key={},
    )

    release1 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "time", "id": "mmm-yy"},
                {"name": "dim1"},
            ]
        },
    )
    state.new_releases = [release1]

    mock_should_get_initial_dimension.return_value = True
    mock_fetch_initial_dimension.return_value = None

    dm = ONSDatasetManager(api_client)

    _ = dm.fetch_new_dataset_dimensions(state)

    # Assert that the initial dimension fetch method was called if _should_get_initial_dimension returned True
    mock_fetch_initial_dimension.assert_called_once()


@patch("macrotrace.sources.ons.ONSDatasetManager._should_get_initial_dimension")
def test_fetch_new_releases_no_initial_dimension_raises(
    mock_should_get_initial_dimension, api_client, empty_state
):
    """
    Test that _fetch_new_releases raises an ValueError when the method is told not to fetch the initial dimension but no initial dimension exists.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    series = Series.create(
        dataset=dataset,
        series_key={},
    )
    state.series = series
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    release1 = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "time"},
                {"name": "dim1"},
            ]
        },
    )
    state.new_releases = [release1]

    mock_should_get_initial_dimension.return_value = False

    dm = ONSDatasetManager(api_client)

    with pytest.raises(ValueError) as exc_info:
        dm.fetch_new_dataset_dimensions(state)
        assert (
            str(exc_info.value)
            == f"Initial dimension should exist but was not found for dataset {state.dataset.dataset_id}"
        )


def test_fetch_new_dataset_dimensions_no_new_releases_returns_empty_list(
    api_client, empty_state
):
    """
    Test that fetch_new_dataset_dimensions returns an empty list when there are no new releases
    and an initial dimension already exists.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id
    state.series = Series.create(
        dataset=dataset,
        series_key={},
    )

    DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="TEST_DATASET",
        title="initial",
        type="numeric",
        valid_from=datetime(2023, 1, 1, tzinfo=UTC),
    )
    state.new_releases = []

    dm = ONSDatasetManager(api_client)
    new_dimensions = dm.fetch_new_dataset_dimensions(state)

    assert new_dimensions == []


def test_fetch_new_dataset_dimensions_no_new_releases_without_initial_dimension_raises_clear_error(
    api_client, empty_state
):
    """
    Test that fetch_new_dataset_dimensions raises a clear error when no releases
    match the requested window during initial ONS dataset setup.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id
    state.series = Series.create(dataset=dataset, series_key={})
    state.release_start_date = datetime(2025, 1, 1, tzinfo=UTC)
    state.new_releases = []

    dm = ONSDatasetManager(api_client)

    with pytest.raises(
        ValueError,
        match=(
            "Cannot initialize ONS dataset TEST_DATASET: no releases were found "
            "on or after 2025-01-01. At least one release is required to create "
            "the initial dataset dimension."
        ),
    ):
        dm.fetch_new_dataset_dimensions(state)
