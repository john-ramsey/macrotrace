import pytest
from datetime import datetime, timezone

from macrotrace.sources.base import UpdateState
from macrotrace.models import (
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
)


def test_update_state_default_initialization():
    """Test that UpdateState initializes with all None values by default."""
    state = UpdateState()

    assert state.dataset is None
    assert state.dataset_id is None
    assert state.source is None
    assert state.dataset_mode is None
    assert state.series is None
    assert state.series_mode is None
    assert state.series_key is None
    assert state.release_start_date is None
    assert state.release_end_date is None
    assert state.new_dataset_dimensions is None
    assert state.new_series_dimension_filters is None
    assert state.new_releases is None
    assert state.new_release_dimensions is None
    assert state.new_observations is None


def test_update_state_with_values():
    """Test that UpdateState can be initialized with specific values."""
    dataset_id = "TEST_DATASET"
    source = "TEST_SOURCE"
    series_key = {"FREQ": "MS", "AREA": "US"}
    start_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end_date = datetime(2023, 12, 31, tzinfo=timezone.utc)

    state = UpdateState(
        dataset_id=dataset_id,
        source=source,
        series_key=series_key,
        release_start_date=start_date,
        release_end_date=end_date,
    )

    assert state.dataset_id == dataset_id
    assert state.source == source
    assert state.series_key == series_key
    assert state.release_start_date == start_date
    assert state.release_end_date == end_date


def test_update_state_field_assignment():
    """Test that UpdateState fields can be assigned after initialization."""
    state = UpdateState()

    state.dataset_id = "NEW_DATASET"
    state.source = "NEW_SOURCE"
    state.series_key = {"KEY": "VALUE"}

    assert state.dataset_id == "NEW_DATASET"
    assert state.source == "NEW_SOURCE"
    assert state.series_key == {"KEY": "VALUE"}
