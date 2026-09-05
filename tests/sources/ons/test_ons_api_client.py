from unittest.mock import MagicMock, patch

import pytest
import requests

from macrotrace.sources.ons import (
    ONSAPIClient,
    _retry_after_seconds,
    wait_retry_after_or_fallback,
    is_429,
    _fallback,
)

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.ons.fixtures import api_client, db_setup_and_teardown


def response(status: int, payload=None, *, retry_after=None):
    result = requests.Response()
    result.status_code = status
    result._content = b""
    result.url = "https://api.beta.ons.gov.uk/test"
    result.request = requests.Request("GET", result.url).prepare()
    if retry_after is not None:
        result.headers["Retry-After"] = retry_after
    result.json = MagicMock(return_value=payload)
    return result


def test_ons_request_headers(api_client):
    """
    Test that the ONSAPIClient._get_request_headers() includes the correct request headers.
    """
    headers = api_client._get_request_headers()

    assert headers == {}


def test_fred_default_params(api_client):
    """
    Test that the FredAPIClient._get_default_params() includes the correct default parameters.
    """
    params = api_client._get_default_params()

    assert params == {}


def test_retry_after_seconds_429_response_with_headers():
    """Test _retry_after_seconds handles 429 responses correctly."""

    mock_response = MagicMock()
    mock_response.status_code = 429

    mock_exception = MagicMock()
    mock_exception.response = mock_response

    # Test with Retry-After header present
    headers_with_retry = {"Retry-After": "120"}
    mock_response.headers = headers_with_retry
    mock_exception.response = mock_response
    assert _retry_after_seconds(mock_exception) == 120


def test_retry_after_seconds_no_429_or_no_headers():
    """Test _retry_after_seconds handles non-429 responses and missing headers."""

    mock_response = MagicMock()
    mock_response.status_code = 429

    mock_exception = MagicMock()
    mock_exception.response = mock_response

    # Test without Retry-After header
    headers_without_retry = {}
    mock_response.headers = headers_without_retry
    mock_exception.response = mock_response
    assert _retry_after_seconds(mock_exception) is None


def test_retry_after_seconds_invalid_header():
    """Test _retry_after_seconds handles invalid Retry-After header gracefully."""

    mock_response = MagicMock()
    mock_response.status_code = 429

    mock_exception = MagicMock()
    mock_exception.response = mock_response

    # Test with invalid Retry-After header
    headers_invalid_retry = {"Retry-After": "invalid"}
    mock_response.headers = headers_invalid_retry
    mock_exception.response = mock_response
    assert _retry_after_seconds(mock_exception) is None


def test_wait_retry_after_or_fallback_no_exception():
    """Test wait_retry_after_or_fallback when no retry_state.outcome is provided."""
    retry_state = MagicMock()
    retry_state.outcome = None
    retry_state.attempt_number = 1

    wait = wait_retry_after_or_fallback(retry_state)
    assert wait == _fallback(retry_state)


def test_wait_retry_after_or_fallback_with_retry_after():
    """Test wait_retry_after_or_fallback when Retry-After header is present."""

    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": "32"}

    exception = type("MockException", (Exception,), {})
    exception.response = resp

    retry_state = MagicMock()
    retry_state.outcome = MagicMock()
    retry_state.outcome.exception.return_value = exception
    retry_state.attempt_number = 1

    wait = wait_retry_after_or_fallback(retry_state)
    assert wait == 32


def test_wait_retry_after_or_fallback_without_retry_after():
    """Test wait_retry_after_or_fallback when Retry-After header is absent."""

    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}

    exception = type("MockException", (Exception,), {})
    exception.response = resp

    retry_state = MagicMock()
    retry_state.outcome = MagicMock()
    retry_state.outcome.exception.return_value = exception
    retry_state.attempt_number = 1

    wait = wait_retry_after_or_fallback(retry_state)
    assert wait == _fallback(retry_state)


def test_is_429_succeeds():
    """Test is_429 function correctly identifies 429 responses."""

    resp = MagicMock()
    resp.status_code = 429

    exception = type("MockException", (Exception,), {})
    exception.response = resp

    assert is_429(exception) is True


def test_is_429_fails():
    """Test is_429 function correctly identifies non-429 responses."""

    resp = MagicMock()
    resp.status_code = 500

    exception = type("MockException", (Exception,), {})
    exception.response = resp

    assert is_429(exception) is False


@pytest.mark.parametrize(
    ("status", "retry_after", "expected_wait"),
    [(429, "7", 7.0), (503, None, 2)],
)
def test_make_request_retries_transient_http_errors(
    api_client, status, retry_after, expected_wait
):
    api_client.session = MagicMock()
    api_client.session.get.side_effect = [
        response(status, retry_after=retry_after),
        response(200, {"items": []}),
    ]

    with patch.object(ONSAPIClient.make_request.retry, "sleep") as sleep:
        result = api_client.make_request("datasets")

    assert result == {"items": []}
    sleep.assert_called_once_with(expected_wait)
    assert api_client.session.get.call_count == 2


@pytest.mark.parametrize("error", [requests.Timeout(), requests.ConnectionError()])
def test_make_request_retries_network_errors(api_client, error):
    api_client.session = MagicMock()
    api_client.session.get.side_effect = [
        error,
        response(200, {"items": []}),
    ]

    with patch.object(ONSAPIClient.make_request.retry, "sleep") as sleep:
        result = api_client.make_request("datasets")

    assert result == {"items": []}
    sleep.assert_called_once_with(2)
    assert api_client.session.get.call_count == 2


def test_make_request_stops_after_four_attempts(api_client):
    api_client.session = MagicMock()
    api_client.session.get.return_value = response(503)

    with patch.object(ONSAPIClient.make_request.retry, "sleep") as sleep:
        with pytest.raises(requests.HTTPError):
            api_client.make_request("datasets")

    assert api_client.session.get.call_count == 4
    assert sleep.call_count == 3


def test_make_request_does_not_retry_permanent_http_error(api_client):
    api_client.session = MagicMock()
    api_client.session.get.return_value = response(404)

    with pytest.raises(requests.HTTPError):
        api_client.make_request("datasets")

    api_client.session.get.assert_called_once()
