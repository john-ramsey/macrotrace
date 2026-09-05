from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
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
from macrotrace.sources.wdi import WDIAPIClient, WDIEditionResult
from tests.sources.wdi.fixtures import (
    INDICATOR,
    edition_record,
    edition_results,
    normalized_observation,
)

UTC = timezone.utc
MODELS = [
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
]


def test_mttimeseries_requires_wdi_country_dictionary():
    with pytest.raises(TypeError, match="must be a dictionary"):
        MTTimeSeries(INDICATOR, "WDI", series_key="USA")  # type: ignore[arg-type]


@pytest.fixture
def wdi_database(tmp_path):
    if not LOCAL_DATABASE.is_closed():
        LOCAL_DATABASE.close()
    LOCAL_DATABASE.init(tmp_path / "macrotrace.sqlite")
    LOCAL_DATABASE.bind(MODELS, bind_refs=False, bind_backrefs=False)
    LOCAL_DATABASE.connect()
    LOCAL_DATABASE.create_tables(MODELS)
    yield tmp_path / "macrotrace.sqlite"
    LOCAL_DATABASE.drop_tables(MODELS)
    LOCAL_DATABASE.close()


def test_wdi_runs_through_storage_and_vintage_operations(wdi_database, edition_results):
    catalogue = [
        edition_record("201406", "2014 Jun"),
        edition_record("201407", "2014 Jul"),
    ]

    def fetch(_client, indicator, edition, **kwargs):
        assert indicator == INDICATOR
        assert kwargs["country"] == "USA"
        return edition_results[edition]

    with (
        patch.object(WDIAPIClient, "list_editions", return_value=catalogue),
        patch.object(
            WDIAPIClient, "fetch_edition_result", autospec=True, side_effect=fetch
        ) as fetch_edition,
    ):
        series = MTTimeSeries(
            INDICATOR,
            "WDI",
            series_key={"country": "USA"},
            vintage_start_date="2014-06-01",
            vintage_end_date="2014-07-31",
            db_path=str(wdi_database),
            cache_path=str(wdi_database.with_name("cache.sqlite")),
        )

        assert series.series_key == {"country": "USA"}
        assert series.release_date == datetime(2014, 7, 31, tzinfo=UTC)
        assert series.as_of("2014-07-30").release_date == datetime(
            2014, 6, 30, tzinfo=UTC
        )
        assert series.as_of("2014-07-31").release_date == datetime(
            2014, 7, 31, tzinfo=UTC
        )

        matrix = series.generate_vintage_matrix()
        assert list(matrix.columns) == [
            pd.Timestamp("2014-06-30", tz="UTC"),
            pd.Timestamp("2014-07-31", tz="UTC"),
        ]
        assert pd.isna(
            matrix.loc[
                pd.Timestamp("2012-01-01", tz="UTC"),
                pd.Timestamp("2014-07-31", tz="UTC"),
            ]
        )

        author_data = series.as_of("2014-06-30").to_series()
        match = series.identify_vintage(author_data)
        assert match.matched
        assert match.release_date == datetime(2014, 6, 30, tzinfo=UTC)

        first_release = Release.get(
            Release.release_date == datetime(2014, 6, 30, tzinfo=UTC)
        )
        assert first_release.additional_metadata["edition_id"] == "201406"
        request_metadata = first_release.additional_metadata["requests"][0]
        assert request_metadata["country_requested"] == "USA"
        assert request_metadata["country_queried"] == ["USA"]
        assert request_metadata["request_urls"] == [
            "https://api.worldbank.org/example/USA/201406"
        ]

        # A repeated refresh is idempotent: stored request provenance marks each
        # immutable historical edition as already ingested for this series.
        again = MTTimeSeries(
            INDICATOR,
            "WDI",
            series_key={"country": "USA"},
            vintage_start_date="2014-06-01",
            vintage_end_date="2014-07-31",
            db_path=str(wdi_database),
        )
        assert again.generate_vintage_matrix().equals(matrix)
        assert fetch_edition.call_count == 2
        assert Observation.select().count() == 4

    local_series = MTTimeSeries(
        INDICATOR,
        "WDI",
        series_key={"country": "usa"},
        update_prior_to_load=False,
        db_path=str(wdi_database),
    )
    assert local_series.series_key == {"country": "USA"}
    assert local_series.release_date == series.release_date


def test_second_country_is_isolated_within_same_indicator(wdi_database):
    catalogue = [edition_record("201407", "2014 Jul")]

    def fetch(_client, indicator, edition, **kwargs):
        code = kwargs["country"]
        value = 100.0 if code == "USA" else 200.0
        name = "United States" if code == "USA" else "Canada"
        return WDIEditionResult(
            edition_id=edition,
            observations=[
                normalized_observation(
                    edition, 2012, value, country_code=code, country_name=name
                )
            ],
            request_urls=[f"https://api.worldbank.org/example/{code}/{edition}"],
            total_rows=1,
        )

    with (
        patch.object(WDIAPIClient, "list_editions", return_value=catalogue),
        patch.object(
            WDIAPIClient, "fetch_edition_result", autospec=True, side_effect=fetch
        ),
    ):
        usa = MTTimeSeries(
            INDICATOR,
            "WDI",
            series_key={"country": "USA"},
            db_path=str(wdi_database),
        )
        can = MTTimeSeries(
            INDICATOR,
            "WDI",
            series_key={"country": "CAN"},
            db_path=str(wdi_database),
        )

    assert usa.current_observations[0].value == 100.0
    assert can.current_observations[0].value == 200.0
    assert Observation.select().count() == 2


def test_alias_fallback_is_recorded_not_silently_rewritten(wdi_database):
    catalogue = [edition_record("201407", "2014 Jul")]

    def fetch(_client, indicator, edition, **kwargs):
        code = kwargs["country"]
        observations = []
        if code == "ZAR":
            observations = [
                normalized_observation(
                    edition,
                    2012,
                    250.0,
                    country_code="ZAR",
                    country_name="Congo, Dem. Rep.",
                )
            ]
        return WDIEditionResult(
            edition_id=edition,
            observations=observations,
            request_urls=[f"https://api.worldbank.org/example/{code}/{edition}"],
            total_rows=len(observations),
        )

    with (
        patch.object(WDIAPIClient, "list_editions", return_value=catalogue),
        patch.object(
            WDIAPIClient, "fetch_edition_result", autospec=True, side_effect=fetch
        ),
    ):
        series = MTTimeSeries(
            INDICATOR,
            "WDI",
            series_key={"country": "COD"},
            db_path=str(wdi_database),
        )

    assert series.series_key == {"country": "COD"}
    release = Release.get()
    request_metadata = release.additional_metadata["requests"][0]
    assert request_metadata["country_requested"] == "COD"
    assert request_metadata["country_queried"] == ["COD", "ZAR"]
    assert request_metadata["response_entities"][0]["country_code"] == "ZAR"


def test_empty_edition_is_recorded_and_not_fetched_again(wdi_database, edition_results):
    catalogue = [
        edition_record("201406", "2014 Jun"),
        edition_record("201407", "2014 Jul"),
    ]
    empty = WDIEditionResult(
        edition_id="201406",
        observations=[],
        request_urls=["https://api.worldbank.org/example/USA/201406"],
        total_rows=0,
    )

    def fetch(_client, indicator, edition, **kwargs):
        return empty if edition == "201406" else edition_results["201407"]

    with (
        patch.object(WDIAPIClient, "list_editions", return_value=catalogue),
        patch.object(
            WDIAPIClient, "fetch_edition_result", autospec=True, side_effect=fetch
        ) as fetch_edition,
    ):
        first = MTTimeSeries(
            INDICATOR,
            "WDI",
            series_key={"country": "USA"},
            db_path=str(wdi_database),
        )
        second = MTTimeSeries(
            INDICATOR,
            "WDI",
            series_key={"country": "USA"},
            db_path=str(wdi_database),
        )

    assert first.release_date == datetime(2014, 7, 31, tzinfo=UTC)
    assert second.release_date == first.release_date
    assert fetch_edition.call_count == 2
    empty_release = Release.get(
        Release.release_date == datetime(2014, 6, 30, tzinfo=UTC)
    )
    request_metadata = empty_release.additional_metadata["requests"][0]
    assert request_metadata["source_row_count"] == 0
    assert request_metadata["non_null_observation_count"] == 0
