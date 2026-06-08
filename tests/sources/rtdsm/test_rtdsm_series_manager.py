from macrotrace.models.db import Dataset, Series
from macrotrace.sources.rtdsm import RTDSMSeriesManager

from tests.sources.rtdsm.fixtures import (
    api_client,
    empty_state,
    db_setup_and_teardown,
)


def test_fetch_new_series_dimension_filters_is_empty(api_client, empty_state):
    """
    The frequency key selects a file, not a dataset dimension, so there are
    never any SeriesDimensionFilter rows to create.
    """
    dataset = Dataset.create(dataset_id="ROUTPUT", source="RTDSM")
    series = Series.create(dataset=dataset, series_key={"frequency": "Q"})
    empty_state.dataset = dataset
    empty_state.series = series
    empty_state.series_key = {"frequency": "Q"}

    sm = RTDSMSeriesManager(api_client)
    assert sm.fetch_new_series_dimension_filters(empty_state) == []
