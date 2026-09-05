from typing import TYPE_CHECKING, List, Optional, Dict, Any, Tuple
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone, tzinfo

import numpy as np
import pandas as pd
from pandas.tseries.frequencies import get_period_alias
from tabulate import tabulate
from darts import TimeSeries
from peewee import JOIN

from macrotrace._time import ensure_timezone
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
    from macrotrace.sources.base import SourceAdapter, UpdateManager, UpdateState

import logging

logger = logging.getLogger(__name__)

# USER is for user provided data, not from an API

# With fewer observations than this, a constant-shift scan can match a vintage
# by coincidence, so identify_vintage only reports shift hints above it.
MIN_OBSERVATIONS_FOR_SHIFT_DETECTION = 5


def _source_adapters() -> Dict[str, "SourceAdapter"]:
    """Return source adapters without importing them during module initialization."""
    from macrotrace.sources.fred import FRED_SOURCE_ADAPTER
    from macrotrace.sources.ons import ONS_SOURCE_ADAPTER
    from macrotrace.sources.rtdsm import RTDSM_SOURCE_ADAPTER
    from macrotrace.sources.user import USER_SOURCE_ADAPTER
    from macrotrace.sources.wdi import WDI_SOURCE_ADAPTER

    return {
        "FRED": FRED_SOURCE_ADAPTER,
        "ONS": ONS_SOURCE_ADAPTER,
        "RTDSM": RTDSM_SOURCE_ADAPTER,
        "WDI": WDI_SOURCE_ADAPTER,
        "USER": USER_SOURCE_ADAPTER,
    }


@dataclass
class VintageMatch:
    """
    Result of matching a data series with an unknown release date against the vintages of an MTTimeSeries (see ``MTTimeSeries.identify_vintage``).

    A match is ambiguous when the supplied data is consistent with more than one vintage.
    This is common when the data only covers observations that were never revised across a run of consecutive vintages, so the values alone cannot pin down a single release.

    Attributes:
        release_dates: Release dates of every vintage whose values matched the supplied data, sorted oldest to newest. Empty when nothing matched.
        n_observations: Number of non-null observations from the supplied data that were compared against each vintage.
        rtol: Relative tolerance used for the value comparison.
        atol: Absolute tolerance used for the value comparison.
        decimals: Number of decimals both sides were rounded to before comparison, or None when no rounding was applied.
        n_vintages_compared: Total number of vintages the supplied data was compared against.
        n_vintages_covering: Number of vintages containing every supplied timestamp. When zero, the data failed on coverage rather than on values; see ``failure_reason``.
        alignment_hint: When nothing matched but a diagnostic pass found a reinterpretation of the timestamps under which the values do match (wrong timezone localization, a constant time shift, or a different day-of-period convention), a human-readable description of it. The hinted reinterpretation never counts as a match; fix the index and re-run.
        time_shift: The constant shift that, added to the supplied index, makes the values match at least one vintage. Only set when the hint came from the constant-shift detector.
    """

    release_dates: List[datetime]
    n_observations: int
    rtol: float
    atol: float
    decimals: Optional[int] = None
    n_vintages_compared: int = 0
    n_vintages_covering: int = 0
    alignment_hint: Optional[str] = None
    time_shift: Optional[timedelta] = None

    @property
    def matched(self) -> bool:
        """True if the supplied data matched at least one vintage."""
        return len(self.release_dates) > 0

    @property
    def is_ambiguous(self) -> bool:
        """True if the supplied data matched more than one vintage."""
        return len(self.release_dates) > 1

    @property
    def failure_reason(self) -> Optional[str]:
        """
        Why the supplied data matched no vintage, or None when it matched.

        Returns "coverage" when no vintage contains the supplied timestamps, usually a sign the index dates or timezone are wrong rather than the values, and "values" when at least one vintage contains the timestamps but none matched (the values disagreed, or ``require_exact_coverage`` excluded vintages carrying extra observations).

        Returns:
            Optional[str]: "coverage", "values", or None when the data matched.
        """
        if self.matched:
            return None
        return "coverage" if self.n_vintages_covering == 0 else "values"

    @property
    def release_date(self) -> Optional[datetime]:
        """
        The single matching vintage's release date.

        Returns None when there was no match or when the match was ambiguous (more than one vintage matched).
        Inspect ``release_dates`` in the ambiguous case.

        Returns:
            Optional[datetime]: The unambiguously matched release date, else None.
        """
        return self.release_dates[0] if len(self.release_dates) == 1 else None

    def __repr__(self) -> str:
        """
        Returns a human-readable summary of the match result.

        Returns:
            str: String representation of the match result.
        """
        compared = f"compared {self.n_observations} observation(s)"
        if not self.matched:
            if self.failure_reason == "coverage":
                message = (
                    "VintageMatch(no matching vintage found; no vintage contains "
                    "the supplied timestamps - check the index dates/timezone"
                )
            else:
                message = (
                    f"VintageMatch(no matching vintage found; "
                    f"{self.n_vintages_covering} vintage(s) contain the supplied "
                    f"timestamps but none matched"
                )
            if self.alignment_hint:
                message += f"; hint: {self.alignment_hint}"
            return f"{message}; {compared})"
        if self.is_ambiguous:
            dates = ", ".join(d.strftime("%Y-%m-%d") for d in self.release_dates)
            return (
                f"VintageMatch(ambiguous - matched {len(self.release_dates)} "
                f"vintages: {dates}; {compared})"
            )
        return (
            f"VintageMatch(matched vintage "
            f"{self.release_dates[0].strftime('%Y-%m-%d')}; {compared})"
        )


class MTTimeSeries:
    def __init__(
        self,
        dataset_id: str,
        source: str,
        series_key: Optional[Dict[str, str]] = None,
        # vintage_start_date and vintage_end_date define the vintage window returned
        # by this MTTimeSeries instance. Update managers may still backfill outside
        # the requested window so future loads can move backward without data loss.
        vintage_start_date: Optional[str | datetime | date] = None,
        vintage_end_date: Optional[str | datetime | date] = None,
        # Recall we want to only filter the observations returned, not the data fetched.
        # Filtering data before writing to the db may cause incomplete vintage chains.
        data_start_date: Optional[str | datetime | date] = None,
        data_end_date: Optional[str | datetime | date] = None,
        update_prior_to_load: bool = True,
        db_path: Optional[str] = None,
        cache_path: Optional[str] = None,
    ):
        """Load time series data from database and/or API.

        All four date windows are inclusive and accept a ``YYYY-MM-DD``
        string, a ``datetime.date``, or a datetime. Naive input is read on
        the source's own clock. A date becomes the source's midnight on that day,
        matching how sources stamp their releases and observations. For example,
        ``vintage_end_date="2018-03-16"`` includes FRED's 2018-03-16
        release even though it is stored at midnight US Central.
        Pass an aware datetime to bound by an exact instant instead.

        Args:
            dataset_id: Dataset identifier (e.g., "GDP", "UNRATE")
            source: Data source ("FRED", "ONS", etc.)
            series_key: Dictionary of dimension filters for multi-dimensional datasets.
            vintage_start_date: Only load vintages released on or after this date
            vintage_end_date: Only load vintages released on or before this date
            data_start_date: Only keep observations stamped on or after this date
            data_end_date: Only keep observations stamped on or before this date
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
        self.series_key = self.source_adapter.normalize_series_key(
            self.dataset_id, series_key
        )
        self.db_path = db_path
        self.cache_path = cache_path

        # Clean and validate dates
        self.vintage_start_date = self._clean_date(vintage_start_date)
        self.vintage_end_date = self._clean_date(vintage_end_date)
        self.data_start_date = self._clean_date(data_start_date)
        self.data_end_date = self._clean_date(data_end_date)

        # Only construct an update manager when we intend to refresh from the source.
        updater = (
            self.source_adapter.create_update_manager(
                dataset_id=self.dataset_id,
                series_key=self.series_key,
                release_start_date=self.vintage_start_date,
                release_end_date=self.vintage_end_date,
                db_path=self.db_path,
                cache_path=self.cache_path,
            )
            if update_prior_to_load
            else None
        )
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
        source_adapters = _source_adapters()
        instance.source_adapter = source_adapters.get(
            source.upper(), source_adapters["USER"]
        )
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
            [v.release_date for v in self._vintages_including_current_series],
            default=None,
        )
        max_release_date = max(
            [v.release_date for v in self._vintages_including_current_series],
            default=None,
        )

        timestamp_format = self._timestamp_format

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

    def as_of(self, target_date: datetime | str | date) -> Optional["MTTimeSeries"]:
        """
        Returns the most recent vintage as of a specific date.

        A date string (``"YYYY-MM-DD"``), a ``datetime.date``, or a naive datetime
        is read on the source's own clock, so a calendar date lands at the source's midnight
        and matches how the source stamps its releases. A timezone-aware datetime is compared as the exact instant it denotes.

        Raises:
            ValueError: If the target is a string not in ``YYYY-MM-DD`` form,
                lies on a future calendar day in the source's timezone, or no
                vintage exists on or before it.

        Args:
            target_date (datetime | str | date): The target date. Pass a
                ``YYYY-MM-DD`` string or a date for a calendar day, or a
                datetime for a specific moment.

        Returns:
            MTTimeSeries: The latest available vintage as of the target_date.
        """
        if not isinstance(target_date, (str, date)):
            raise ValueError(
                f"Invalid target date type: {type(target_date)}. Must be a string, a date, or a datetime."
            )
        target_date = self._clean_date(target_date)

        # Guard against targets on a future calendar day. Comparing dates on
        # the source's clock (not instants) keeps "as of today" valid even
        # while the source's calendar day still lags UTC's.
        native_tz = self._native_observation_timezone()
        now_local = datetime.now(timezone.utc).astimezone(native_tz)
        if target_date.astimezone(native_tz).date() > now_local.date():
            raise ValueError("The target date cannot be in the future.")

        eligible_vintages = self._find_eligible_vintages(target_date)
        if not eligible_vintages:
            raise ValueError(
                "No vintages available. Are you sure the target date is valid?"
            )

        as_of_vintage = max(eligible_vintages, key=lambda v: v.release_date)

        return as_of_vintage

    def identify_vintage(
        self,
        series: pd.Series,
        rtol: float = 1e-05,
        atol: float = 1e-08,
        require_exact_coverage: bool = False,
        decimals: Optional[int] = None,
    ) -> VintageMatch:
        """
        Identify which vintage(s) a block of data with an unknown release date came from.

        Replication packages frequently ship a series of observations with no release date attached, only a source.
        This compares the supplied data against every vintage in this MTTimeSeries and reports the release date(s) whose values it is consistent with, so you can recover the vintage you are actually working with.
        Note that only the release date is treated as unknown: the observations themselves must be dated, with the series index supplying the observation dates.

        The supplied data is treated as a (possibly incomplete) window of a vintage: every timestamp in ``series`` must be present in a vintage and its values must agree (within tolerance) for that vintage to match.
        A vintage may carry extra observations the data does not include.
        When the data does not change across consecutive vintages the match is necessarily ambiguous, and all consistent release dates are returned.

        When nothing matches, a diagnostic pass checks whether the values would match under a common timestamp misalignment, such as the index localized to the wrong timezone, shifted by a constant offset, or stamped with a different day-of-period convention (e.g. month-end instead of month-start), and reports it via ``VintageMatch.alignment_hint``.
        A hinted reinterpretation is never counted as a match.

        Args:
            series (pd.Series): The data to identify, indexed by observation date.
                A tz-naive index (dates, date strings, or naive timestamps) is interpreted in the source's native observation timezone, e.g. midnight US Central for FRED, falling back to UTC with a warning when the source has no registered manager.
                A ``pd.PeriodIndex`` is compared on each period's start timestamp.
                A numeric index is rejected, because pandas would silently read it as nanosecond offsets from 1970 rather than dates.
                Null values are dropped before matching.
            rtol (float): Relative tolerance for the value comparison, passed through to ``numpy.isclose``. Defaults to 1e-05.
            atol (float): Absolute tolerance for the value comparison, passed through to ``numpy.isclose``. Defaults to 1e-08.
            require_exact_coverage (bool): If True, a vintage only matches when its timestamps are exactly the timestamps in ``series``, rather than allowing the data to be a sub-window of the vintage. Defaults to False.
            decimals (Optional[int]): When set, both the supplied data and each vintage's values are rounded to this many decimals before comparison.
                Use this when the data was published at a fixed precision (e.g. ``decimals=1`` for a series published at one decimal place); it is more faithful than loosening ``atol``, which both accepts values that round apart and rejects values that round together. Defaults to None (no rounding).

        Returns:
            VintageMatch: The matching release date(s) and comparison details.
                Check ``matched`` to see whether at least one vintage matched, ``failure_reason`` to distinguish data whose timestamps no vintage contains ("coverage") from data that no vintage matched despite containing its timestamps ("values"), and ``alignment_hint`` for a detected timestamp misalignment.

        Raises:
            TypeError: If ``series`` is not a pandas Series.
            ValueError: If ``series`` is empty, has a numeric, non-date, or duplicated index, or contains no non-null observations.
        """
        candidate, original_tz = self._prepare_candidate_series(series)
        candidate_values = candidate.to_numpy(dtype=float)
        if decimals is not None:
            candidate_values = np.round(candidate_values, decimals)

        matches: List[datetime] = []
        vintage_frames: List[Tuple[datetime, pd.Series]] = []
        n_vintages_covering = 0
        for vintage in self._vintages_including_current_series:
            vintage_df = vintage.to_dataframe(mode="default", tz="utc")
            vintage_series = vintage_df.set_index("timestamp")["value"]
            vintage_frames.append((vintage.release_date, vintage_series))

            # Every supplied timestamp must exist in the vintage, otherwise the data cannot be a window of it.
            if not candidate.index.isin(vintage_series.index).all():
                continue
            n_vintages_covering += 1

            # With exact coverage the vintage must hold exactly the supplied timestamps and nothing more.
            if (
                require_exact_coverage
                and not vintage_series.index.isin(candidate.index).all()
            ):
                continue

            aligned_values = vintage_series.reindex(candidate.index).to_numpy(
                dtype=float
            )
            if decimals is not None:
                aligned_values = np.round(aligned_values, decimals)
            if np.isclose(
                candidate_values,
                aligned_values,
                rtol=rtol,
                atol=atol,
            ).all():
                matches.append(vintage.release_date)

        alignment_hint: Optional[str] = None
        time_shift: Optional[timedelta] = None
        if not matches:
            alignment_hint, time_shift = self._diagnose_misalignment(
                candidate,
                candidate_values,
                vintage_frames,
                rtol,
                atol,
                decimals,
                original_tz,
            )
            if alignment_hint is not None:
                logger.warning("No vintage matched, but %s.", alignment_hint)

        return VintageMatch(
            release_dates=sorted(matches),
            n_observations=len(candidate),
            rtol=rtol,
            atol=atol,
            decimals=decimals,
            n_vintages_compared=len(vintage_frames),
            n_vintages_covering=n_vintages_covering,
            alignment_hint=alignment_hint,
            time_shift=time_shift,
        )

    def _prepare_candidate_series(
        self, series: pd.Series
    ) -> Tuple[pd.Series, Optional[tzinfo]]:
        """
        Validate and normalize a user-supplied data series for vintage matching.

        Coerces the values to numeric, drops nulls, and renders the index as a sorted, unique, tz-aware UTC DatetimeIndex so it lines up with the timestamps produced by ``to_dataframe(tz="utc")``.
        A tz-naive index is interpreted in the source's native observation timezone (see ``_native_observation_timezone``), a PeriodIndex is taken at each period's start, and a numeric index is rejected.

        Args:
            series (pd.Series): The user-supplied data indexed by date.

        Returns:
            Tuple[pd.Series, Optional[tzinfo]]: The cleaned candidate series indexed by UTC timestamps, and the timezone the supplied index carried (None when it was tz-naive) so misalignment diagnostics can recover the original wall-clock times.

        Raises:
            TypeError: If ``series`` is not a pandas Series.
            ValueError: If ``series`` is empty, has a numeric, non-date, or duplicated index, or contains no non-null observations.
        """
        if not isinstance(series, pd.Series):
            raise TypeError(
                f"series must be a pandas Series, got {type(series).__name__}."
            )
        if series.empty:
            raise ValueError("The series is empty. There is nothing to match against.")

        candidate = pd.to_numeric(series, errors="raise").dropna()
        if candidate.empty:
            raise ValueError("The series contains no non-null observations to match.")

        index_data = candidate.index
        # Periods carry real dates; compare on each period's start timestamp.
        if isinstance(index_data, pd.PeriodIndex):
            index_data = index_data.to_timestamp()

        # Reject positional/numeric indexes before pd.to_datetime, which would
        # silently read them as nanosecond offsets from 1970-01-01.
        if pd.api.types.is_numeric_dtype(index_data):
            raise ValueError(
                "The series has a numeric index, not dates. Set the observation dates on the index before matching."
            )

        try:
            index = pd.to_datetime(index_data)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "The series must be indexed by dates that pandas can parse."
            ) from exc

        if not isinstance(index, pd.DatetimeIndex):
            raise ValueError("The series must be indexed by dates, not scalar values.")

        original_tz = index.tz
        if index.tz is None:
            native_tz = self._native_observation_timezone()
            logger.warning(
                "The series index has no timezone information. Interpreting it in "
                "the source's native observation timezone (%s).",
                native_tz,
            )
            index = index.tz_localize(native_tz).tz_convert("UTC")
        else:
            index = index.tz_convert("UTC")

        if index.has_duplicates:
            raise ValueError("The series index contains duplicate timestamps.")

        candidate.index = index
        return candidate.sort_index(), original_tz

    def _diagnose_misalignment(
        self,
        candidate: pd.Series,
        candidate_values: np.ndarray,
        vintage_frames: List[Tuple[datetime, pd.Series]],
        rtol: float,
        atol: float,
        decimals: Optional[int],
        original_tz: Optional[tzinfo],
    ) -> Tuple[Optional[str], Optional[timedelta]]:
        """
        Look for a timestamp reinterpretation under which the unmatched data would match.

        Runs the detectors from most to least specific: wrong timezone localization, a constant time shift, then a day-of-period convention mismatch. It stops at the first that fires.

        Args:
            candidate (pd.Series): The prepared candidate series (UTC index).
            candidate_values (np.ndarray): The candidate values, already rounded when ``decimals`` is set.
            vintage_frames (List[Tuple[datetime, pd.Series]]): Each vintage's release date and UTC-indexed values.
            rtol (float): Relative tolerance for the value comparison.
            atol (float): Absolute tolerance for the value comparison.
            decimals (Optional[int]): Decimals both sides are rounded to, or None.
            original_tz (Optional[tzinfo]): The timezone the supplied index carried, None when it was tz-naive.

        Returns:
            Tuple[Optional[str], Optional[timedelta]]: A human-readable hint and, for the constant-shift detector only, the shift that aligns the index. Both None when no detector fired.
        """
        hint = self._diagnose_wrong_timezone(
            candidate,
            candidate_values,
            vintage_frames,
            rtol,
            atol,
            decimals,
            original_tz,
        )
        if hint is not None:
            return hint, None

        hint, shift = self._diagnose_constant_shift(
            candidate, candidate_values, vintage_frames, rtol, atol, decimals
        )
        if hint is not None:
            return hint, shift

        hint = self._diagnose_period_alignment(
            candidate, candidate_values, vintage_frames, rtol, atol, decimals
        )
        return hint, None

    def _diagnose_wrong_timezone(
        self,
        candidate: pd.Series,
        candidate_values: np.ndarray,
        vintage_frames: List[Tuple[datetime, pd.Series]],
        rtol: float,
        atol: float,
        decimals: Optional[int],
        original_tz: Optional[tzinfo],
    ) -> Optional[str]:
        """
        Check whether the data matches when its wall-clock times are read in the source's native timezone.

        Only applies to a tz-aware index (a naive one already went through the native timezone), and catches indexes localized to the wrong timezone, including across DST changes where the error is not a constant offset.

        Returns:
            Optional[str]: The hint, or None when the detector did not fire.
        """
        if original_tz is None:
            return None
        native_tz = self._native_observation_timezone()
        wall_clock = candidate.index.tz_convert(original_tz).tz_localize(None)
        try:
            reinterpreted = wall_clock.tz_localize(native_tz).tz_convert("UTC")
        except Exception:
            # Wall-clock times that do not exist (or are ambiguous) in the
            # native timezone around a DST change cannot be reinterpreted.
            return None
        if reinterpreted.has_duplicates or reinterpreted.equals(candidate.index):
            return None

        n_matching = sum(
            self._candidate_matches_vintage(
                reinterpreted, vintage_series, candidate_values, rtol, atol, decimals
            )
            for _, vintage_series in vintage_frames
        )
        if n_matching == 0:
            return None
        return (
            f"the values match {n_matching} vintage(s) when the wall-clock times "
            f"are reinterpreted in the source's native observation timezone "
            f"({native_tz}) — the index appears to be localized to the wrong "
            f"timezone; pass a tz-naive index or localize it to {native_tz}"
        )

    def _diagnose_constant_shift(
        self,
        candidate: pd.Series,
        candidate_values: np.ndarray,
        vintage_frames: List[Tuple[datetime, pd.Series]],
        rtol: float,
        atol: float,
        decimals: Optional[int],
    ) -> Tuple[Optional[str], Optional[timedelta]]:
        """
        Check whether the data matches a vintage when its index is shifted by a constant offset.

        Offsets are anchored on aligning the first candidate timestamp to each vintage timestamp and pruned by requiring the middle and last timestamps to land in the vintage too, so only structurally possible shifts are value-checked.
        Skipped for short candidates, where some shift could match by coincidence (see ``MIN_OBSERVATIONS_FOR_SHIFT_DETECTION``).

        Returns:
            Tuple[Optional[str], Optional[timedelta]]: The hint and the shift to add to the index, or (None, None) when the detector did not fire.
        """
        if len(candidate) < MIN_OBSERVATIONS_FOR_SHIFT_DETECTION:
            return None, None

        first = candidate.index[0]
        middle = candidate.index[len(candidate) // 2]
        last = candidate.index[-1]
        shifts: Dict[timedelta, int] = {}
        for _, vintage_series in vintage_frames:
            offsets = vintage_series.index - first
            offsets = offsets[(middle + offsets).isin(vintage_series.index)]
            offsets = offsets[(last + offsets).isin(vintage_series.index)]
            for offset in offsets:
                if offset == pd.Timedelta(0):
                    # A zero shift is the comparison that already failed.
                    continue
                if self._candidate_matches_vintage(
                    candidate.index + offset,
                    vintage_series,
                    candidate_values,
                    rtol,
                    atol,
                    decimals,
                ):
                    shifts[offset] = shifts.get(offset, 0) + 1

        if not shifts:
            return None, None
        best = min(shifts, key=abs)
        direction = "forward" if best > pd.Timedelta(0) else "back"
        hint = (
            f"the values match {shifts[best]} vintage(s) when the index is "
            f"shifted {direction} by {abs(best)} — the timestamps appear to "
            f"follow a different convention than the stored observations"
        )
        return hint, best

    def _diagnose_period_alignment(
        self,
        candidate: pd.Series,
        candidate_values: np.ndarray,
        vintage_frames: List[Tuple[datetime, pd.Series]],
        rtol: float,
        atol: float,
        decimals: Optional[int],
    ) -> Optional[str]:
        """
        Check whether the data matches a vintage when both are compared by calendar period.

        Reduces both indexes to periods at the series frequency (daily or coarser), which washes out time-of-day and day-of-period conventions. This catches, for example, month-end dates against month-start storage, a mismatch that is not a constant offset.

        Returns:
            Optional[str]: The hint, or None when the detector did not fire.
        """
        try:
            freq = self._infer_pandas_freq()
        except (ValueError, TypeError):
            # Too few observations, or per-row DST offsets that pandas cannot
            # combine into a single tz-aware index.
            return None
        if freq is None:
            return None
        period_freq = get_period_alias(freq)
        if period_freq is None or period_freq[:1].upper() not in {
            "D",
            "W",
            "M",
            "Q",
            "A",
            "Y",
        }:
            return None

        candidate_periods = candidate.index.tz_localize(None).to_period(period_freq)
        if candidate_periods.has_duplicates:
            return None

        n_matching = 0
        for _, vintage_series in vintage_frames:
            vintage_periods = vintage_series.index.tz_localize(None).to_period(
                period_freq
            )
            if vintage_periods.has_duplicates:
                continue
            period_series = pd.Series(vintage_series.to_numpy(), index=vintage_periods)
            if self._candidate_matches_vintage(
                candidate_periods, period_series, candidate_values, rtol, atol, decimals
            ):
                n_matching += 1

        if n_matching == 0:
            return None
        return (
            f"the values match {n_matching} vintage(s) when compared by calendar "
            f"period ({period_freq}) — the index appears to use a different "
            f"day-of-period or time convention than the stored observations "
            f"(e.g. month-end instead of month-start dates)"
        )

    @staticmethod
    def _candidate_matches_vintage(
        index: pd.Index,
        vintage_series: pd.Series,
        candidate_values: np.ndarray,
        rtol: float,
        atol: float,
        decimals: Optional[int],
    ) -> bool:
        """
        Whether every index entry exists in the vintage with values agreeing within tolerance.

        Args:
            index (pd.Index): The (possibly reinterpreted) candidate index.
            vintage_series (pd.Series): The vintage values, indexed compatibly with ``index``.
            candidate_values (np.ndarray): The candidate values, already rounded when ``decimals`` is set.
            rtol (float): Relative tolerance for the value comparison.
            atol (float): Absolute tolerance for the value comparison.
            decimals (Optional[int]): Decimals to round the vintage values to, or None.

        Returns:
            bool: True when the index is fully covered and all values agree.
        """
        if not index.isin(vintage_series.index).all():
            return False
        aligned = vintage_series.reindex(index).to_numpy(dtype=float)
        if decimals is not None:
            aligned = np.round(aligned, decimals)
        return bool(np.isclose(candidate_values, aligned, rtol=rtol, atol=atol).all())

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
            v.to_dataframe() for v in self._vintages_including_current_series
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
        all_vintages = self._vintages_including_current_series

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
                ``"utc"`` (default) returns a tz-aware UTC ``datetime64[ns, UTC]`` column:
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

            # utc=True is required: source-localized observations carry per-row pytz
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

    def to_series(self, mode: str = "default", tz: str = "utc") -> pd.Series:
        """
        Converts the current observations of the time series to a date-indexed pandas Series.

        This is the values-only counterpart to ``to_dataframe``: the observation timestamps become the index and the values become the data.
        The Series is named after ``dataset_id`` so it carries a meaningful label when plotted or concatenated alongside other series.

        Args:
            mode (str, optional): The mode for which the series is provided.
                Supports "default" (unmodified observations), "first_difference" (first differences of observations), and "pct_change" (percentage change of observations).
                Defaults to "default".
            tz (str, optional): How to render the index. ``"utc"`` (default) returns a tz-aware UTC index; ``"source"`` returns a tz-naive index on the source's wall-clock calendar. See ``to_dataframe`` for the full explanation.

        Returns:
            pd.Series: The observation values indexed by timestamp, named after the dataset_id.
        """
        df = self.to_dataframe(mode=mode, tz=tz)
        series = df.set_index("timestamp")["value"]
        series.name = self.dataset_id
        return series

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
            for v in self._vintages_including_current_series
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

    @property
    def _timestamp_format(self) -> str:
        """
        The appropriate strftime format string based on the series frequency.
        Sub-daily frequencies include time and timezone, while daily and above show only the date.

        Returns:
            str: The strftime format string.
        """
        if not self.metadata.frequency:
            return "%Y-%m-%d"

        # Create a base date and add one frequency period to it
        # If the difference is less than 1 day, it's a sub-daily frequency
        base_date = pd.Timestamp("2020-01-01")
        next_date = base_date + pd.tseries.frequencies.to_offset(
            self.metadata.frequency
        )
        is_sub_daily = (next_date - base_date) < pd.Timedelta(days=1)

        if is_sub_daily:
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
        Parses a ``YYYY-MM-DD`` string to the source's midnight on that day.

        Date strings denote calendar days, never instants, so only the
        unambiguous ISO 8601 calendar form is accepted. Please pass a datetime
        object when a specific time matters. The day is anchored at midnight
        in the source's native timezone, which is how every source stamps its
        release dates and observation timestamps.

        Args:
            dt (str): The date string to parse, in ``YYYY-MM-DD`` form.

        Returns:
            datetime: The source-local midnight starting that calendar day.

        Raises:
            ValueError: If the string is not in ``YYYY-MM-DD`` form.
        """
        try:
            parsed_dt = datetime.strptime(dt, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"Invalid date string format {dt}. Date strings must be 'YYYY-MM-DD'; pass a datetime object to target a specific time."
            )
        return ensure_timezone(parsed_dt, self._native_observation_timezone())

    def _set_source(self, source: str):
        """Validate and set the data source."""
        source = source.upper()
        source_adapters = _source_adapters()
        try:
            self.source_adapter = source_adapters[source]
        except KeyError:
            raise ValueError(
                f"Unsupported source: {source}. "
                f"Must be one of {list(source_adapters)}"
            ) from None
        self.source = self.source_adapter.source

    def _clean_date(self, dt: str | datetime | date) -> Optional[datetime]:
        """
        Normalize a date input to an aware datetime on the source's clock.
        """
        if dt is None:
            return None
        if isinstance(dt, str):
            return self._parse_string_date(dt)
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                logger.warning(
                    "Datetime object provided without timezone info. "
                    "Interpreting it in the source's native timezone (%s).",
                    self._native_observation_timezone(),
                )
                dt = ensure_timezone(dt, self._native_observation_timezone())
            return dt
        if isinstance(dt, date):
            return ensure_timezone(
                datetime(dt.year, dt.month, dt.day),
                self._native_observation_timezone(),
            )
        raise TypeError(f"Invalid date format: {dt}")  # Not a string or datetime

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

    def _get_observations_for_release(
        self, release_pk: int, series_pk: Optional[int] = None
    ) -> List[Observation]:
        """Get observations associated with a release and, when given, a series."""
        conditions = [Observation.release == release_pk]
        if series_pk is not None:
            conditions.append(Observation.series == series_pk)
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

    @property
    def _vintage_window_description(self) -> str:
        """A human-readable description of the requested vintage window."""
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

    @property
    def _vintages_including_current_series(self) -> List["MTTimeSeries"]:
        """
        A list of all vintages including the current series.

        Returns:
            List[MTTimeSeries]: A list of all vintages including the current series.
        """
        return self.vintages + [self]

    def _native_observation_timezone(self) -> tzinfo:
        """
        The timezone this series' source stamps observation timestamps with.

        Looked up from the lightweight source adapter without constructing an
        API client or update manager.

        Returns:
            tzinfo: The source's declared observation timezone.
        """
        return self.source_adapter.native_observation_timezone

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
                    f"({self._vintage_window_description})."
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
        observations = self._get_observations_for_release(release.id, state.series.id)

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
