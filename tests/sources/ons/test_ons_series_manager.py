from macrotrace.sources.ons import ONSSeriesManager
from tests.sources.ons.fixtures import api_client


def test_initialization(api_client):
    """
    Test that the ONSSeriesManager initializes correctly with the provided API client.
    """
    sm = ONSSeriesManager(api_client)

    assert sm.api_client == api_client
