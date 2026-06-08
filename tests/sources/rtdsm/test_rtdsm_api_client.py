from datetime import datetime, timezone

import pytest
import requests
import requests_cache
from unittest.mock import MagicMock, patch

from macrotrace.sources.rtdsm import (
    RTDSMAPIClient,
    RTDSM_BASE_URL,
    _first_of_next_month,
)

from tests.sources.rtdsm.fixtures import (
    api_client,
    db_setup_and_teardown,
    make_xlsx_bytes,
)

UTC = timezone.utc

VALID_XLSX = None


def _valid_xlsx():
    return make_xlsx_bytes(["DATE", "ROUTPUT65Q4"], [["1947:Q1", 306.4]])


def _mock_response(content, from_cache=False):
    resp = MagicMock()
    resp.content = content
    resp.status_code = 200
    resp.from_cache = from_cache
    resp.raise_for_status = MagicMock()
    return resp


def test_initialization(api_client):
    assert api_client.dataset_id == "ROUTPUT"
    assert api_client.filename == "routputqvqd.xlsx"
    assert api_client.data_freq == "Q"
    assert api_client.base_url == RTDSM_BASE_URL
    assert api_client._get_request_headers() == {}
    assert api_client._get_default_params() == {}


def test_download_returns_bytes(api_client):
    """A valid .xlsx response is returned as bytes."""
    content = _valid_xlsx()
    api_client.session = MagicMock()
    api_client.session.get.return_value = _mock_response(content)

    result = api_client._download()
    assert result == content
    # No caching session, so expire_after must not be passed.
    _, kwargs = api_client.session.get.call_args
    assert "expire_after" not in kwargs


def test_download_soft_404_raises(api_client):
    """An HTML error page served with HTTP 200 is rejected (soft-404)."""
    api_client.session = MagicMock()
    api_client.session.get.return_value = _mock_response(
        b"<html><title>Error - 404</title></html>"
    )
    with pytest.raises(ValueError, match="did not return a valid"):
        api_client._download()


def test_download_saves_excel_when_dir_set(tmp_path):
    """When excel_dir is set, the downloaded file is written to disk."""
    client = RTDSMAPIClient(
        dataset_id="ROUTPUT",
        filename="routputqvqd.xlsx",
        data_freq="Q",
        excel_dir=str(tmp_path),
        cache_settings={"caching": False},
    )
    content = _valid_xlsx()
    client.session = MagicMock()
    client.session.get.return_value = _mock_response(content)

    client._download()
    saved = tmp_path / "routputqvqd.xlsx"
    assert saved.exists()
    assert saved.read_bytes() == content


def test_download_passes_month_expiry_for_cached_session():
    """With a caching session, the request carries a next-month expiry."""
    client = RTDSMAPIClient(
        dataset_id="ROUTPUT",
        filename="routputqvqd.xlsx",
        data_freq="Q",
        cache_settings={"caching": True, "cache_expiry": 86400},
        cache_path=":memory:",
    )
    assert isinstance(client.session, requests_cache.CachedSession)
    client.session.get = MagicMock(
        return_value=_mock_response(_valid_xlsx(), from_cache=True)
    )

    client._download()
    _, kwargs = client.session.get.call_args
    assert "expire_after" in kwargs
    # The expiry must be exactly the first of next month (not just any
    # first-of-month), so that a same-month reload is served from cache and a
    # next-month reload re-fetches.
    assert kwargs["expire_after"] == _first_of_next_month(datetime.now(UTC))


def test_download_saves_excel_from_cached_response(tmp_path):
    """
    excel_dir is honored even when the response is served from the request
    cache. A first run with excel_dir=None caches the file; a later run that
    opts into archiving (excel_dir set) still writes it, because the save is
    gated on excel_dir and acts on the (cached) response content.
    """
    client = RTDSMAPIClient(
        dataset_id="ROUTPUT",
        filename="routputqvqd.xlsx",
        data_freq="Q",
        excel_dir=str(tmp_path / "xl"),
        cache_settings={"caching": True, "cache_expiry": 86400},
        cache_path=":memory:",
    )
    assert isinstance(client.session, requests_cache.CachedSession)
    client.session.get = MagicMock(
        return_value=_mock_response(_valid_xlsx(), from_cache=True)
    )

    client._download()

    saved = tmp_path / "xl" / "routputqvqd.xlsx"
    assert saved.exists()
    assert saved.read_bytes() == _valid_xlsx()


def test_get_parsed_file_memoizes(api_client):
    """get_parsed_file downloads and parses only once."""
    with patch.object(
        api_client, "_download", return_value=_valid_xlsx()
    ) as mock_download:
        first = api_client.get_parsed_file()
        second = api_client.get_parsed_file()
    assert first is second
    mock_download.assert_called_once()
    assert first.vintages[0][0] == "ROUTPUT65Q4"


def test_download_retries_on_request_exception(api_client):
    """Transient network errors are retried (the base tenacity policy)."""
    content = _valid_xlsx()
    api_client.session = MagicMock()
    api_client.session.get.side_effect = [
        requests.ConnectionError("boom"),
        _mock_response(content),
    ]
    result = api_client._download()
    assert result == content
    assert api_client.session.get.call_count == 2
