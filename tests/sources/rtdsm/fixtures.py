import io

import openpyxl
import pytest
from datetime import datetime, timezone
from peewee import SqliteDatabase

from macrotrace.models.db import (
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
)

from macrotrace.sources.base import UpdateState
from macrotrace.sources.rtdsm import RTDSMAPIClient, ParsedVintageFile

UTC = timezone.utc


def make_xlsx_bytes(header, data_rows):
    """
    Build an in-memory .xlsx with the given header row and data rows.

    Used to exercise the workbook parser without any network access.

    Args:
        header: The first row (DATE plus vintage labels).
        data_rows: The subsequent rows (observation label plus values).

    Returns:
        bytes: The serialized workbook.
    """
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(list(header))
    for row in data_rows:
        worksheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def api_client():
    """RTDSM API client for ROUTPUT with caching disabled (no cache file)."""
    return RTDSMAPIClient(
        dataset_id="ROUTPUT",
        filename="routputqvqd.xlsx",
        data_freq="Q",
        cache_settings={"caching": False},
    )


@pytest.fixture
def empty_state():
    """An empty UpdateState."""
    return UpdateState()


@pytest.fixture
def sample_parsed():
    """A small parsed vintage file: two quarterly vintages of quarterly data."""
    v1 = ("ROUTPUT65Q4", datetime(1965, 11, 15, tzinfo=UTC))
    v2 = ("ROUTPUT66Q1", datetime(1966, 2, 15, tzinfo=UTC))
    cells = {
        v1[0]: [
            (datetime(1947, 1, 1, tzinfo=UTC), 306.4),
            (datetime(1947, 4, 1, tzinfo=UTC), 309.0),
        ],
        v2[0]: [
            (datetime(1947, 1, 1, tzinfo=UTC), 306.4),
            (datetime(1947, 4, 1, tzinfo=UTC), 309.0),
            (datetime(1947, 7, 1, tzinfo=UTC), 310.0),
        ],
    }
    return ParsedVintageFile(vintages=[v1, v2], cells=cells)


# In-memory test database, recreated for each test.
db = SqliteDatabase(":memory:")


@pytest.fixture(scope="function", autouse=True)
def db_setup_and_teardown():
    models = [
        Dataset,
        DatasetDimension,
        Release,
        ReleaseDimension,
        Series,
        SeriesDimensionFilter,
        Observation,
    ]
    db.bind(models, bind_refs=False, bind_backrefs=False)
    db.connect(reuse_if_open=True)
    db.create_tables(models)

    yield

    db.drop_tables(models)
    db.close()
