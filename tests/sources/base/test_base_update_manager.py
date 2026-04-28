import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call
from typing import Optional, Dict, Any

from macrotrace.sources.base import (
    APIClient,
    DatasetManager,
    SeriesManager,
    ReleaseManager,
    ObservationManager,
    UpdateManager,
)
from macrotrace.models.db import (
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
)

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.base.fixtures import api_client, empty_state, db_setup_and_teardown


def test_initialize_update_manager_fails():
    """Test that initializing the base UpdateManager raises NotImplementedError. We should not be able to instantiate it directly."""
    with pytest.raises(NotImplementedError):
        UpdateManager(dataset_id="TEST", source="SOURCE")


def test_create_api_client():
    """Test that _create_api_client raises NotImplementedError in the base UpdateManager."""
    with patch.object(UpdateManager, "__init__", lambda self, **kwargs: None):
        update_manager = UpdateManager(dataset_id="TEST", source="SOURCE")
        with pytest.raises(NotImplementedError):
            update_manager._create_api_client()


def test_create_dataset_manager():
    """Test that _create_dataset_manager raises NotImplementedError in the base UpdateManager."""
    with patch.object(UpdateManager, "__init__", lambda self, **kwargs: None):
        update_manager = UpdateManager(dataset_id="TEST", source="SOURCE")
        with pytest.raises(NotImplementedError):
            update_manager._create_dataset_manager()


def test_create_release_manager():
    """Test that _create_release_manager raises NotImplementedError in the base UpdateManager."""
    with patch.object(UpdateManager, "__init__", lambda self, **kwargs: None):
        update_manager = UpdateManager(dataset_id="TEST", source="SOURCE")
        with pytest.raises(NotImplementedError):
            update_manager._create_release_manager()


def test_create_series_manager():
    """Test that _create_series_manager raises NotImplementedError in the base UpdateManager."""
    with patch.object(UpdateManager, "__init__", lambda self, **kwargs: None):
        update_manager = UpdateManager(dataset_id="TEST", source="SOURCE")
        with pytest.raises(NotImplementedError):
            update_manager._create_series_manager()


def test_create_observation_manager():
    """Test that _create_observation_manager raises NotImplementedError in the base UpdateManager."""
    with patch.object(UpdateManager, "__init__", lambda self, **kwargs: None):
        update_manager = UpdateManager(dataset_id="TEST", source="SOURCE")
        with pytest.raises(NotImplementedError):
            update_manager._create_observation_manager()


class _TestUpdateManager(UpdateManager):
    """Concrete implementation for testing write_objects_to_db."""

    def _create_api_client(
        self,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ) -> APIClient:
        client = APIClient(base_url="https://api.example.com")
        client._get_request_headers = lambda: {}
        client._get_default_params = lambda: {}
        return client

    def _create_dataset_manager(self) -> DatasetManager:
        """Override this to provide a specific dataset manager."""
        return DatasetManager(self.api_client)

    def _create_release_manager(self) -> ReleaseManager:
        """Override this to provide a specific release manager."""
        return ReleaseManager(self.api_client)

    def _create_series_manager(self) -> SeriesManager:
        """Override this to provide a specific series manager."""
        return SeriesManager(self.api_client)

    def _create_observation_manager(self) -> ObservationManager:
        """Override this to provide a specific observation manager."""
        return ObservationManager(self.api_client)


def test_write_objects_to_db_inserts():
    """
    Test UpdateManager._write_objects_to_db() correctly inserts new records into the database.
    """
    objs = [
        Dataset(dataset_id="TEST1", source="SOURCE"),
        Dataset(dataset_id="TEST2", source="SOURCE"),
    ]

    update_manager = _TestUpdateManager(dataset_id="TEST1", source="SOURCE")
    update_manager._write_objects_to_db(objs)

    assert Dataset.select().count() == 2

    # Retrieve by realtime_start to verify both records
    dataset_list = list(Dataset.select().order_by(Dataset.dataset_id))
    assert dataset_list[0].dataset_id == "TEST1"
    assert dataset_list[1].dataset_id == "TEST2"
    assert len(dataset_list) == 2


def test_write_objects_to_db_no_writes_on_empty():
    """
    Test UpdateManager._write_objects_to_db() does nothing when given an empty list.
    """
    update_manager = _TestUpdateManager(dataset_id="TEST1", source="SOURCE")
    update_manager._write_objects_to_db([])
    assert Observation.select().count() == 0


def test_write_objects_to_db_upserts():
    """
    Test UpdateManager._write_objects_to_db() correctly upserts existing records in the database.
    """
    initial_dataset = Dataset.create(dataset_id="TEST1", source="SOURCE")

    initial_dataset_dimension = DatasetDimension.create(
        dataset=initial_dataset,
        dataset_dimension_id="DIM1",
        title="Dimension1",
        type="numeric",
        frequency="MS",
        valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert (
        DatasetDimension.get(
            DatasetDimension.id == initial_dataset_dimension.id
        ).valid_to
        is None
    )

    updated_dataset_dimension = DatasetDimension(
        dataset=initial_dataset,
        dataset_dimension_id="DIM1",
        title="Dimension1",
        type="numeric",
        frequency="MS",
        valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        valid_to=datetime(2025, 12, 31, tzinfo=timezone.utc),
    )

    update_manager = _TestUpdateManager(dataset_id="TEST1", source="SOURCE")
    update_manager._write_objects_to_db([updated_dataset_dimension])

    assert DatasetDimension.select().count() == 1
    dimension_in_db = DatasetDimension.get(
        (DatasetDimension.dataset == initial_dataset)
        & (DatasetDimension.dataset_dimension_id == "DIM1")
    )
    assert dimension_in_db.valid_to == datetime(2025, 12, 31, tzinfo=timezone.utc)


@patch.object(ObservationManager, "fetch_new_observations")
@patch.object(SeriesManager, "fetch_new_series_dimension_filters")
@patch.object(ReleaseManager, "fetch_new_release_dimensions")
@patch.object(DatasetManager, "fetch_new_dataset_dimensions")
@patch.object(ReleaseManager, "fetch_new_releases")
@patch.object(SeriesManager, "fetch_or_create_series_definition")
@patch.object(DatasetManager, "fetch_or_create_dataset_definition")
@patch.object(_TestUpdateManager, "_write_objects_to_db")
def test_update_full_flow_success(
    mock_write,
    mock_fetch_dataset,
    mock_fetch_series,
    mock_fetch_releases,
    mock_fetch_dataset_dims,
    mock_fetch_release_dims,
    mock_fetch_series_filters,
    mock_fetch_observations,
):
    """
    Test complete update flow with all components working (Integration Test - Happy Path).
    Verifies that the update method orchestrates all manager calls correctly and returns
    a properly populated UpdateState.
    """
    # Create test data
    test_dataset = Dataset(dataset_id="TEST1", source="SOURCE")
    test_series = Series(dataset=test_dataset, series_key={"geo": "US"})
    test_releases = [
        Release(
            dataset=test_dataset,
            release_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        ),
        Release(
            dataset=test_dataset,
            release_date=datetime(2025, 2, 1, tzinfo=timezone.utc),
        ),
    ]
    test_dataset_dimensions = [
        DatasetDimension(
            dataset=test_dataset,
            dataset_dimension_id="geo",
            title="Geography",
            type="text",
            frequency="MS",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    ]
    test_release_dimensions = [
        ReleaseDimension(
            release=test_releases[0],
            dimension=test_dataset_dimensions[0],
            value="US",
        )
    ]
    test_series_dimension_filters = [
        SeriesDimensionFilter(
            series=test_series,
            dimension=test_dataset_dimensions[0],
            value="US",
        )
    ]
    test_observations = [
        Observation(
            series=test_series,
            release=test_releases[0],
            date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            value=100.0,
        ),
        Observation(
            series=test_series,
            release=test_releases[1],
            date=datetime(2025, 2, 1, tzinfo=timezone.utc),
            value=101.0,
        ),
    ]

    # Configure mocks with return values
    mock_fetch_dataset.return_value = test_dataset
    mock_fetch_series.return_value = test_series
    mock_fetch_releases.return_value = test_releases
    mock_fetch_dataset_dims.return_value = test_dataset_dimensions
    mock_fetch_release_dims.return_value = test_release_dimensions
    mock_fetch_series_filters.return_value = test_series_dimension_filters
    mock_fetch_observations.return_value = test_observations

    # Create update manager after mocks are set up
    update_manager = _TestUpdateManager(
        dataset_id="TEST1", source="SOURCE", series_key={"geo": "US"}
    )

    # Run the update
    state = update_manager.update()

    # Verify all fetch methods were called
    mock_fetch_dataset.assert_called_once_with(update_manager.state)
    mock_fetch_series.assert_called_once_with(update_manager.state)
    mock_fetch_releases.assert_called_once_with(update_manager.state)
    mock_fetch_dataset_dims.assert_called_once_with(update_manager.state)
    mock_fetch_release_dims.assert_called_once_with(update_manager.state)
    mock_fetch_series_filters.assert_called_once_with(update_manager.state)
    mock_fetch_observations.assert_called_once_with(update_manager.state)

    # Verify _write_objects_to_db was called with the correct objects
    assert mock_write.call_count == 5
    mock_write.assert_any_call(test_releases)
    mock_write.assert_any_call(test_dataset_dimensions)
    mock_write.assert_any_call(test_release_dimensions)
    mock_write.assert_any_call(test_series_dimension_filters)
    mock_write.assert_any_call(test_observations)

    # Verify state contains expected data.
    # Use `is` since unsaved Peewee models with id=None compare unequal
    # under Model.__eq__ (which requires _pk to be non-None).
    # Note: state.new_releases is re-queried from the DB after write, so under
    # mocked writes it is replaced with an empty list.
    assert state.dataset is test_dataset
    assert state.series is test_series
    assert state.new_releases == []
    assert state.new_dataset_dimensions is test_dataset_dimensions
    assert state.new_release_dimensions is test_release_dimensions
    assert state.new_series_dimension_filters is test_series_dimension_filters
    assert state.new_observations is test_observations


@patch.object(ObservationManager, "fetch_new_observations")
@patch.object(SeriesManager, "fetch_new_series_dimension_filters")
@patch.object(ReleaseManager, "fetch_new_release_dimensions")
@patch.object(DatasetManager, "fetch_new_dataset_dimensions")
@patch.object(ReleaseManager, "fetch_new_releases")
@patch.object(SeriesManager, "fetch_or_create_series_definition")
@patch.object(DatasetManager, "fetch_or_create_dataset_definition")
def test_update_manager_call_order(
    mock_fetch_dataset,
    mock_fetch_series,
    mock_fetch_releases,
    mock_fetch_dataset_dims,
    mock_fetch_release_dims,
    mock_fetch_series_filters,
    mock_fetch_observations,
):
    """
    Test that UpdateManager.update() calls managers in the correct sequence.
    Verifies that dataset/series definitions are fetched before dependent operations,
    and that writes happen after fetches.
    """
    # Create test data
    test_dataset = Dataset(dataset_id="TEST1", source="SOURCE")
    test_series = Series(dataset=test_dataset, series_key={"geo": "US"})

    # Track call order
    call_tracker = []

    def return_dataset(*args, **kwargs):
        call_tracker.append("fetch_dataset")
        return test_dataset

    def return_series(*args, **kwargs):
        call_tracker.append("fetch_series")
        return test_series

    # Configure mocks with side effects that track calls
    mock_fetch_dataset.side_effect = return_dataset
    mock_fetch_series.side_effect = return_series
    mock_fetch_releases.side_effect = lambda state: (
        call_tracker.append("fetch_releases"),
        [],
    )[1]
    mock_fetch_dataset_dims.side_effect = lambda state: (
        call_tracker.append("fetch_dataset_dims"),
        [],
    )[1]
    mock_fetch_release_dims.side_effect = lambda state: (
        call_tracker.append("fetch_release_dims"),
        [],
    )[1]
    mock_fetch_series_filters.side_effect = lambda state: (
        call_tracker.append("fetch_series_filters"),
        [],
    )[1]
    mock_fetch_observations.side_effect = lambda state: (
        call_tracker.append("fetch_observations"),
        [],
    )[1]

    # Create update manager after mocks are set up
    update_manager = _TestUpdateManager(
        dataset_id="TEST1", source="SOURCE", series_key={"geo": "US"}
    )

    # Run the update
    update_manager.update()

    # Verify call order
    assert call_tracker == [
        "fetch_dataset",
        "fetch_series",
        "fetch_releases",
        "fetch_dataset_dims",
        "fetch_release_dims",
        "fetch_series_filters",
        "fetch_observations",
    ]

    # Verify dataset is fetched before series
    dataset_idx = call_tracker.index("fetch_dataset")
    series_idx = call_tracker.index("fetch_series")
    assert dataset_idx < series_idx

    # Verify releases are fetched before release dimensions
    releases_idx = call_tracker.index("fetch_releases")
    release_dims_idx = call_tracker.index("fetch_release_dims")
    assert releases_idx < release_dims_idx

    # Verify observations are fetched last
    observations_idx = call_tracker.index("fetch_observations")
    assert observations_idx == len(call_tracker) - 1


@patch.object(DatasetManager, "fetch_or_create_dataset_definition")
def test_update_rollback_on_dataset_fetch_failure(mock_fetch_dataset):
    """
    Test that the database transaction rolls back when dataset fetch fails.
    Verifies no partial data is persisted when the first operation fails.
    """
    mock_fetch_dataset.side_effect = Exception("Dataset fetch failed")

    update_manager = _TestUpdateManager(dataset_id="TEST1", source="SOURCE")
    with pytest.raises(Exception, match="Dataset fetch failed"):
        update_manager.update()

    # Verify no data was persisted
    assert Dataset.select().count() == 0
    assert Series.select().count() == 0
    assert Release.select().count() == 0
    assert DatasetDimension.select().count() == 0
    assert Observation.select().count() == 0


@patch.object(ReleaseManager, "fetch_new_releases")
@patch.object(SeriesManager, "fetch_or_create_series_definition")
@patch.object(DatasetManager, "fetch_or_create_dataset_definition")
def test_update_rollback_on_release_fetch_failure(
    mock_fetch_dataset, mock_fetch_series, mock_fetch_releases
):
    """
    Test that the database transaction rolls back when release fetch fails.
    Verifies that dataset and series creation are rolled back when a later operation fails.
    """
    test_dataset = Dataset(dataset_id="TEST1", source="SOURCE")
    test_series = Series(dataset=test_dataset, series_key={"geo": "US"})

    mock_fetch_dataset.return_value = test_dataset
    mock_fetch_series.return_value = test_series
    mock_fetch_releases.side_effect = Exception("Release fetch failed")

    update_manager = _TestUpdateManager(
        dataset_id="TEST1", source="SOURCE", series_key={"geo": "US"}
    )

    with pytest.raises(Exception, match="Release fetch failed"):
        update_manager.update()

    # Verify no data was persisted (including dataset and series that were created before failure)
    assert Dataset.select().count() == 0
    assert Series.select().count() == 0
    assert Release.select().count() == 0
    assert DatasetDimension.select().count() == 0
    assert Observation.select().count() == 0


@patch.object(ObservationManager, "fetch_new_observations")
@patch.object(SeriesManager, "fetch_new_series_dimension_filters")
@patch.object(ReleaseManager, "fetch_new_release_dimensions")
@patch.object(DatasetManager, "fetch_new_dataset_dimensions")
@patch.object(ReleaseManager, "fetch_new_releases")
@patch.object(SeriesManager, "fetch_or_create_series_definition")
@patch.object(DatasetManager, "fetch_or_create_dataset_definition")
@patch.object(_TestUpdateManager, "_write_objects_to_db")
def test_update_rollback_on_observation_write_failure(
    mock_write,
    mock_fetch_dataset,
    mock_fetch_series,
    mock_fetch_releases,
    mock_fetch_dataset_dims,
    mock_fetch_release_dims,
    mock_fetch_series_filters,
    mock_fetch_observations,
):
    """
    Test that the database transaction rolls back when observation write fails.
    Verifies that all previous writes (releases, dimensions, filters) are rolled back
    when the final write operation fails.
    """
    test_dataset = Dataset(dataset_id="TEST1", source="SOURCE")
    test_series = Series(dataset=test_dataset, series_key={"geo": "US"})
    test_releases = [
        Release(
            dataset=test_dataset,
            release_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    ]
    test_dataset_dimensions = [
        DatasetDimension(
            dataset=test_dataset,
            dataset_dimension_id="geo",
            title="Geography",
            type="text",
            frequency="MS",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    ]
    test_release_dimensions = [
        ReleaseDimension(
            release=test_releases[0],
            dimension=test_dataset_dimensions[0],
            value="US",
        )
    ]
    test_series_dimension_filters = [
        SeriesDimensionFilter(
            series=test_series,
            dimension=test_dataset_dimensions[0],
            value="US",
        )
    ]
    test_observations = [
        Observation(
            series=test_series,
            release=test_releases[0],
            date=datetime(2025, 1, 1, tzinfo=timezone.utc),
            value=100.0,
        )
    ]

    #  All fetches succeed, but last write fails
    mock_fetch_dataset.return_value = test_dataset
    mock_fetch_series.return_value = test_series
    mock_fetch_releases.return_value = test_releases
    mock_fetch_dataset_dims.return_value = test_dataset_dimensions
    mock_fetch_release_dims.return_value = test_release_dimensions
    mock_fetch_series_filters.return_value = test_series_dimension_filters
    mock_fetch_observations.return_value = test_observations

    def write_side_effect(objs):
        if objs == test_observations:
            raise Exception("Observation write failed")

    mock_write.side_effect = write_side_effect

    update_manager = _TestUpdateManager(
        dataset_id="TEST1", source="SOURCE", series_key={"geo": "US"}
    )

    with pytest.raises(Exception, match="Observation write failed"):
        update_manager.update()

    # Verify no data was persisted (all writes should be rolled back)
    assert Dataset.select().count() == 0
    assert Series.select().count() == 0
    assert Release.select().count() == 0
    assert DatasetDimension.select().count() == 0
    assert ReleaseDimension.select().count() == 0
    assert SeriesDimensionFilter.select().count() == 0
    assert Observation.select().count() == 0


@patch.object(ObservationManager, "fetch_new_observations")
@patch.object(SeriesManager, "fetch_new_series_dimension_filters")
@patch.object(ReleaseManager, "fetch_new_release_dimensions")
@patch.object(DatasetManager, "fetch_new_dataset_dimensions")
@patch.object(ReleaseManager, "fetch_new_releases")
@patch.object(SeriesManager, "fetch_or_create_series_definition")
@patch.object(DatasetManager, "fetch_or_create_dataset_definition")
def test_update_rollback_preserves_existing_data(
    mock_fetch_dataset,
    mock_fetch_series,
    mock_fetch_releases,
    mock_fetch_dataset_dims,
    mock_fetch_release_dims,
    mock_fetch_series_filters,
    mock_fetch_observations,
):
    """
    Test that rollback doesn't affect existing data that was committed before the update.
    Verifies that pre-existing database records remain intact after a failed update.
    """
    # Create existing data in the database BEFORE the update
    existing_dataset = Dataset.create(dataset_id="EXISTING", source="SOURCE")
    existing_series = Series.create(dataset=existing_dataset, series_key={"geo": "UK"})

    test_dataset = Dataset(dataset_id="TEST1", source="SOURCE")
    test_series = Series(dataset=test_dataset, series_key={"geo": "US"})
    mock_fetch_dataset.return_value = test_dataset
    mock_fetch_series.side_effect = Exception("Series fetch failed")

    update_manager = _TestUpdateManager(
        dataset_id="TEST1", source="SOURCE", series_key={"geo": "US"}
    )

    with pytest.raises(Exception, match="Series fetch failed"):
        update_manager.update()

    # Verify only the existing data persists (new data rolled back)
    assert Dataset.select().count() == 1
    assert Series.select().count() == 1
    assert Dataset.get(Dataset.dataset_id == "EXISTING") == existing_dataset
    assert Series.get(Series.id == existing_series.id) == existing_series

    # Verify the failed dataset creation was rolled back
    assert Dataset.get_or_none(Dataset.dataset_id == "TEST1") is None


@patch.object(ObservationManager, "fetch_new_observations")
@patch.object(SeriesManager, "fetch_new_series_dimension_filters")
@patch.object(ReleaseManager, "fetch_new_release_dimensions")
@patch.object(DatasetManager, "fetch_new_dataset_dimensions")
@patch.object(ReleaseManager, "fetch_new_releases")
@patch.object(SeriesManager, "fetch_or_create_series_definition")
@patch.object(DatasetManager, "fetch_or_create_dataset_definition")
@patch.object(_TestUpdateManager, "_write_objects_to_db")
def test_update_rollback_on_mid_write_failure(
    mock_write,
    mock_fetch_dataset,
    mock_fetch_series,
    mock_fetch_releases,
    mock_fetch_dataset_dims,
    mock_fetch_release_dims,
    mock_fetch_series_filters,
    mock_fetch_observations,
):
    """
    Test that rollback works when a failure occurs in the middle of the update process.
    Verifies that earlier successful writes are rolled back along with later operations.
    """
    test_dataset = Dataset(dataset_id="TEST1", source="SOURCE")
    test_series = Series(dataset=test_dataset, series_key={"geo": "US"})
    test_releases = [
        Release(
            dataset=test_dataset,
            release_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    ]
    test_dataset_dimensions = [
        DatasetDimension(
            dataset=test_dataset,
            dataset_dimension_id="geo",
            title="Geography",
            type="text",
            frequency="MS",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
    ]

    mock_fetch_dataset.return_value = test_dataset
    mock_fetch_series.return_value = test_series
    mock_fetch_releases.return_value = test_releases
    mock_fetch_dataset_dims.return_value = test_dataset_dimensions
    mock_fetch_release_dims.side_effect = Exception("Release dimension fetch failed")
    call_count = [0]

    def write_side_effect(objs):
        call_count[0] += 1

    mock_write.side_effect = write_side_effect

    update_manager = _TestUpdateManager(
        dataset_id="TEST1", source="SOURCE", series_key={"geo": "US"}
    )

    with pytest.raises(Exception, match="Release dimension fetch failed"):
        update_manager.update()

    # Verify that even though some writes succeeded, everything was rolled back
    assert Dataset.select().count() == 0
    assert Series.select().count() == 0
    assert Release.select().count() == 0
    assert DatasetDimension.select().count() == 0
    assert ReleaseDimension.select().count() == 0

    # Verify write was called for releases and dataset dimensions before the failure
    assert mock_write.call_count == 2
