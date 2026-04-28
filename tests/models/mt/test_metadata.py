import logging

import pytest
from datetime import timedelta, date

from macrotrace.models.mt.series_metadata import MTSeriesMetadata


@pytest.fixture
def make_metadata():
    today = date.today()
    metadata = MTSeriesMetadata(
        dataset_id="TEST",
        source="FRED",
        title="Gross TEST Product",
        units="Billions of Dollars",
        realtime_start=today - timedelta(days=365),
        realtime_end=today,
        observation_start=today - timedelta(days=365 * 10),
        observation_end=today,
        frequency="D",
        seasonal_adjustment="Seasonally Adjusted Annual Rate",
        series_key={"test_key": "test_value"},
    )
    return metadata


def test_repr_metadata(make_metadata):
    today = date.today()
    metadata = make_metadata
    output = repr(metadata)
    assert "Dataset ID: TEST" in output
    assert "Title: Gross TEST Product" in output
    assert "Source: FRED" in output
    assert "Units: Billions of Dollars" in output
    assert "Frequency: D" in output
    assert f"Realtime Range: {today - timedelta(days=365)} to {today}" in output
    assert f"Observation Range: {today - timedelta(days=365 * 10)} to {today}" in output
    assert "Seasonal Adjustment: Seasonally Adjusted Annual Rate" in output
    assert "Series Key: " in output


def _make_metadata_with_frequency(freq: str) -> MTSeriesMetadata:
    today = date.today()
    return MTSeriesMetadata(
        dataset_id="TEST",
        source="FRED",
        title="Gross TEST Product",
        units="Billions of Dollars",
        realtime_start=today - timedelta(days=365),
        realtime_end=today,
        observation_start=today - timedelta(days=365 * 10),
        observation_end=today,
        frequency=freq,
        seasonal_adjustment="Seasonally Adjusted Annual Rate",
        series_key={},
    )


@pytest.mark.parametrize(
    ("frequency", "expected"),
    [
        ("D", 366),  # 2000 is a leap year
        ("MS", 12),
        ("QS", 4),
        ("B", 260),
    ],
)
def test_get_frequency_as_numeric_common_frequencies(frequency, expected):
    """Returns the number of pandas-generated periods per year for common frequencies."""
    metadata = _make_metadata_with_frequency(frequency)
    assert metadata.get_frequency_as_numeric() == expected


def test_get_frequency_as_numeric_annual_returns_one(caplog):
    """Annual ('YS') frequency yields a single period and returns 1, with a warning logged."""
    metadata = _make_metadata_with_frequency("YS")
    with caplog.at_level(logging.WARNING):
        result = metadata.get_frequency_as_numeric()
    assert result == 1
    assert any(
        "YS" in rec.message and "1 time" in rec.message for rec in caplog.records
    )


def test_get_frequency_as_numeric_logs_info_for_multi_period(caplog):
    """A multi-period frequency logs an info message reporting the resolved count."""
    metadata = _make_metadata_with_frequency("MS")
    with caplog.at_level(logging.INFO):
        result = metadata.get_frequency_as_numeric()
    assert result == 12
    assert any("MS" in rec.message and "12" in rec.message for rec in caplog.records)


def test_get_frequency_as_numeric_invalid_frequency_raises():
    """An unrecognized frequency string propagates pandas's ValueError."""
    metadata = _make_metadata_with_frequency("not-a-freq")
    with pytest.raises(ValueError):
        metadata.get_frequency_as_numeric()
