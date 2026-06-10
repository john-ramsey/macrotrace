import pytest
from datetime import datetime, timezone

from macrotrace.models.db import Dataset, DatasetDimension, Release
from macrotrace.sources.rtdsm import RTDSMReleaseManager

from tests.sources.rtdsm.fixtures import (
    api_client,
    empty_state,
    sample_parsed,
    db_setup_and_teardown,
)

UTC = timezone.utc


def test_fetch_new_releases_all_new(api_client, empty_state, sample_parsed):
    api_client._parsed = sample_parsed
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset

    rm = RTDSMReleaseManager(api_client)
    releases = rm.fetch_new_releases(empty_state)

    dates = sorted(r.release_date for r in releases)
    assert dates == [
        datetime(1965, 11, 15, tzinfo=UTC),
        datetime(1966, 2, 15, tzinfo=UTC),
    ]


def test_fetch_new_releases_dedup(api_client, empty_state, sample_parsed):
    """Vintages already in the database are not re-created."""
    api_client._parsed = sample_parsed
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset
    Release.create(dataset=dataset, release_date=datetime(1965, 11, 15, tzinfo=UTC))

    rm = RTDSMReleaseManager(api_client)
    releases = rm.fetch_new_releases(empty_state)

    assert [r.release_date for r in releases] == [datetime(1966, 2, 15, tzinfo=UTC)]


def test_fetch_new_releases_window_filter(api_client, empty_state, sample_parsed):
    """
    Vintages outside the requested window are excluded; naive bounds are
    treated as UTC.
    """
    api_client._parsed = sample_parsed
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset
    empty_state.release_start_date = datetime(1966, 1, 1)  # naive on purpose

    rm = RTDSMReleaseManager(api_client)
    releases = rm.fetch_new_releases(empty_state)

    assert [r.release_date for r in releases] == [datetime(1966, 2, 15, tzinfo=UTC)]


def test_fetch_new_release_dimensions_associates(api_client, empty_state):
    api_client._parsed = None
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset
    dim = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="ROUTPUT",
        title="Real GNP/GDP (ROUTPUT)",
        type="numeric",
        frequency="QS",
        valid_from=datetime(1965, 11, 15, tzinfo=UTC),
    )
    r1 = Release.create(
        dataset=dataset, release_date=datetime(1965, 11, 15, tzinfo=UTC)
    )
    r2 = Release.create(dataset=dataset, release_date=datetime(1966, 2, 15, tzinfo=UTC))
    empty_state.new_releases = [r1, r2]

    rm = RTDSMReleaseManager(api_client)
    rds = rm.fetch_new_release_dimensions(empty_state)

    assert len(rds) == 2
    assert all(rd.dimension.id == dim.id for rd in rds)


def test_fetch_new_release_dimensions_excludes_before_valid_from(
    api_client, empty_state
):
    """A release earlier than the dimension's valid_from is not associated."""
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset
    DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="ROUTPUT",
        title="Real GNP/GDP (ROUTPUT)",
        type="numeric",
        frequency="QS",
        valid_from=datetime(1966, 1, 1, tzinfo=UTC),
    )
    early = Release.create(
        dataset=dataset, release_date=datetime(1965, 11, 15, tzinfo=UTC)
    )
    empty_state.new_releases = [early]

    rm = RTDSMReleaseManager(api_client)
    assert rm.fetch_new_release_dimensions(empty_state) == []


def test_fetch_new_release_dimensions_no_dims_raises(api_client, empty_state):
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset
    empty_state.new_releases = [
        Release.create(dataset=dataset, release_date=datetime(1965, 11, 15, tzinfo=UTC))
    ]

    rm = RTDSMReleaseManager(api_client)
    with pytest.raises(ValueError, match="no dimensions"):
        rm.fetch_new_release_dimensions(empty_state)
