from typing import TYPE_CHECKING, List, Optional, Dict, Any
from dataclasses import replace
from dateutil import parser
from datetime import datetime, timezone

import pandas as pd
from tabulate import tabulate
from darts import TimeSeries
from peewee import JOIN

from macrotrace.models.db import (
    Dataset,
    DatasetDimension,
    Series,
    SeriesDimensionFilter,
    Observation,
    Release,
)
from macrotrace.models.mt.series_metadata import MTSeriesMetadata
from macrotrace.models.mt.observation import MTObservation
from macrotrace.models.mt.plotter import MTTimeSeriesPlotter
from macrotrace.models.mt.analysis import MTTimeSeriesAnalysis

if TYPE_CHECKING:  # pragma: no cover
    from macrotrace.sources.base import UpdateManager, UpdateState

import logging

logger = logging.getLogger(__name__)

VALID_SOURCES = ["FRED", "ONS", "USER"]
# USER is for user provided data, not from an API


class MTTimeSeries:

    def __init__(
        self,
        dataset_id: str,
        source: str,
        series_key: Dict[str, str] = None,
        # vintage_start_date and vintage_end_date define the vintage window returned
        # by this MTTimeSeries instance. Update managers may still backfill outside
        # the requested window so future loads can move backward without data loss.
        vintage_start_date: Optional[str | datetime] = None,
        vintage_end_date: Optional[str | datetime] = None,
        # Recall we want to only filter the observations returned, not the data fetched.
        # Filtering data before writing to the db may cause incomplete vintage chains.
        data_start_date: Optional[str | datetime] = None,
        data_end_date: Optional[str | datetime] = None,
        update_prior_to_load: bool = True,
        db_path: Optional[str] = None,
        cache_path: Optional[str] = None,
    ):
        """Load time series data from database and/or API.

        Args:
            dataset_id: Dataset identifier (e.g., "GDP", "UNRATE")
            source: Data source ("FRED", "ONS", etc.)
            series_key: Dictionary of dimension filters for multi-dimensional datasets
            vintage_start_date: Start date for vintage window
            vintage_end_date: End date for vintage window
            data_start_date: Filter observations after this date
            data_end_date: Filter observations before this date
            update_prior_to_load: Whether to fetch new data from API before loading
            db_path: Path to the SQLite database. Resolution: this argument,
                then the ``MACROTRACE_DB`` env var, then ``MacroTrace.db`` in
                the current working directory.
            cache_path: Path to the request-cache SQLite file. Resolution:
                this argument, then ``MACROTRACE_CACHE``, then beside
                ``MACROTRACE_DB`` if set, else
                ``MacroTraceRequestCache.sqlite`` in the current working
                directory.
        """
        self.dataset_id = dataset_id
        self._set_source(source)
        self.series_key = series_key or {}
        self.db_path = db_path
        self.cache_path = cache_path

        # Clean and validate dates
        self.vintage_start_date = self._clean_date(vintage_start_date)
        self.vintage_end_date = self._clean_date(vintage_end_date)
        self.data_start_date = self._clean_date(data_start_date)
        self.data_end_date = self._clean_date(data_end_date)

        # Only construct an update manager when we intend to refresh from the source.
        updater = self._get_update_manager() if update_prior_to_load else None
        state = self._fetch_or_load_state(updater, update_prior_to_load)

        # Load all vintages from releases
        time_series_list = self._load_vintages_from_releases(state)

        # Set attributes from the latest time series
        latest_ts = time_series_list[-1]
        self.release_date = latest_ts.release_date
        self.current_observations = latest_ts.current_observations
        self.vintages = latest_ts.vintages
        self.metadata = latest_ts.metadata

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        dataset_id: str,
        title: Optional[str] = None,
        units: Optional[str] = None,
        frequency: Optional[str] = None,
        seasonal_adjustment: Optional[str] = None,
    ) -> "MTTimeSeries":
        """Create an MTTimeSeries from a pandas DataFrame.

        This allows users to construct a time series from their own data rather than
        loading from the database or API. The DataFrame should contain columns for
        'timestamp', 'value', and 'release_date'. If multiple release dates are present,
        they will be used to construct a vintage chain.

        Args:
            df: DataFrame with columns 'timestamp', 'value', and 'release_date'
            dataset_id: Dataset identifier (e.g., "GDP", "UNRATE")
            title: Optional series title (defaults to dataset_id)
            units: Optional units description (defaults to "Units")
            frequency: Optional frequency string (if None, will be inferred from timestamps)
            seasonal_adjustment: Optional seasonal adjustment description

        Returns:
            MTTimeSeries: A new time series instance with vintage chain if applicable

        Raises:
            ValueError: If required columns are missing from the DataFrame
        """
        # Validate required columns
        required_cols = {"timestamp", "value", "release_date"}
        if not required_cols.issubset(df.columns):
            missing = required_cols - set(df.columns)
            raise ValueError(
                f"DataFrame must contain columns: {required_cols}. Missing: {missing}"
            )

        # Ensure proper data types
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["release_date"] = pd.to_datetime(df["release_date"])
        df["value"] = pd.to_numeric(df["value"], errors="raise")

        # Ensure timezone-aware datetimes (assume UTC if none provided)
        if df["timestamp"].dt.tz is None:
            logger.warning(
                "Timestamp column has no timezone information. Assuming UTC."
            )
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

        if df["release_date"].dt.tz is None:
            logger.warning(
                "Release date column has no timezone information. Assuming UTC."
            )
            df["release_date"] = df["release_date"].dt.tz_localize("UTC")

        # Sort by release_date to build vintages chronologically
        df = df.sort_values("release_date")

        # Get unique release dates
        release_dates = sorted(df["release_date"].unique())

        # Build vintage chain
        time_series_list = []

        for release_date in release_dates:
            # Get observations for this release
            release_df = df[df["release_date"] == release_date].sort_values("timestamp")

            # Convert to MTObservation objects
            observations = [
                MTObservation(
                    timestamp=row["timestamp"],
                    value=row["value"],
                    release_date=release_date,
                )
                for _, row in release_df.iterrows()
            ]

            # Create MTTimeSeries for this vintage
            vintage = cls._from_data(
                dataset_id=dataset_id,
                release_date=release_date,
                current_observations=observations,
                vintages=time_series_list[:],  # Copy of all previous vintages
                source="USER",
                series_key={},  # No series_key when creating from DataFrame
                units=units,
                frequency=frequency,
                title=title,
                seasonal_adjustment=seasonal_adjustment,
            )
            time_series_list.append(vintage)

        # Return the latest vintage (which contains all previous vintages in its chain)
        return time_series_list[-1]

    @classmethod
    def _from_data(
        cls,
        dataset_id: str,
        release_date: datetime,
        current_observations: List[MTObservation],
        vintages: List["MTTimeSeries"],
        source: str,
        series_key: Optional[Dict[str, str]] = None,
        units: Optional[str] = None,
        frequency: Optional[str] = None,
        title: Optional[str] = None,
        seasonal_adjustment: Optional[str] = None,
    ) -> "MTTimeSeries":
        """Internal factory method to create MTTimeSeries from already-loaded data.

        This is used internally when building vintages. External users should use
        the main __init__ constructor which loads data automatically, or the
        from_dataframe classmethod to create from a pandas DataFrame.
        """
        instance = cls.__new__(cls)
        instance.dataset_id = dataset_id
        instance.release_date = release_date
        instance.current_observations = current_observations
        instance.vintages = vintages
        instance.source = source
        instance.series_key = series_key or {}
        instance.vintage_start_date = None
        instance.vintage_end_date = None
        instance.data_start_date = None
        instance.data_end_date = None
        instance.db_path = None
        instance.cache_path = None

        units = units if units else "Units"
        frequency = frequency if frequency else instance._infer_pandas_freq()

        instance.metadata = instance._make_metadata(
            source=source,
            title=title if title else dataset_id,
            units=units,
            frequency=frequency,
            seasonal_adjustment=seasonal_adjustment,
        )

        return instance

    def __repr__(self) -> str:
        """
        Returns a string representation of the time series, including the series ID,
        title, source, units, latest release date, and available vintages.

        Returns:
            str: String representation of the time series.
        """

        min_release_date = min(
            [v.release_date for v in self._vintages_including_current_series()],
            default=None,
        )
        max_release_date = max(
            [v.release_date for v in self._vintages_including_current_series()],
            default=None,
        )

        timestamp_format = self._get_timestamp_format()

        title = f"{self.metadata.title}"
        header = f"\nTime Series: {self.dataset_id} ({title})"
        header += f"\nSource: {self.metadata.source}"
        header += f"\nUnits: {self.metadata.units}"
        header += (
            f"\nLatest Vintage Date: {self.release_date.strftime(timestamp_format)}"
        )
        if min_release_date and max_release_date:
            header += f"\nVintages: {len(self.vintages)} available from {min_release_date.strftime(timestamp_format)} to {max_release_date.strftime(timestamp_format)}"

        obs_table = tabulate(
            [
                (o.timestamp.strftime(timestamp_format), o.value)
                for o in self.current_observations[-10:]
            ],
            headers=["Timestamp", "Value"],
            tablefmt="pretty",
        )
        return f"{header}\n{obs_table}\n"

    @property
    def plot(self) -> MTTimeSeriesPlotter:
        """
        Access plotting methods for this time series.

        Returns:
            MTTimeSeriesPlotter: A plotter instance for creating visualizations.

        Examples:
            >>> ts = MTTimeSeries(dataset_id="GDP", source="FRED")
            >>> ts.plot.timeseries().show()
            >>> ts.plot.revision_histogram().show()
            >>> ts.plot.timeseries_comparison(["2020-01-01", "2021-01-01"]).show()
        """
        return MTTimeSeriesPlotter(self)

    @property
    def analysis(self) -> MTTimeSeriesAnalysis:
        if not hasattr(self, "_analysis"):
            self._analysis = MTTimeSeriesAnalysis(self)
        return self._analysis

    def as_of(self, target_date: datetime | str) -> Optional["MTTimeSeries"]:
        """
        Returns the most recent vintage as of a specific date.

        Raises:
            ValueError: If no vintages are available.

        Args:
            target_date (datetime | str): The target date to check against.
                If a string is provided, it will be parsed into a datetime object.
                If no timezone is provided, it is assumed to be in UTC.

        Returns:
            MTTimeSeries: The latest available vintage on or before the target_date.
        """
        if type(target_date) is str:
            target_date = self._parse_string_date(target_date)
        elif isinstance(target_date, datetime):
            if target_date.tzinfo is None:
                logger.warning(
                    "Datetime object provided without timezone info. Assuming UTC."
                )
                target_date = target_date.replace(tzinfo=timezone.utc)
        elif not isinstance(target_date, datetime):
            raise ValueError(
                f"Invalid target date type: {type(target_date)}. Must be a string or a datetime."
            )

        # ensure the target date is not in the future
        if target_date > datetime.now().astimezone():
            raise ValueError("The target date cannot be in the future.")

        eligible_vintages = self._find_eligible_vintages(target_date)
        if not eligible_vintages:
            raise ValueError(
                "No vintages available. Are you sure the target date is valid?"
            )

        as_of_vintage = max(eligible_vintages, key=lambda v: v.release_date)

        return as_of_vintage

    ### Theoretically if the units change, we should not be able to compare them
    def generate_vintage_matrix(self) -> pd.DataFrame:
        """
        Generates a vintage matrix DataFrame with timestamps as rows and vintages as columns.
        Note that this does not account in any way for benchmark revisions.
        Please assess the series definition and metadata with `series_definitions` to ensure that the vintages are comparable.

        Returns:
            pd.DataFrame: A DataFrame with timestamps as rows and vintages as columns.
        """

        vintage_dfs = [
            v.to_dataframe() for v in self._vintages_including_current_series()
        ]

        merged_df = pd.concat(vintage_dfs, axis=0, ignore_index=True)

        merged_df = merged_df.pivot(
            index="timestamp",
            columns="release_date",
            values="value",
        )

        return merged_df

    def _metadata_substantively_changed(
        self, metadata1: MTSeriesMetadata, metadata2: MTSeriesMetadata
    ) -> bool:
        """
        Check if two metadata objects differ in substantive properties.

        Ignores temporal fields (realtime_start, realtime_end, observation_start, observation_end)
        which naturally change with each vintage but don't represent actual series redefinitions.

        Compares: title, units, frequency, seasonal_adjustment

        Args:
            metadata1: First metadata object to compare
            metadata2: Second metadata object to compare

        Returns:
            bool: True if substantive properties differ, False otherwise
        """
        return (
            metadata1.title != metadata2.title
            or metadata1.units != metadata2.units
            or metadata1.frequency != metadata2.frequency
            or metadata1.seasonal_adjustment != metadata2.seasonal_adjustment
        )

    def get_historical_metadata(self) -> dict[datetime, MTSeriesMetadata]:
        """
        Returns a dict demonstrating how the series metadata has changed over time.
        The key is the first vintage date when the metadata appeared and the value is the metadata itself.

        Only tracks substantive changes (title, units, frequency, seasonal adjustment) and ignores
        temporal metadata fields when identifying epochs. Within each epoch, the returned
        metadata value is updated to the latest vintage in that epoch so temporal fields like
        realtime_end and observation_end reflect the full validity window of that definition.

        Returns:
            dict[datetime, MTSeriesMetadata]: A dictionary mapping the first appearance date to the metadata.
        """
        historical_metadata = {}

        # Iterate forward through vintages to find first appearance of each metadata
        all_vintages = self._vintages_including_current_series()

        if not all_vintages:
            return historical_metadata

        # Record the first epoch keyed by its first appearance date.
        current_epoch_start = all_vintages[0].release_date
        previous_metadata = all_vintages[0].metadata
        historical_metadata[current_epoch_start] = replace(
            previous_metadata,
            realtime_start=current_epoch_start,
        )

        # Walk forward through vintages. If substantive metadata changes, start a new
        # epoch keyed by the first appearance date of that definition. If the metadata
        # is substantively unchanged, update the current epoch value so its temporal
        # fields reflect the latest vintage within that epoch.
        for v in all_vintages[1:]:
            if self._metadata_substantively_changed(v.metadata, previous_metadata):
                current_epoch_start = v.release_date
            historical_metadata[current_epoch_start] = replace(
                v.metadata,
                realtime_start=current_epoch_start,
            )
            previous_metadata = v.metadata

        return historical_metadata

    def return_first_vintages(self) -> pd.DataFrame:
        """
        Return the first vintage of each observation.
        I.e. We iterate through the vintages and grab the first vintage and the date it first appeared

        Returns:
            pd.DataFrame: A DataFrame containing the first vintage of each observation and the date it first appeared
        """
        df = self.analysis.select_vintage_by_index(
            vintage_index=1,
            include_vintage_date=True,
            dropna=True,
        )
        df = df.rename(columns={"vintage_date": "first_vintage_date"})
        return df[["timestamp", "first_vintage_date", "value"]]

    def to_darts_timeseries(
        self,
        fill_missing_dates: bool = False,
        fillna_value: Optional[float] = None,
        static_covariates: Optional[pd.DataFrame | pd.Series] = None,
        hierarchy: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[Any, Any]] = None,
        to_dataframe_kwargs: Dict[str, Any] = {},
    ) -> TimeSeries:
        """
        Converts the current observations of the time series to a Darts TimeSeries object.

        Args:
            fill_missing_dates (bool): If True, fills missing dates in the time series.
                Defaults to False.
            fillna_value (Optional[float]): If provided, fills NaN values in the time series with this value.
            static_covariates (Optional[pd.DataFrame | pd.Series]): From Darts documentation:
                Optionally, a set of static covariates to be added to the TimeSeries. Either a pandas Series or a pandas DataFrame.
                If a Series, the index represents the static variables.
                The covariates are globally 'applied' to all components of the TimeSeries.
                If a DataFrame, the columns represent the static variables and the rows represent the components of the uni/multivariate TimeSeries.
                If a single-row DataFrame, the covariates are globally 'applied' to all components of the TimeSeries.
                If a multi-row DataFrame, the number of rows must match the number of components of the TimeSeries (in this case, the number of columns in value_cols).
                This adds control for component-specific static covariates.
            hierarchy (Dict[str, str]): A dictionary representing the hierarchy of the time series.
                See: https://unit8co.github.io/darts/generated_api/darts.dataprocessing.transformers.reconciliation.html
            metadata (Dict[Any, Any]): Additional metadata to be added to the TimeSeries.

        Returns:
            TimeSeries: A Darts TimeSeries object containing the current observations.
        """

        # Darts/xarray rejects tz-aware DatetimeIndexes, and a UTC-anchored
        # column would shift wall-clock stamps off the declared freq grid for
        # non-UTC sources (FRED midnight EST → 05:00 UTC vs freq='MS'). Asking
        # to_dataframe for the source-local representation gives us a naive
        # column whose calendar dates align with metadata.frequency.
        kwargs_for_df = {**(to_dataframe_kwargs or {}), "tz": "source"}
        df = self.to_dataframe(**kwargs_for_df)

        return TimeSeries.from_dataframe(
            df,
            time_col="timestamp",
            value_cols="value",
            fill_missing_dates=fill_missing_dates,
            freq=self.metadata.frequency,
            fillna_value=fillna_value,
            static_covariates=static_covariates,
            hierarchy=hierarchy,
            metadata=metadata,
        )

    def to_dataframe(self, mode: str = "default", tz: str = "utc") -> pd.DataFrame:
        """
        Converts the current observations of the time series to a pandas DataFrame.

        Args:
            mode (str, optional): The mode for which the dataframe is provided.
                Supports "default" (unmodified observations), "first_difference" (first differences of observations), and "pct_change" (percentage change of observations).
                Defaults to "default".
            tz (str, optional): How to render the ``timestamp`` and ``release_date`` columns.
                ``"utc"`` (default) returns a tz-aware UTC ``datetime64[ns, UTC]`` column —
                absolute time, the same instant the source published. ``"source"`` returns a
                tz-naive column anchored on the source's wall-clock calendar (e.g. a FRED
                ``2010-02-01`` print stays ``2010-02-01 00:00`` instead of becoming
                ``2010-02-01 05:00 UTC``). Use ``"source"`` when you need the calendar to align
                with downstream tools (e.g. Darts ``freq='MS'``) and don't care about offset.

        Returns:
            pd.DataFrame: A DataFrame containing the current observations with columns:
                - 'timestamp': The timestamp of the observation.
                - 'value': The value of the observation.
                - 'release_date': The release date of the observation.
        """
        if mode not in ["default", "first_difference", "pct_change"]:
            raise ValueError(
                f"Invalid mode: {mode}. Supported modes are 'default', 'first_difference', and 'pct_change'."
            )
        if tz not in ("utc", "source"):
            raise ValueError(
                f"Invalid tz: {tz}. Supported values are 'utc' and 'source'."
            )

        if tz == "source":
            # Strip per-row tzinfo before pandas builds the column. Sidesteps the
            # mixed-offset coalescing problem entirely (no need for utc=True) and
            # preserves each observation's source-local calendar date.
            df = pd.DataFrame(
                [
                    {
                        "timestamp": obs.timestamp.replace(tzinfo=None),
                        "value": obs.value,
                        "release_date": (
                            obs.release_date.replace(tzinfo=None)
                            if obs.release_date.tzinfo is not None
                            else obs.release_date
                        ),
                    }
                    for obs in self.current_observations
                ]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["release_date"] = pd.to_datetime(df["release_date"])
        else:
            df = pd.DataFrame(
                [
                    {
                        "timestamp": obs.timestamp,
                        "value": obs.value,
                        "release_date": obs.release_date,
                    }
                    for obs in self.current_observations
                ]
            )

            # utc=True is required: source-localised observations carry per-row pytz
            # tzinfo objects (e.g. distinct CST and CDT singletons from
            # America/Chicago), and pandas refuses to build a single datetime64[ns, tz]
            # column from mixed offsets without it. Anchoring on UTC preserves
            # absolute time; downstream callers can pass ``tz="source"`` (or
            # ``.dt.tz_convert(...)`` themselves) when they need wall-clock alignment.
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df["release_date"] = pd.to_datetime(df["release_date"], utc=True)

        df["value"] = pd.to_numeric(df["value"], errors="raise")

        if mode == "first_difference":
            df["value"] = df["value"].diff()
            df = df.dropna()
        elif mode == "pct_change":
            df["value"] = df["value"].pct_change() * 100
            df = df.dropna()

        return df

    def _find_eligible_vintages(self, target_date: datetime) -> List["MTTimeSeries"]:
        """
        Finds eligible vintages based on (before or equal to) the target date.

        Args:
            target_date (datetime): The target date to check against.

        Returns:
            List[MTTimeSeries]: A list of eligible vintages.
        """
        return [
            v
            for v in self._vintages_including_current_series()
            if v.release_date <= target_date
        ]

    def _infer_pandas_freq(self) -> str:
        """
        Infers the pandas frequency string from the current observations.

        Returns:
            str: The inferred pandas frequency string.
        """
        if len(self.current_observations) < 2:
            raise ValueError(
                "Not enough observations to infer frequency. At least two observations are required."
            )

        timestamps = [obs.timestamp for obs in self.current_observations]
        inferred_freq = pd.infer_freq(pd.DatetimeIndex(timestamps))
        return inferred_freq

    def _get_timestamp_format(self) -> str:
        """
        Returns the appropriate strftime format string based on the series frequency.
        Subdaily frequencies include time and timezone, while daily and above show only the date.

        Returns:
            str: The strftime format string.
        """
        if not self.metadata.frequency:
            return "%Y-%m-%d"

        # Create a base date and add one frequency period to it
        # If the difference is less than 1 day, it's a subdaily frequency
        base_date = pd.Timestamp("2020-01-01")
        next_date = base_date + pd.tseries.frequencies.to_offset(
            self.metadata.frequency
        )
        is_subdaily = (next_date - base_date) < pd.Timedelta(days=1)

        if is_subdaily:
            return "%Y-%m-%d %H:%M:%S %Z"
        else:
            return "%Y-%m-%d"

    def _is_successful_revision(
        self, current_value: float, prior_value: float, final_value: float
    ) -> bool:
        """
        Determines if a revision was successful based on whether it brought the value closer to the final value.
        The values raises an exception if the values are the same or if either value is NaN.

        Args:
            current_value (float): The current value of the observation.
            prior_value (float): The prior value of the observation.
            final_value (float): The final value of the observation.

        Returns:
            bool: True if the revision was successful, False otherwise.
        """
        if current_value == prior_value:
            raise ValueError("Current value and prior value are the same.")
        elif pd.isna(current_value) or pd.isna(prior_value) or pd.isna(final_value):
            raise ValueError(
                "Current value, prior value, and final value cannot be NaN for a successful revision."
            )

        return abs(current_value - final_value) < abs(prior_value - final_value)

    def _make_metadata(
        self,
        source: str,
        title: str,
        frequency: str,
        units: str,
        seasonal_adjustment: Optional[str],
    ) -> MTSeriesMetadata:
        obs_start = min(
            [obs.timestamp for obs in self.current_observations], default=None
        )
        obs_end = max(
            [obs.timestamp for obs in self.current_observations], default=None
        )
        all_vintages = self.vintages + [self]
        min_release_date = min([v.release_date for v in all_vintages], default=None)
        max_release_date = max([v.release_date for v in all_vintages], default=None)

        return MTSeriesMetadata(
            dataset_id=self.dataset_id,
            source=source,
            title=title,
            realtime_start=min_release_date,
            realtime_end=max_release_date,
            observation_start=obs_start,
            observation_end=obs_end,
            frequency=frequency,
            units=units,
            seasonal_adjustment=seasonal_adjustment,
        )

    def _parse_string_date(self, dt: str) -> datetime:
        """
        Parses a string date into a datetime object.

        Args:
            dt (str): The datetime string to parse.

        Returns:
            datetime: The parsed datetime object.
        """
        try:
            parsed_dt = parser.parse(dt)
            if parsed_dt.tzinfo is None:
                # If no timezone is provided, assume UTC
                logger.warning(
                    f"Assuming datetime string {dt} is UTC timezone. Please provide a datetime object with timezone info if this is not the case."
                )
                parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)
            return parsed_dt

        except ValueError:
            raise ValueError(
                f"Invalid date string format {dt}. Please provide a datetime or a date string which can be parsed by dateutil.parser."
            )

    def _set_source(self, source: str):
        """Validate and set the data source."""
        source_upper = source.upper()
        if source_upper not in VALID_SOURCES:
            raise ValueError(
                f"Unsupported source: {source}. Must be one of {VALID_SOURCES}"
            )
        self.source = source_upper

    def _clean_date(self, dt: str | datetime) -> datetime:
        """Convert a date string to a datetime object. Returns None if dt is None."""
        if dt is None:
            return None
        if isinstance(dt, str):
            dt = parser.isoparse(dt)
        elif isinstance(dt, datetime):
            pass  # No need to parse, already a datetime object
        else:
            raise TypeError(f"Invalid date format: {dt}")  # Not a string or datetime

        if dt.tzinfo is None:
            logger.warning(
                "Datetime object provided without timezone info. Assuming UTC."
            )
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _get_series_dimension_from_key(self, state) -> List[DatasetDimension]:
        """
        After applying dimension filters, each series definition should map to a single
        dataset dimension id (including multiple versions of that dimension).
        This function retrieves that dimension.

        Args:
            state (UpdateState): The current update state containing series definitions.

        Returns:
            List[DatasetDimension]: The matched dataset dimensions.
        """
        series_dimension = (
            DatasetDimension.select()
            .join(
                SeriesDimensionFilter,
                JOIN.LEFT_OUTER,
                on=(
                    (DatasetDimension.id == SeriesDimensionFilter.dimension)
                    & (SeriesDimensionFilter.series == state.series)
                ),
            )
            .where(
                (DatasetDimension.dataset == state.dataset)
                & (SeriesDimensionFilter.id.is_null())
            )
        )
        dimension_ids = {d.dataset_dimension_id for d in series_dimension}
        if len(dimension_ids) != 1:
            raise ValueError(
                f"Series key {self.series_key} did not uniquely identify a single dataset dimension. "
                f"Found {len(dimension_ids)} unique dimensions."
            )
        return list(series_dimension)

    def _get_valid_dimension_from_date(
        self, dimensions: List[DatasetDimension], as_of_date: datetime
    ) -> DatasetDimension:
        """Get the valid dataset dimension for the given date."""
        for dim in dimensions:
            if dim.valid_from <= as_of_date and (
                dim.valid_to is None or dim.valid_to >= as_of_date
            ):
                return dim
        raise ValueError(f"No valid dataset dimension found for date {as_of_date}.")

    def _strip_empty_observations(
        self, observations: List[Observation]
    ) -> List[Observation]:
        """Strip empty observations from the start and end of the list."""
        observations = list(observations)
        while observations and observations[0].value is None:
            observations = observations[1:]
        while observations and observations[-1].value is None:
            observations = observations[:-1]
        return observations

    def _get_observations_for_release(self, release_pk: int) -> List[Observation]:
        """Get all observations associated with the release PK."""
        conditions = [Observation.release == release_pk]
        if self.data_start_date:
            conditions.append(Observation.observation_timestamp >= self.data_start_date)
        if self.data_end_date:
            conditions.append(Observation.observation_timestamp <= self.data_end_date)

        observations = (
            Observation.select()
            .where(*conditions)
            .order_by(Observation.observation_timestamp.asc())
        )

        observations = self._strip_empty_observations(list(observations))
        return observations

    def _get_releases(self, dataset_pk: int) -> List[Release]:
        """Get dataset releases within the requested vintage window."""
        conditions = [Release.dataset == dataset_pk]
        if self.vintage_start_date:
            conditions.append(Release.release_date >= self.vintage_start_date)
        if self.vintage_end_date:
            conditions.append(Release.release_date <= self.vintage_end_date)

        releases = (
            Release.select().where(*conditions).order_by(Release.release_date.asc())
        )
        return releases

    def _describe_vintage_window(self) -> str:
        """Return a human-readable description of the requested vintage window."""
        fmt = "%Y-%m-%d"
        start = (
            self.vintage_start_date.astimezone(timezone.utc).strftime(fmt)
            if self.vintage_start_date
            else None
        )
        end = (
            self.vintage_end_date.astimezone(timezone.utc).strftime(fmt)
            if self.vintage_end_date
            else None
        )

        if start and end:
            return f"between {start} and {end}"
        if start:
            return f"on or after {start}"
        if end:
            return f"on or before {end}"
        return "for all vintages"

    def _vintages_including_current_series(self) -> List["MTTimeSeries"]:
        """
        Get a list of all vintages including the current series.

        Returns:
            List[MTTimeSeries]: A list of all vintages including the current series.
        """
        return self.vintages + [self]

    def _get_update_manager(self):
        """Get the appropriate update manager for the data source.

        Returns:
            UpdateManager: An instance of the appropriate update manager class.
        """
        from macrotrace.sources.fred import FredUpdateManager
        from macrotrace.sources.ons import ONSUpdateManager

        source_managers = {
            "FRED": FredUpdateManager,
            "ONS": ONSUpdateManager,
        }

        assert (
            self.source in source_managers.keys()
        ), f"Unsupported source: {self.source}. No update manager available."

        updater_class = source_managers[self.source]

        return updater_class(
            dataset_id=self.dataset_id,
            series_key=self.series_key,
            release_start_date=self.vintage_start_date,
            release_end_date=self.vintage_end_date,
            db_path=self.db_path,
            cache_path=self.cache_path,
        )

    def _ensure_local_database_initialized(self):
        """Ensure the current model database is ready for local-only loads."""
        from macrotrace._paths import resolve_db_path

        database = Dataset._meta.database
        tables = [
            Dataset,
            DatasetDimension,
            Release,
            Series,
            SeriesDimensionFilter,
            Observation,
        ]

        # The deferred-init database needs a path resolved before connecting.
        if database.database is None:
            database.init(resolve_db_path(self.db_path))

        if database.is_closed():
            database.connect(reuse_if_open=True)
        database.create_tables(tables, safe=True)
        return database

    def _load_state_from_db(self):
        """Load an existing dataset/series pair from the local database only."""
        from macrotrace.sources.base import UpdateState

        self._ensure_local_database_initialized()

        dataset = (
            Dataset.select()
            .where(
                (Dataset.dataset_id == self.dataset_id)
                & (Dataset.source == self.source)
            )
            .first()
        )
        if dataset is None:
            raise ValueError(
                f"No locally stored dataset found for dataset {self.dataset_id} "
                f"from source {self.source}."
            )

        series_key = self.series_key or {}
        series = (
            Series.select()
            .where((Series.dataset == dataset) & (Series.series_key == series_key))
            .first()
        )
        if series is None:
            raise ValueError(
                f"No locally stored series found for dataset {self.dataset_id} "
                f"and series key {series_key}."
            )

        return UpdateState(
            dataset=dataset,
            dataset_id=self.dataset_id,
            source=self.source,
            series=series,
            series_key=series_key,
            release_start_date=self.vintage_start_date,
            release_end_date=self.vintage_end_date,
        )

    def _fetch_or_load_state(
        self, updater: Optional["UpdateManager"], update_prior_to_load: bool
    ):
        """Fetch new data from API or load existing data from database.

        Args:
            updater: The update manager instance when refreshes are enabled.
            update_prior_to_load: Whether to fetch new data from API.

        Returns:
            UpdateState: The current state containing dataset and series information.
        """
        if update_prior_to_load:
            if updater is None:
                raise ValueError(
                    "Update manager is required when refreshing from source."
                )
            return updater.update()
        return self._load_state_from_db()

    def _load_vintages_from_releases(
        self, state: "UpdateState"
    ) -> List["MTTimeSeries"]:
        """Load all time series vintages from database releases.

        Args:
            state: The current update state containing dataset and series information.

        Returns:
            List[MTTimeSeries]: A list of all loaded time series vintages.

        Raises:
            ValueError: If no time series data is found.
        """
        # Get series dimensions from series key
        series_dimensions = self._get_series_dimension_from_key(state)

        # Get all releases for this dataset
        series_releases = list(self._get_releases(state.dataset.id))
        time_series_list = []

        # Build time series for each release
        for release in series_releases:
            vintage = self._build_vintage_for_release(
                release, series_dimensions, time_series_list, state
            )
            if vintage is not None:
                time_series_list.append(vintage)

        if len(time_series_list) == 0:
            if self.vintage_start_date is not None or self.vintage_end_date is not None:
                raise ValueError(
                    f"No vintages available for dataset {state.dataset.dataset_id} "
                    f"and series key {state.series.series_key} "
                    f"within the requested vintage window "
                    f"({self._describe_vintage_window()})."
                )
            raise ValueError(
                f"No time series data found for dataset {state.dataset.dataset_id} "
                f"and series key {state.series.series_key}."
            )

        return time_series_list

    def _build_vintage_for_release(
        self,
        release,
        series_dimensions: List[DatasetDimension],
        time_series_list: List["MTTimeSeries"],
        state: "UpdateState",
    ) -> Optional["MTTimeSeries"]:
        """Build a single vintage time series for a given release.

        Args:
            release: The release object to build a vintage for.
            series_dimensions: List of valid dataset dimensions.
            time_series_list: The current list of time series (used for vintage chain).
            state: The current update state.

        Returns:
            Optional[MTTimeSeries]: The built time series vintage, or None if no observations.
        """
        observations = self._get_observations_for_release(release.id)

        # Skip releases without observations
        if len(observations) == 0:
            logger.debug(
                f"No observations found for dataset {state.series.dataset.dataset_id}, "
                f"series key {state.series.series_key}, and release date {release.release_date}. Skipping."
            )
            return None

        current_ts_observations = [
            MTObservation(
                timestamp=obs.observation_timestamp,
                value=obs.value,
                release_date=release.release_date,
            )
            for obs in observations
        ]

        dimension = self._get_valid_dimension_from_date(
            series_dimensions, release.release_date
        )

        # Create vintage using factory method
        return MTTimeSeries._from_data(
            dataset_id=self.dataset_id,
            release_date=release.release_date,
            current_observations=current_ts_observations,
            source=self.source,
            series_key=self.series_key,
            vintages=time_series_list[:],  # Shallow copy
            units=dimension.units,
            frequency=dimension.frequency,
            title=dimension.title,
            seasonal_adjustment=dimension.seasonal_adjustment,
        )
