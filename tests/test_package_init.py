import importlib

import pytest

import macrotrace
from macrotrace.models.mt.analysis import VintageComparison
from macrotrace.models.mt.observation import MTObservation
from macrotrace.models.mt.plotter import MTTimeSeriesPlotter
from macrotrace.models.mt.series_metadata import MTSeriesMetadata
from macrotrace.models.mt.time_series import MTTimeSeries


def test_package_lazy_exports_resolve():
    """Lazy attributes on the top-level package resolve to the underlying classes."""
    assert macrotrace.MTTimeSeries is MTTimeSeries
    assert macrotrace.MTObservation is MTObservation
    assert macrotrace.MTSeriesMetadata is MTSeriesMetadata
    assert macrotrace.MTTimeSeriesPlotter is MTTimeSeriesPlotter
    assert macrotrace.VintageComparison is VintageComparison


def test_package_unknown_attribute_raises():
    """Accessing a missing top-level attribute raises AttributeError."""
    with pytest.raises(AttributeError):
        macrotrace.NotAThing  # noqa: B018


def test_package_version_exposed():
    """`macrotrace.__version__` is exposed at the package root."""
    assert isinstance(macrotrace.__version__, str)
    assert macrotrace.__version__  # non-empty


def test_package_reload_keeps_lazy_protocol():
    """Reloading the package preserves the lazy-import contract."""
    importlib.reload(macrotrace)
    assert macrotrace.MTTimeSeries is not None


def test_sources_create_and_drop_tables_delegate():
    """`sources.create_tables` / `drop_tables` delegate to the bound database."""
    from unittest.mock import MagicMock

    from macrotrace.sources import create_tables, drop_tables

    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)

    create_tables(db, ["table-a"])
    drop_tables(db, ["table-b"])

    db.create_tables.assert_called_once_with(["table-a"])
    db.drop_tables.assert_called_once_with(["table-b"])
