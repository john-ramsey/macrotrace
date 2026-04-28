from typing import Any, List, Dict, Optional, Tuple
from datetime import datetime, timezone
from math import floor
from dataclasses import dataclass
from importlib.metadata import version, PackageNotFoundError

import requests
import requests_cache
from peewee import fn, JOIN
from tqdm import tqdm
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

from macrotrace.models import (
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
)
from macrotrace._paths import resolve_cache_path, resolve_db_path
import logging

logger = logging.getLogger(__name__)

try:
    __version__ = version("macrotrace")
except PackageNotFoundError:
    # Package is not installed
    __version__ = "unknown"


USER_AGENT = f"Macrotrace/{__version__} (contact: john@johnramsey.com)"
UTC = timezone.utc


@dataclass
class UpdateState:
    """Shared state container for the update process."""

    dataset: Dataset | None = None
    dataset_id: str | None = None
    source: str | None = None
    dataset_mode: str | None = None

    series: Series | None = None
    series_mode: str | None = None
    series_key: Dict | None = None

    release_start_date: datetime | None = None
    release_end_date: datetime | None = None

    new_dataset_dimensions: List[DatasetDimension] | None = None
    new_series_dimension_filters: List[SeriesDimensionFilter] | None = None

    new_releases: List[Release] | None = None
    new_release_dimensions: List[ReleaseDimension] | None = None

    new_observations: List[Observation] | None = None


class APIClient:
    def __init__(
        self,
        base_url: str,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ):
        """
        Args:
            base_url (str): Base URL for the API
            cache_settings (Dict[str, Any], optional): Cache settings. Defaults to {"caching": True, "cache_expiry": 86400}.
            cache_path (str, optional): Path to the request-cache SQLite
                file. Resolution: this argument, then ``MACROTRACE_CACHE``,
                then beside ``MACROTRACE_DB`` if set, else
                ``MacroTraceRequestCache.sqlite`` in the current
                working directory.
        """
        self.user_agent = USER_AGENT
        self.base_url = base_url
        if cache_settings is None:
            cache_settings = {"caching": True, "cache_expiry": 86400}

        self.session = (
            requests.Session()
            if not cache_settings["caching"]
            else requests_cache.CachedSession(
                resolve_cache_path(cache_path),
                expire_after=cache_settings["cache_expiry"],
            )
        )
        logger.debug(
            f"Initialized APIClient with base_url={base_url}, caching={cache_settings['caching']}"
        )

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

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def make_request(
        self, endpoint: str, params: Dict[str, Any] = {}
    ) -> Dict[str, Any]:
        """
        Make a request to the API endpoint. Note that this method does not handle pagination.

        Args:
            endpoint (str): API endpoint path
            params (Dict[str, Any], optional): Additional parameters for the request. To be merged with default parameters. Defaults to {}.

        Returns:
            Dict[str, Any]: JSON response from the API
        """
        headers = self._get_request_headers()
        # Merge user agent into headers
        headers["User-Agent"] = self.user_agent

        default_params = self._get_default_params()
        params = default_params | params

        logger.debug(
            f"Making API request to endpoint: {endpoint} with params: {params}"
        )

        resp = self.session.get(
            self.base_url + endpoint, headers=headers, params=params
        )

        # Check if response came from cache
        is_cached = getattr(resp, "from_cache", False)
        logger.debug(
            f"API response received: status={resp.status_code}, "
            f"cached={is_cached}, size={len(resp.content)} bytes"
        )

        resp.raise_for_status()
        return resp.json()

    def make_paginated_request(
        self,
        endpoint: str,
        params: Dict[str, Any] = {},
        limit_param: str = "limit",
        offset_param: str = "offset",
        limit: int = 1000,
        items_key: Optional[str] = None,
        max_pages: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Make paginated requests to the API endpoint using limit/offset pagination.
        Automatically fetches all pages when the number of returned items equals the limit.

        Args:
            endpoint (str): API endpoint path
            params (Dict[str, Any], optional): Additional parameters for the request. Defaults to {}.
            limit_param (str, optional): The parameter name for the page size limit. Defaults to "limit".
            offset_param (str, optional): The parameter name for the offset. Defaults to "offset".
            limit (int, optional): The page size for each request. Defaults to 1000.
            items_key (Optional[str], optional): The key in the response containing the items list.
                If None, assumes the entire response is the items list. Defaults to None.
            max_pages (int, optional): Maximum number of pages to fetch as a safety limit. Defaults to 50.

        Returns:
            List[Dict[str, Any]]: A combined list of all items from all pages

        Raises:
            RuntimeError: If max_pages is reached before pagination completes naturally
        """
        all_items = []

        logger.debug(
            f"Starting paginated request to endpoint: {endpoint} "
            f"(limit={limit}, limit_param={limit_param}, offset_param={offset_param}, max_pages={max_pages})"
        )

        for page_num in range(max_pages):
            offset = page_num * limit
            paginated_params = params.copy()
            paginated_params[limit_param] = limit
            paginated_params[offset_param] = offset

            response = self.make_request(endpoint, paginated_params)

            if items_key:
                items = response.get(items_key, [])
            else:
                items = response if isinstance(response, list) else []

            items_count = len(items)
            all_items.extend(items)

            logger.debug(
                f"Fetched {items_count} items at offset {offset} (page {page_num + 1}/{max_pages}) "
                f"(total accumulated: {len(all_items)})"
            )

            if items_count < limit:
                logger.debug(
                    f"Pagination complete: received {items_count} < {limit}, "
                    f"total items: {len(all_items)} across {page_num + 1} page(s)"
                )
                break
        else:
            logger.error(
                f"Reached maximum page limit ({max_pages}) for endpoint {endpoint}. "
                f"Fetched {len(all_items)} items. This may indicate an API issue."
            )
            raise RuntimeError(
                f"Pagination limit reached: max_pages={max_pages}. "
                f"Fetched {len(all_items)} items. This may indicate an API issue."
            )

        logger.info(
            f"Completed paginated request to {endpoint}: {len(all_items)} total items across {page_num + 1} page(s)"
        )
        return all_items

    def make_request_dry_run(
        self, endpoint: str, params: Dict[str, Any] = {}
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Generate the request URL and parameters without making the actual request.
        Useful for debugging or logging purposes.

        Args:
            endpoint (str): API endpoint path
            params (Dict[str, Any], optional): Additional parameters for the request. To be merged with default parameters. Defaults to {}.
        Returns:
            Tuple[str, Dict[str, Any]]: The full request URL and the parameters.
        """
        default_params = self._get_default_params()
        merged_params = default_params | params
        prepared = self.session.prepare_request(
            requests.Request(
                method="GET",
                url=self.base_url + endpoint,
                params=merged_params,
            )
        )
        return prepared.url, merged_params


class DatasetManager:
    def __init__(self, api_client: APIClient):
        self.api_client = api_client

    def fetch_or_create_dataset_definition(self, state: UpdateState) -> Dataset:
        """
        Fetch dataset definition from the data source. If the dataset does not exist locally, it is created.
        This method may be overridden by subclasses to provide specific implementation if needed.
        NOTE: This method needs to write to the database if the dataset does not exist.

        Args:
            state (UpdateState): The update state containing dataset_id and source.

        Returns:
            Dataset: The dataset definition.
        """
        dataset = (
            Dataset.select()
            .where(
                (Dataset.dataset_id == state.dataset_id)
                & (Dataset.source == state.source)
            )
            .first()
        )

        if not dataset:
            logger.info(
                f"Creating new dataset: dataset_id={state.dataset_id}, source={state.source}"
            )
            dataset = Dataset.create(dataset_id=state.dataset_id, source=state.source)
        else:
            logger.debug(
                f"Found existing dataset: dataset_id={state.dataset_id}, id={dataset.id}"
            )

        return dataset

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

    def _get_all_local_dataset_dimensions(
        self, dataset_pk: int
    ) -> List[DatasetDimension]:
        """
        A helper function to retrieve all local DatasetDimensions for the given Dataset.

        Args:
            dataset_pk: The primary key of the dataset.
        Returns:
            List[DatasetDimension]: A list of local dataset dimensions.
        """
        return list(
            DatasetDimension.select().where(DatasetDimension.dataset == dataset_pk)
        )

    def _get_latest_local_dataset_dimension(
        self, dataset_pk: int, dataset_dimension_id: str
    ):
        """
        Retrieve the latest local dataset dimension for the given dataset PK and dimension ID.

        Args:
            dataset_pk (int): The primary key of the dataset.
            dataset_dimension_id (str): The ID of the dataset dimension.
        Returns:
            DatasetDimension: The latest DatasetDimension object.
        """
        return (
            DatasetDimension.select()
            .where(
                (DatasetDimension.dataset == dataset_pk)
                & (DatasetDimension.dataset_dimension_id == dataset_dimension_id)
            )
            .order_by(DatasetDimension.valid_from.desc())
            .first()
        )

    def _get_latest_valid_from(self, dataset_pk: int):
        """
        Get the latest valid_from date for the given dataset PK.
        This is defined as the maximum valid_from date among all non-time dimensions OR the default date of 1800-01-01 if no dimensions exist.

        Args:
            dataset_pk (int): The primary key of the dataset.
        Returns:
            datetime: The latest valid_from date.
        """
        all_dims = self._get_all_local_dataset_dimensions(dataset_pk)
        if all_dims:
            latest_valid_from = max(all_dims, key=lambda d: d.valid_from).valid_from
            logger.debug(
                f"Latest valid_from for dataset {dataset_pk}: {latest_valid_from} "
                f"({len(all_dims)} dimensions found)"
            )
        else:
            latest_valid_from = datetime(1800, 1, 1, tzinfo=UTC)
            logger.debug(
                f"No dimensions found for dataset {dataset_pk}, using default date {latest_valid_from}"
            )
        return latest_valid_from


class ReleaseManager:
    def __init__(self, api_client: APIClient):
        self.api_client = api_client

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

    def _get_current_releases_in_db(self, dataset_pk: int) -> List[datetime]:
        """
        Retrieve all current release dates from the database for the series ID.
        This method queries the Release table and retrieves all release dates associated with the dataset ID.

        Returns:
            List[datetime]: A list of release dates associated with the dataset ID.
        """
        return [
            v.release_date
            for v in Release.select().where(Release.dataset == dataset_pk)
        ]

    def _get_latest_local_release_date(self, dataset_pk: int) -> Optional[datetime]:
        """
        Get the latest local release date for the given dataset PK.
        If no release dates are found, returns datetime(1800, 1, 1, tzinfo=UTC).

        Args:
            dataset_pk (int): The primary key of the dataset.

        Returns:
            datetime: The latest local vintage date or datetime(1800, 1, 1, tzinfo=UTC) if no vintage date is found.
        """
        latest_vintage = (
            Release.select(fn.MAX(Release.release_date))
            .where(Release.dataset == dataset_pk)
            .scalar()
        )
        result = latest_vintage if latest_vintage else datetime(1800, 1, 1, tzinfo=UTC)
        logger.debug(f"Latest local release date for dataset {dataset_pk}: {result}")
        return result

    def _get_api_start_date(
        self, dataset_pk: int, release_start_date: Optional[datetime] = None
    ) -> datetime:
        """
        Calculate the appropriate start date for API queries that accept date range parameters.

        When release_start_date is None, fetches all available data from the beginning.
        When release_start_date is specified, uses it as a constraint.
        The _is_new_release check prevents duplicate entries.

        Examples:
        - Have no data, request None: fetches from 1800 (gets all available data)
        - Have no data, request 2020: fetches from 2020 (constrained initial load)
        - Have data from 2020+, request None: fetches from 1800 (backfills start-2020, skips existing 2020+)
        - Have data from 2020+, request 2010: fetches from 2010 (backfills 2010-2020)

        **When to use this method:**
        - Your data source API accepts date range parameters (e.g., FRED's realtime_start)
        - The API only returns data within the specified range
        - You need to adjust the API call to enable backfilling

        **When NOT to use this method:**
        - Your API returns all releases and you filter client-side (e.g., ONS)
        - In this case, use _is_wanted_release() to filter after fetching

        Args:
            dataset_pk (int): The primary key of the dataset.
            release_start_date (Optional[datetime]): The requested start date, if any.

        Returns:
            datetime: The start date to use in API calls.
        """
        api_start_date = datetime(1800, 1, 1, tzinfo=UTC)

        # No constraint - fetch all available data from the beginning

        # In cases where we have loaded some but not all prior data, this enables backfilling.
        # We don't need to worry about duplicates, _is_new_release will prevent duplicates.
        # If we do not return the earliest possible date here, we may miss data across multiple user loads.
        if not release_start_date:
            logger.debug(
                f"No release_start_date specified, using default start date: {api_start_date}"
            )
        # If user specifies a start date, use it (constrained fetch)
        # Otherwise use earliest possible date to get all available data (no filter)
        else:
            latest_release_date = self._get_latest_local_release_date(dataset_pk)
            api_start_date = min(release_start_date, latest_release_date)
            logger.debug(
                f"Calculated API start date: {api_start_date} "
                f"(requested: {release_start_date}, latest local: {latest_release_date})"
            )

        return api_start_date

    def _get_all_local_dataset_dimensions(
        self, dataset_pk: int
    ) -> List[DatasetDimension]:
        """
        A helper function to retrieve all local DatasetDimensions for the given Dataset.

        Args:
            dataset_pk: The primary key of the dataset.
        Returns:
            List[DatasetDimension]: A list of local dataset dimensions.
        """
        return list(
            DatasetDimension.select().where(DatasetDimension.dataset == dataset_pk)
        )

    def _is_new_release(
        self, release_date: datetime, current_release_dates_in_db: List[datetime]
    ) -> bool:
        """
        Check if a given release date is new (i.e., not already present in the database)
        And is within the specified release date range.

        Args:
            release_date (datetime): The release date to check.
            current_release_dates_in_db (List[datetime]): A list of current release dates in the database.

        Returns:
            bool: True if the release date is new and within the specified range, False otherwise.
        """
        if release_date in current_release_dates_in_db:
            logger.debug(
                f"Release date {release_date} already exists in database, skipping"
            )
            return False
        return True

    def _is_wanted_release(
        self,
        release_date: datetime,
        release_start_date: Optional[datetime] = None,
        release_end_date: Optional[datetime] = None,
    ) -> bool:
        """
        Check if a given release date is within the specified release date range.

        Args:
            release_date (datetime): The release date to check.
            release_start_date (Optional[datetime]): The start date for filtering releases.
            release_end_date (Optional[datetime]): The end date for filtering releases.
        Returns:
            bool: True if the release date is within the specified range, False otherwise.
        """
        if release_start_date and release_date < release_start_date:
            logger.debug(
                f"Release date {release_date} before start date {release_start_date}, filtering out"
            )
            return False

        if release_end_date and release_date > release_end_date:
            logger.debug(
                f"Release date {release_date} after end date {release_end_date}, filtering out"
            )
            return False

        return True


class SeriesManager:
    def __init__(self, api_client: APIClient):
        self.api_client = api_client

    def fetch_or_create_series_definition(self, state: UpdateState) -> Series:
        """
        Fetch the series definition from the data source.
        Since a series is a particular slice of the dataset, it is not mutable and only one version exists.
        NOTE: This method needs to write to the database if the series does not exist.

        This method may be overridden by subclasses to provide a specific implementation.

        Args:
            state (UpdateState): The update state containing dataset and series_key.

        Returns:
            Series: The series definition.
        """
        series = (
            Series.select()
            .where(Series.dataset == state.dataset)
            .where(Series.series_key == state.series_key)
            .first()
        )

        if not series:
            logger.info(
                f"Creating new series for dataset {state.dataset.id} with key: {state.series_key}"
            )
            series = Series.create(
                dataset=state.dataset,
                series_key=state.series_key if state.series_key else {},
            )
        else:
            logger.debug(
                f"Found existing series: id={series.id}, key={state.series_key}"
            )

        return series

    def fetch_new_series_dimension_filters(
        self, state: UpdateState
    ) -> List[SeriesDimensionFilter]:
        """
        Fetch series dimension filters from the data source.
        This method may overridden by subclasses to provide a specific implementation (i.e in the case of ).

        Args:
            series (Series): The series for which to fetch dimension filters.
        Returns:
            List[SeriesDimensionFilter]: The series dimension filters.
        """
        if not state.series_key:
            logger.debug("No series_key provided, returning empty filters")
            return []

        current_filters = self._get_series_dimension_filters(state.series.id)

        filters_to_create = []
        for key, value in state.series_key.items():
            matched = False
            for f in current_filters:
                if f.dataset_dimension_id == key and f.value == value:
                    matched = True
                    break
            if not matched:
                current_dimension = DatasetDimension.get(
                    dataset_dimension_id=key, dataset=state.dataset
                )

                filters_to_create.append(
                    SeriesDimensionFilter(
                        series=state.series,
                        dimension=current_dimension,
                        value=value,
                    )
                )

        logger.debug(
            f"Found {len(filters_to_create)} new dimension filters to create "
            f"({len(current_filters)} existing)"
        )
        return filters_to_create

    def _get_series_dimension_filters(
        self, series_pk: int
    ) -> List[SeriesDimensionFilter]:
        """
        A helper function to retrieve all SeriesDimensionFilters for the given Series.

        Args:
            series_pk: The primary key of the series.
        Returns:
            List[SeriesDimensionFilter]: A list of series dimension filters.
        """
        current_filters = (
            SeriesDimensionFilter.select(
                SeriesDimensionFilter,
                DatasetDimension.dataset_dimension_id,
            )
            .join(
                DatasetDimension,
                JOIN.LEFT_OUTER,
                on=(SeriesDimensionFilter.dimension == DatasetDimension.id),
            )
            .where(SeriesDimensionFilter.series == series_pk)
            .objects()
        )
        return list(current_filters)


class ObservationManager:
    def __init__(self, api_client: APIClient):
        self.api_client = api_client

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


class UpdateManager:
    def __init__(
        self,
        dataset_id: str,
        source: str,
        series_key: Optional[Dict] = None,
        release_start_date: Optional[datetime] = None,
        release_end_date: Optional[datetime] = None,
        db_path: Optional[str] = None,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ):
        self.state = UpdateState(
            dataset_id=dataset_id,
            source=source,
            series_key=series_key,
            release_start_date=release_start_date,
            release_end_date=release_end_date,
        )

        # Ensure database is initialized before creating managers
        self.database = self._ensure_db_initialized(db_path)

        self.api_client = self._create_api_client(
            cache_settings=cache_settings, cache_path=cache_path
        )
        self.dataset_manager = self._create_dataset_manager()
        self.series_manager = self._create_series_manager()
        self.release_manager = self._create_release_manager()
        self.observation_manager = self._create_observation_manager()

    def _ensure_db_initialized(self, db_path: Optional[str] = None):
        """
        Check that the db exists and is initialized with all required tables.
        If tables don't exist, create them.

        Args:
            db_path (Optional[str]): Path to the database file. Resolution
                order: this argument, then the ``MACROTRACE_DB``
                environment variable, then ``MacroTrace.db`` in the
                current working directory.

        Returns:
            The initialized database instance.
        """
        from macrotrace.models import LOCAL_DATABASE

        db_path = resolve_db_path(db_path)

        logger.info(f"Initializing database at path: {db_path}")

        # Initialize database connection with the specified path
        LOCAL_DATABASE.init(db_path)

        # Create tables if they don't exist
        tables = [
            Dataset,
            DatasetDimension,
            Release,
            ReleaseDimension,
            Series,
            SeriesDimensionFilter,
            Observation,
        ]

        with LOCAL_DATABASE:
            LOCAL_DATABASE.create_tables(tables, safe=True)
            logger.debug(f"Ensured {len(tables)} tables exist in database")

        return LOCAL_DATABASE

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

    def update(self) -> UpdateState:
        """
        Orchestrate the update process for series definitions, vintages, and observations.

        Uses database transaction to ensure atomicity - if any step fails,
        all changes are rolled back to maintain database consistency.
        """
        logger.info(
            f"Starting update for dataset_id={self.state.dataset_id}, "
            f"source={self.state.source}, series_key={self.state.series_key}"
        )

        try:
            with self.database.atomic():
                # First we fetch or create the dataset and series definitions.
                logger.debug("Fetching/creating dataset definition")
                self.state.dataset = self.state.dataset_mode = (
                    self.dataset_manager.fetch_or_create_dataset_definition(self.state)
                )

                logger.debug("Fetching/creating series definition")
                self.state.series = self.state.series_mode = (
                    self.series_manager.fetch_or_create_series_definition(self.state)
                )

                logger.debug("Fetching new releases")
                self.state.new_releases = self.release_manager.fetch_new_releases(
                    self.state
                )
                if self.state.new_releases:
                    logger.debug(
                        f"Writing {len(self.state.new_releases)} new releases to database"
                    )
                    self._write_objects_to_db(self.state.new_releases)
                    # insert_many does not populate integer PKs on the in-memory
                    # objects, but downstream steps (release dimensions, observations)
                    # need release.id. Re-query to load the persisted rows.
                    self.state.new_releases = list(
                        Release.select().where(
                            (Release.dataset == self.state.dataset)
                            & (
                                Release.release_date.in_(
                                    [r.release_date for r in self.state.new_releases]
                                )
                            )
                        )
                    )
                else:
                    logger.debug("No new releases to write")

                logger.debug("Fetching new dataset dimensions")
                self.state.new_dataset_dimensions = (
                    self.dataset_manager.fetch_new_dataset_dimensions(self.state)
                )
                if self.state.new_dataset_dimensions:
                    logger.debug(
                        f"Writing {len(self.state.new_dataset_dimensions)} new dataset dimensions to database"
                    )
                    self._write_objects_to_db(self.state.new_dataset_dimensions)
                else:
                    logger.debug("No new dataset dimensions to write")

                logger.debug("Fetching new release dimensions")
                self.state.new_release_dimensions = (
                    self.release_manager.fetch_new_release_dimensions(self.state)
                )
                if self.state.new_release_dimensions:
                    logger.debug(
                        f"Writing {len(self.state.new_release_dimensions)} new release dimensions to database"
                    )
                    self._write_objects_to_db(self.state.new_release_dimensions)
                else:
                    logger.debug("No new release dimensions to write")

                logger.debug("Fetching new series dimension filters")
                self.state.new_series_dimension_filters = (
                    self.series_manager.fetch_new_series_dimension_filters(self.state)
                )
                if self.state.new_series_dimension_filters:
                    logger.debug(
                        f"Writing {len(self.state.new_series_dimension_filters)} new series dimension filters to database"
                    )
                    self._write_objects_to_db(self.state.new_series_dimension_filters)
                else:
                    logger.debug("No new series dimension filters to write")

                logger.debug("Fetching new observations")
                self.state.new_observations = (
                    self.observation_manager.fetch_new_observations(self.state)
                )
                if self.state.new_observations:
                    logger.debug(
                        f"Writing {len(self.state.new_observations)} new observations to database"
                    )
                    self._write_objects_to_db(self.state.new_observations)
                else:
                    logger.debug("No new observations to write")

                logger.info(
                    "Update process completed successfully, committing transaction"
                )
                return self.state

        except Exception as e:
            logger.error(
                f"Update failed for dataset_id={self.state.dataset_id}, "
                f"series_key={self.state.series_key}: {e}. DB changes have been rolled back.",
                exc_info=True,
            )
            raise

    def _write_objects_to_db(self, objs: List[Any]) -> None:
        """
        Dynamically batch write objects to the database in chunks to avoid SQLite variable limits.

        Args:
            objs (List[Any]): A list of model instances to be written to the database.
        """
        if not objs:
            logger.debug("No objects to write to database")
            return

        model_class = type(objs[0])
        data = [obj.__data__ for obj in objs]
        num_fields = len(data[0])
        max_sqlite_vars = 999  # SQLite limit
        chunk_size = max(1, floor(max_sqlite_vars / num_fields))
        num_batches = (len(data) + chunk_size - 1) // chunk_size

        logger.debug(
            f"Writing {len(objs)} {model_class.__name__} objects in {num_batches} batches "
            f"(chunk_size={chunk_size}, num_fields={num_fields})"
        )

        # Note: We don't wrap this in atomic() because update() already has a transaction
        # If called outside update(), the individual inserts will auto-commit
        for i in tqdm(
            range(0, len(data), chunk_size),
            desc=f"Writing {model_class.__name__} objects in batches",
            leave=False,
        ):
            batch = data[i : i + chunk_size]
            # We are inserting the batch of objects into the database.
            # Using `on_conflict_replace` to handle conflicts by replacing existing records. I.e. upserting.
            model_class.insert_many(batch).on_conflict_replace().execute()

        logger.info(
            f"Successfully wrote {len(objs)} {model_class.__name__} objects to database"
        )
