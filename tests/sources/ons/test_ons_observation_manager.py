import logging
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from macrotrace.models.db import Dataset, Release, Series, Observation
from macrotrace.sources.ons import ONSObservationManager, year_quarter_to_ymd

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.ons.fixtures import (
    api_client,
    empty_state,
    db_setup_and_teardown,
    UTC,
)


def test_initialization(api_client):
    """
    Test that the ONSObservationManager initializes correctly with the provided API client.
    """
    om = ONSObservationManager(api_client)

    assert om.api_client == api_client


def test_validate_series_key_against_release_success(api_client):
    """
    Test the method _validate_series_key_against_release for a valid series key.
    """
    om = ONSObservationManager(api_client)
    release = MagicMock()
    release.additional_metadata = {
        "dimensions": [
            {"name": "geography"},
            {"name": "age"},
            {"name": "time"},
        ]
    }

    series_key = {
        "geography": "K02000001",
        "age": "A--T",
    }

    is_valid = om._validate_series_key_against_release(release, series_key)

    assert is_valid is None


def test_validate_series_key_against_release_failure(api_client):
    """
    Test the method _validate_series_key_against_release for an invalid series key.
    """
    om = ONSObservationManager(api_client)
    release = MagicMock()
    release.additional_metadata = {
        "dimensions": [
            {"name": "geography"},
            {"name": "age"},
            {"name": "time"},
        ]
    }

    series_key = {
        "geography": "K02000001",
        # Missing 'age'
    }

    with pytest.raises(
        ValueError,
        match="Series key is missing required dimension: age",
    ):
        om._validate_series_key_against_release(release, series_key)


def test_build_observations_endpoint(api_client, empty_state):
    """
    Test the method _build_observations_endpoint constructs the correct endpoint.
    """
    state = empty_state
    release = MagicMock()
    release.additional_metadata = {
        "version": "release-123",
    }
    dataset = MagicMock()
    dataset.dataset_id = "example-dataset"
    state.dataset = dataset

    om = ONSObservationManager(api_client)

    expected_endpoint = "datasets/example-dataset/editions/time-series/versions/release-123/observations"
    endpoint = om._build_observations_endpoint(state, release)

    assert endpoint == expected_endpoint


def test_build_observations_params(api_client, empty_state):
    """
    Test the method _build_observations_params constructs the correct parameters.
    """
    state = empty_state
    series_key = {
        "geography": "K02000001",
        "age": "A--T",
    }
    state.series_key = series_key

    om = ONSObservationManager(api_client)

    expected_params = {
        "geography": "K02000001",
        "age": "A--T",
        # Time is added as a wildcard to fetch all time periods
        "time": "*",
    }
    params = om._build_observations_params(state)

    assert params == expected_params


def test_create_observation_from_response(api_client, empty_state):
    """
    Test the method _create_observation_from_response creates an observation correctly.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="example-dataset", source="ONS")
    state.dataset = dataset
    state.dataset_id = "example-dataset"
    state.series_key = {
        "geography": "K02000001",
        "age": "A--T",
    }

    release = Release.create(
        dataset=dataset,
        release_date=datetime(2023, 1, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "geography"},
                {"name": "age"},
                {"name": "time", "id": "mmm-yy"},
            ],
            "version": "release-123",
        },
    )

    series = Series.create(
        dataset=dataset,
        series_key=state.series_key,
    )

    om = ONSObservationManager(api_client)
    response_item = {
        "observation": 123.45,
        "dimensions": {
            "Time": {"label": "Jan-23"},
        },
    }

    observation = om._create_observation_from_response(
        response_item, series, release, freq="mmm-yy"
    )

    assert observation.value == 123.45
    assert observation.observation_timestamp == datetime(2023, 1, 1, tzinfo=UTC)
    assert observation.release == release
    assert observation.series == series
    assert isinstance(observation, Observation)


@patch("macrotrace.sources.ons.ONSAPIClient.make_request")
def test_fetch_observations_for_release(mock_make_request, api_client, empty_state):
    """
    Test the method _fetch_observations_for_release fetches observations correctly.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="example-dataset", source="ONS")
    state.dataset = dataset
    state.dataset_id = "example-dataset"
    state.series_key = {
        "geography": "K02000001",
        "age": "A--T",
    }

    release_feb = Release.create(
        dataset=dataset,
        release_date=datetime(2025, 2, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "geography"},
                {"name": "age"},
                # Need the ID for frequency parsing
                {
                    "id": "mmm-yy",
                    "name": "time",
                },
            ],
            "version": "release-123",
        },
    )

    mock_make_request.return_value = {
        "observations": [
            {
                "observation": 123.45,
                "dimensions": {
                    "Time": {"label": "Jan-25"},
                },
            },
            {
                "observation": 234.56,
                "dimensions": {
                    "Time": {"label": "Feb-25"},
                },
            },
        ]
    }

    om = ONSObservationManager(api_client)

    observations = om._fetch_observations_for_release(state, release_feb)

    assert len(observations) == 2
    assert all(isinstance(obs, Observation) for obs in observations)
    assert observations[0].value == 123.45
    assert observations[1].value == 234.56


@patch("macrotrace.sources.ons.ONSAPIClient.make_request")
def test_fetch_observations_for_release_response_none(
    mock_make_request, api_client, empty_state, caplog
):
    """
    Test the method _fetch_observations_for_release when no observations are returned.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="example-dataset", source="ONS")
    state.dataset = dataset
    state.dataset_id = "example-dataset"
    state.series_key = {
        "geography": "K02000001",
        "age": "A--T",
    }

    release_mar = Release.create(
        dataset=dataset,
        release_date=datetime(2025, 3, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "geography"},
                {"name": "age"},
                {
                    "id": "mmm-yy",
                    "name": "time",
                },
            ],
            "version": "release-123",
        },
    )

    # yes... this can happen
    mock_make_request.return_value = {"observations": None}

    om = ONSObservationManager(api_client)

    # check the debug output to ensure it records no observations found
    with caplog.at_level(logging.DEBUG):
        observations = om._fetch_observations_for_release(state, release_mar)
        assert "No observations found in response" in caplog.text

    assert len(observations) == 0


@patch("macrotrace.sources.ons.ONSObservationManager._fetch_observations_for_release")
def test_fetch_new_observations(
    mock_fetch_observations_for_release, api_client, empty_state
):
    """
    Test the method fetch_new_observations fetches observations across multiple releases.
    """
    state = empty_state
    dataset = Dataset.create(dataset_id="example-dataset", source="ONS")
    state.dataset = dataset
    state.dataset_id = "example-dataset"
    state.series_key = {
        "geography": "K02000001",
        "age": "A--T",
    }

    release_jan = Release.create(
        dataset=dataset,
        release_date=datetime(2025, 1, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "geography"},
                {"name": "age"},
                {"name": "time"},
            ],
            "version": "release-jan",
        },
    )

    release_feb = Release.create(
        dataset=dataset,
        release_date=datetime(2025, 2, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "geography"},
                {"name": "age"},
                {"name": "time"},
            ],
            "version": "release-feb",
        },
    )
    state.new_releases = [release_jan, release_feb]

    series = Series.create(
        dataset=dataset,
        series_key=state.series_key,
    )
    state.series = series

    def return_values(state, release):
        if release == release_jan:
            return [
                Observation(
                    value=111.11,
                    observation_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
                    release=release_jan,
                    series=None,
                )
            ]
        elif release == release_feb:
            return [
                Observation(
                    value=111.11,
                    observation_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
                    release=release_feb,
                    series=None,
                ),
                Observation(
                    value=222.22,
                    observation_timestamp=datetime(2025, 2, 1, tzinfo=UTC),
                    release=release_feb,
                    series=None,
                ),
            ]
        return []

    mock_fetch_observations_for_release.side_effect = return_values

    om = ONSObservationManager(api_client)
    observations = om.fetch_new_observations(state)

    expected_obs = [
        (111.11, datetime(2025, 1, 1, tzinfo=UTC), release_jan),
        (111.11, datetime(2025, 1, 1, tzinfo=UTC), release_feb),
        (222.22, datetime(2025, 2, 1, tzinfo=UTC), release_feb),
    ]

    assert len(observations) == 3
    for obs, (exp_value, exp_timestamp, exp_release) in zip(observations, expected_obs):
        assert obs.value == exp_value
        assert obs.observation_timestamp == exp_timestamp
        assert obs.release == exp_release


def test_year_quarter_to_ymd_q1():
    """Test conversion of Q1 to ISO date string."""
    result = year_quarter_to_ymd("2023-q1")
    assert result == "2023-01-01T00:00:00"


def test_year_quarter_to_ymd_q2():
    """Test conversion of Q2 to ISO date string."""
    result = year_quarter_to_ymd("2023-q2")
    assert result == "2023-04-01T00:00:00"


def test_year_quarter_to_ymd_q3():
    """Test conversion of Q3 to ISO date string."""
    result = year_quarter_to_ymd("2023-q3")
    assert result == "2023-07-01T00:00:00"


def test_year_quarter_to_ymd_q4():
    """Test conversion of Q4 to ISO date string."""
    result = year_quarter_to_ymd("2023-q4")
    assert result == "2023-10-01T00:00:00"


def test_year_quarter_to_ymd_uppercase():
    """Test that uppercase input works correctly."""
    result = year_quarter_to_ymd("2025-Q1")
    assert result == "2025-01-01T00:00:00"


def test_parse_observation_timestamp_calendar_years(api_client):
    """Test parsing calendar year format."""
    om = ONSObservationManager(api_client)
    result = om._parse_observation_timestamp("2023", "calendar-years")

    assert result == datetime(2023, 1, 1, tzinfo=UTC)


def test_parse_observation_timestamp_mmm_yy(api_client):
    """Test parsing mmm-yy format (e.g., Jan-23)."""
    om = ONSObservationManager(api_client)
    result = om._parse_observation_timestamp("Jan-23", "mmm-yy")

    assert result == datetime(2023, 1, 1, tzinfo=UTC)


def test_parse_observation_timestamp_yyyy_qq(api_client):
    """Test parsing yyyy-qq format with custom parsing logic."""
    om = ONSObservationManager(api_client)
    result = om._parse_observation_timestamp("2023-q1", "yyyy-qq")

    assert result == datetime(2023, 1, 1, tzinfo=UTC)
