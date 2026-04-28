from unittest.mock import patch

from tests.sources.fred.fixtures import api_client


def test_fred_request_headers(api_client):
    """
    Test that the FredAPIClient._get_request_headers() includes the correct request headers.
    """
    # Mock the API response to ensure no real API calls are made
    headers = api_client._get_request_headers()

    assert headers == {}


def test_fred_default_params(api_client):
    """
    Test that the FredAPIClient._get_default_params() includes the correct default parameters.
    """
    params = api_client._get_default_params()

    assert params["api_key"] == "ABC"
    assert params["file_type"] == "json"
