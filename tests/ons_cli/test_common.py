from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from macrotrace.ons_cli.common import (
    ONSExplorer,
    ONSExplorerClient,
    coerce_int,
    dimension_key,
    dimension_label,
    extract_code_list_edition,
    extract_code_list_id,
    is_time_dimension,
    norm_text,
    parse_datetime,
    pick_latest_code_list_edition,
    resolve_ons_frequency_from_dimensions,
    resolve_ons_frequency_from_version_metadata,
    version_sort_key,
)

from tests.ons_cli.utils import (  # noqa: F401  pytest fixtures
    SAMPLE_CODE_LIST_EDITIONS,
    SAMPLE_CODES,
    SAMPLE_DATASETS,
    SAMPLE_DIMENSIONS,
    SAMPLE_EDITIONS,
    SAMPLE_VERSIONS,
    explorer,
    explorer_client,
    mock_session,
)


def test_parse_datetime_valid_iso():
    """Parses a valid ISO-8601 UTC string into a timezone-aware datetime."""
    dt = parse_datetime("2024-01-15T10:30:00Z")
    assert dt == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_datetime_valid_with_offset():
    """Parses an ISO string with a UTC offset and normalises it to UTC."""
    dt = parse_datetime("2024-01-15T10:30:00+01:00")
    assert dt.tzinfo is not None
    assert dt.tzinfo == timezone.utc


def test_parse_datetime_invalid_string():
    """Returns datetime.min (UTC) when the string cannot be parsed as a date."""
    dt = parse_datetime("not-a-date")
    assert dt == datetime.min.replace(tzinfo=timezone.utc)


def test_parse_datetime_non_string():
    """Returns datetime.min (UTC) for non-string inputs such as None or integers."""
    dt = parse_datetime(None)
    assert dt == datetime.min.replace(tzinfo=timezone.utc)

    dt = parse_datetime(42)
    assert dt == datetime.min.replace(tzinfo=timezone.utc)


def test_parse_datetime_naive_iso_gets_utc():
    """Attaches UTC timezone to a naive ISO datetime string."""
    dt = parse_datetime("2024-01-15T10:30:00")
    assert dt.tzinfo == timezone.utc


def test_coerce_int_valid():
    """Converts a string or integer to int when the value is valid."""
    assert coerce_int("3") == 3
    assert coerce_int(5) == 5


def test_coerce_int_invalid_uses_fallback():
    """Returns the default fallback of -1 for non-numeric inputs."""
    assert coerce_int("abc") == -1
    assert coerce_int(None) == -1


def test_coerce_int_custom_fallback():
    """Returns a caller-supplied fallback value when coercion fails."""
    assert coerce_int("abc", fallback=0) == 0


def test_norm_text_casefold():
    """Strips surrounding whitespace and case-folds the input string."""
    assert norm_text("  Hello WORLD  ") == "hello world"


def test_norm_text_already_normalised():
    """Returns the string unchanged when it is already lowercase and trimmed."""
    assert norm_text("time") == "time"


def test_dimension_key_prefers_name():
    """Uses the 'name' field as the primary dimension key."""
    dim = {"name": "aggregate", "id": "cpih1dim1A0", "label": "Aggregate"}
    assert dimension_key(dim) == "aggregate"


def test_dimension_key_falls_back_to_id():
    """Falls back to 'id' when 'name' is absent."""
    dim = {"id": "cpih1dim1A0", "label": "Aggregate"}
    assert dimension_key(dim) == "cpih1dim1A0"


def test_dimension_key_falls_back_to_label():
    """Falls back to 'label' when both 'name' and 'id' are absent."""
    dim = {"label": "Aggregate"}
    assert dimension_key(dim) == "Aggregate"


def test_dimension_key_empty_dict():
    """Returns the sentinel 'unknown_dimension' for an empty dimension dict."""
    assert dimension_key({}) == "unknown_dimension"


def test_dimension_label_prefers_label():
    """Returns the 'label' field when present."""
    dim = {"name": "aggregate", "label": "Aggregate Label"}
    assert dimension_label(dim) == "Aggregate Label"


def test_dimension_label_falls_back_to_key():
    """Falls back to dimension_key() when 'label' is absent."""
    dim = {"name": "aggregate"}
    assert dimension_label(dim) == "aggregate"


def test_is_time_dimension_by_name():
    """Identifies a time dimension by its 'name' field equalling 'time'."""
    dim = {"name": "time", "id": "mmm-yy", "label": "Time"}
    assert is_time_dimension(dim) is True


def test_is_time_dimension_by_label():
    """Identifies a time dimension by its 'label' field equalling 'time'."""
    dim = {"name": "aggregate", "id": "cpih1dim1A0", "label": "Time"}
    assert is_time_dimension(dim) is True


def test_is_time_dimension_false():
    """Returns False for a non-time dimension."""
    dim = {"name": "aggregate", "id": "cpih1dim1A0", "label": "Aggregate"}
    assert is_time_dimension(dim) is False


def test_extract_code_list_id_from_id_field():
    """Extracts the code list id directly from the links.code_list.id field."""
    dim = {"links": {"code_list": {"id": "cpih1dim1A0"}}}
    assert extract_code_list_id(dim) == "cpih1dim1A0"


def test_extract_code_list_id_from_href():
    """Extracts the code list id by parsing the href URL when no id field is present."""
    dim = {
        "links": {
            "code_list": {
                "href": "https://api.beta.ons.gov.uk/v1/code-lists/my-list/editions/2021"
            }
        }
    }
    assert extract_code_list_id(dim) == "my-list"


def test_extract_code_list_id_missing():
    """Returns None when the dimension has no code list link at all."""
    assert extract_code_list_id({}) is None
    assert extract_code_list_id({"links": {}}) is None


def test_extract_code_list_edition_from_edition_field():
    """Extracts the code list edition from the links.code_list.edition field."""
    dim = {"links": {"code_list": {"edition": "time-series"}}}
    assert extract_code_list_edition(dim) == "time-series"


def test_extract_code_list_edition_from_href():
    """Extracts the code list edition by parsing the href URL when no edition field is present."""
    dim = {
        "links": {
            "code_list": {
                "href": "https://api.beta.ons.gov.uk/v1/code-lists/my-list/editions/2021"
            }
        }
    }
    assert extract_code_list_edition(dim) == "2021"


def test_extract_code_list_edition_missing():
    """Returns None when no edition information can be found."""
    assert extract_code_list_edition({}) is None


def test_pick_latest_code_list_edition_returns_most_recent():
    """Selects the edition with the most recent last_updated timestamp."""
    editions = [
        {"edition": "2021", "last_updated": "2022-01-01T00:00:00Z"},
        {"edition": "time-series", "last_updated": "2024-03-01T00:00:00Z"},
    ]
    assert pick_latest_code_list_edition(editions) == "time-series"


def test_pick_latest_code_list_edition_single():
    """Returns the only edition when exactly one is provided."""
    editions = [{"edition": "one-off", "last_updated": "2023-06-01T00:00:00Z"}]
    assert pick_latest_code_list_edition(editions) == "one-off"


def test_pick_latest_code_list_edition_empty_raises():
    """Raises ValueError when passed an empty list."""
    with pytest.raises(ValueError, match="empty"):
        pick_latest_code_list_edition([])


def test_resolve_ons_frequency_from_dimensions_no_time():
    """Returns (None, None) when no time dimension is present."""
    dims = [{"name": "aggregate", "id": "cpih1dim1A0", "label": "Aggregate"}]
    time_dim_id, freq = resolve_ons_frequency_from_dimensions(dims)
    assert time_dim_id is None
    assert freq is None


def test_resolve_ons_frequency_from_dimensions_with_known_time():
    """mmm-yy is a known ONS monthly frequency that maps to a pandas frequency string."""
    dims = [{"name": "time", "id": "mmm-yy", "label": "Time"}]
    time_dim_id, freq = resolve_ons_frequency_from_dimensions(dims)
    assert time_dim_id == "mmm-yy"
    assert freq is not None


def test_resolve_ons_frequency_from_version_metadata_no_dimensions():
    """Returns (None, None) when the metadata dict has no dimensions key."""
    metadata = {}
    time_dim_id, freq = resolve_ons_frequency_from_version_metadata(metadata)
    assert time_dim_id is None
    assert freq is None


def test_resolve_ons_frequency_from_version_metadata_non_list_dimensions():
    """Returns (None, None) when the dimensions value is not a list."""
    metadata = {"dimensions": "not-a-list"}
    time_dim_id, freq = resolve_ons_frequency_from_version_metadata(metadata)
    assert time_dim_id is None
    assert freq is None


def test_resolve_ons_frequency_from_version_metadata_with_time_dim():
    """Resolves the time dimension id and pandas frequency from version metadata."""
    metadata = {
        "dimensions": [
            {"name": "time", "id": "mmm-yy"},
            {"name": "aggregate", "id": "cpih1dim1A0"},
        ]
    }
    time_dim_id, freq = resolve_ons_frequency_from_version_metadata(metadata)
    assert time_dim_id == "mmm-yy"
    assert freq is not None


def test_resolve_ons_frequency_from_version_metadata_no_time_dim():
    """Returns (None, None) when the metadata dimensions contain no time dimension."""
    metadata = {"dimensions": [{"name": "aggregate", "id": "cpih1dim1A0"}]}
    time_dim_id, freq = resolve_ons_frequency_from_version_metadata(metadata)
    assert time_dim_id is None
    assert freq is None


def test_version_sort_key_sorts_by_date_then_version_number():
    """Produces a sort key that orders versions newest-first by release date then version number."""
    versions = [
        {"version": 1, "release_date": "2023-01-01T00:00:00Z"},
        {"version": 3, "release_date": "2024-01-01T00:00:00Z"},
        {"version": 2, "release_date": "2023-06-01T00:00:00Z"},
    ]
    sorted_versions = sorted(versions, key=version_sort_key, reverse=True)
    assert [v["version"] for v in sorted_versions] == [3, 2, 1]


def test_client_uses_requests_session_when_no_cache():
    """Creates a plain requests.Session when caching is disabled."""
    import requests

    client = ONSExplorerClient(use_cache=False)
    assert isinstance(client.session, requests.Session)


def test_client_uses_cached_session_when_cache_enabled():
    """Creates a requests_cache.CachedSession when caching is enabled."""
    import requests_cache

    client = ONSExplorerClient(use_cache=True)
    assert isinstance(client.session, requests_cache.CachedSession)
    client.session.cache.clear()


def test_client_cache_name_resolves_through_env(monkeypatch, tmp_path):
    """When cache_name is None, ``MACROTRACE_CACHE`` should be honored."""
    cache_path = tmp_path / "shared.sqlite"
    monkeypatch.setenv("MACROTRACE_CACHE", str(cache_path))
    monkeypatch.delenv("MACROTRACE_DB", raising=False)

    with patch(
        "macrotrace.ons_cli.common.requests_cache.CachedSession"
    ) as mock_session_cls:
        ONSExplorerClient(use_cache=True)

    mock_session_cls.assert_called_once()
    assert mock_session_cls.call_args.kwargs["cache_name"] == str(cache_path)


def test_client_cache_name_explicit_arg_wins(monkeypatch):
    """An explicit ``cache_name`` overrides the env var."""
    monkeypatch.setenv("MACROTRACE_CACHE", "/should/not/be/used.sqlite")

    with patch(
        "macrotrace.ons_cli.common.requests_cache.CachedSession"
    ) as mock_session_cls:
        ONSExplorerClient(use_cache=True, cache_name="/explicit.sqlite")

    assert mock_session_cls.call_args.kwargs["cache_name"] == "/explicit.sqlite"


def test_client_base_url_always_ends_with_slash():
    """Ensures the base URL is normalized to always end with a trailing slash."""
    client = ONSExplorerClient(base_url="https://example.com/v1", use_cache=False)
    assert client.base_url.endswith("/")


def test_client_make_request_success(explorer_client, mock_session):
    """Returns the parsed JSON body on a successful 200 response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "cpih01"}
    mock_session.get.return_value = mock_response

    result = explorer_client.make_request("datasets/cpih01")
    assert result == {"id": "cpih01"}


def test_client_make_request_raises_on_http_error(explorer_client, mock_session):
    """Propagates an HTTPError raised by raise_for_status."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.raise_for_status.side_effect = requests.HTTPError("404")
    mock_session.get.return_value = mock_response

    with pytest.raises(requests.HTTPError):
        explorer_client.make_request("datasets/does-not-exist")


def test_client_make_request_handles_rate_limit_with_callback(
    explorer_client, mock_session
):
    """Retries after a 429 response and invokes the rate-limit callback."""
    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.json.return_value = {"items": []}

    rate_limited = MagicMock()
    rate_limited.status_code = 429
    rate_limited.headers = {"Retry-After": "0"}

    mock_session.get.side_effect = [
        rate_limited,
        rate_limited,
        rate_limited,
        ok_response,
    ]

    callback = MagicMock()
    explorer_client.rate_limit_callback = callback

    with patch("time.sleep"):
        result = explorer_client.make_request("datasets")

    assert result == {"items": []}
    assert callback.call_count >= 1


def test_client_make_paginated_request_single_page(explorer_client, mock_session):
    """Returns all items when the API returns fewer items than the page size."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"items": [{"id": "cpih01"}, {"id": "gdp"}]}
    mock_session.get.return_value = mock_response

    items = explorer_client.make_paginated_request("datasets", page_size=100)
    assert len(items) == 2
    assert items[0]["id"] == "cpih01"


def test_client_make_paginated_request_multiple_pages(explorer_client, mock_session):
    """Accumulates items across multiple pages until a partial page signals completion."""
    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {"items": [{"id": f"ds{i}"} for i in range(5)]}

    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = {"items": [{"id": "ds5"}, {"id": "ds6"}]}

    mock_session.get.side_effect = [page1, page2]

    items = explorer_client.make_paginated_request("datasets", page_size=5)
    assert len(items) == 7


def test_client_make_paginated_request_calls_progress_callback(
    explorer_client, mock_session
):
    """Invokes the progress callback after each page with the page index and total loaded."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"items": [{"id": "cpih01"}]}
    mock_session.get.return_value = mock_response

    callback = MagicMock()
    explorer_client.make_paginated_request(
        "datasets", page_size=100, progress_callback=callback
    )
    callback.assert_called_once_with(1, 1)


def test_client_make_paginated_request_handles_list_response(
    explorer_client, mock_session
):
    """Accepts a top-level list response in addition to the standard items-keyed dict."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [{"id": "cpih01"}]
    mock_session.get.return_value = mock_response

    items = explorer_client.make_paginated_request("datasets", page_size=100)
    assert items == [{"id": "cpih01"}]


def test_client_make_paginated_request_raises_on_non_list_items(
    explorer_client, mock_session
):
    """Raises ValueError when the items field in the response is not a list."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"items": "not-a-list"}
    mock_session.get.return_value = mock_response

    with pytest.raises(ValueError, match="Expected list"):
        explorer_client.make_paginated_request("datasets", page_size=100)


def test_client_make_paginated_request_raises_on_max_pages(
    explorer_client, mock_session
):
    """Raises RuntimeError when pagination exceeds the max_pages limit."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"items": [{"id": "x"}] * 2}
    mock_session.get.return_value = mock_response

    with pytest.raises(RuntimeError, match="Pagination limit reached"):
        explorer_client.make_paginated_request("datasets", page_size=2, max_pages=3)


def test_client_clear_cache_calls_cache_clear(explorer_client, mock_session):
    """Calls clear() on the underlying cache object when one is present."""
    mock_cache = MagicMock()
    mock_session.cache = mock_cache
    explorer_client.clear_cache()
    mock_cache.clear.assert_called_once()


def test_client_clear_cache_no_cache_attr_does_not_raise():
    """Does not raise when the session has no cache attribute (non-cached mode)."""
    client = ONSExplorerClient(use_cache=False)
    client.clear_cache()


def test_client_set_rate_limit_callback():
    """Stores the provided callback so it can be invoked on future rate-limit events."""
    client = ONSExplorerClient(use_cache=False)
    cb = MagicMock()
    client.set_rate_limit_callback(cb)
    assert client.rate_limit_callback is cb


def test_explorer_list_datasets_sorted(explorer, explorer_client):
    """Returns datasets sorted alphabetically by id regardless of API response order."""
    explorer_client.make_paginated_request = MagicMock(
        return_value=[
            {"id": "gdp", "title": "GDP"},
            {"id": "ashe", "title": "ASHE"},
            {"id": "cpih01", "title": "CPIH"},
        ]
    )
    datasets = explorer.list_datasets(page_size=100, max_pages=5)
    assert [d["id"] for d in datasets] == ["ashe", "cpih01", "gdp"]


def test_explorer_get_dataset(explorer, explorer_client):
    """Fetches a single dataset by id and returns the raw API payload."""
    explorer_client.make_request = MagicMock(
        return_value={"id": "cpih01", "title": "CPIH"}
    )
    dataset = explorer.get_dataset("cpih01")
    explorer_client.make_request.assert_called_once_with("datasets/cpih01")
    assert dataset["id"] == "cpih01"


def test_explorer_list_editions(explorer, explorer_client):
    """Returns the items list from the editions endpoint response."""
    explorer_client.make_request = MagicMock(
        return_value={"items": [{"edition": "time-series"}, {"edition": "2021"}]}
    )
    editions = explorer.list_editions("cpih01")
    assert len(editions) == 2
    assert editions[0]["edition"] == "time-series"


def test_explorer_list_editions_missing_items_key(explorer, explorer_client):
    """Returns an empty list when the response contains no items key."""
    explorer_client.make_request = MagicMock(return_value={})
    editions = explorer.list_editions("cpih01")
    assert editions == []


def test_explorer_list_versions_sorted(explorer, explorer_client):
    """Returns versions sorted newest-first by release date."""
    explorer_client.make_paginated_request = MagicMock(return_value=SAMPLE_VERSIONS)
    versions = explorer.list_versions("cpih01", "time-series")
    assert versions[0]["version"] == 3


def test_explorer_resolve_version_latest(explorer, explorer_client):
    """Resolves 'latest' to the most recent version item."""
    explorer_client.make_paginated_request = MagicMock(return_value=SAMPLE_VERSIONS)
    version_item = explorer.resolve_version("cpih01", "time-series", "latest")
    assert version_item["version"] == 3


def test_explorer_resolve_version_by_number(explorer, explorer_client):
    """Resolves a specific version number to the matching version item."""
    explorer_client.make_paginated_request = MagicMock(return_value=SAMPLE_VERSIONS)
    version_item = explorer.resolve_version("cpih01", "time-series", "2")
    assert version_item["version"] == 2


def test_explorer_resolve_version_not_found(explorer, explorer_client):
    """Raises ValueError when the requested version number does not exist."""
    explorer_client.make_paginated_request = MagicMock(return_value=SAMPLE_VERSIONS)
    with pytest.raises(ValueError, match="Version '99' not found"):
        explorer.resolve_version("cpih01", "time-series", "99")


def test_explorer_resolve_version_empty_versions(explorer, explorer_client):
    """Raises ValueError when there are no versions to resolve."""
    explorer_client.make_paginated_request = MagicMock(return_value=[])
    with pytest.raises(ValueError, match="No versions found"):
        explorer.resolve_version("cpih01", "time-series", "latest")


def test_explorer_list_dimensions(explorer, explorer_client):
    """Returns the list of dimension dicts for a given dataset/edition/version."""
    explorer_client.make_request = MagicMock(return_value={"items": SAMPLE_DIMENSIONS})
    dims = explorer.list_dimensions("cpih01", "time-series", "3")
    assert len(dims) == 2


def test_explorer_resolve_dimension_by_name(explorer):
    """Finds the dimension whose name matches the query string."""
    dim = explorer.resolve_dimension(SAMPLE_DIMENSIONS, "aggregate")
    assert dim["id"] == "cpih1dim1A0"


def test_explorer_resolve_dimension_case_insensitive(explorer):
    """Resolves a dimension name regardless of input case."""
    dim = explorer.resolve_dimension(SAMPLE_DIMENSIONS, "AGGREGATE")
    assert dim["id"] == "cpih1dim1A0"


def test_explorer_resolve_dimension_not_found(explorer):
    """Raises ValueError when no dimension matches the query string."""
    with pytest.raises(ValueError, match="not found"):
        explorer.resolve_dimension(SAMPLE_DIMENSIONS, "nonexistent")


def test_explorer_list_code_list_editions(explorer, explorer_client):
    """Returns the list of available editions for a code list."""
    explorer_client.make_request = MagicMock(
        return_value={"items": SAMPLE_CODE_LIST_EDITIONS}
    )
    editions = explorer.list_code_list_editions("cpih1dim1A0")
    assert len(editions) == 2


def test_explorer_list_dimension_options_with_edition(explorer, explorer_client):
    """Returns the codes for a dimension when a specific code list edition is provided."""
    explorer_client.make_paginated_request = MagicMock(return_value=SAMPLE_CODES)
    edition, options = explorer.list_dimension_options(
        code_list_id="cpih1dim1A0",
        code_list_edition="time-series",
    )
    assert edition == "time-series"
    assert len(options) == 2


def test_explorer_list_dimension_options_auto_picks_latest_edition(
    explorer, explorer_client
):
    """Automatically selects the latest code list edition when none is specified."""
    explorer_client.make_request = MagicMock(
        return_value={"items": SAMPLE_CODE_LIST_EDITIONS}
    )
    explorer_client.make_paginated_request = MagicMock(return_value=SAMPLE_CODES)

    edition, options = explorer.list_dimension_options(code_list_id="cpih1dim1A0")
    assert edition == "time-series"


def test_explorer_list_dimension_options_no_editions_raises(explorer, explorer_client):
    """Raises ValueError when no editions exist for the requested code list."""
    explorer_client.make_request = MagicMock(return_value={"items": []})
    with pytest.raises(ValueError, match="No code-list editions found"):
        explorer.list_dimension_options(code_list_id="cpih1dim1A0")
