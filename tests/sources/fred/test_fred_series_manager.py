import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from macrotrace.sources.fred import FredSeriesManager

# Note that importing db_setup_and_teardown fixture sets up and tears down the database for each test automatically
from tests.sources.fred.fixtures import (
    api_client,
    empty_state,
    db_setup_and_teardown,
    US_CENTRAL,
)


def test_initialization(api_client):
    """Test that the FredSeriesManager initializes correctly."""
    dm = FredSeriesManager(api_client=api_client)
    assert dm.api_client == api_client


def test_fetch_series_dimension_selection(api_client, empty_state):
    """Test that the fetch_series_dimension_selection always returns an empty list"""
    dm = FredSeriesManager(api_client=api_client)
    selection = dm.fetch_series_dimension_selection(state=empty_state)
    assert selection == []
