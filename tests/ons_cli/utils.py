import pytest
from unittest.mock import MagicMock

from macrotrace.ons_cli.common import ONSExplorerClient, ONSExplorer


@pytest.fixture
def mock_session():
    """A mock requests session (no real HTTP calls)."""
    session = MagicMock()
    return session


@pytest.fixture
def explorer_client(mock_session):
    """ONSExplorerClient with caching disabled and a mock session injected."""
    client = ONSExplorerClient(use_cache=False)
    client.session = mock_session
    return client


@pytest.fixture
def explorer(explorer_client):
    """ONSExplorer built on top of the mock client."""
    return ONSExplorer(explorer_client)


SAMPLE_DATASETS = [
    {"id": "cpih01", "title": "CPIH", "description": "Consumer price inflation"},
    {"id": "gdp", "title": "GDP", "description": "Gross domestic product"},
    {
        "id": "ashe",
        "title": "ASHE",
        "description": "Annual Survey of Hours and Earnings",
    },
]

SAMPLE_EDITIONS = [
    {"edition": "time-series", "label": "Time Series"},
    {"edition": "2021", "label": "2021 Edition"},
]

SAMPLE_VERSIONS = [
    {"version": 3, "release_date": "2024-01-01T00:00:00Z", "id": "v3"},
    {"version": 2, "release_date": "2023-06-01T00:00:00Z", "id": "v2"},
    {"version": 1, "release_date": "2023-01-01T00:00:00Z", "id": "v1"},
]

SAMPLE_DIMENSIONS = [
    {
        "name": "aggregate",
        "id": "cpih1dim1A0",
        "label": "Aggregate",
        "links": {
            "code_list": {
                "id": "cpih1dim1A0",
                "href": "https://api.beta.ons.gov.uk/v1/code-lists/cpih1dim1A0/editions/time-series",
                "edition": "time-series",
            }
        },
    },
    {
        "name": "time",
        "id": "mmm-yy",
        "label": "Time",
        "links": {
            "code_list": {
                "id": "mmm-yy",
                "href": "https://api.beta.ons.gov.uk/v1/code-lists/mmm-yy/editions/one-off",
            }
        },
    },
]

SAMPLE_CODES = [
    {"code": "cpih1dim1A0", "label": "All items"},
    {"code": "cpih1dim1G10100", "label": "Food and non-alcoholic beverages"},
]

SAMPLE_CODE_LIST_EDITIONS = [
    {"edition": "time-series", "last_updated": "2024-03-01T00:00:00Z"},
    {"edition": "2021", "last_updated": "2022-01-01T00:00:00Z"},
]
