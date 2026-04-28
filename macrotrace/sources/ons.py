from typing import List, Dict, Any, Optional
from datetime import datetime
import pytz

from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    retry_if_exception,
)

from macrotrace.models.db import (
    Dataset,
    DatasetDimension,
    Release,
    ReleaseDimension,
    Series,
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

import logging

logger = logging.getLogger(__name__)

ONS_SOURCE = "ONS"
BASE_URL = "https://api.beta.ons.gov.uk/v1/"
UTC = pytz.timezone("UTC")

ONS_TO_PD_FREQUENCIES = {
    "calendar-years": "YS",
    # Ex. Some are 2050-51 while others are 2050.
    # ONS Question: How should this be interpreted?
    # Which years are financial and which are calendar?
    # Shouldn't we have a separate dim (str) which denotes a financial vs calendar year?
    "financial-and-calendar-years": None,  # Not supported, need clarity
    # Some of these are three months 'oct-dec-2026' (i.e. a quarter? Why not quarterly?)
    # While others are are an unclear number months 'Apr-Mar 2008' (is this one is also reversed?)
    # ONS Question: How should these be interpreted?
    # Is 'oct-dec-2026' the same as Q4, or does it end on December 1st?
    # 'Apr-Mar 2008' Does April - March 2008 mean April 2007 to March 2008? or April 2008 to March 2009? or March & April 2008 or something else?
    "mmm-mmm-yyyy": None,  # Not supported, need clarity
    "mmm-yy": "MS",
    # Ex, '2004-06'
    # ONS Question: How should these be interpreted? Is '2004-06' the same as 2004 until 2006 or 2004, 2005, and 2006?
    "two-year-intervals": None,
    # Examples include "2029", "2029-q4", and "2029-dec". There is inconsistent spacing, capitalization, and hyphenation
    # Its not easy to parse these into a single frequency.
    # ONS Question: Why aren't these separated. 2029 surely represents a year, right? '2029-q4' is a quarter, and '2029-dec' is a month?
    # If so, why are they all in the same dimension versus multiple different dimensions with clear frequencies and granularities?
    "years-quarters-months": None,  # Not supported, need clarity
    # ONS Question: Per the code list for 'yyyy-qq' it is possible to have a Q0 value. What does this represent?
    # Ex. '2010-q0'. There are 14 of these values in the list.
    "yyyy-qq": "QS",
    # Example: 2020-21
    # ONS Question: For 'yyyy-yy' is '2020-21' the same as 2020 to 2021 or 2020 and 2021?
    "yyyy-yy": None,  # Not supported, need clarity
}

ONS_TO_PARSING_FREQUENCIES = {
    "calendar-years": "%Y",
    "financial-and-calendar-years": None,  # Not supported, need clarity
    "mmm-mmm-yyyy": None,  # Not supported, need clarity
    "mmm-yy": "%b-%y",
    "two-year-intervals": None,  # Not supported, need clarity
    "years-quarters-months": None,  # Not supported, need clarity
    "yyyy-qq": "yyyy-qq",  # Custom parsing needed, python does not support this directly
    "yyyy-yy": None,  # Not supported, need clarity
}


"""
This module provides an example implementation of a data source integration.
To implement a new data source, subclass the classes defined below and override the necessary methods.
"""


def _retry_after_seconds(exc: BaseException) -> Optional[float]:
    """
    Return seconds to wait if the exception is a 429 with a Retry-After header.
    Handles Retry-After as delta-seconds.
    """
    resp = getattr(exc, "response", None)

    ra = resp.headers.get("Retry-After")
    if not ra:
        return None

    try:
        return float(ra)
    except Exception:
        return None


_fallback = wait_fixed(2)


def wait_retry_after_or_fallback(retry_state) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if exc:
        ra = _retry_after_seconds(exc)
        if ra is not None:
            return ra
    return _fallback(retry_state)


def is_429(exc: BaseException) -> bool:
    resp = getattr(exc, "response", None)
    return resp is not None and resp.status_code == 429


def year_quarter_to_ymd(s):
    '""Custom parsing for yyyy-qq format to ISO 8601 date string (yyyy-mm-dd)"""'
    parts = s.upper().split("-Q")
    dt = datetime(int(parts[0]), int(parts[1]) * 3 - 2, 1)
    return dt.isoformat()


class ONSAPIClient(APIClient):
    def __init__(
        self,
        base_url: str = BASE_URL,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ):
        logger.debug(f"Initializing ONSAPIClient with base_url={base_url}")
        super().__init__(
            base_url=base_url,
            cache_settings=cache_settings,
            cache_path=cache_path,
        )

    def _get_request_headers(self) -> Dict[str, Any]:
        """
        Get the request details for the API client.

        Returns:
            Dict[str, Any]: A dictionary containing request headers.
        """
        return {}

    def _get_default_params(self) -> Dict[str, str]:
        """
        Get the default parameters for the API client. For instance, API keys or file types.

        Returns:
            Dict[str, str]: A dictionary containing default parameters.
        """
        return {}

    # Add an additional retry layer to handle 429 responses
    # This is needed because ONS API rate limits are strict due to them not using API keys
    # The Retry-After header is respected if provided
    @retry(
        stop=stop_after_attempt(1),
        wait=wait_retry_after_or_fallback,
        retry=retry_if_exception(is_429),
        reraise=True,
    )
    def make_request(
        self, endpoint: str, params: Dict[str, Any] = {}
    ) -> Dict[str, Any]:
        # Call parent's make_request with retry logic for 429 responses
        return super().make_request(endpoint=endpoint, params=params)

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
        # Use parent's pagination logic, which will call our overridden make_request
        # (with retry logic for 429 responses)
        return super().make_paginated_request(
            endpoint=endpoint,
            params=params,
            limit_param=limit_param,
            offset_param=offset_param,
            limit=limit,
            items_key=items_key,
            max_pages=max_pages,
        )


class ONSDatasetManager(DatasetManager):
    def __init__(self, api_client: APIClient):
        super().__init__(api_client)

    def _describe_release_window(
        self,
        release_start_date: Optional[datetime],
        release_end_date: Optional[datetime],
    ) -> str:
        """Return a human-readable description of the requested release window."""
        fmt = "%Y-%m-%d"
        start = (
            release_start_date.astimezone(UTC).strftime(fmt)
            if release_start_date
            else None
        )
        end = (
            release_end_date.astimezone(UTC).strftime(fmt) if release_end_date else None
        )

        if start and end:
            return f"between {start} and {end}"
        if start:
            return f"on or after {start}"
        if end:
            return f"on or before {end}"
        return "for any available release date"

    def _series_is_timeseries(self, dataset_id) -> bool:
        """
        Returns whether the series is a time series.
        An ONS time series is identified by having an edition labeled "time-series".

        Args:
            dataset_id (str): The dataset ID of the series to check.
        """
        logger.debug(f"Checking if {dataset_id} is a time series")

        # I wish we could paginate this request but ONS API doesn't support it here
        # You can't pass through limit/offset params to this endpoint unfortunately
        editions = self.api_client.make_request(
            endpoint=f"datasets/{dataset_id}/editions"
        )
        editions = editions.get("items", [])
        time_series_editions = [i for i in editions if i["edition"] == "time-series"]
        is_ts = len(time_series_editions) == 1
        logger.debug(f"Dataset {dataset_id} is_timeseries={is_ts}")
        return is_ts

    def _fetch_dataset_definition(self, state: UpdateState) -> Dataset | None:
        """
        Fetch dataset definition from the data source.

        Args:
            dataset_id (str): The dataset ID to fetch.
        Returns:
            Dataset | None: The dataset definition, or None if not found.
        """
        dataset = (
            Dataset.select()
            .where(
                (Dataset.dataset_id == state.dataset_id)
                & (Dataset.source == state.source)
            )
            .first()
        )

        return dataset

    def fetch_or_create_dataset_definition(self, state: UpdateState) -> Dataset:
        """
        Fetch dataset definition from the data source. If the dataset does not exist locally, it is created.
        This method is overridden to provide a specific time-series check for ONS.

        Args:
            state (UpdateState): The update state containing dataset_id and source.

        Returns:
            Dataset: The dataset definition.
        """
        assert self._series_is_timeseries(
            state.dataset_id
        ), f"Dataset {state.dataset_id} is not a time series."

        dataset = self._fetch_dataset_definition(state)
        if not dataset:
            logger.info(
                f"Creating new ONS dataset: dataset_id={state.dataset_id}, source={state.source}"
            )
            dataset = Dataset.create(dataset_id=state.dataset_id, source=state.source)
        else:
            logger.debug(
                f"Found existing ONS dataset: dataset_id={state.dataset_id}, id={dataset.id}"
            )

        return dataset

    def _track_dimension_appearances_across_releases(
        self, state: UpdateState
    ) -> Dict[str, Dict[str, Any]]:
        """
        Track each dimension's appearances across releases.
        This is used to determine the valid_from and valid_to dates for each dimension.

        Args:
            state (UpdateState): The update state containing dataset information.
        Returns:
            Dict[str, Dict[str, Any]]: A dictionary mapping dimension names to their appearance info.
        """
        logger.debug(
            f"Tracking dimension appearances across {len(state.new_releases)} release(s)"
        )
        dimension_appearances = {}
        sorted_releases = sorted(state.new_releases, key=lambda r: r.release_date)

        for release in sorted_releases:
            dimensions_metadata = release.additional_metadata.get("dimensions", [])
            for dim_meta in dimensions_metadata:
                dataset_dimension_name = dim_meta["name"]
                # skip time dimension
                if dataset_dimension_name == "time":
                    continue
                # Initialize entry if not present
                if dataset_dimension_name not in dimension_appearances:
                    dimension_appearances[dataset_dimension_name] = {
                        "releases": [],
                        "metadata": dim_meta,
                    }
                # Record appearance of this dimension in the release
                dimension_appearances[dataset_dimension_name]["releases"].append(
                    release.release_date
                )

        logger.debug(
            f"Found {len(dimension_appearances)} unique dimension(s) across releases"
        )
        return dimension_appearances

    def _determine_dimension_validity_period(
        self, dimension_release_dates: List[datetime], latest_release_date: datetime
    ) -> tuple[datetime, Optional[datetime]]:
        """
        Determine the valid_from and valid_to dates for a dimension given the releases.
        Recall that valid_to is None if the dimension is still valid in the latest release.

        Args:
            dimension_release_dates (List[datetime]): List of release dates where the dimension appears.
            latest_release_date (datetime): The date of the latest release.

        Returns:
            tuple[datetime, Optional[datetime]]: A tuple containing valid_from and valid_to dates.
        """
        valid_from = dimension_release_dates[0]
        valid_to = (
            None
            if dimension_release_dates[-1] == latest_release_date
            else dimension_release_dates[-1]
        )
        return valid_from, valid_to

    def _construct_dataset_dimension(
        self,
        state: UpdateState,
        dimension_name: str,
        dim_meta: Dict,
        valid_from: datetime,
        valid_to: Optional[datetime],
    ) -> DatasetDimension:
        """
        Create a new dataset dimension object given the following data.

        Args:
            state (UpdateState): The update state containing dataset information.
            dimension_name (str): The name of the dimension.
            dim_meta (Dict): Metadata associated with the dimension.
            valid_from (datetime): The date from which the dimension is valid.
            valid_to (Optional[datetime]): The date until which the dimension is valid, or None if still valid.
        Returns:
            DatasetDimension: A new DatasetDimension object.
        """
        return DatasetDimension(
            dataset=state.dataset,
            dataset_dimension_id=dimension_name,
            title=dim_meta["name"],
            # Since all non-initial dimensions are categorical in ONS (they all have code lists),
            # we can safely assume they are 'text'
            type="text",
            valid_from=valid_from,
            valid_to=valid_to,
            frequency=None,  # Note that non-initial dimensions do not have frequencies
            description=None,
            units=None,
            seasonal_adjustment=None,
        )

    def _fetch_initial_dataset_dimension(
        self, state, first_release_date: datetime, freq: str
    ) -> DatasetDimension:
        """
        When initializing a dataset, we may need to create the initial dataset dimension.
        This dimension is not returned as metadata associated from the ONS API (as are the other dimensions)
        This is retrieved from the https://api.beta.ons.gov.uk/v1/datasets/{dataset_id} endpoint.

        Args:
            state (UpdateState): The update state containing dataset information.
            first_release_date (datetime): The date of the first release.
            freq (str): The frequency string for the dimension.

        Returns:
            DatasetDimension: The initial DatasetDimension object.
        """
        logger.debug(f"Fetching initial dimension for {state.dataset.dataset_id}")
        response = self.api_client.make_request(f"datasets/{state.dataset.dataset_id}")

        if not response:
            raise ValueError(
                f"No dataset metadata returned from ONS API for dataset {state.dataset.dataset_id}"
            )

        return DatasetDimension(
            dataset=state.dataset,
            dataset_dimension_id=state.dataset.dataset_id,
            title=response.get("title", state.dataset.dataset_id),
            type="numeric",
            frequency=freq,
            units=response.get("unit_of_measure"),
            description=response.get("description"),
            valid_from=first_release_date,
        )

    def _update_existing_dimension_validity_period(
        self,
        dimension: DatasetDimension,
        earliest_appearance: datetime,
        last_appearance: datetime,
        latest_release_date: datetime,
    ) -> None:
        """
        Update the valid_from and/or valid_to dates of an existing dimension.

        Updates valid_from if we found earlier releases than previously known.
        Updates valid_to if the dimension no longer appears in the latest release.

        Args:
            dimension (DatasetDimension): The dataset dimension to update.
            earliest_appearance (datetime): The earliest appearance date of the dimension.
            last_appearance (datetime): The last appearance date of the dimension.
            latest_release_date (datetime): The date of the latest release.

        Returns:
            None
        """
        updated = False
        updates = []

        # Update valid_from if we found earlier releases
        if earliest_appearance < dimension.valid_from:
            dimension.valid_from = earliest_appearance
            updated = True
            updates.append(f"valid_from={earliest_appearance}")

        # Update valid_to if dimension no longer appears in latest release
        if last_appearance < latest_release_date:
            dimension.valid_to = last_appearance
            updated = True
            updates.append(f"valid_to={last_appearance}")

        if updated:
            logger.debug(
                f"Updating dimension {dimension.dataset_dimension_id}: {', '.join(updates)}"
            )
            dimension.save()

    def _should_get_initial_dimension(
        self, current_dimensions: List[DatasetDimension], dataset_id: str
    ) -> bool:
        """
        Determine if we need to create the initial dataset dimension.
        The initial dimension has dataset_dimension_id == dataset_id.

        Args:
            current_dimensions (List[DatasetDimension]): A list of current dataset dimensions.
            dataset_id (str): The dataset ID to check for.

        Returns:
            bool: True if the initial dimension does NOT exist and needs to be created, False otherwise.
        """
        # Check if the initial dimension already exists
        initial_dim_exists = any(
            d.dataset_dimension_id == dataset_id for d in current_dimensions
        )

        # Return True if we SHOULD get it (i.e., it doesn't exist yet)
        return not initial_dim_exists

    def _get_freq_from_dim_metadata(self, dim_meta: Dict) -> str:
        """
        Get the pandas frequency string from dimension metadata.

        Args:
            dim_meta (Dict): The dimension metadata.
        Returns:
            str: The pandas frequency string.
        """
        dimensions = dim_meta["dimensions"]
        time_dim = next((d for d in dimensions if d["name"] == "time"), None)

        if not time_dim:
            raise ValueError("No time dimension found in dimension metadata.")
        time_dim_id = time_dim["id"]
        freq = ONS_TO_PD_FREQUENCIES.get(time_dim_id)
        if not freq:
            raise ValueError(f"Unknown ONS frequency: {time_dim_id}")

        return freq

    def fetch_new_dataset_dimensions(
        self, state: UpdateState
    ) -> List[DatasetDimension]:
        """
        Fetch new dataset dimensions from the data source.
        Since ONS dimensions are tied to releases, we check the dimensions
        for each new release and create any that do not exist locally.

        Args:
            state (UpdateState): The update state containing dataset information.
        Returns:
            List[DatasetDimension]: A list of new dataset dimensions.
        """
        logger.debug("Fetching ONS dataset dimensions")
        new_dimensions = []
        current_dims = self._get_all_local_dataset_dimensions(state.dataset.id)
        sorted_releases = sorted(state.new_releases, key=lambda r: r.release_date)
        should_get_initial_dimension = self._should_get_initial_dimension(
            current_dims, state.dataset.dataset_id
        )

        if not sorted_releases:
            if should_get_initial_dimension:
                requested_window = self._describe_release_window(
                    state.release_start_date,
                    state.release_end_date,
                )
                raise ValueError(
                    f"Cannot initialize ONS dataset {state.dataset.dataset_id}: "
                    f"no releases were found {requested_window}. "
                    f"At least one release is required to create the initial dataset dimension."
                )
            logger.debug(
                f"No new releases found for dataset {state.dataset.dataset_id}; "
                f"no dataset dimension updates required."
            )
            return new_dimensions

        first_release_date = sorted_releases[0].release_date
        latest_release_date = sorted_releases[-1].release_date
        dimension_appearances = self._track_dimension_appearances_across_releases(state)

        if should_get_initial_dimension:
            logger.debug("Creating initial dimension")
            first_release_metadata = sorted_releases[0].additional_metadata

            # Note that the frequency here is not the 'release_frequency' returned by the api in the _fetch_initial_dataset_dimension call
            # This is because the release_frequency can be different from the actual time dimension frequency
            first_release_freq = self._get_freq_from_dim_metadata(
                first_release_metadata
            )

            initial_dimension = self._fetch_initial_dataset_dimension(
                state, first_release_date, first_release_freq
            )
            new_dimensions.append(initial_dimension)
        else:
            logger.debug("Updating existing initial dimension if needed")
            # Initial dimension exists - update it if we found earlier releases
            initial_dim = next(
                (
                    d
                    for d in current_dims
                    if d.dataset_dimension_id == state.dataset.dataset_id
                ),
                None,
            )
            if not initial_dim:
                raise ValueError(
                    f"Initial dimension should exist but was not found for dataset {state.dataset.dataset_id}"
                )

            # If we found earlier releases, update valid_from on the initial dimension. Otherwise do nothing.
            # Note this only works at the moment since ONS code lists are not continuously changing / versioned
            if len(state.new_releases) > 0:
                earliest_release = first_release_date
                if earliest_release < initial_dim.valid_from:
                    logger.debug(
                        f"Updating initial dimension valid_from to {earliest_release}"
                    )
                    initial_dim.valid_from = earliest_release
                    initial_dim.save()

        # Dim appearances here are Dicts in the format:
        # {
        #   "dimension_name": {
        #       "releases": [list of release dates],
        #       "metadata": {dimension metadata from ONS}
        #   },
        # }
        for dataset_dimension_name, data in dimension_appearances.items():
            release_dates = data["releases"]
            dim_meta = data["metadata"]

            # Check if dimension already exists locally
            existing_dim = next(
                (
                    d
                    for d in current_dims
                    if d.dataset_dimension_id == dataset_dimension_name
                ),
                None,
            )

            if existing_dim:
                # Update validity period (both valid_from and valid_to if needed)
                self._update_existing_dimension_validity_period(
                    existing_dim,
                    earliest_appearance=release_dates[0],
                    last_appearance=release_dates[-1],
                    latest_release_date=latest_release_date,
                )
            else:
                logger.debug(f"Creating new dimension: {dataset_dimension_name}")
                valid_from, valid_to = self._determine_dimension_validity_period(
                    dimension_release_dates=release_dates,
                    latest_release_date=latest_release_date,
                )

                new_dim = self._construct_dataset_dimension(
                    state=state,
                    dimension_name=dataset_dimension_name,
                    dim_meta=dim_meta,
                    valid_from=valid_from,
                    valid_to=valid_to,
                )
                new_dimensions.append(new_dim)

        logger.info(f"Found {len(new_dimensions)} new dataset dimension(s) for ONS")
        return new_dimensions


class ONSReleaseManager(ReleaseManager):
    def __init__(self, api_client: APIClient):
        super().__init__(api_client)

    def _skip_release(
        self,
        release_date: datetime,
        state: UpdateState,
        current_release_dates: List[datetime],
    ) -> bool:
        """
        Determine whether to skip a release based on the state's release date range or if it already exists in the database.

        Args:
            release_date (datetime): The release date to check.
            state (UpdateState): The update state containing release date range.
            current_release_dates (List[datetime]): List of current release dates in the database.

        Returns:
            bool: True if the release should be skipped, False otherwise.
        """
        if state.release_start_date and release_date < state.release_start_date:
            return True
        if state.release_end_date and release_date > state.release_end_date:
            return True
        if self._release_exists_in_db(release_date, current_release_dates):
            return True
        return False

    def _construct_release(
        self,
        state: UpdateState,
        release_date: datetime,
        release_data: Dict[str, Any],
    ) -> Release:
        """
        Create a new release object given the following data.

        Args:
            state (UpdateState): The update state containing dataset information.
            release_date (datetime): The date of the release.
            release_data (Dict[str, Any]): Additional data for the release.

        Returns:
            Release: A new Release object.
        """
        return Release(
            dataset=state.dataset,
            release_date=release_date,
            additional_metadata={
                "version": release_data["version"],
                "id": release_data["id"],
                "dimensions": release_data["dimensions"],
            },
        )

    def _release_exists_in_db(
        self, release_date: datetime, current_release_dates: List[datetime]
    ) -> bool:
        """
        Check if a release with the given release date already exists in the database.

        Args:
            release_date (str): The release date string to check.
            current_releases (List[Release]): A list of current releases in the database.

        Returns:
            bool: True if the release exists, False otherwise.
        """

        for existing_release_date in current_release_dates:
            if existing_release_date == release_date:
                return True
        return False

    def fetch_new_releases(self, state: UpdateState) -> List[Release]:
        """
        Fetch new releases from the ONS API. We want to also ensure that the releases
        store the metadata about dimensions as we will need these later.

        Args:
            state (UpdateState): The update state containing dataset and release date range.

        Returns:
            List[Release]: A list of new releases.
        """
        logger.debug(f"Fetching ONS releases for {state.dataset.dataset_id}")
        versions = self.api_client.make_paginated_request(
            endpoint=f"datasets/{state.dataset.dataset_id}/editions/time-series/versions",
            items_key="items",
        )

        current_release_dates = self._get_current_releases_in_db(state.dataset.id)
        new_releases = []
        total_versions = len(versions)
        skipped_count = 0

        logger.debug(f"Processing {total_versions} ONS version(s)")

        # Each item here is a version with the following spec:
        # https://developer.ons.gov.uk/dataset/datasets-id-editions-edition-versions-version/
        for item in versions:
            release_date_str = item.get("release_date")
            if not release_date_str:
                logger.debug("Skipping version without release_date")
                skipped_count += 1
                continue
            else:
                release_date = datetime.fromisoformat(release_date_str).replace(
                    tzinfo=UTC
                )

            if self._skip_release(release_date, state, current_release_dates):
                skipped_count += 1
                continue

            release = self._construct_release(
                state=state,
                release_date=release_date,
                release_data=item,
            )
            new_releases.append(release)

        logger.info(
            f"Found {len(new_releases)} new ONS release(s) "
            f"(skipped {skipped_count}/{total_versions})"
        )
        return new_releases

    def _get_dimension_for_release(
        self,
        current_dataset_dimensions: List[DatasetDimension],
        dim_name: str,
        release_date: datetime,
    ) -> DatasetDimension:
        """
        Returns the appropriate DatasetDimension for the release given a name and the local DatasetDimensions

        Args:
            current_dataset_dimensions (List[DatasetDimension]): A list of current dataset dimensions.
            dim_name (str): The name of the dimension.
            release_date (datetime): The release date to check validity against.

        Returns:
            DatasetDimension: The corresponding DatasetDimension.
        """
        matching_dims = [
            d
            for d in current_dataset_dimensions
            if d.dataset_dimension_id == dim_name
            and d.valid_from <= release_date
            and (d.valid_to is None or d.valid_to >= release_date)
        ]
        if len(matching_dims) == 0:
            raise ValueError(
                f"No valid DatasetDimension found for dimension {dim_name} at release date {release_date}"
            )
        if len(matching_dims) > 1:
            raise ValueError(
                f"Multiple valid DatasetDimensions found for dimension {dim_name} at release date {release_date}"
            )
        return matching_dims[0]

    def _get_initial_dimension(
        self, current_dataset_dimensions: List[DatasetDimension]
    ) -> DatasetDimension:
        """
        Returns the initial DatasetDimension for the dataset.
        This is identified by having the same dataset_dimension_id as the dataset_id.

        Returns:
            DatasetDimension: The initial DatasetDimension.
        """
        initial_dimension = [
            d
            for d in current_dataset_dimensions
            if d.dataset_dimension_id == d.dataset.dataset_id
        ]

        if len(initial_dimension) == 0:
            raise ValueError("Initial dataset dimension not found.")
        elif len(initial_dimension) > 1:
            raise ValueError("Multiple initial dataset dimensions found.")

        return initial_dimension[0]

    def fetch_new_release_dimensions(
        self, state: UpdateState
    ) -> List[ReleaseDimension]:
        """
        Fetch new release dimensions from the ONS. Since these are tied to releases,
        we check the dimensions for each new release and create ReleaseDimension entries.

        Args:
            state (UpdateState): The update state containing dataset information.
        Returns:
            List[ReleaseDimension]: A list of new release dimensions.
        """
        logger.debug(
            f"Fetching ONS release dimensions for {len(state.new_releases)} release(s)"
        )
        current_dataset_dimensions = self._get_all_local_dataset_dimensions(
            state.dataset.id
        )

        initial_dim = self._get_initial_dimension(current_dataset_dimensions)

        new_release_dimensions = []
        for release in state.new_releases:
            release_dimensions = release.additional_metadata.get("dimensions", [])
            # Each new release also needs to be tied the initial dimension
            # NOTE: This logic only works right now because each ONS dataset only has
            # one dimension and dimensions are not versioned.
            new_release_dimensions.append(
                ReleaseDimension(release=release, dimension=initial_dim)
            )

            if len(release_dimensions) == 0:
                logger.warning(
                    f"Release {release} has no dimensions in metadata; skipping."
                )
                continue

            for dim in release_dimensions:
                if dim["name"] == "time":
                    continue
                # find the corresponding DatasetDimension
                dataset_dim = self._get_dimension_for_release(
                    current_dataset_dimensions,
                    dim_name=dim["name"],
                    release_date=release.release_date,
                )

                new_release_dimensions.append(
                    ReleaseDimension(release=release, dimension=dataset_dim)
                )

        logger.info(
            f"Created {len(new_release_dimensions)} ONS release-dimension association(s)"
        )
        return new_release_dimensions


class ONSSeriesManager(SeriesManager):
    def __init__(self, api_client: APIClient):
        super().__init__(api_client)


class ONSObservationManager(ObservationManager):
    def __init__(self, api_client: APIClient):
        super().__init__(api_client)

    def _validate_series_key_against_release(
        self, release: Release, series_key: Dict[str, Any]
    ) -> None:
        """
        Validate that the series key contains all required dimensions from the release.

        Args:
            release (Release): The release to validate against.
            series_key (Dict[str, Any]): The series key to validate.

        Raises:
            ValueError: If a required dimension is missing from the series key.
        """
        release_dims = release.additional_metadata["dimensions"]
        missing_dims = []
        for dim in release_dims:
            if dim["name"] == "time":
                continue
            if dim["name"] not in series_key:
                missing_dims.append(dim["name"])

        if missing_dims:
            logger.error(
                f"Series key validation failed: missing dimensions {missing_dims}"
            )
            raise ValueError(
                f"Series key is missing required dimension: {missing_dims[0]}."
            )

    def _build_observations_endpoint(self, state: UpdateState, release: Release) -> str:
        """
        Build the API endpoint for fetching observations for a specific release.

        Args:
            state (UpdateState): The update state containing dataset information.
            release (Release): The release to fetch observations for.

        Returns:
            str: The API endpoint.
        """
        version = release.additional_metadata["version"]
        dataset_id = state.dataset.dataset_id

        return f"datasets/{dataset_id}/editions/time-series/versions/{version}/observations"

    def _build_observations_params(self, state: UpdateState) -> Dict[str, Any]:
        """
        Build the query parameters for the observations API request.

        Args:
            state (UpdateState): The update state containing series key.

        Returns:
            Dict[str, Any]: The query parameters.
        """
        return {"time": "*"} | state.series_key

    def _parse_observation_timestamp(self, time_label: str, freq: str) -> datetime:
        """
        Parse the observation timestamp from the ONS time label.

        Args:
            time_label (str): The time label string (e.g., "Jan-23").
            freq (str): The frequency string to determine the parsing format.

        Returns:
            datetime: The parsed timestamp with UTC timezone.
        """
        strptime_format = ONS_TO_PARSING_FREQUENCIES[freq]
        if strptime_format == "yyyy-qq":
            # Custom parsing for yyyy-qq format
            iso_date_str = year_quarter_to_ymd(time_label)
            return datetime.fromisoformat(iso_date_str).replace(tzinfo=UTC)

        return datetime.strptime(time_label, strptime_format).replace(tzinfo=UTC)

    def _create_observation_from_response(
        self,
        observation_data: Dict[str, Any],
        series: Series,
        release: Release,
        freq: str,
    ) -> Observation:
        """
        Create an Observation object from API response data.

        Args:
            observation_data (Dict[str, Any]): The observation data from the API.
            series (Series): The series this observation belongs to.
            release (Release): The release this observation is from.
            freq (str): The frequency string to determine timestamp parsing.

        Returns:
            Observation: A new Observation object.
        """
        time_label = observation_data["dimensions"]["Time"]["label"]
        if time_label in ["On.-  ", "Se.- T"]:
            # ONS question: Why is this happening?
            return None  # ONS API quirk for missing time labels. This appears to be a null observation but is an issue
        dt = self._parse_observation_timestamp(time_label, freq)

        return Observation(
            series=series,
            observation_timestamp=dt,
            release=release,
            value=observation_data["observation"],
        )

    def _get_frequency_from_initial_dimension(self, release: Release) -> str:
        """
        Get the frequency string from the release's additional metadata.

        Args:
            release (Release): The release to get frequency from.

        Returns:
            str: The frequency string.
        """

        metadata = release.additional_metadata
        dimensions = metadata.get("dimensions", [])
        time_dim = next((d for d in dimensions if d["name"] == "time"), None)

        if not time_dim:
            raise ValueError("No time dimension found in release metadata.")
        freq = time_dim["id"]
        return freq

    def _fetch_observations_for_release(
        self, state: UpdateState, release: Release
    ) -> List[Observation]:
        """
        Fetch all observations for a single release.

        Args:
            state (UpdateState): The update state containing dataset and series information.
            release (Release): The release to fetch observations for.

        Returns:
            List[Observation]: A list of observations for the release.
        """
        logger.debug(f"Fetching observations for release {release.release_date}")
        self._validate_series_key_against_release(release, state.series_key)

        endpoint = self._build_observations_endpoint(state, release)
        params = self._build_observations_params(state)
        freq = self._get_frequency_from_initial_dimension(release)

        # ONS Question: This is not an endpoint we can paginate (passing through limit/offset produces an invalid request)
        # but the docs current state that "This is currently limited to 10,000 observations." Why?
        # https://developer.ons.gov.uk/cmdobservations/
        response = self.api_client.make_request(endpoint=endpoint, params=params)
        response_obs = response.get("observations")

        # This is broken out separately from the get above for the cases where the ONS API returns a None/null observations field
        # (Yes this happens, why it is not an empty list for schema enforcement is beyond me)
        if response_obs is None:
            logger.debug(f"No observations found in response for endpoint {endpoint}")
            return []

        observations = []
        for o in response_obs:
            observation = self._create_observation_from_response(
                o, state.series, release, freq
            )
            if observation:
                observations.append(observation)

        logger.debug(
            f"Retrieved {len(observations)} observation(s) for release {release.release_date}"
        )
        return observations

    def fetch_new_observations(self, state: UpdateState) -> List[Observation]:
        """
        Fetch new observations from the ONS API.

        Args:
            state (UpdateState): The update state containing the series and new releases.

        Returns:
            List[Observation]: A list of new observations.
        """
        logger.info(
            f"Fetching ONS observations for {len(state.new_releases)} release(s)"
        )
        new_observations = []

        for release in state.new_releases:
            release_observations = self._fetch_observations_for_release(state, release)
            new_observations.extend(release_observations)

        logger.info(f"Created {len(new_observations)} new ONS observation(s)")
        return new_observations


class ONSUpdateManager(UpdateManager):
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
        logger.debug(
            f"Initializing ONSUpdateManager for dataset_id={dataset_id}, series_key={series_key}"
        )
        super().__init__(
            dataset_id=dataset_id,
            source=ONS_SOURCE,
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
        return ONSAPIClient(cache_settings=cache_settings, cache_path=cache_path)

    def _create_dataset_manager(self) -> DatasetManager:
        return ONSDatasetManager(self.api_client)

    def _create_release_manager(self) -> ReleaseManager:
        return ONSReleaseManager(self.api_client)

    def _create_series_manager(self) -> SeriesManager:
        return ONSSeriesManager(self.api_client)

    def _create_observation_manager(self) -> ObservationManager:
        return ONSObservationManager(self.api_client)
