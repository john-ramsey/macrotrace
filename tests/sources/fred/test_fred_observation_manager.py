import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from macrotrace.models.db import Dataset, Release, Series, Observation
from macrotrace.sources.fred import FredObservationManager

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.fred.fixtures import (
    api_client,
    empty_state,
    US_CENTRAL,
    db_setup_and_teardown,
)


def test_initialization(api_client):
    """Test that the FredObservationManager initializes correctly."""
    rm = FredObservationManager(api_client=api_client)
    assert rm.api_client == api_client


def test_clean_vintage_str_date(api_client):
    """Test that _clean_vintage_str_date correctly cleans vintage date strings."""
    om = FredObservationManager(api_client=api_client)
    sample = "SERIESID_20250101"
    cleaned_date = om._clean_vintage_str_date(sample)
    assert cleaned_date == US_CENTRAL.localize(datetime(2025, 1, 1))


def test_clean_vintage_str_date_invalid(api_client):
    """Test that _clean_vintage_str_date raises ValueError on invalid input."""
    om = FredObservationManager(api_client=api_client)
    sample = "INVALID_STRING"
    with pytest.raises(ValueError):
        om._clean_vintage_str_date(sample)


def test_create_release_date_chunks_single_chunk(api_client):
    """Test that _create_release_date_chunks creates a single chunk when all dates fit."""
    om = FredObservationManager(api_client=api_client)

    release1 = MagicMock()
    release1.release_date = datetime(2025, 1, 1)
    release2 = MagicMock()
    release2.release_date = datetime(2025, 2, 1)
    release3 = MagicMock()
    release3.release_date = datetime(2025, 3, 1)

    releases = [release1, release2, release3]
    chunks = om._create_release_date_chunks(
        releases, current_url_len=100, max_url_len=7500
    )
    assert len(chunks) == 1
    assert chunks[0] == "2025-01-01,2025-02-01,2025-03-01"


def test_create_release_date_chunks_multiple_chunks(api_client):
    """Test that _create_release_date_chunks creates multiple chunks when dates exceed max URL length."""
    om = FredObservationManager(api_client=api_client)

    releases = []
    for i in range(1, 25):  # 24 months to ensure multiple chunks
        release = MagicMock()
        year = 2025 + (i - 1) // 12
        month = (i - 1) % 12 + 1
        release.release_date = datetime(year, month, 1)
        releases.append(release)

    chunks = om._create_release_date_chunks(
        releases, current_url_len=100, max_url_len=200
    )
    assert len(chunks) == 4
    for chunk in chunks:
        assert len(chunk) <= 200


def test_create_release_date_chunks_errors_no_budget(api_client):
    """Test that _create_release_date_chunks raises an error when no budget is available."""
    om = FredObservationManager(api_client=api_client)

    releases = []
    for i in range(1, 3):  # Only 2 releases to keep it simple
        release = MagicMock()
        release.release_date = datetime(2025, i, 1)
        releases.append(release)

    with pytest.raises(ValueError):
        om._create_release_date_chunks(releases, current_url_len=100, max_url_len=10)


def test_create_new_observations(api_client, empty_state):
    """Test that _create_new_observations creates Observation objects correctly."""
    state = empty_state

    dataset = Dataset.create(dataset_id="TESTDATASET", source="FRED")
    state.dataset = dataset

    release1 = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2025, 1, 1))
    )
    release2 = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2025, 2, 1))
    )

    series = Series.create(dataset=dataset, series_key={})
    state.series = series

    om = FredObservationManager(api_client=api_client)
    obs_data = [
        {"date": "2025-01-01", "TESTDATASET_20250101": 10.0},
        {"date": "2025-02-01", "TESTDATASET_20250201": 20.0},
    ]
    release_dates_to_id = {
        US_CENTRAL.localize(datetime(2025, 1, 1)): release1.id,
        US_CENTRAL.localize(datetime(2025, 2, 1)): release2.id,
    }

    new_observations = om._create_new_observations(state, obs_data, release_dates_to_id)
    assert len(new_observations) == 2
    assert new_observations[0].series.id == series.id
    assert new_observations[0].release.id == release1.id
    assert new_observations[0].value == 10.0
    assert new_observations[1].series.id == series.id
    assert new_observations[1].release.id == release2.id
    assert new_observations[1].value == 20.0


def test_create_new_observations_with_missing_values(api_client, empty_state):
    """Test that _create_new_observations handles missing values correctly."""
    state = empty_state

    dataset = Dataset.create(dataset_id="TESTDATASET", source="FRED")
    state.dataset = dataset

    release1 = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2025, 1, 1))
    )
    release2 = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2025, 2, 1))
    )

    series = Series.create(dataset=dataset, series_key={})
    state.series = series

    om = FredObservationManager(api_client=api_client)
    obs_data = [
        {"date": "2025-01-01", "TESTDATASET_20250101": "."},
        {"date": "2025-02-01", "TESTDATASET_20250201": 20.0},
    ]
    release_dates_to_id = {
        US_CENTRAL.localize(datetime(2025, 1, 1)): release1.id,
        US_CENTRAL.localize(datetime(2025, 2, 1)): release2.id,
    }

    new_observations = om._create_new_observations(state, obs_data, release_dates_to_id)
    assert len(new_observations) == 2
    assert new_observations[0].value != new_observations[0].value  # NaN check
    assert new_observations[1].value == 20.0


@patch("macrotrace.sources.fred.APIClient.make_request")
def test_batch_query_fred_observations_batches_properly(mock_make_request, api_client):
    """Test that _batch_query_fred_observations correctly batches API requests."""
    args = {
        "endpoint": "/series/observations",
        "params": {
            "vintage_dates": "",
        },
    }

    chunks = [
        "2025-01-01,2025-02-01",
        "2025-03-01,2025-04-01",
    ]

    # Capture the vintage_dates values at call time
    # Needed as the args dict is mutated in the method
    captured_vintage_dates = []

    def capture_call(endpoint, params=None):
        if params is None:
            params = {}
        captured_vintage_dates.append(params["vintage_dates"])
        return {"observations": []}

    mock_make_request.side_effect = capture_call

    om = FredObservationManager(api_client=api_client)

    _ = om._batch_query_fred_observations(release_date_chunks=chunks, api_args=args)

    assert mock_make_request.call_count == 2
    assert captured_vintage_dates[0] == "2025-01-01,2025-02-01"
    assert captured_vintage_dates[1] == "2025-03-01,2025-04-01"


def test_batch_query_fred_observations_returns_properly(api_client):
    """Test that _batch_query_fred_observations returns combined observation data."""
    om = FredObservationManager(api_client=api_client)

    args = {
        "endpoint": "/series/observations",
        "params": {
            "vintage_dates": "",
        },
    }

    chunks = [
        "2025-01-01,2025-02-01",
        "2025-03-01,2025-04-01",
    ]

    # Mock the API client's make_request method
    def mock_make_request(endpoint, params):
        if params["vintage_dates"] == "2025-01-01,2025-02-01":
            return {
                "observations": [
                    {"date": "2025-01-01", "value": "10.0"},
                    {"date": "2025-02-01", "value": "20.0"},
                ]
            }
        elif params["vintage_dates"] == "2025-03-01,2025-04-01":
            return {
                "observations": [
                    {"date": "2025-03-01", "value": "30.0"},
                    {"date": "2025-04-01", "value": "40.0"},
                ]
            }
        return {"observations": []}

    om.api_client.make_request = mock_make_request

    combined_obs = om._batch_query_fred_observations(
        release_date_chunks=chunks, api_args=args
    )

    assert len(combined_obs) == 4
    assert combined_obs[0] == {"date": "2025-01-01", "value": "10.0"}
    assert combined_obs[1] == {"date": "2025-02-01", "value": "20.0"}
    assert combined_obs[2] == {"date": "2025-03-01", "value": "30.0"}
    assert combined_obs[3] == {"date": "2025-04-01", "value": "40.0"}


@patch("macrotrace.sources.fred.FredObservationManager._create_new_observations")
@patch("macrotrace.sources.fred.FredObservationManager._batch_query_fred_observations")
@patch("macrotrace.sources.fred.FredObservationManager._create_release_date_chunks")
@patch("macrotrace.sources.base.APIClient.make_request_dry_run")
def test_fetch_new_observations_full_run(
    mock_make_request_dry_run,
    mock_create_release_date_chunks,
    mock_batch_query_fred_observations,
    mock_create_new_observations,
    api_client,
    empty_state,
):
    state = empty_state

    dataset = Dataset.create(dataset_id="TESTDATASET", source="FRED")
    state.dataset = dataset
    state.dataset_id = dataset.dataset_id

    release1 = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2025, 1, 1))
    )
    release2 = Release.create(
        dataset=dataset, release_date=US_CENTRAL.localize(datetime(2025, 2, 1))
    )
    state.new_releases = [release1, release2]

    series = Series.create(dataset=dataset, series_key={})
    state.series = series

    mock_make_request_dry_run.return_value = "12345", {}
    mock_create_release_date_chunks.return_value = ["2025-01-01,2025-02-01"]
    mock_batch_query_fred_observations.return_value = [
        {"date": "2025-01-01", "TESTDATASET_20250101": 10.0},
        {"date": "2025-02-01", "TESTDATASET_20250201": 20.0},
    ]

    om = FredObservationManager(api_client=api_client)
    new_observations = om.fetch_new_observations(state)

    mock_make_request_dry_run.assert_called_once_with(
        endpoint="series/observations",
        params={
            "series_id": "TESTDATASET",
            "output_type": "2",
            "vintage_dates": "",
        },
    )
    mock_create_release_date_chunks.assert_called_once_with(
        releases=state.new_releases, current_url_len=5
    )
    mock_batch_query_fred_observations.assert_called_once()
    mock_create_new_observations.assert_called_once_with(
        state,
        mock_batch_query_fred_observations.return_value,
        {
            US_CENTRAL.localize(datetime(2025, 1, 1)): release1.id,
            US_CENTRAL.localize(datetime(2025, 2, 1)): release2.id,
        },
    )
    assert new_observations == mock_create_new_observations.return_value


def test_fetch_new_observations_no_new_releases(api_client, empty_state):
    """Test that fetch_new_observations returns an empty list when there are no new releases."""
    state = empty_state
    state.new_releases = []

    om = FredObservationManager(api_client=api_client)
    new_observations = om.fetch_new_observations(state)
    assert new_observations == []
