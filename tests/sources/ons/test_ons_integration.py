from datetime import datetime
from unittest.mock import patch

import pytest

from macrotrace import MTTimeSeries
from macrotrace.models.db import (
    LOCAL_DATABASE,
    Dataset,
    DatasetDimension,
    Observation,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
)
from macrotrace.sources.ons import (
    ONSAPIClient,
    ONSDatasetManager,
    ONSReleaseManager,
    UTC,
)


DATASET_ID = "gdp-to-four-decimal-places"
RELEASE_DATE = datetime(2026, 8, 24, tzinfo=UTC)
OBSERVATION_DATE = datetime(2026, 6, 1, tzinfo=UTC)
TOTAL_KEY = {
    "geography": "K02000001",
    "unofficialstandardindustrialclassification": "A--T",
}
MANUFACTURING_KEY = {
    "geography": "K02000001",
    "unofficialstandardindustrialclassification": "C",
}
MODELS = [
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
]


@pytest.fixture
def ons_database(tmp_path):
    """Provide an isolated persistent database and request cache."""
    database_path = tmp_path / "macrotrace.sqlite"
    cache_path = tmp_path / "requests.sqlite"
    if not LOCAL_DATABASE.is_closed():
        LOCAL_DATABASE.close()
    LOCAL_DATABASE.init(database_path)
    LOCAL_DATABASE.bind(MODELS, bind_refs=False, bind_backrefs=False)
    LOCAL_DATABASE.connect()
    LOCAL_DATABASE.create_tables(MODELS)
    yield database_path, cache_path
    if LOCAL_DATABASE.is_closed():
        LOCAL_DATABASE.connect()
    LOCAL_DATABASE.drop_tables(MODELS)
    LOCAL_DATABASE.close()


def test_second_ons_series_backfills_existing_release_and_remains_isolated(
    ons_database,
):
    """Backfill a second ONS slice without borrowing the first slice's values."""
    database_path, cache_path = ons_database

    dataset = Dataset.create(dataset_id=DATASET_ID, source="ONS")
    initial_dimension = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id=DATASET_ID,
        title="GDP monthly estimate",
        type="numeric",
        frequency="MS",
        units="Index. Seasonally adjusted 2016=100",
        valid_from=RELEASE_DATE,
    )
    geography = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="geography",
        title="Geography",
        type="text",
        valid_from=RELEASE_DATE,
    )
    industry = DatasetDimension.create(
        dataset=dataset,
        dataset_dimension_id="unofficialstandardindustrialclassification",
        title="Industry",
        type="text",
        valid_from=RELEASE_DATE,
    )
    release = Release.create(
        dataset=dataset,
        release_date=RELEASE_DATE,
        additional_metadata={
            "version": 69,
            "id": "release-69",
            "dimensions": [
                {"name": "geography"},
                {"name": "unofficialstandardindustrialclassification"},
                {"name": "time", "id": "mmm-yy"},
            ],
        },
    )
    ReleaseDimension.create(release=release, dimension=initial_dimension)
    ReleaseDimension.create(release=release, dimension=geography)
    ReleaseDimension.create(release=release, dimension=industry)
    total_series = Series.create(dataset=dataset, series_key=TOTAL_KEY)
    SeriesDimensionFilter.create(
        series=total_series,
        dimension=geography,
        value=TOTAL_KEY["geography"],
    )
    SeriesDimensionFilter.create(
        series=total_series,
        dimension=industry,
        value=TOTAL_KEY["unofficialstandardindustrialclassification"],
    )
    Observation.create(
        series=total_series,
        release=release,
        observation_timestamp=OBSERVATION_DATE,
        value=103.4055,
    )

    observation_response = {
        "observations": [
            {
                "observation": "100.5823",
                "dimensions": {"Time": {"label": "Jun-26"}},
            }
        ]
    }
    with (
        patch.object(ONSDatasetManager, "_series_is_timeseries", return_value=True),
        patch.object(ONSReleaseManager, "fetch_new_releases", return_value=[]),
        patch.object(
            ONSAPIClient,
            "make_request",
            return_value=observation_response,
        ) as make_request,
    ):
        manufacturing = MTTimeSeries(
            DATASET_ID,
            "ONS",
            series_key=MANUFACTURING_KEY,
            vintage_start_date="2026-08-24",
            vintage_end_date="2026-08-24",
            db_path=str(database_path),
            cache_path=str(cache_path),
        )
        repeated = MTTimeSeries(
            DATASET_ID,
            "ONS",
            series_key=MANUFACTURING_KEY,
            vintage_start_date="2026-08-24",
            vintage_end_date="2026-08-24",
            db_path=str(database_path),
            cache_path=str(cache_path),
        )

    total = MTTimeSeries(
        DATASET_ID,
        "ONS",
        series_key=TOTAL_KEY,
        vintage_start_date="2026-08-24",
        vintage_end_date="2026-08-24",
        update_prior_to_load=False,
        db_path=str(database_path),
    )

    assert manufacturing.current_observations[0].value == 100.5823
    assert repeated.current_observations[0].value == 100.5823
    assert total.current_observations[0].value == 103.4055
    assert Observation.select().count() == 2
    make_request.assert_called_once_with(
        endpoint=(
            f"datasets/{DATASET_ID}/editions/time-series/versions/69/observations"
        ),
        params={"time": "*"} | MANUFACTURING_KEY,
    )
