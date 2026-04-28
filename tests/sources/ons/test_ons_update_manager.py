from macrotrace.sources.ons import (
    ONSUpdateManager,
    ONSAPIClient,
    ONSDatasetManager,
    ONSObservationManager,
    ONSReleaseManager,
    ONSSeriesManager,
    ONS_SOURCE,
)


def test_initialization():
    """Test that the ONSUpdateManager initializes correctly."""
    dataset_id = "test-dataset"
    release_start_date = "2020-01-01"
    release_end_date = "2020-12-31"

    um = ONSUpdateManager(
        dataset_id=dataset_id,
        release_start_date=release_start_date,
        release_end_date=release_end_date,
    )

    assert um.state.dataset_id == dataset_id
    assert um.state.source == ONS_SOURCE
    assert um.state.release_start_date == release_start_date
    assert um.state.release_end_date == release_end_date

    assert isinstance(um.api_client, ONSAPIClient)
    assert isinstance(um.dataset_manager, ONSDatasetManager)
    assert isinstance(um.release_manager, ONSReleaseManager)
    assert isinstance(um.series_manager, ONSSeriesManager)
    assert isinstance(um.observation_manager, ONSObservationManager)
