import os
from datetime import datetime
from typing import Any, List, Optional, Dict
from dateutil import parser

import numpy as np
import pytz

from tqdm import tqdm


from macrotrace.sources.base import (
    APIClient,
    UpdateManager,
    DatasetManager,
    ReleaseManager,
    SeriesManager,
    ObservationManager,
    UpdateState,
)
from macrotrace.models.db import (
    DatasetDimension,
    Release,
    ReleaseDimension,
    SeriesDimensionFilter,
    Observation,
)

import logging

logger = logging.getLogger(__name__)

FRED_DATE_FORMAT = "%Y-%m-%d"
FRED_SOURCE = "FRED"
FRED_BASE_URL = "https://api.stlouisfed.org/fred/"
US_CENTRAL = pytz.timezone("America/Chicago")

FRED_TO_PD_OFFSETS = {
    "Daily": "D",
    "Daily, 7-Day": "D",
    "Daily, Close": "D",
    "Weekly": "W",
    "Weekly, Ending Monday": "W-MON",
    "Weekly, Ending Tuesday": "W-TUE",
    "Weekly, Ending Wednesday": "W-WED",
    "Weekly, Ending Thursday": "W-THU",
    "Weekly, Ending Friday": "W-FRI",
    "Weekly, Ending Saturday": "W-SAT",
    "Weekly, Ending Sunday": "W-SUN",
    "Biweekly, Ending Wednesday": "2W-WED",
    "Monthly": "MS",
    "Monthly, End of Period": "ME",
    "Quarterly": "QS",
    "Quarterly, End of Period": "QE",
    "Quarterly, End of Quarter": "QE",
    "Semiannual": "2Q",
    "Annual": "YS",
    "Annual, As of February": "A-FEB",
    "Annual, As of July 1": "A-JUL",
    "Annual, End of Period": "YE",
    "Annual, End of Year": "YE",
    # Fiscal is difficult since this could mean many things
    "Annual, Fiscal Year": "YS",
    "5 Year": "5A",
}


class FredAPIClient(APIClient):

    def __init__(
        self,
        api_key: Optional[str] = None,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ):
        self.api_key = os.getenv("FRED_API_KEY") if api_key is None else api_key
        if self.api_key:
            logger.debug("FRED API key found")
        else:
            logger.warning("No FRED API key provided or found in environment variables")
            raise EnvironmentError(
                "FRED API key is required to use the FRED API client. Please provide one with the 'FRED_API_KEY' environment variable."
            )
        super().__init__(
            base_url=FRED_BASE_URL,
            cache_settings=cache_settings,
            cache_path=cache_path,
        )

    def _get_request_headers(self) -> Dict[str, str]:
        """
        Get the request headers for the FRED API client.

        Returns:
            Dict[str, str]: Request headers including the API key and file type.
        """
        return {}

    def _get_default_params(self) -> Dict[str, str]:
        """
        Get the default parameters for the FRED API client.

        Returns:
            Dict[str, str]: Default parameters including the API key and file type.
        """
        return {
            "api_key": self.api_key,
            "file_type": "json",
        }


class FredDatasetManager(DatasetManager):
    def __init__(self, api_client: FredAPIClient):
        super().__init__(api_client)

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse the FRED date string from FRED API into a datetime object.
        FRED uses "9999-12-31" to indicate an ongoing dimension, which we convert to None.

        Args:
            date_str (str): The date string from FRED API.
        Returns:
            Optional[datetime]: A datetime object representing valid_to, or None if ongoing.
        """
        try:
            date = parser.parse(date_str)
            if date.tzinfo is None:
                # Use pytz.localize() rather than .replace(tzinfo=...) — the latter
                # binds pytz's first historical entry for America/Chicago (LMT,
                # -05:50:36) instead of CST/CDT, which silently drifts dates by
                # ~9 minutes and causes downstream day-rollback bugs after
                # tz_convert + normalize. See tests/sources/fred/test_fred_tz_handling.py.
                date = US_CENTRAL.localize(date)
            if date.year == 9999 and date.month == 12 and date.day == 31:
                logger.debug("Parsed ongoing dimension date (9999-12-31) as None")
                return None
            return date
        except (ValueError, OverflowError) as e:
            # FRED uses 9999-12-31 to indicate "ongoing" check for parsing errors "date value out of range"
            if "out of range" in str(e):
                logger.debug(
                    f"Date {date_str} out of range, treating as ongoing (None)"
                )
                return None
            else:
                raise e

    def _convert_frequency(self, fred_frequency: str) -> Optional[str]:
        """
        Convert FRED frequency to internal representation.

        Args:
            fred_frequency (str): The frequency string from FRED API.
        Returns:
            Optional[str]: The converted frequency string or None if not found.
        """
        converted_freq = FRED_TO_PD_OFFSETS.get(fred_frequency, None)
        if converted_freq is None:
            logger.warning(f"Unknown FRED frequency: {fred_frequency}")

        return converted_freq

    def _is_new_dimension(
        self, response_realtime_start: datetime, latest_realtime_start: datetime
    ) -> bool:
        """
        Determine if the given response_realtime_start indicates a new dimension.

        Args:
            response_realtime_start (datetime): The realtime_start date of the dimension.
            latest_realtime_start (datetime): The latest known realtime_start locally.
        Returns:
            bool: True if the dimension is new, False otherwise.
        """
        return response_realtime_start > latest_realtime_start

    def _is_updated_dimension(
        self,
        response_realtime_start: datetime,
        latest_realtime_start: datetime,
        response_realtime_end: datetime,
    ) -> bool:
        """
        Determine if the given response_realtime_start and end indicate the latest dimension was updated

        Args:
            response_realtime_start (datetime): The realtime_start date of the dimension.
            latest_realtime_start (datetime): The latest known realtime_start locally.
            response_realtime_end (datetime): The realtime_end date of the dimension.

        Returns:
            bool: True if the latest dimension was updated, False otherwise.
        """
        return (
            response_realtime_start == latest_realtime_start
            and response_realtime_end is not None
        )

    def fetch_new_dataset_dimensions(
        self, state: UpdateState
    ) -> List[DatasetDimension]:
        """
        Fetch the dataset versions from FRED.

        Args:
            state (UpdateState): The current update state containing dataset information.

        Returns:
            List[DatasetVersion]: The dataset versions.
        """
        latest_realtime_start = self._get_latest_valid_from(state.dataset.id)
        logger.debug(
            f"Fetching FRED dimensions for {state.dataset_id} from {latest_realtime_start}"
        )

        # The FRED API effectively returns "series versions" from the API which in essence are dimensions
        fred_dimensions = self.api_client.make_paginated_request(
            "series",
            {
                "series_id": state.dataset_id,
                "realtime_start": latest_realtime_start.strftime(FRED_DATE_FORMAT),
                "realtime_end": "9999-12-31",
            },
            items_key="seriess",
        )

        new_dataset_dimensions = []
        num_series = len(fred_dimensions)
        logger.debug(f"Processing {num_series} FRED dimension(s)")

        for series_info in fred_dimensions:
            response_realtime_start = self._parse_date(
                series_info.get("realtime_start")
            )
            response_realtime_end = self._parse_date(series_info.get("realtime_end"))
            if self._is_new_dimension(response_realtime_start, latest_realtime_start):
                logger.debug(
                    f"Found new dimension: valid_from={response_realtime_start}, "
                    f"valid_to={response_realtime_end}"
                )
                frequency = self._convert_frequency(series_info.get("frequency"))
                new_dataset_dimensions.append(
                    DatasetDimension(
                        dataset=state.dataset,
                        dataset_dimension_id=state.dataset_id,
                        title=series_info.get("title"),
                        type="numeric",  # FRED series are always numeric other than time
                        frequency=frequency,
                        description=series_info.get("notes"),
                        units=series_info.get("units"),
                        seasonal_adjustment=series_info.get("seasonal_adjustment"),
                        valid_from=response_realtime_start,
                        valid_to=response_realtime_end,
                    )
                )
            elif self._is_updated_dimension(
                response_realtime_start, latest_realtime_start, response_realtime_end
            ):
                # The latest dimension was updated, so we need to set its valid_to
                # We do this by creating a new dimension with the same valid_from as the latest
                # but with the new valid_to from the response
                logger.debug(
                    f"Updating existing dimension: setting valid_to={response_realtime_end}"
                )
                latest_dimension = self._get_latest_local_dataset_dimension(
                    state.dataset.id, state.dataset_id
                )
                if latest_dimension is None:
                    raise ValueError(
                        f"Latest dimension for dataset {state.dataset.id} and dimension ID {state.dataset_id} not found."
                    )

                latest_dimension.valid_to = response_realtime_end
                latest_dimension.save()
            else:
                # Not new or updated, skip
                logger.debug(
                    f"Dimension already exists: realtime_start={response_realtime_start}"
                )

        logger.info(f"Found {len(new_dataset_dimensions)} new dataset dimension(s)")
        return new_dataset_dimensions


class FredReleaseManager(ReleaseManager):
    def __init__(self, api_client: FredAPIClient):
        super().__init__(api_client)

    def _ensure_us_central(self, dt: datetime) -> datetime:
        """
        Ensure the given datetime is in US Central timezone.

        Args:
            dt (datetime): The datetime to check.
        Returns:
            datetime: The datetime in US Central timezone.
        """
        if dt is None:
            return None
        if dt.tzinfo is None:
            # Assume US Central if no timezone info. Use pytz.localize() so the
            # CST/CDT offset is selected per-date instead of LMT (-05:50:36).
            return US_CENTRAL.localize(dt)
        # Otherwise, convert to US Central
        return dt.astimezone(US_CENTRAL)

    def fetch_new_releases(
        self,
        state: UpdateState,
    ) -> List[Release]:
        """
        This method retrieves the vintage dates for the given series ID from the FRED API.
        It compares the vintage dates with the latest local vintage date and creates new Release objects.
        The objects are not immediately saved to the database so we can batch them later.
        An empty list is returned if no new vintages are found.

        Args:
            state (UpdateState): The current update state containing dataset information.

        Returns:
            List[Release]: A list of new Release objects to be created.
        """
        # Convert release_start_date and release_end_date to US Central timezone if they are not None and have no timezone info
        state.release_start_date = self._ensure_us_central(state.release_start_date)
        state.release_end_date = self._ensure_us_central(state.release_end_date)

        # Get the appropriate API start date (handles backfilling)
        api_start_date = self._get_api_start_date(
            state.dataset.id, state.release_start_date
        )

        logger.debug(
            f"Fetching FRED vintages for {state.dataset_id} from {api_start_date}"
        )

        release_data = self.api_client.make_paginated_request(
            "series/vintagedates",
            {
                "series_id": state.dataset_id,
                "realtime_start": api_start_date.strftime(FRED_DATE_FORMAT),
            },
            items_key="vintage_dates",
        )

        new_vintages = []
        current_vintages_in_db = self._get_current_releases_in_db(state.dataset.id)

        total_vintages = len(release_data)
        logger.debug(f"Processing {total_vintages} vintage date(s) from FRED API")

        for dt_str in release_data:
            dt = US_CENTRAL.localize(datetime.strptime(dt_str, FRED_DATE_FORMAT))
            is_new_release = self._is_new_release(dt, current_vintages_in_db)
            is_wanted_release = self._is_wanted_release(
                dt,
                state.release_start_date,
                state.release_end_date,
            )

            if is_new_release and is_wanted_release:
                new_vintages.append(
                    Release(
                        dataset=state.dataset,
                        release_date=dt,
                    )
                )

        logger.info(
            f"Found {len(new_vintages)} new release(s) out of {total_vintages} total vintages"
        )
        return new_vintages

    def fetch_new_release_dimensions(
        self,
        state: UpdateState,
    ) -> List[ReleaseDimension]:
        """
        For each new release in the state, we need to associate it with the dataset dimensions.

        Args:
            state (UpdateState): The current update state containing dataset information.
        Returns:
            List[ReleaseDimension]: A list of new ReleaseDimension objects to be created.
        """
        all_dims = self._get_all_local_dataset_dimensions(state.dataset.id)
        if not all_dims:
            raise ValueError(
                f"Dataset {state.dataset.id} has no dimensions to associate with releases."
            )

        logger.debug(
            f"Associating {len(state.new_releases)} release(s) with {len(all_dims)} dimension(s)"
        )

        # check if the release date is greater than or equal to the dimension's valid_from
        # and less than or equal to the dimension's valid_to (if valid_to is not None)
        new_release_dimensions = []
        for release in state.new_releases:
            for dimension in all_dims:

                # The bounds should be inclusive on both ends per FRED's definition of realtime_start and realtime_end
                # https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
                in_lower_bound = release.release_date >= dimension.valid_from
                in_upper_bound = (
                    dimension.valid_to is None
                    or release.release_date <= dimension.valid_to
                )

                if in_lower_bound and in_upper_bound:
                    new_release_dimensions.append(
                        ReleaseDimension(
                            release=release,
                            dimension=dimension,
                        )
                    )

        logger.info(
            f"Created {len(new_release_dimensions)} release-dimension association(s)"
        )
        return new_release_dimensions


class FredSeriesManager(SeriesManager):
    def __init__(self, api_client: FredAPIClient):
        super().__init__(api_client)

    def fetch_series_dimension_selection(
        self, state: UpdateState
    ) -> List[SeriesDimensionFilter]:
        """
        FRED does not require different series dimension filters as there is only ever one defined dimension.
        Since we don't need to filter on anything, we return an empty list.

        Args:
            state (UpdateState): The current update state containing series information.
        Returns:
            List[SeriesDimensionFilter]: An empty list.
        """
        return []


class FredObservationManager(ObservationManager):
    def __init__(self, api_client: FredAPIClient):
        super().__init__(api_client)

    def _clean_vintage_str_date(self, release_date: str) -> datetime:
        """
        Convert a vintage (release) date string to a datetime object.
        This method extracts the date from the key string, which is expected to be in the format "{series_id}_YYYYMMDD".

        Args:
            release_date (str): The vintage date string in the format "{series_id}_YYYYMMDD".

        Returns:
            datetime: A datetime object representing the vintage date.
        """
        return US_CENTRAL.localize(
            datetime.strptime(release_date.split("_")[1], "%Y%m%d")
        )

    def _create_release_date_chunks(
        self, releases: List[Release], current_url_len: int, max_url_len: int = 7500
    ) -> List[str]:
        """
        Create chunks of release dates that fit within the maximum URL length for FRED API requests.
        The limit is some upstream URL length limit which isn't currently known.
        FRED's docs specify 2k vintage dates are allowed, but in practice this leads to errors.
        Default max_url_len is set to 7500 characters seems to be safe.

        Args:
            releases (List[Release]): A list of Release objects.
            current_url_len (int): The current length of the URL being constructed.
            max_url_len (int, optional): The maximum allowed length of the URL. Defaults to 7500.

        Returns:
            List[str]: A list of strings, each representing a chunk of release dates suitable for URL inclusion.
        """

        DATE_LEN = 10
        SEP_LEN = 3  # comma becomes '%2C' in your observed URLs

        remaining = max_url_len - current_url_len

        if remaining <= DATE_LEN:
            raise ValueError(
                f"Not enough URL budget: current_url_len={current_url_len}, max_url_len={max_url_len}"
            )

        max_per_chunk = 1 + (remaining - DATE_LEN) // (SEP_LEN + DATE_LEN)
        max_per_chunk = max(1, int(max_per_chunk))

        out: List[str] = []
        i = 0
        n = len(releases)
        while i < n:
            chunk = releases[i : i + max_per_chunk]
            out.append(
                ",".join(d.release_date.strftime(FRED_DATE_FORMAT) for d in chunk)
            )
            i += max_per_chunk

        return out

    def _create_new_observations(
        self,
        state: UpdateState,
        obs_data: List[Dict],
        release_dates_to_id: Dict[datetime, int],
    ) -> List[Observation]:
        """
        Takes raw observation data from FRED and converts it into Observation objects.

        Args:
            state (UpdateState): The current update state containing series information.
            obs_data (List[Dict]): A list of dictionaries where each dict is in the format {"date": "dt_str", "vintage": value_str}
            release_dates_to_id (Dict[datetime, int]): A mapping from release dates to their corresponding integer PKs.

        Returns:
            List[Observation]: A list of new Observation objects to be created.
        """

        new_observations = []

        for obs in tqdm(obs_data, desc="Processing Observations", leave=False):
            obs_date = US_CENTRAL.localize(
                datetime.strptime(obs.pop("date"), FRED_DATE_FORMAT)
            )
            for key, value in obs.items():
                release_pk = release_dates_to_id[self._clean_vintage_str_date(key)]

                new_observations.append(
                    Observation(
                        series=state.series,
                        release=release_pk,
                        observation_timestamp=obs_date,
                        # FRED uses "." to indicate missing / empty values
                        value=float(value) if value != "." else np.nan,
                    )
                )
        return new_observations

    def _batch_query_fred_observations(
        self,
        release_date_chunks: List[str],
        api_args: Dict[str, str],
    ) -> List[Dict]:
        """
        Batch query FRED observations for the given release date groups.

        Args:
            release_date_chunks (List[str]): A list of strings, each representing a chunk of release dates.
            api_args (Dict[str, str]): The API arguments to use for the requests.

        Returns:
            List[Dict]: A list of observation data dictionaries retrieved from the FRED API.
        """

        obs_data = []

        for releases_str in tqdm(
            release_date_chunks,
            desc="Querying FRED's Release data in batches",
            leave=False,
        ):
            api_args["params"]["vintage_dates"] = releases_str
            res = self.api_client.make_paginated_request(
                **api_args, items_key="observations"
            )
            obs_data.extend(res)

        return obs_data

    def fetch_new_observations(self, state: UpdateState) -> List[Observation]:
        """
        Fetch new observations for the given releases and series.

        This method retrieves observations for the provided releases from the FRED API.
        Since we are not filtering on dimensions here, we do not need to use the series key.

        It breaks the vintages (FRED's term for releases) into chunks of 100 to avoid URL length issues.
        For each vintage, it fetches the observations and creates Observation objects.

        If no new releases are provided, an empty list is returned.

        Args:
            state (UpdateState): The current update state containing series information.

        Returns:
            List[Observation]: A list of new Observation objects to be created.
        """
        if not state.new_releases:
            logger.debug("No new releases to fetch observations for")
            return []

        # Make a dictionary mapping of release dates to their integer PKs
        release_dates_to_id = {v.release_date: v.id for v in state.new_releases}

        # API call prep
        args = {
            "endpoint": "series/observations",
            "params": {
                "series_id": state.dataset_id,
                "output_type": "2",
                # need empty "vintage_dates" here for accurate url length calculation
                "vintage_dates": "",
            },
        }
        url, _ = self.api_client.make_request_dry_run(**args)

        # Create release date chunks to avoid URL length issues
        release_date_chunks = self._create_release_date_chunks(
            releases=state.new_releases.copy(), current_url_len=len(url)
        )

        logger.info(
            f"Fetching observations for {len(state.new_releases)} release(s) "
            f"in {len(release_date_chunks)} batch(es)"
        )

        obs_data = self._batch_query_fred_observations(
            release_date_chunks=release_date_chunks, api_args=args
        )

        new_observations = self._create_new_observations(
            state, obs_data, release_dates_to_id
        )

        logger.info(f"Created {len(new_observations)} new observation(s)")
        return new_observations


class FredUpdateManager(UpdateManager):
    def __init__(
        self,
        dataset_id: str,
        source: str = FRED_SOURCE,
        series_key: Dict[str, str] = {},
        release_start_date: Optional[datetime] = None,
        release_end_date: Optional[datetime] = None,
        db_path: Optional[str] = None,
        cache_settings: Optional[Dict[str, Any]] = None,
        cache_path: Optional[str] = None,
    ):
        # Recall that FRED series do not have keys
        # They only have a single dimension other than time
        if series_key != {}:
            logger.warning(
                f"FRED series do not have series keys. Ignoring provided series_key={series_key}"
            )

        logger.debug(f"Initializing FredUpdateManager for dataset_id={dataset_id}")

        super().__init__(
            dataset_id=dataset_id,
            source=source,
            series_key=None,
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
    ) -> FredAPIClient:
        return FredAPIClient(cache_settings=cache_settings, cache_path=cache_path)

    def _create_dataset_manager(self) -> DatasetManager:
        """Override this to provide a specific dataset manager."""
        return FredDatasetManager(self.api_client)

    def _create_release_manager(self) -> ReleaseManager:
        """Override this to provide a specific release manager."""
        return FredReleaseManager(self.api_client)

    def _create_series_manager(self) -> SeriesManager:
        """Override this to provide a specific series manager."""
        return FredSeriesManager(self.api_client)

    def _create_observation_manager(self) -> ObservationManager:
        """Override this to provide a specific observation manager."""
        return FredObservationManager(self.api_client)
