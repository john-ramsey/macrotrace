from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest
import requests

from macrotrace.sources.wdi import (
    WDIAPIClient,
    WDIResponseError,
    WDI_SOURCE_ADAPTER,
    WDIUpdateManager,
    _retry_after_seconds,
    country_code_candidates,
    edition_to_vintage_timestamp,
    is_retryable_wdi_error,
)
from tests.sources.wdi.fixtures import (
    INDICATOR,
    api_client,
    catalogue_pages,
    data_row,
    data_pages,
)

UTC = timezone.utc


def response(status: int, payload=None, *, retry_after=None):
    result = requests.Response()
    result.status_code = status
    result._content = b""
    result.url = "https://api.worldbank.org/test"
    result.request = requests.Request("GET", result.url).prepare()
    if retry_after is not None:
        result.headers["Retry-After"] = retry_after
    result.json = MagicMock(return_value=payload)
    return result


def test_edition_timestamp_is_conservative_month_end_utc():
    assert edition_to_vintage_timestamp("201407") == datetime(2014, 7, 31, tzinfo=UTC)
    assert edition_to_vintage_timestamp("202402") == datetime(2024, 2, 29, tzinfo=UTC)


@pytest.mark.parametrize("edition", ["2014-07", "201413", "abc", ""])
def test_edition_timestamp_rejects_invalid_ids(edition):
    with pytest.raises(ValueError, match="Invalid WDI edition ID"):
        edition_to_vintage_timestamp(edition)


def test_country_aliases_are_explicit_and_bidirectional():
    assert country_code_candidates("ZAR") == ["ZAR", "COD"]
    assert country_code_candidates("cod") == ["COD", "ZAR"]
    assert country_code_candidates("USA") == ["USA"]


def test_wdi_series_key_accepts_country_dictionary():
    assert WDI_SOURCE_ADAPTER.normalize_series_key(INDICATOR, {"country": "usa"}) == {
        "country": "USA"
    }


def test_wdi_series_key_rejects_string_shorthand():
    with pytest.raises(TypeError, match="must be a dictionary"):
        WDI_SOURCE_ADAPTER.normalize_series_key(INDICATOR, "usa")


@pytest.mark.parametrize("series_key", [None, {}, {"country": ""}])
def test_wdi_series_key_requires_nonempty_country(series_key):
    with pytest.raises(ValueError, match="requires one country/economy"):
        WDI_SOURCE_ADAPTER.normalize_series_key(INDICATOR, series_key)


def test_wdi_series_key_requires_string_country():
    with pytest.raises(TypeError, match="country.*must be a string"):
        WDI_SOURCE_ADAPTER.normalize_series_key(INDICATOR, {"country": 123})


def test_wdi_series_key_rejects_panel_and_unknown_dimensions():
    with pytest.raises(ValueError, match="one WDI country/economy"):
        WDI_SOURCE_ADAPTER.normalize_series_key(INDICATOR, {"country": "all"})
    with pytest.raises(ValueError, match="unexpected key"):
        WDI_SOURCE_ADAPTER.normalize_series_key(
            INDICATOR, {"country": "USA", "time": "all"}
        )


def test_public_client_has_no_credentials_or_authorization(api_client):
    assert api_client._get_request_headers() == {}
    assert api_client._get_default_params() == {"format": "json"}


def test_catalogue_paginates_and_extracts_version_concept(api_client, catalogue_pages):
    with patch.object(
        api_client, "_request_json", side_effect=catalogue_pages
    ) as request:
        editions = api_client.list_editions(per_page=1)

    assert [item["edition_id"] for item in editions] == ["201406", "201407"]
    assert editions[1]["edition_label"] == "2014 Jul"
    assert editions[1]["vintage_timestamp"] == datetime(2014, 7, 31, tzinfo=UTC)
    assert request.call_args_list == [
        call(
            "sources/57/version",
            {"per_page": 1, "page": 1},
            cache_forever=False,
            force_refresh=False,
        ),
        call(
            "sources/57/version",
            {"per_page": 1, "page": 2},
            cache_forever=False,
            force_refresh=False,
        ),
    ]


def test_catalogue_is_reused_in_memory_until_force_refresh(api_client, catalogue_pages):
    with patch.object(
        api_client,
        "_request_json",
        side_effect=catalogue_pages + catalogue_pages,
    ) as request:
        first = api_client.list_editions(per_page=1)
        second = api_client.list_editions(per_page=1)
        refreshed = api_client.list_editions(per_page=1, force_refresh=True)

    assert first == second == refreshed
    assert request.call_count == 4
    assert request.call_args_list[2].kwargs["force_refresh"] is True


def test_fetch_edition_paginates_indexes_concepts_and_ignores_nulls(
    api_client, data_pages
):
    with patch.object(api_client, "_request_json", side_effect=data_pages) as request:
        observations = api_client.fetch_edition(
            INDICATOR, "201407", country="USA", per_page=2
        )

    assert len(observations) == 2
    first = observations[0]
    assert first["indicator_code"] == INDICATOR
    assert first["country_code"] == "USA"
    assert first["country_name"] == "United States"
    assert first["observation_year"] == 2011
    assert first["observation_date"] == datetime(2011, 1, 1, tzinfo=UTC)
    assert first["edition_id"] == "201407"
    assert first["edition_label"] == "2014 Jul"
    assert first["value"] == 100.5
    assert first["source_id"] == "57"
    assert first["source_name"] == "WDI Database Archives"
    assert first["entity_type"] == "unclassified"
    assert first["entity_metadata"]["id"] == "USA"
    assert request.call_count == 2
    endpoint = request.call_args_list[0].args[0]
    assert endpoint == (
        "sources/57/country/USA/series/NY.GDP.PCAP.KD/time/all/version/201407/data"
    )


def test_empty_edition_is_a_valid_result(api_client):
    payload = {
        "page": 1,
        "pages": 1,
        "per_page": 40000,
        "total": 0,
        "source": {"id": "57", "name": "WDI Database Archives", "data": []},
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/empty"),
    ):
        result = api_client.fetch_edition_result(INDICATOR, "201407", country="USA")

    assert result.observations == []
    assert result.total_rows == 0


def test_exact_edition_uses_client_indicator_and_country(api_client, data_pages):
    api_client.indicator = INDICATOR
    api_client.country = "USA"
    with patch.object(api_client, "_request_json", side_effect=data_pages):
        observations = api_client.edition("201407", per_page=2)
    assert {item["edition_id"] for item in observations} == {"201407"}


def test_catalogue_requires_list_source(api_client):
    payload = {
        "page": 1,
        "pages": 1,
        "per_page": 300,
        "total": 0,
        "source": {},
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match="source.*list"):
            api_client.list_editions()


def test_data_requires_object_source(api_client):
    payload = {
        "page": 1,
        "pages": 1,
        "per_page": 40000,
        "total": 0,
        "source": [],
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match="source.*object"):
            api_client.fetch_edition(INDICATOR, "201407", country="USA")


def test_data_total_must_match_rows(api_client):
    payload = {
        "page": 1,
        "pages": 1,
        "per_page": 40000,
        "total": 1,
        "source": {"id": "57", "name": "WDI Database Archives", "data": []},
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match="row count"):
            api_client.fetch_edition(INDICATOR, "201407", country="USA")


@pytest.mark.parametrize(
    ("status", "retry_after", "expected_wait"),
    [(429, "7", 7.0), (503, None, 1)],
)
def test_transient_http_errors_are_retried(
    api_client, status, retry_after, expected_wait
):
    api_client.session.get = MagicMock(
        side_effect=[
            response(status, retry_after=retry_after),
            response(200, {"page": 1}),
        ]
    )
    with patch.object(WDIAPIClient._get_response.retry, "sleep") as sleep:
        payload, _url = api_client._request_json(
            "test", {}, cache_forever=False, force_refresh=False
        )

    assert payload == {"page": 1}
    sleep.assert_called_once_with(expected_wait)
    assert api_client.session.get.call_count == 2


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_timeout_and_connection_errors_are_retried(api_client, error):
    api_client.session.get = MagicMock(side_effect=[error, response(200, {"page": 1})])
    with patch.object(WDIAPIClient._get_response.retry, "sleep") as sleep:
        payload, _url = api_client._request_json(
            "test", {}, cache_forever=False, force_refresh=False
        )

    assert payload == {"page": 1}
    sleep.assert_called_once_with(1)
    assert api_client.session.get.call_count == 2


def test_retryable_errors_stop_after_four_attempts(api_client):
    api_client.session.get = MagicMock(return_value=response(503))
    with patch.object(WDIAPIClient._get_response.retry, "sleep") as sleep:
        with pytest.raises(requests.HTTPError):
            api_client._request_json(
                "test", {}, cache_forever=False, force_refresh=False
            )

    assert api_client.session.get.call_count == 4
    assert sleep.call_count == 3


def test_permanent_4xx_is_not_retried(api_client):
    api_client.session.get = MagicMock(return_value=response(404))
    with pytest.raises(requests.HTTPError):
        api_client._request_json("test", {}, cache_forever=False, force_refresh=False)
    api_client.session.get.assert_called_once()


def test_historical_request_uses_permanent_cache_and_force_dimensions(tmp_path):
    client = WDIAPIClient(cache_path=str(tmp_path / "cache.sqlite"))
    client.session.get = MagicMock(return_value=response(200, {}))
    client._request_json(
        "endpoint", {"page": 3}, cache_forever=True, force_refresh=True
    )

    kwargs = client.session.get.call_args.kwargs
    assert kwargs["params"] == {"format": "json", "page": 3}
    assert kwargs["expire_after"] == -1
    assert kwargs["force_refresh"] is True
    assert "Authorization" not in kwargs["headers"]


def test_retry_after_seconds_accepts_http_date_and_rejects_invalid_header():
    dated = requests.HTTPError(
        response=response(429, retry_after="21 Oct 2099 07:28:00")
    )
    invalid = requests.HTTPError(response=response(429, retry_after="invalid"))

    assert _retry_after_seconds(dated) > 0
    assert _retry_after_seconds(invalid) is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ValueError(), False),
        (requests.HTTPError(response=response(400)), False),
        (requests.HTTPError(response=response(500)), True),
    ],
)
def test_retryable_error_classification(error, expected):
    assert is_retryable_wdi_error(error) is expected


def test_request_json_rejects_malformed_json(api_client):
    malformed = response(200)
    malformed.json.side_effect = requests.exceptions.JSONDecodeError("bad", "x", 0)
    api_client.session.get = MagicMock(return_value=malformed)

    with pytest.raises(WDIResponseError, match="malformed JSON"):
        api_client._request_json("test", {}, cache_forever=False, force_refresh=False)


def test_request_json_requires_object(api_client):
    api_client.session.get = MagicMock(return_value=response(200, []))

    with pytest.raises(WDIResponseError, match="must be an object"):
        api_client._request_json("test", {}, cache_forever=False, force_refresh=False)


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ({}, "has no 'page'"),
        ({"page": "many"}, "invalid 'page'"),
        ({"page": 0}, "invalid 'page'"),
    ],
)
def test_catalogue_requires_valid_pagination(api_client, payload, match):
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match=match):
            api_client.list_editions()


def test_catalogue_page_number_must_match_request(api_client):
    payload = {
        "page": 2,
        "pages": 2,
        "per_page": 1,
        "total": 1,
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match="reported page 2, expected 1"):
            api_client.list_editions()


def test_catalogue_pagination_metadata_must_remain_stable(api_client, catalogue_pages):
    second_payload, second_url = catalogue_pages[1]
    changed_second_payload = dict(second_payload, total=3)
    pages = [catalogue_pages[0], (changed_second_payload, second_url)]

    with patch.object(api_client, "_request_json", side_effect=pages):
        with pytest.raises(WDIResponseError, match="metadata changed"):
            api_client.list_editions(per_page=1)


@pytest.mark.parametrize(
    ("source", "match"),
    [
        ([], "source 57 exactly once"),
        ([{"id": "57", "concept": {}}], "no concept list"),
        ([{"id": "57", "concept": []}], "no valid version variables"),
        (
            [{"id": "57", "concept": [{"id": "version", "variable": [None]}]}],
            "invalid version",
        ),
    ],
)
def test_catalogue_rejects_invalid_source_metadata(api_client, source, match):
    payload = {
        "page": 1,
        "pages": 1,
        "per_page": 300,
        "total": 0,
        "source": source,
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match=match):
            api_client.list_editions()


def test_catalogue_total_must_match_versions(api_client):
    payload = {
        "page": 1,
        "pages": 1,
        "per_page": 300,
        "total": 1,
        "source": [
            {
                "id": "57",
                "concept": [{"id": "version", "variable": []}],
            }
        ],
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match="row count"):
            api_client.list_editions()


@pytest.mark.parametrize(
    ("source", "match"),
    [
        ({"id": "2", "data": []}, "expected '57'"),
        ({"id": "57", "data": {}}, "no data list"),
        ({"id": "57", "data": [None]}, "non-object row"),
    ],
)
def test_data_rejects_invalid_source_content(api_client, source, match):
    payload = {
        "page": 1,
        "pages": 1,
        "per_page": 40000,
        "total": len(source["data"]),
        "source": source,
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match=match):
            api_client.fetch_edition(INDICATOR, "201407", country="USA")


@pytest.mark.parametrize(
    ("row", "match"),
    [
        ({"value": 1, "variable": {}}, "no variable list"),
        ({"value": 1, "variable": [None]}, "invalid variable"),
        (
            {
                "value": 1,
                "variable": [
                    {"concept": "Country", "id": "USA"},
                    {"concept": "Version", "id": "201407"},
                    {"concept": "Series", "id": INDICATOR},
                ],
            },
            "missing 'Time'",
        ),
        (
            data_row(2012, 1)
            | {
                "variable": [
                    {**item, "id": "OTHER"} if item["concept"] == "Series" else item
                    for item in data_row(2012, 1)["variable"]
                ]
            },
            "returned indicator",
        ),
        (
            data_row(2012, 1)
            | {
                "variable": [
                    {**item, "id": "201406"} if item["concept"] == "Version" else item
                    for item in data_row(2012, 1)["variable"]
                ]
            },
            "returned edition",
        ),
        (
            data_row(2012, 1)
            | {
                "variable": [
                    {**item, "id": "2012"} if item["concept"] == "Time" else item
                    for item in data_row(2012, 1)["variable"]
                ]
            },
            "invalid annual time ID",
        ),
        (data_row(2012, 1) | {"value": "not-a-number"}, "non-numeric value"),
    ],
)
def test_data_rejects_malformed_observations(api_client, row, match):
    payload = {
        "page": 1,
        "pages": 1,
        "per_page": 40000,
        "total": 1,
        "source": {
            "id": "57",
            "name": "WDI Database Archives",
            "data": [row],
        },
    }
    with patch.object(
        api_client,
        "_request_json",
        return_value=(payload, "https://api.worldbank.org/bad"),
    ):
        with pytest.raises(WDIResponseError, match=match):
            api_client.fetch_edition(INDICATOR, "201407", country="USA")


@pytest.mark.parametrize(
    ("indicator", "country", "time_selection"),
    [("", "USA", "all"), (INDICATOR, "", "all"), (INDICATOR, "USA", "")],
)
def test_fetch_edition_requires_nonempty_request_dimensions(
    api_client, indicator, country, time_selection
):
    with pytest.raises(ValueError, match="must be non-empty"):
        api_client.fetch_edition(
            indicator,
            "201407",
            country=country,
            time_selection=time_selection,
        )


def test_exact_edition_requires_indicator(api_client):
    with pytest.raises(ValueError, match="indicator is required"):
        api_client.edition("201407")


def test_update_manager_requires_indicator_and_series_key():
    with pytest.raises(ValueError, match="indicator code must be non-empty"):
        WDIUpdateManager("", series_key={"country": "USA"})
    with pytest.raises(ValueError, match="normalized country series key"):
        WDIUpdateManager(INDICATOR)
