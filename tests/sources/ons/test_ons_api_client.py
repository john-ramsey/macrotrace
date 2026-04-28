from unittest.mock import MagicMock

from macrotrace.sources.ons import (
    _retry_after_seconds,
    wait_retry_after_or_fallback,
    is_429,
    _fallback,
)

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.ons.fixtures import api_client, db_setup_and_teardown


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
