import pytest
import os
from macrotrace.sources.fred import (
    FredUpdateManager,
    FredAPIClient,
    FredDatasetManager,
    FredObservationManager,
    FredReleaseManager,
    FredSeriesManager,
    FRED_SOURCE,
)


def test_initialization():
    """Test that the FredUpdateManager initializes correctly."""
    dataset_id = "test-dataset"
    release_start_date = "2020-01-01"
    release_end_date = "2020-12-31"

    os.environ["FRED_API_KEY"] = "test_api_key"

    um = FredUpdateManager(
        dataset_id=dataset_id,
        release_start_date=release_start_date,
        release_end_date=release_end_date,
    )

    assert um.state.dataset_id == dataset_id
    assert um.state.source == FRED_SOURCE
    assert um.state.release_start_date == release_start_date
    assert um.state.release_end_date == release_end_date

    assert isinstance(um.api_client, FredAPIClient)
    assert isinstance(um.dataset_manager, FredDatasetManager)
    assert isinstance(um.release_manager, FredReleaseManager)
    assert isinstance(um.series_manager, FredSeriesManager)
    assert isinstance(um.observation_manager, FredObservationManager)


def test_series_key_warning(caplog):
    """Test that a warning is raised when series_key is used."""
    dataset_id = "test-dataset"
    series_key = {"not used": "NOT_USED"}
    os.environ["FRED_API_KEY"] = "test_api_key"

    um = FredUpdateManager(
        dataset_id=dataset_id,
        series_key=series_key,
    )

    assert "FRED series do not have series keys" in caplog.text


def test_missing_api_key_raises():
    """Test that missing FRED API key raises a ValueError."""
    dataset_id = "test-dataset"

    if "FRED_API_KEY" in os.environ:
        del os.environ["FRED_API_KEY"]

    with pytest.raises(
        EnvironmentError,
        match="FRED API key is required to use the FRED API client. Please provide one with the 'FRED_API_KEY' environment variable.",
    ):
        FredUpdateManager(dataset_id=dataset_id)
