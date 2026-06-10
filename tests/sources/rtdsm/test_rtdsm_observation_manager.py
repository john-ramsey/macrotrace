from datetime import datetime, timezone

from macrotrace.models.db import Dataset, Release, Series, Observation
from macrotrace.sources.rtdsm import RTDSMObservationManager

from tests.sources.rtdsm.fixtures import (
    api_client,
    empty_state,
    sample_parsed,
    db_setup_and_teardown,
)

UTC = timezone.utc


def test_fetch_new_observations_no_new_releases(api_client, empty_state):
    empty_state.new_releases = []
    om = RTDSMObservationManager(api_client)
    assert om.fetch_new_observations(empty_state) == []


def test_fetch_new_observations_maps_cells(api_client, empty_state, sample_parsed):
    """Each non-missing cell of a new release becomes one observation."""
    api_client._parsed = sample_parsed
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    series = Series.create(dataset=dataset, series_key={"frequency": "Q"})
    r1 = Release.create(
        dataset=dataset, release_date=datetime(1965, 11, 15, tzinfo=UTC)
    )
    r2 = Release.create(dataset=dataset, release_date=datetime(1966, 2, 15, tzinfo=UTC))
    empty_state.dataset = dataset
    empty_state.series = series
    empty_state.new_releases = [r1, r2]

    om = RTDSMObservationManager(api_client)
    obs = om.fetch_new_observations(empty_state)

    # 2 observations for the first vintage, 3 for the second.
    assert len(obs) == 5
    assert all(o.series.id == series.id for o in obs)
    r1_obs = [o for o in obs if o.release.id == r1.id]
    assert len(r1_obs) == 2
    first = next(
        o for o in r1_obs if o.observation_timestamp == datetime(1947, 1, 1, tzinfo=UTC)
    )
    assert first.value == 306.4


def test_fetch_new_observations_skips_release_without_column(
    api_client, empty_state, sample_parsed
):
    """A release whose date has no matching vintage column contributes nothing."""
    api_client._parsed = sample_parsed
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    series = Series.create(dataset=dataset, series_key={"frequency": "Q"})
    # This release date is not present in sample_parsed.
    orphan = Release.create(
        dataset=dataset, release_date=datetime(1999, 8, 15, tzinfo=UTC)
    )
    empty_state.dataset = dataset
    empty_state.series = series
    empty_state.new_releases = [orphan]

    om = RTDSMObservationManager(api_client)
    assert om.fetch_new_observations(empty_state) == []
