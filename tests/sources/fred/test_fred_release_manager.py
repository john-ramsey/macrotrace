import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import pytz

from macrotrace.models.db import Release, Dataset, DatasetDimension
from macrotrace.sources.fred import FredReleaseManager

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.fred.fixtures import (
    api_client,
    empty_state,
    db_setup_and_teardown,
    US_CENTRAL,
)


def assert_release_equal(release, expected_release_dict):
    """Helper function to assert that two Release objects are equal."""
    assert release.dataset.id == expected_release_dict["dataset"]
    assert release.release_date == expected_release_dict["release_date"]
    assert release.additional_metadata == expected_release_dict.get(
        "additional_metadata", None
    )


def test_initialization(api_client):
    """Test that the FredReleaseManager initializes correctly."""
    rm = FredReleaseManager(api_client=api_client)
    assert rm.api_client == api_client


def test_ensure_us_central_no_tz(api_client):
    """Test that _ensure_us_central adds US Central timezone to naive datetime."""
    rm = FredReleaseManager(api_client=api_client)
    naive_dt = datetime(2020, 1, 1, 12, 0, 0)
    converted_dt = rm._ensure_us_central(naive_dt)
    assert converted_dt == US_CENTRAL.localize(naive_dt)
    # Verify it landed on real CST (-6h), not pytz LMT (-5h50m36s).
    assert converted_dt.utcoffset() == timedelta(hours=-6)


def test_ensure_us_central_with_tz(api_client):
    """Test that _ensure_us_central converts aware datetime to US Central."""
    rm = FredReleaseManager(api_client=api_client)
    aware_dt = datetime(2020, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    converted_dt = rm._ensure_us_central(aware_dt)
    expected_dt = aware_dt.astimezone(US_CENTRAL)
    assert converted_dt == expected_dt


def test_ensure_us_central_none(api_client):
    """Test that _ensure_us_central returns None when given None."""
    rm = FredReleaseManager(api_client=api_client)
    assert rm._ensure_us_central(None) is None


def test_get_new_releases_all_new(api_client, empty_state):
    """Test that all releases are new when none exist in the database."""
    state = empty_state
    dataset = Dataset.create(
        dataset_id="TEST_DATASET",
        source="FRED",
    )
    state.dataset = dataset

    api_client.make_request = MagicMock(
        return_value={
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "vintage_dates": ["2025-01-01", "2025-02-01", "2025-03-01"],
        }
    )

    expected_releases = [
        {
            "dataset": dataset.id,
            "release_date": US_CENTRAL.localize(datetime(2025, 1, 1)),
            "additional_metadata": None,
        },
        {
            "dataset": dataset.id,
            "release_date": US_CENTRAL.localize(datetime(2025, 2, 1)),
            "additional_metadata": None,
        },
        {
            "dataset": dataset.id,
            "release_date": US_CENTRAL.localize(datetime(2025, 3, 1)),
            "additional_metadata": None,
        },
    ]

    rm = FredReleaseManager(api_client=api_client)
    new_releases = rm.fetch_new_releases(state)

    assert len(new_releases) == 3
    for new_release, expected_release_dict in zip(new_releases, expected_releases):
        assert_release_equal(new_release, expected_release_dict)


def test_get_new_releases_none_new(api_client, empty_state):
    """Test that no releases are new when all exist in the database."""
    state = empty_state
    dataset = Dataset.create(
        dataset_id="TEST_DATASET",
        source="FRED",
    )
    state.dataset = dataset

    existing_release_dates = [
        US_CENTRAL.localize(datetime(2025, 1, 1)),
        US_CENTRAL.localize(datetime(2025, 2, 1)),
        US_CENTRAL.localize(datetime(2025, 3, 1)),
    ]

    for release_date in existing_release_dates:
        Release.create(
            dataset=state.dataset,
            release_date=release_date,
        )

    api_client.make_request = MagicMock(
        return_value={
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "vintage_dates": ["2025-01-01", "2025-02-01", "2025-03-01"],
        }
    )

    rm = FredReleaseManager(api_client=api_client)
    new_releases = rm.fetch_new_releases(empty_state)

    assert len(new_releases) == 0


def test_get_new_releases_some_new(api_client, empty_state):
    """Test that only new releases are returned when some exist in the database."""
    state = empty_state
    dataset = Dataset.create(
        dataset_id="TEST_DATASET",
        source="FRED",
    )
    state.dataset = dataset

    existing_release_date = US_CENTRAL.localize(datetime(2025, 1, 1))

    Release.create(
        dataset=state.dataset,
        release_date=existing_release_date,
    )

    api_client.make_request = MagicMock(
        return_value={
            "realtime_start": "1776-07-04",
            "realtime_end": "9999-12-31",
            "vintage_dates": ["2025-01-01", "2025-02-01", "2025-03-01"],
        }
    )

    expected_releases = [
        {
            "dataset": dataset.id,
            "release_date": US_CENTRAL.localize(datetime(2025, 2, 1)),
            "additional_metadata": None,
        },
        {
            "dataset": dataset.id,
            "release_date": US_CENTRAL.localize(datetime(2025, 3, 1)),
            "additional_metadata": None,
        },
    ]

    rm = FredReleaseManager(api_client=api_client)
    new_releases = rm.fetch_new_releases(state)

    assert len(new_releases) == 2
    for new_release, expected_release_dict in zip(new_releases, expected_releases):
        assert_release_equal(new_release, expected_release_dict)


@patch("macrotrace.sources.fred.FredReleaseManager._get_all_local_dataset_dimensions")
def test_fetch_new_release_dimensions_errors_with_no_new_releases(
    mock_get_all_local_dataset_dimensions, api_client, empty_state
):
    """Test that fetch_new_release_dimensions raises an error when no new releases."""
    state = empty_state

    mock_get_all_local_dataset_dimensions.return_value = []
    dataset = MagicMock()
    dataset.id = 1
    state.dataset = dataset

    rm = FredReleaseManager(api_client=api_client)
    with pytest.raises(
        ValueError,
        match=f"Dataset {dataset.id} has no dimensions to associate with releases.",
    ):
        rm.fetch_new_release_dimensions(state)


def test_fetch_new_release_dimensions_all_new_one_dim(api_client, empty_state):
    """Test that fetch_new_release_dimensions works when all releases are new and one dimension exists."""
    state = empty_state
    dataset = Dataset.create(
        dataset_id="TEST_DATASET",
        source="FRED",
    )
    state.dataset = dataset

    release1 = Release.create(
        dataset=dataset,
        release_date=US_CENTRAL.localize(datetime(2025, 1, 1)),
    )
    release2 = Release.create(
        dataset=dataset,
        release_date=US_CENTRAL.localize(datetime(2025, 2, 1)),
    )
    state.new_releases = [release1, release2]

    dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim1",
        title="Dimension",
        type="numeric",
        frequency="MS",
        valid_from=US_CENTRAL.localize(datetime(2025, 1, 1)),
        valid_to=None,
    )

    rm = FredReleaseManager(api_client=api_client)
    new_release_dimensions = rm.fetch_new_release_dimensions(state)

    assert len(new_release_dimensions) == 2
    for rd in new_release_dimensions:
        assert rd.release.id in [release1.id, release2.id]
        assert rd.dimension.id == dimension.id


def test_fetch_new_release_dimensions_all_new_multiple_dims(api_client, empty_state):
    """Test that fetch_new_release_dimensions works when all releases are new and multiple dimensions exist."""
    state = empty_state
    dataset = Dataset.create(
        dataset_id="TEST_DATASET",
        source="FRED",
    )
    state.dataset = dataset

    release1 = Release.create(
        dataset=dataset,
        release_date=US_CENTRAL.localize(datetime(2025, 1, 1)),
    )
    release2 = Release.create(
        dataset=dataset,
        release_date=US_CENTRAL.localize(datetime(2025, 6, 1)),
    )
    state.new_releases = [release1, release2]

    dimension1 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim1",
        title="Dimension 1",
        type="numeric",
        frequency="MS",
        valid_from=US_CENTRAL.localize(datetime(2025, 1, 1)),
        valid_to=US_CENTRAL.localize(datetime(2025, 3, 31)),
    )

    dimension2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim1",
        title="Dimension 1 (Updated)",
        type="numeric",
        frequency="MS",
        valid_from=US_CENTRAL.localize(datetime(2025, 4, 1)),
        valid_to=None,
    )

    rm = FredReleaseManager(api_client=api_client)
    new_release_dimensions = rm.fetch_new_release_dimensions(state)

    assert len(new_release_dimensions) == 2
    for rd in new_release_dimensions:
        if rd.release.id == release1.id:
            assert rd.dimension.id == dimension1.id
        elif rd.release.id == release2.id:
            assert rd.dimension.id == dimension2.id


def test_fetch_new_release_dimensions_no_new_releases(api_client, empty_state):
    """Test that fetch_new_release_dimensions returns an empty list when no new releases."""
    state = empty_state
    dataset = Dataset.create(
        dataset_id="TEST_DATASET",
        source="FRED",
    )
    state.dataset = dataset

    _ = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="dim1",
        title="Dimension",
        type="numeric",
        frequency="MS",
        valid_from=US_CENTRAL.localize(datetime(2025, 1, 1)),
        valid_to=None,
    )

    state.new_releases = []

    rm = FredReleaseManager(api_client=api_client)
    new_release_dimensions = rm.fetch_new_release_dimensions(state)

    assert new_release_dimensions == []
