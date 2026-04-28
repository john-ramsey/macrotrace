import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from macrotrace.sources.ons import ONSReleaseManager

from macrotrace.models.db import Dataset, DatasetDimension, Release, ReleaseDimension

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.ons.fixtures import (
    api_client,
    empty_state,
    db_setup_and_teardown,
    UTC,
)


def test_initialization(api_client):
    """
    Test that the ONSReleaseManager initializes correctly with the provided API client.
    """
    rm = ONSReleaseManager(api_client)

    assert rm.api_client == api_client


def test_skip_release_before_start_date(api_client, empty_state):
    """
    Test that the _skip_release method skips releases before the start date in state.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.release_start_date = "2023-01-01"
    release_date = "2022-12-31"
    current_release_dates = []
    assert rm._skip_release(release_date, state, current_release_dates) is True


def test_skip_release_after_end_date(api_client, empty_state):
    """
    Test that the _skip_release method skips releases after the end date in state.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.release_start_date = None
    state.release_end_date = "2023-12-31"
    release_date = "2024-01-01"
    current_release_dates = []
    assert rm._skip_release(release_date, state, current_release_dates) is True


def test_skip_release_before_within_range(api_client, empty_state):
    """
    Test that the _skip_release method does not skip releases within the date range in state.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.release_start_date = "2023-01-01"
    state.release_end_date = "2023-12-31"
    release_date = "2023-06-15"
    current_release_dates = []
    assert rm._skip_release(release_date, state, current_release_dates) is False


def test_skip_release_no_dates(api_client, empty_state):
    """
    Test that the _skip_release method does not skip releases when no dates are set in state.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.release_start_date = None
    state.release_end_date = None
    release_date = "2023-06-15"
    current_release_dates = []
    assert rm._skip_release(release_date, state, current_release_dates) is False


def test_skip_release_exists_in_db(api_client, empty_state):
    """
    Test that the _skip_release method skips releases that already exist in the database.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.release_start_date = None
    state.release_end_date = None
    release_date = datetime(2023, 6, 15, tzinfo=UTC)
    current_release_dates = [datetime(2023, 6, 15, tzinfo=UTC)]
    assert rm._skip_release(release_date, state, current_release_dates) is True


def test_construct_release(api_client, empty_state):
    """
    Test that the _construct_release method creates a Release object with correct attributes.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    release_date = "2023-06-15"
    release_data = {
        "version": "1.0",
        "id": "release_123",
        "dimensions": {"geography": "K02000001"},
    }

    release = rm._construct_release(state, release_date, release_data)

    assert release.dataset == state.dataset
    assert release.release_date == release_date
    assert release.additional_metadata["version"] == "1.0"
    assert release.additional_metadata["id"] == "release_123"
    assert release.additional_metadata["dimensions"] == {"geography": "K02000001"}


def test_release_exists_in_db_exists(api_client, empty_state):
    """
    Test that the _release_exists_in_db method correctly identifies existing releases.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")

    existing_release = Release.create(
        dataset=state.dataset,
        release_date=datetime(2023, 6, 15, tzinfo=UTC),
        additional_metadata={},
    )

    current_release_dates = [existing_release.release_date]

    assert (
        rm._release_exists_in_db(
            datetime(2023, 6, 15, tzinfo=UTC), current_release_dates
        )
        is True
    )


def test_release_exists_in_db_not_exists(api_client, empty_state):
    """
    Test that the _release_exists_in_db method correctly identifies non-existing releases.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")

    current_releases = []

    assert (
        rm._release_exists_in_db(datetime(2023, 6, 15, tzinfo=UTC), current_releases)
        is False
    )


@patch("macrotrace.sources.ons.ONSAPIClient.make_request")
def test_fetch_new_releases_flow_all_new(mock_make_request, api_client, empty_state):
    """
    Test that fetch_new_releases correctly fetches new releases within the date range.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    state.release_start_date = datetime(2023, 1, 1, tzinfo=UTC)
    state.release_end_date = datetime(2023, 12, 31, tzinfo=UTC)

    release_data = {
        "items": [
            {
                "release_date": "2023-01-15",
                "version": "1.0",
                "id": "release_001",
                "dimensions": {"geography": "K02000001"},
            },
            {
                "release_date": "2023-07-20",
                "version": "1.1",
                "id": "release_002",
                "dimensions": {"geography": "K02000001"},
            },
            {
                "release_date": "2024-01-10",
                "version": "1.2",
                "id": "release_003",
                "dimensions": {"geography": "K02000001"},
            },
        ]
    }

    mock_make_request.return_value = release_data

    new_releases = rm.fetch_new_releases(state)

    assert len(new_releases) == 2  # Only two releases are within the date range
    for i, release in enumerate(new_releases):
        assert release.release_date == datetime.fromisoformat(
            release_data["items"][i]["release_date"]
        ).replace(tzinfo=UTC)
        assert (
            release.additional_metadata["version"]
            == release_data["items"][i]["version"]
        )
        assert release.additional_metadata["id"] == release_data["items"][i]["id"]
        assert (
            release.additional_metadata["dimensions"]
            == release_data["items"][i]["dimensions"]
        )


@patch("macrotrace.sources.ons.ONSAPIClient.make_request")
def test_fetch_new_releases_flow_none_new(mock_make_request, api_client, empty_state):
    """
    Test that fetch_new_releases returns an empty list when no new releases are found.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")

    current_releases = [
        Release.create(
            dataset=state.dataset,
            release_date=datetime(2025, 1, 1, tzinfo=UTC),
            additional_metadata={},
        ),
        Release.create(
            dataset=state.dataset,
            release_date=datetime(2025, 2, 20, tzinfo=UTC),
            additional_metadata={},
        ),
    ]

    release_data = {
        "items": [
            {
                "release_date": "2025-01-01",
                "version": "1.0",
                "id": "release_001",
                "dimensions": {"geography": "K02000001"},
            },
            {
                "release_date": "2025-02-20",
                "version": "1.1",
                "id": "release_002",
                "dimensions": {"geography": "K02000001"},
            },
        ]
    }

    mock_make_request.return_value = release_data

    new_releases = rm.fetch_new_releases(state)

    assert len(new_releases) == 0


def test_get_dimension_for_release_finds_release_single_version(api_client):
    """
    Test that the _get_dimension_for_release method filters and returns the correct DatasetDimension.
    In this test both dimensions have non-ending validity dates.
    """
    current_dataset_dimensions = [
        MagicMock(
            id=1,
            dataset_dimension_id="geography",
            valid_from=datetime(2022, 1, 1),
            valid_to=None,
        ),
        MagicMock(
            id=2,
            dataset_dimension_id="age",
            valid_from=datetime(2023, 1, 1),
            valid_to=None,
        ),
    ]
    dim_name = "age"
    release_date = datetime(2023, 6, 15)

    rm = ONSReleaseManager(api_client)
    dimension = rm._get_dimension_for_release(
        current_dataset_dimensions, dim_name, release_date
    )
    assert dimension.dataset_dimension_id == "age"
    assert dimension.id == 2


def test_get_dimension_for_release_multiple_versions():
    """
    Test that the _get_dimension_for_release method filters and returns the correct DatasetDimension.
    In this test one dimension has an ending validity date.
    """
    current_dataset_dimensions = [
        MagicMock(
            id=1,
            dataset_dimension_id="geography",
            valid_from=datetime(2022, 1, 1),
            valid_to=None,
        ),
        MagicMock(
            id=2,
            dataset_dimension_id="age",
            valid_from=datetime(2020, 1, 1),
            valid_to=datetime(2023, 5, 31),
        ),
        MagicMock(
            id=3,
            dataset_dimension_id="age",
            valid_from=datetime(2023, 6, 1),
            valid_to=None,
        ),
    ]
    dim_name = "age"
    release_date = datetime(2023, 6, 15)

    rm = ONSReleaseManager(MagicMock())
    dimension = rm._get_dimension_for_release(
        current_dataset_dimensions, dim_name, release_date
    )
    assert dimension.dataset_dimension_id == "age"
    assert dimension.id == 3


def test_get_dimension_for_release_no_valid_version():
    """
    Test that the _get_dimension_for_release method raises an error when no valid DatasetDimension is found.
    """
    current_dataset_dimensions = [
        MagicMock(
            id=1,
            dataset_dimension_id="geography",
            valid_from=datetime(2022, 1, 1),
            valid_to=None,
        ),
        MagicMock(
            id=2,
            dataset_dimension_id="age",
            valid_from=datetime(2020, 1, 1),
            valid_to=datetime(2023, 5, 31),
        ),
    ]
    dim_name = "age"
    release_date = datetime(2023, 6, 15)

    rm = ONSReleaseManager(MagicMock())
    with pytest.raises(ValueError) as excinfo:
        rm._get_dimension_for_release(
            current_dataset_dimensions, dim_name, release_date
        )
    assert (
        f"No valid DatasetDimension found for dimension {dim_name} at release date {release_date}"
        in str(excinfo.value)
    )


def test_get_dimension_for_release_multiple_matches():
    """
    Test that the _get_dimension_for_release method raises an error when multiple valid DatasetDimensions are found.
    """
    current_dataset_dimensions = [
        MagicMock(
            id=1,
            dataset_dimension_id="geography",
            valid_from=datetime(2022, 1, 1),
            valid_to=None,
        ),
        MagicMock(
            id=2,
            dataset_dimension_id="age",
            valid_from=datetime(2020, 1, 1),
            valid_to=None,
        ),
        MagicMock(
            id=3,
            dataset_dimension_id="age",
            valid_from=datetime(2021, 1, 1),
            valid_to=None,
        ),
    ]
    dim_name = "age"
    release_date = datetime(2023, 6, 15)

    rm = ONSReleaseManager(MagicMock())
    with pytest.raises(ValueError) as excinfo:
        rm._get_dimension_for_release(
            current_dataset_dimensions, dim_name, release_date
        )
    assert (
        f"Multiple valid DatasetDimensions found for dimension {dim_name} at release date {release_date}"
        in str(excinfo.value)
    )


def test_fetch_new_release_dimensions_flow(api_client, empty_state):
    """
    Test that fetch_new_release_dimensions correctly constructs ReleaseDimension objects for a release.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")

    release = Release.create(
        dataset=state.dataset,
        release_date=datetime(2025, 1, 1, tzinfo=UTC),
        additional_metadata={
            "dimensions": [
                {"name": "geography"},
                {"name": "age"},
                # Time is included here but should be excluded in the results
                {"name": "time"},
            ]
        },
    )
    state.new_releases = [release]

    current_dataset_dimensions = [
        DatasetDimension.create(
            dataset=state.dataset,
            dataset_dimension_id="TEST_DATASET",
            title="Initial Dimension",
            type="numeric",
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            valid_to=None,
        ),
        DatasetDimension.create(
            dataset=state.dataset,
            dataset_dimension_id="geography",
            title="Geography",
            type="text",
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            valid_to=None,
        ),
        DatasetDimension.create(
            dataset=state.dataset,
            dataset_dimension_id="age",
            title="Age",
            type="numeric",
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            valid_to=None,
        ),
    ]

    release_dimensions = rm.fetch_new_release_dimensions(state)

    assert len(release_dimensions) == 3
    assert all(isinstance(rd, ReleaseDimension) for rd in release_dimensions)
    dimension_names = {rd.dimension.dataset_dimension_id for rd in release_dimensions}
    assert dimension_names == {"geography", "age", "TEST_DATASET"}


def test_fetch_new_release_dimensions_warning(api_client, empty_state, caplog):
    """
    Test that fetch_new_release_dimensions logs a warning when a DatasetDimension is not found for a release dimension.
    """
    rm = ONSReleaseManager(api_client)

    state = empty_state
    state.dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")

    release = Release.create(
        dataset=state.dataset,
        release_date=datetime(2025, 1, 1, tzinfo=UTC),
        # Note: metadata is intentionally missing to trigger the warning
        additional_metadata={},
    )
    state.new_releases = [release]

    current_dataset_dimensions = [
        DatasetDimension.create(
            dataset=state.dataset,
            dataset_dimension_id="TEST_DATASET",
            title="Initial Dimension",
            type="numeric",
            valid_from=datetime(2025, 1, 1, tzinfo=UTC),
            valid_to=None,
        )
    ]

    with caplog.at_level("WARNING"):
        release_dimensions = rm.fetch_new_release_dimensions(state)

    # Check that a warning was logged for the missing 'age' dimension
    warning_messages = [
        record.message for record in caplog.records if record.levelname == "WARNING"
    ]
    assert any(
        f"Release {release} has no dimensions in metadata; skipping." in message
        for message in warning_messages
    )


def test_get_initial_dimension_success(api_client, empty_state):
    """
    Test that ONSReleaseManager._get_initial_dimension returns the correct initial dimension.
    """

    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")
    initial_dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id=dataset.dataset_id,  # Initial dimension uses dataset_id
        title="Initial Dimension",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    other_dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="geography",
        title="Geography",
        type="text",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    state = empty_state
    state.dataset = dataset
    current_dataset_dimensions = [initial_dimension, other_dimension]

    rm = ONSReleaseManager(api_client)
    result_dimension = rm._get_initial_dimension(current_dataset_dimensions)
    assert result_dimension == initial_dimension


def test_get_initial_dimension_fail_not_found(api_client, empty_state):
    """
    Test that ONSReleaseManager._get_initial_dimension raises an error when the initial dimension is not found.
    """
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")

    other_dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="geography",
        title="Geography",
        type="text",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    state = empty_state
    state.dataset = dataset
    current_dataset_dimensions = [other_dimension]

    rm = ONSReleaseManager(api_client)
    with pytest.raises(ValueError) as excinfo:
        rm._get_initial_dimension(current_dataset_dimensions)
    assert "Initial dataset dimension not found." in str(excinfo.value)


def test_get_initial_dimension_fail_multiple_found(api_client, empty_state):
    """
    Test that ONSReleaseManager._get_initial_dimension raises an error when multiple initial dimensions are found.
    """
    dataset = Dataset.create(dataset_id="TEST_DATASET", source="ONS")

    initial_dimension1 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id=dataset.dataset_id,  # Initial dimension uses dataset_id
        title="Initial Dimension 1",
        type="numeric",
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    initial_dimension2 = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id=dataset.dataset_id,  # Initial dimension uses dataset_id
        title="Initial Dimension 2",
        type="numeric",
        valid_from=datetime(2021, 1, 1, tzinfo=UTC),
        valid_to=None,
    )

    state = empty_state
    state.dataset = dataset
    current_dataset_dimensions = [initial_dimension1, initial_dimension2]

    rm = ONSReleaseManager(api_client)
    with pytest.raises(ValueError) as excinfo:
        rm._get_initial_dimension(current_dataset_dimensions)
    assert "Multiple initial dataset dimensions found." in str(excinfo.value)
