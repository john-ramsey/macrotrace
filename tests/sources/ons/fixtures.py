import pytest
from peewee import SqliteDatabase
import pytz

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
from macrotrace.sources.ons import ONSAPIClient


@pytest.fixture
def api_client():
    """Shared ONS API client fixture for tests."""
    return ONSAPIClient()


@pytest.fixture
def empty_state():
    """Fixture representing an empty UpdateState."""
    return UpdateState()


# Create a test database (in-memory)
db = SqliteDatabase(":memory:")
UTC = pytz.timezone("UTC")


# Note that importing db_setup_and_teardown fixture within test .py files sets up and tears down the database for each test automatically
@pytest.fixture(scope="function", autouse=True)
def db_setup_and_teardown():
    # Bind models to test DB
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
