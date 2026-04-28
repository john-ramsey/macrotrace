"""Macrotrace top-level package exports."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

try:
    __version__ = version("macrotrace")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = [
    "MTTimeSeries",
    "MTObservation",
    "MTSeriesMetadata",
    "MTTimeSeriesPlotter",
    "VintageComparison",
    "__version__",
]

_LAZY_IMPORTS = {
    "MTTimeSeries": ("macrotrace.models.mt.time_series", "MTTimeSeries"),
    "MTObservation": ("macrotrace.models.mt.observation", "MTObservation"),
    "MTSeriesMetadata": ("macrotrace.models.mt.series_metadata", "MTSeriesMetadata"),
    "MTTimeSeriesPlotter": ("macrotrace.models.mt.plotter", "MTTimeSeriesPlotter"),
    "VintageComparison": ("macrotrace.models.mt.analysis", "VintageComparison"),
}


def __getattr__(name: str) -> Any:
    """Lazily expose heavy model imports at package level."""
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'macrotrace' has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    return getattr(import_module(module_name), attr)
