"""Template for adding a new data source to Macrotrace.

This module is **not** a working data source — every method raises
`NotImplementedError`. It exists as a starting point for contributors
who want to integrate a new provider (e.g. Eurostat, OECD, BEA).

To add a new source, copy this file to `macrotrace/sources/<name>.py`
and subclass the manager classes below, overriding the methods that
need provider-specific logic. See `macrotrace/sources/fred.py` and
`macrotrace/sources/ons.py` for complete reference implementations.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

from macrotrace.models.db import (
    DatasetDimension,
    Release,
    Observation,
)
from macrotrace.sources.base import (
    UpdateState,
    UpdateManager,
    APIClient,
    DatasetManager,
    ReleaseManager,
    SeriesManager,
    ObservationManager,
)

EXAMPLE_SOURCE_NAME = "Example"
BASE_URL = "https://api.example.com/"


class ExampleAPIClient(APIClient):
    def __init__(self, base_url: str, caching: bool = True, cache_expiry: int = 86400):
        super().__init__(base_url, caching, cache_expiry)

    def _get_request_headers(self) -> Dict[str, Any]:
        """
        Get the request details for the API client.
        This method must be overridden by subclasses to provide specific details.

        Returns:
            Dict[str, Any]: A dictionary containing request headers.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def _get_default_params(self) -> Dict[str, str]:
        """
        Get the default parameters for the API client. For instance, API keys or file types.
        This method must be overridden by subclasses to provide specific parameters.

        Returns:
            Dict[str, str]: A dictionary containing default parameters.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class ExampleDatasetManager(DatasetManager):
    def __init__(self, api_client: APIClient):
        super().__init__(api_client)

    def fetch_new_dataset_dimensions(
        self, state: UpdateState
    ) -> List[DatasetDimension]:
        """
        Fetch new dataset dimensions from the data source.
        This method must be overridden by subclasses to provide a specific implementation.

        Args:
            state (UpdateState): The update state containing dataset information.
        Returns:
            List[DatasetDimension]: A list of new dataset dimensions.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class ExampleReleaseManager(ReleaseManager):
    def __init__(self, api_client: APIClient):
        super().__init__(api_client)

    def fetch_new_releases(self, state: UpdateState) -> List[Release]:
        """
        Fetch new releases from the data source.
        This method must be overridden by subclasses to provide a specific implementation.

        Args:
            state (UpdateState): The update state containing dataset and release date range.

        Returns:
            List[Release]: A list of new releases.
        """
        raise NotImplementedError("Subclasses must implement this method.")

    def fetch_new_release_dimensions(
        self, state: UpdateState
    ) -> List[DatasetDimension]:
        """
        Fetch new release dimensions from the data source.
        This method must be overridden by subclasses to provide a specific implementation.

        Args:
            state (UpdateState): The update state containing dataset information.
        Returns:
            List[DatasetDimension]: A list of new release dimensions.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class ExampleSeriesManager(SeriesManager):
    def __init__(self, api_client: APIClient):
        super().__init__(api_client)


class ExampleObservationManager(ObservationManager):
    def __init__(self, api_client: APIClient):
        super().__init__(api_client)

    def fetch_new_observations(self, state: UpdateState) -> List[Observation]:
        """
        Fetch new observations from the data source for the given series and releases.
        This method must be overridden by subclasses to provide a specific implementation.

        Args:
            new_releases (List[Release]): A list of new releases for which to fetch observations.
            state (UpdateState): The update state containing the series.
        Returns:
            List[Observation]: A list of new observations.
        """
        raise NotImplementedError("Subclasses must implement this method.")


class ExampleUpdateManager(UpdateManager):
    def __init__(
        self,
        dataset_id: str,
        series_key: Optional[Dict] = None,
        release_start_date: Optional[datetime] = None,
        release_end_date: Optional[datetime] = None,
        db_path: Optional[str] = None,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ):
        """
        Initialize the ExampleUpdateManager.

        Args:
            dataset_id (str): The dataset identifier.
            series_key (Optional[Dict], optional): The series key. Defaults to None.
            release_start_date (Optional[datetime], optional): The start date for releases. Defaults to None.
            release_end_date (Optional[datetime], optional): The end date for releases. Defaults to None.
            db_path (Optional[str], optional): The database path. Defaults to None.
            cache_settings (Optional[Dict[str, Any]], optional): Cache settings. Defaults to None which uses default settings {"caching": True, "cache_expiry": 86400}.
            cache_path (Optional[str], optional): Path to the request-cache SQLite file. Defaults to None.
        """
        super().__init__(
            dataset_id=dataset_id,
            source=EXAMPLE_SOURCE_NAME,
            series_key=series_key,
            release_start_date=release_start_date,
            release_end_date=release_end_date,
            db_path=db_path,
            cache_settings=cache_settings,
            cache_path=cache_path,
        )

    def _create_api_client(
        self,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ) -> APIClient:
        """Override this to provide a specific API client."""
        raise NotImplementedError("Subclasses must implement this method.")

    def _create_dataset_manager(self) -> DatasetManager:
        """Override this to provide a specific dataset manager."""
        raise NotImplementedError("Subclasses must implement this method.")

    def _create_release_manager(self) -> ReleaseManager:
        """Override this to provide a specific release manager."""
        raise NotImplementedError("Subclasses must implement this method.")

    def _create_series_manager(self) -> SeriesManager:
        """Override this to provide a specific series manager."""
        raise NotImplementedError("Subclasses must implement this method.")

    def _create_observation_manager(self) -> ObservationManager:
        """Override this to provide a specific observation manager."""
        raise NotImplementedError("Subclasses must implement this method.")
