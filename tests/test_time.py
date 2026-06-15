from datetime import datetime, timedelta, timezone

import pytest
import pytz

from macrotrace._time import ensure_timezone

US_CENTRAL = pytz.timezone("America/Chicago")
LMT_OFFSET = timedelta(hours=-5, minutes=-50, seconds=-36)


def test_none_passes_through():
    assert ensure_timezone(None, US_CENTRAL) is None


def test_aware_input_is_converted():
    aware = datetime(2020, 1, 1, 12, 0, 0, tzinfo=pytz.utc)
    assert ensure_timezone(aware, US_CENTRAL) == aware.astimezone(US_CENTRAL)


def test_stdlib_timezone_localizes_naive():
    naive = datetime(2020, 1, 1, 12, 0, 0)
    assert ensure_timezone(naive, timezone.utc) == naive.replace(tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "naive_dt,expected_offset",
    [
        (datetime(2020, 1, 1), timedelta(hours=-6)),  # CST
        (datetime(2020, 7, 1), timedelta(hours=-5)),  # CDT
        (datetime(2020, 3, 8, 3, 0, 0), timedelta(hours=-5)),  # just after DST start
        (datetime(2020, 11, 1, 1, 30, 0), timedelta(hours=-6)),  # 2020 DST ends Nov 1
    ],
)
def test_pytz_zone_localizes_to_real_offset(naive_dt, expected_offset):
    """Naive datetimes must land on real CST/CDT, never pytz's LMT entry."""
    converted = ensure_timezone(naive_dt, US_CENTRAL)
    assert converted == US_CENTRAL.localize(naive_dt)
    assert converted.utcoffset() != LMT_OFFSET
    assert converted.utcoffset() == expected_offset
