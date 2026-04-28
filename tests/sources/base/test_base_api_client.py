import pytest
from unittest.mock import patch
import requests
from importlib.metadata import version, PackageNotFoundError

from tests.sources.base.fixtures import api_client  # noqa: F401  pytest fixture


def test_initialization(api_client):
    """
    Test that the APIClient initializes correctly
    """
    assert api_client.base_url == "https://api.example.com/"
    assert isinstance(api_client.session, requests.Session)


@patch("macrotrace.sources.base.APIClient._get_default_params")
@patch("macrotrace.sources.base.APIClient._get_request_headers")
@patch("requests.Session.get")
def test_make_request_success(mock_get, mock_headers, mock_default_params, api_client):
    """
    Test that the APIClient.make_request() makes successful API requests correctly
    """
    try:
        __version__ = version("macrotrace")
    except PackageNotFoundError:
        # Package is not installed
        __version__ = "unknown"

    mock_headers.return_value = {}
    mock_default_params.return_value = {}
    mock_response = mock_get.return_value
    mock_response.status_code = 200
    mock_response.json.return_value = {"key": "value"}

    result = api_client.make_request("series", {"series_id": "TEST"})

    # Check URL structure
    assert mock_get.called
    called_url = mock_get.call_args[1]["params"]
    assert called_url["series_id"] == "TEST"

    # Check headers were used
    headers = mock_get.call_args[1]["headers"]
    assert (
        headers["User-Agent"]
        == f"Macrotrace/{__version__} (contact: john@johnramsey.com)"
    )

    assert result == {"key": "value"}


@patch("macrotrace.sources.base.APIClient._get_default_params")
@patch("macrotrace.sources.base.APIClient._get_request_headers")
@patch("requests.Session.get")
def test_make_request_raises_on_error(
    mock_get, mock_headers, mock_default_params, api_client
):
    """
    Test that the APIClient.make_request() raises an error on bad responses
    """
    mock_headers.return_value = {}
    mock_default_params.return_value = {}
    mock_response = mock_get.return_value
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "Bad request"
    )
    mock_response.status_code = 400

    with pytest.raises(requests.exceptions.HTTPError):
        api_client.make_request("series", {"series_id": "BAD_ID"})


def test_get_request_headers(api_client):
    """
    Test that the APIClient._get_request_headers() raises a NotImplementedError
    """
    with pytest.raises(NotImplementedError):
        api_client._get_request_headers()


def test_get_default_params(api_client):
    """
    Test that the APIClient._get_default_params() raises a NotImplementedError
    """
    with pytest.raises(NotImplementedError):
        api_client._get_default_params()


@patch("requests.Session.get")
@patch("macrotrace.sources.base.APIClient._get_request_headers")
@patch("macrotrace.sources.base.APIClient._get_default_params")
def test_make_request_dry_run(
    mock_default_params, mock_request_headers, mock_get, api_client
):
    """
    Test that the APIClient.make_request() does not make a request in dry run mode
    """
    mock_default_params.return_value = {"default_param": "value"}
    mock_request_headers.return_value = {"User-Agent": "Test-Agent"}

    prepared_url, merged_params = api_client.make_request_dry_run(
        "test/endpoint", {"custom_param": "custom_value"}
    )

    assert (
        prepared_url
        == "https://api.example.com/test/endpoint?default_param=value&custom_param=custom_value"
    )
    assert merged_params == {
        "default_param": "value",
        "custom_param": "custom_value",
    }
    mock_get.assert_not_called()


@patch("macrotrace.sources.base.APIClient.make_request")
def test_make_paginated_request_single_page(mock_make_request, api_client):
    """
    Test that make_paginated_request handles a single page correctly (items < limit)
    """
    mock_make_request.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

    result = api_client.make_paginated_request("test/endpoint", limit=10)

    assert len(result) == 3
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
    mock_make_request.assert_called_once_with(
        "test/endpoint", {"limit": 10, "offset": 0}
    )


@patch("macrotrace.sources.base.APIClient.make_request")
def test_make_paginated_request_multiple_pages(mock_make_request, api_client):
    """
    Test that make_paginated_request fetches multiple pages correctly
    """
    # First page returns full limit, second page returns partial
    mock_make_request.side_effect = [
        [{"id": i} for i in range(10)],
        [{"id": i} for i in range(10, 15)],
    ]

    result = api_client.make_paginated_request("test/endpoint", limit=10)

    assert len(result) == 15
    assert mock_make_request.call_count == 2

    assert mock_make_request.call_args_list[0][0][0] == "test/endpoint"
    assert mock_make_request.call_args_list[0][0][1] == {"limit": 10, "offset": 0}

    assert mock_make_request.call_args_list[1][0][0] == "test/endpoint"
    assert mock_make_request.call_args_list[1][0][1] == {"limit": 10, "offset": 10}


@patch("macrotrace.sources.base.APIClient.make_request")
def test_make_paginated_request_with_items_key(mock_make_request, api_client):
    """
    Test that make_paginated_request correctly extracts items using items_key
    """
    mock_make_request.side_effect = [
        {"data": [{"id": 1}, {"id": 2}], "meta": {"count": 2}},
        {"data": [{"id": 3}], "meta": {"count": 1}},
    ]

    result = api_client.make_paginated_request(
        "test/endpoint", limit=2, items_key="data"
    )

    assert len(result) == 3
    assert result == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert mock_make_request.call_count == 2


@patch("macrotrace.sources.base.APIClient.make_request")
def test_make_paginated_request_custom_params(mock_make_request, api_client):
    """
    Test that make_paginated_request correctly uses custom limit/offset parameter names
    """
    mock_make_request.return_value = [{"id": 1}]

    result = api_client.make_paginated_request(
        "test/endpoint",
        params={"filter": "active"},
        limit_param="page_size",
        offset_param="page_offset",
        limit=5,
    )

    assert len(result) == 1
    mock_make_request.assert_called_once_with(
        "test/endpoint", {"filter": "active", "page_size": 5, "page_offset": 0}
    )


@patch("macrotrace.sources.base.APIClient.make_request")
def test_make_paginated_request_max_pages_reached(mock_make_request, api_client):
    """
    Test that make_paginated_request raises RuntimeError when max_pages is reached
    """

    mock_make_request.return_value = [{"id": i} for i in range(10)]

    with pytest.raises(RuntimeError) as exc_info:
        api_client.make_paginated_request("test/endpoint", limit=10, max_pages=3)

    assert "Pagination limit reached: max_pages=3" in str(exc_info.value)
    assert mock_make_request.call_count == 3


@patch("macrotrace.sources.base.APIClient.make_request")
def test_make_paginated_request_empty_response(mock_make_request, api_client):
    """
    Test that make_paginated_request handles empty responses correctly
    """
    mock_make_request.return_value = []

    result = api_client.make_paginated_request("test/endpoint", limit=10)

    assert len(result) == 0
    assert result == []
    mock_make_request.assert_called_once()


@patch("macrotrace.sources.base.APIClient.make_request")
def test_make_paginated_request_exact_limit_boundary(mock_make_request, api_client):
    """
    Test pagination behavior when response has exactly the limit on last page
    """
    mock_make_request.side_effect = [
        [{"id": i} for i in range(10)],
        [],
    ]

    result = api_client.make_paginated_request("test/endpoint", limit=10)

    assert len(result) == 10
    assert mock_make_request.call_count == 2


@patch("macrotrace.sources.base.APIClient.make_request")
def test_make_paginated_request_with_items_key_missing(mock_make_request, api_client):
    """
    Test that make_paginated_request handles missing items_key gracefully
    """
    mock_make_request.return_value = {"meta": {"count": 0}}

    result = api_client.make_paginated_request(
        "test/endpoint", limit=10, items_key="data"
    )

    assert len(result) == 0
    assert result == []
