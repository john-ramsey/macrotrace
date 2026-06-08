from datetime import datetime, timezone

from macrotrace.models.db import Dataset, DatasetDimension
from macrotrace.sources.rtdsm import RTDSMDatasetManager, ParsedVintageFile

from tests.sources.rtdsm.fixtures import (
    api_client,
    empty_state,
    sample_parsed,
    db_setup_and_teardown,
)

UTC = timezone.utc


def test_fetch_new_dataset_dimensions_creates_one(
    api_client, empty_state, sample_parsed
):
    """
    A fresh dataset gets exactly one numeric dimension anchored at the
    earliest vintage date.
    """
    api_client._parsed = sample_parsed
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset

    dm = RTDSMDatasetManager(api_client)
    dims = dm.fetch_new_dataset_dimensions(empty_state)

    assert len(dims) == 1
    dim = dims[0]
    assert dim.dataset_dimension_id == "ROUTPUT"
    assert dim.type == "numeric"
    assert dim.frequency == "QS"
    assert dim.valid_from == datetime(1965, 11, 15, tzinfo=UTC)
    assert dim.valid_to is None
    assert dim.title == "Real GNP/GDP (ROUTPUT)"


def test_fetch_new_dataset_dimensions_returns_empty_when_exists(
    api_client, empty_state, sample_parsed
):
    """If the dimension already exists, no new dimension is created."""
    api_client._parsed = sample_parsed
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset
    DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="ROUTPUT",
        title="Real GNP/GDP (ROUTPUT)",
        type="numeric",
        frequency="QS",
        valid_from=datetime(1965, 11, 15, tzinfo=UTC),
    )

    dm = RTDSMDatasetManager(api_client)
    assert dm.fetch_new_dataset_dimensions(empty_state) == []


def test_fetch_new_dataset_dimensions_no_vintages(api_client, empty_state):
    """An empty file produces no dimension."""
    api_client._parsed = ParsedVintageFile(vintages=[], cells={})
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    empty_state.dataset = dataset

    dm = RTDSMDatasetManager(api_client)
    assert dm.fetch_new_dataset_dimensions(empty_state) == []
