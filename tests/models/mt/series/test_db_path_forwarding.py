"""``MTTimeSeries`` forwards ``db_path``/``cache_path`` to update managers."""

import os
from unittest.mock import patch

import pytest

from macrotrace.models.mt.time_series import MTTimeSeries

# Importing utils brings in the autouse db_setup_and_teardown fixture so the
# test models stay bound to the in-memory test db.
from tests.models.mt.utils import *  # noqa: F401,F403


@pytest.fixture
def empty_ts():
    """Build an MTTimeSeries that hasn't actually loaded anything yet."""
    instance = MTTimeSeries.__new__(MTTimeSeries)
    instance.dataset_id = "PAYEMS"
    instance.source = "FRED"
    instance.series_key = {}
    instance.vintage_start_date = None
    instance.vintage_end_date = None
    instance.data_start_date = None
    instance.data_end_date = None
    instance.db_path = None
    instance.cache_path = None
    return instance


def test_get_update_manager_forwards_db_and_cache_path(empty_ts):
    os.environ["FRED_API_KEY"] = "test"
    empty_ts.db_path = "/tmp/forward.db"
    empty_ts.cache_path = "/tmp/forward.sqlite"

    with patch(
        "macrotrace.sources.fred.FredUpdateManager.__init__", return_value=None
    ) as mock_init:
        empty_ts._get_update_manager()

    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["db_path"] == "/tmp/forward.db"
    assert kwargs["cache_path"] == "/tmp/forward.sqlite"


def test_get_update_manager_forwards_none_by_default(empty_ts):
    os.environ["FRED_API_KEY"] = "test"

    with patch(
        "macrotrace.sources.fred.FredUpdateManager.__init__", return_value=None
    ) as mock_init:
        empty_ts._get_update_manager()

    kwargs = mock_init.call_args.kwargs
    assert kwargs["db_path"] is None
    assert kwargs["cache_path"] is None


def test_local_only_load_uses_provided_db_path(tmp_path, monkeypatch):
    """An ``update_prior_to_load=False`` load against an empty user-supplied
    db path should raise the "no locally stored dataset" error, proving the
    resolver opened the file we asked for and not the default."""
    monkeypatch.delenv("MACROTRACE_DB", raising=False)
    db_path = tmp_path / "local_only.db"

    with pytest.raises(ValueError, match="No locally stored dataset"):
        MTTimeSeries(
            dataset_id="DOES_NOT_EXIST",
            source="FRED",
            update_prior_to_load=False,
            db_path=str(db_path),
        )
