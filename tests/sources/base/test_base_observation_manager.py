import pytest

from macrotrace.sources.base import ObservationManager
from fixtures import api_client, empty_state


def test_initialization(api_client):
    """Test that ObservationManager initializes correctly with the given API client."""
    om = ObservationManager(api_client=api_client)
    assert om.api_client == api_client


def test_fetch_new_observations_not_implemented(api_client, empty_state):
    """Test that fetch_new_observations method returns a NotImplementedError."""
    om = ObservationManager(api_client=api_client)

    with pytest.raises(NotImplementedError):
        om.fetch_new_observations(state=empty_state)
