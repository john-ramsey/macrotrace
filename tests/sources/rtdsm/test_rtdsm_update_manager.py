import pytest

from macrotrace.sources.rtdsm import (
    RTDSMAPIClient,
    RTDSMDatasetManager,
    RTDSMReleaseManager,
    RTDSMSeriesManager,
    RTDSMObservationManager,
    RTDSM_SOURCE,
    RTDSM_SOURCE_ADAPTER,
)


def _make(tmp_path, **kwargs):
    dataset_id = kwargs.pop("dataset_id")
    series_key = RTDSM_SOURCE_ADAPTER.normalize_series_key(
        dataset_id, kwargs.pop("series_key", None)
    )
    return RTDSM_SOURCE_ADAPTER.create_update_manager(
        dataset_id=dataset_id,
        series_key=series_key,
        db_path=str(tmp_path / "rtdsm.db"),
        cache_settings={"caching": False},
        **kwargs,
    )


def test_initialization(tmp_path):
    """
    The adapter resolves the series and the manager wires the
    component managers.
    """
    um = _make(tmp_path, dataset_id="routput", series_key={"frequency": "Q"})

    assert um.dataset_id == "ROUTPUT"
    assert um.data_freq == "Q"
    assert um.vintage_freq == "Q"
    assert um.filename == "routputqvqd.xlsx"
    assert um.state.dataset_id == "ROUTPUT"
    assert um.state.source == RTDSM_SOURCE
    assert um.state.series_key == {"frequency": "Q"}

    assert isinstance(um.api_client, RTDSMAPIClient)
    assert isinstance(um.dataset_manager, RTDSMDatasetManager)
    assert isinstance(um.release_manager, RTDSMReleaseManager)
    assert isinstance(um.series_manager, RTDSMSeriesManager)
    assert isinstance(um.observation_manager, RTDSMObservationManager)


def test_monthly_vintage_selection(tmp_path):
    """A monthly vintage request maps to the MvQd file."""
    um = _make(tmp_path, dataset_id="RCON", series_key={"frequency": "M"})
    assert um.vintage_freq == "M"
    assert um.filename == "rconmvqd.xlsx"


def test_default_frequency_single_option(tmp_path):
    """A series with one vintage frequency needs no explicit key."""
    um = _make(tmp_path, dataset_id="EMPLOY")
    assert um.vintage_freq == "M"
    assert um.filename == "employmvmd.xlsx"


def test_default_frequency_prefers_quarterly(tmp_path):
    """A dual-frequency series defaults to quarterly vintages."""
    um = _make(tmp_path, dataset_id="ROUTPUT")
    assert um.vintage_freq == "Q"


def test_excel_dir_forwarded_to_client(tmp_path):
    um = _make(tmp_path, dataset_id="ROUTPUT", excel_dir=str(tmp_path / "xl"))
    assert um.api_client.excel_dir == str(tmp_path / "xl")


def test_unknown_series_raises_at_construction(tmp_path):
    """
    An unknown dataset_id fails fast at construction (the catalog is bundled),
    rather than deferring the error to fetch time.
    """
    with pytest.raises(ValueError, match="Unknown RTDSM series"):
        _make(tmp_path, dataset_id="NOTASERIES")


def test_unavailable_frequency_raises():
    with pytest.raises(ValueError, match="does not offer M-frequency"):
        RTDSM_SOURCE_ADAPTER.normalize_series_key("DIV", {"frequency": "M"})
