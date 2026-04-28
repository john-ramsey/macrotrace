import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
from darts import TimeSeries

from macrotrace.models import MTTimeSeries, MTObservation, MTSeriesMetadata
from tests.models.mt.utils import (
    sample_time_series,
    sample_time_series_with_revisions,
    empty_timeseries,
)


@pytest.fixture
def expected_vintage_matrix():
    """
    Based on the sample time series data, return the expected vintage matrix
    Note that this loads a dataframe from a CSV string assuming the following sample dates:
        Dates: 2024-12-01 to 2024-12-15
        Starting Value: 100
        Ascending: True

    Returns:
        pd.DataFrame: The expected vintage matrix.
    """
    expected_vm = pd.read_csv("tests/assets/mt/time_series/expected_vm.csv").set_index(
        "timestamp", drop=True
    )
    expected_vm.index = pd.to_datetime(expected_vm.index, utc=True)
    expected_vm.columns = pd.to_datetime(expected_vm.columns, utc=True)
    expected_vm.columns.name = "release_date"
    return expected_vm


def test_repr_with_metadata_and_vintages(sample_time_series_with_revisions):
    output = repr(sample_time_series_with_revisions)
    assert "Time Series: TEST (Gross TEST Product)" in output
    assert "Source: TEST" in output
    assert "Units: Billions of Dollars" in output
    assert (
        f"Vintages: {len(sample_time_series_with_revisions.vintages)} available"
        in output
    )
    assert "Timestamp" in output
    assert "Value" in output
    assert "Vintage Date" in output
    assert output.count("\n") > 10  # table is being printed


def test_repr_observation_limit(sample_time_series_with_revisions):
    output = repr(sample_time_series_with_revisions)
    # Check that only the last 10 observations are shown
    assert output.count("|") == 3 * 10 + 3  # 3 columns, 10 rows, plus headers
    last_obs = sample_time_series_with_revisions.current_observations[-1]
    assert str(last_obs.timestamp.date()) in output
    assert str(last_obs.release_date.date()) in output


def test_get_timestamp_formats(empty_timeseries):
    """Test that various frequencies return the correct timestamp formats."""
    frequencies_and_formats = {
        "D": "%Y-%m-%d",
        "h": "%Y-%m-%d %H:%M:%S %Z",
        "15min": "%Y-%m-%d %H:%M:%S %Z",
        "s": "%Y-%m-%d %H:%M:%S %Z",
        "W": "%Y-%m-%d",
        "MS": "%Y-%m-%d",
        "QS": "%Y-%m-%d",
    }

    for freq, expected_format in frequencies_and_formats.items():
        empty_timeseries.metadata = MagicMock(frequency=freq)
        format_str = empty_timeseries._get_timestamp_format()
        assert format_str == expected_format, f"Failed for frequency: {freq}"


def test_get_timestamp_format_no_frequency(empty_timeseries):
    """Test that no frequency returns date-only format."""
    empty_timeseries.metadata = MagicMock(frequency=None)
    format_str = empty_timeseries._get_timestamp_format()
    assert format_str == "%Y-%m-%d"


def test_get_timestamp_format_invalid_frequency_raises_error(empty_timeseries):
    """Test that invalid frequency defaults to date-only format."""
    empty_timeseries.metadata = MagicMock(frequency="INVALID")
    with pytest.raises(
        ValueError,
        match="Invalid frequency: INVALID",
    ):
        empty_timeseries._get_timestamp_format()


def test_to_dataframe(sample_time_series_with_revisions):
    df = sample_time_series_with_revisions.to_dataframe()
    expected_df = pd.DataFrame(
        [
            {
                "timestamp": datetime(2024, 12, 1, tzinfo=timezone.utc),
                "value": 103.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 2, tzinfo=timezone.utc),
                "value": 104.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 3, tzinfo=timezone.utc),
                "value": 105.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 4, tzinfo=timezone.utc),
                "value": 106.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 5, tzinfo=timezone.utc),
                "value": 107.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 6, tzinfo=timezone.utc),
                "value": 108.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 7, tzinfo=timezone.utc),
                "value": 109.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 8, tzinfo=timezone.utc),
                "value": 110.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 9, tzinfo=timezone.utc),
                "value": 111.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 10, tzinfo=timezone.utc),
                "value": 112.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 11, tzinfo=timezone.utc),
                "value": 112.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 12, tzinfo=timezone.utc),
                "value": 112.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 13, tzinfo=timezone.utc),
                "value": 112.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 14, tzinfo=timezone.utc),
                "value": 113.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
            {
                "timestamp": datetime(2024, 12, 15, tzinfo=timezone.utc),
                "value": 114.0,
                "release_date": datetime(2024, 12, 16, tzinfo=timezone.utc),
            },
        ]
    )

    pd.testing.assert_frame_equal(df, expected_df)


def test_to_dataframe_unsupported_mode(sample_time_series_with_revisions):
    with pytest.raises(
        ValueError,
        match="Invalid mode: invalid_mode. Supported modes are 'default', 'first_difference', and 'pct_change'.",
    ):
        sample_time_series_with_revisions.to_dataframe(mode="invalid_mode")


def test_to_dataframe_first_difference(sample_time_series):
    df = sample_time_series.to_dataframe(mode="first_difference")

    assert len(df) == 14
    # since the make observation function just adds one to the prior value, we expect all values to be the same
    assert len(df["value"].unique()) == 1


def test_to_dataframe_pct_change(sample_time_series):
    df = sample_time_series.to_dataframe(mode="pct_change")

    assert len(df) == 14
    assert len(df["value"].unique()) == 14
    # The percentage change from 100 to 101 is 1%
    assert df["value"].iloc[0] == pytest.approx(1.00, abs=1e-2)
    # The percentage change from 113 to 114 is approximately 0.88%
    assert df["value"].iloc[-1] == pytest.approx(0.88, abs=1e-2)


def test_generate_vintage_matrix(sample_time_series, expected_vintage_matrix):
    vm = sample_time_series.generate_vintage_matrix()

    pd.testing.assert_frame_equal(vm, expected_vintage_matrix)


def test_to_dataframe_handles_mixed_dst_offsets():
    """
    Regression test for the notebook bug where to_dataframe() raised
    `Tz-aware datetime.datetime cannot be converted to datetime64 unless utc=True`
    when the underlying observations spanned a DST transition.

    Source-localised observations carry distinct pytz tzinfo singletons for CST
    and CDT (e.g. ``<DstTzInfo 'America/Chicago' CST>`` vs
    ``<DstTzInfo 'America/Chicago' CDT>``); pandas refuses to coalesce these
    into a single ``datetime64[ns, tz]`` column unless we anchor on UTC.
    """
    import pytz

    chicago = pytz.timezone("America/Chicago")
    release_date = chicago.localize(datetime(2020, 6, 1))

    # Five monthly observations spanning the spring-2020 DST transition
    # (DST began 2020-03-08): Jan and Feb are CST, Mar/Apr/May are CDT.
    obs = [
        MTObservation(
            timestamp=chicago.localize(datetime(2020, m, 1)),
            value=100.0 + m,
            release_date=release_date,
        )
        for m in range(1, 6)
    ]

    # Verify the test setup actually has mixed offsets — otherwise the test
    # would silently pass even if the bug returned.
    offsets = {o.timestamp.utcoffset() for o in obs}
    assert offsets == {
        timedelta(hours=-6),
        timedelta(hours=-5),
    }, f"test setup must span DST; got offsets {offsets}"

    ts = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=release_date,
        current_observations=obs,
        vintages=[],
        source="TEST_SOURCE",
        units="Units",
        frequency="MS",
        title="DST Span",
        seasonal_adjustment="NSA",
    )

    # The original failure: this raised ValueError at the first CDT row.
    df = ts.to_dataframe()
    assert len(df) == 5
    # After the fix the column is anchored on UTC; absolute time is preserved.
    assert str(df["timestamp"].dt.tz) == "UTC"
    assert str(df["release_date"].dt.tz) == "UTC"
    # Sanity-check round-trip back to Chicago: original calendar dates survive.
    chicago_dates = df["timestamp"].dt.tz_convert(chicago).dt.date.tolist()
    assert chicago_dates == [datetime(2020, m, 1).date() for m in range(1, 6)]

    # generate_vintage_matrix is the path the failing notebook actually took
    # (via analysis.select_vintage_by_index → return_first_vintages).
    vm = ts.generate_vintage_matrix()
    assert len(vm) == 5
    assert str(vm.index.tz) == "UTC"


def test_is_revision_successful_true(empty_timeseries):
    assert (
        empty_timeseries._is_successful_revision(
            current_value=100.0,
            prior_value=99.0,
            final_value=101.0,
        )
        is True
    )


def test_is_revision_successful_false(empty_timeseries):
    assert (
        empty_timeseries._is_successful_revision(
            current_value=99.0,
            prior_value=100.0,
            final_value=101.0,
        )
        is False
    )


def test_is_revision_successful_nones(empty_timeseries):
    error_message = "Current value, prior value, and final value cannot be NaN for a successful revision."

    try:
        empty_timeseries._is_successful_revision(
            current_value=np.nan,
            prior_value=99.0,
            final_value=101.0,
        )
    except ValueError as e:
        assert str(e) == error_message

    try:
        empty_timeseries._is_successful_revision(
            current_value=100.0,
            prior_value=np.nan,
            final_value=101.0,
        )
    except ValueError as e:
        assert str(e) == error_message

    try:
        empty_timeseries._is_successful_revision(
            current_value=100.0,
            prior_value=99.0,
            final_value=np.nan,
        )
    except ValueError as e:
        assert str(e) == error_message


def test_is_revision_successful_negative_values(empty_timeseries):
    assert (
        empty_timeseries._is_successful_revision(
            current_value=-100.0,
            prior_value=-101.0,
            final_value=-99.0,
        )
        is True
    )

    assert (
        empty_timeseries._is_successful_revision(
            current_value=-101.0,
            prior_value=-100.0,
            final_value=-99.0,
        )
        is False
    )


def test_is_revision_successful_same_values(empty_timeseries):
    with pytest.raises(ValueError, match="Current value and prior value are the same."):
        empty_timeseries._is_successful_revision(
            current_value=100.0,
            prior_value=100.0,
            final_value=101.0,
        )


def test_vintages_including_current_series_includes_current(sample_time_series):
    vintages = sample_time_series._vintages_including_current_series()
    assert len(vintages) == len(sample_time_series.vintages) + 1
    assert sample_time_series in vintages


@patch("pandas.infer_freq")
def test_infer_pandas_freq(mock_infer_freq, sample_time_series):
    mock_infer_freq.return_value = "D"
    expected_call_arg = pd.DatetimeIndex(
        [obs.timestamp for obs in sample_time_series.current_observations]
    )

    freq = sample_time_series._infer_pandas_freq()

    # assert that pd.infer_freq was called once and with the correct argument
    mock_infer_freq.assert_called_once()
    actual_call_arg = mock_infer_freq.call_args[0][0]
    pd.testing.assert_index_equal(actual_call_arg, expected_call_arg)
    assert freq == mock_infer_freq.return_value


def test_infer_pandas_freq_not_enough_data(empty_timeseries):
    with pytest.raises(
        ValueError,
        match="Not enough observations to infer frequency. At least two observations are required.",
    ):
        empty_timeseries._infer_pandas_freq()


def test_as_of(sample_time_series):
    as_of_date = datetime(2024, 12, 10, tzinfo=timezone.utc)
    as_of_ts = sample_time_series.as_of(as_of_date)

    assert isinstance(as_of_ts, MTTimeSeries)  # Return type should be MTTimeSeries
    assert (
        as_of_ts.release_date <= as_of_date
    )  # Release date should be before or equal to as_of_date
    assert all(
        obs.timestamp <= as_of_date for obs in as_of_ts.current_observations
    )  # All observations should be before or equal to as_of_date
    assert all(
        vintage.release_date <= as_of_date for vintage in as_of_ts.vintages
    )  # All vintages should be before or equal to as_of_date


def test_as_of_date_parsing(sample_time_series):
    # converting to a string and back to simulate us cutting off the time component
    as_of_date_str = (datetime(2024, 12, 10)).strftime("%Y-%m-%d")
    as_of_date = datetime.strptime(as_of_date_str, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )

    # Create a mock that returns a valid vintage
    mock_find_eligible_vintages = MagicMock(
        return_value=[MagicMock(release_date=as_of_date)]
    )

    # Set up the mock
    sample_time_series._find_eligible_vintages = mock_find_eligible_vintages

    # Call as_of with the string
    as_of_ts = sample_time_series.as_of(as_of_date_str)

    # Verify the mock was called with the correctly parsed datetime
    mock_find_eligible_vintages.assert_called_once()
    called_date = mock_find_eligible_vintages.call_args[0][0]
    assert isinstance(called_date, datetime)
    assert called_date == as_of_date


def test_as_of_date_parsing_invalid(sample_time_series):
    as_of_date_str = "ABCDEF"  # Invalid date format for this test
    with pytest.raises(
        ValueError,
        match=f"Invalid date string format {as_of_date_str}. Please provide a datetime or a date string which can be parsed by dateutil.parser.",
    ):
        sample_time_series.as_of(as_of_date_str)


def test_as_of_not_a_datetime(sample_time_series):
    as_of_date_invalid = 12345  # Invalid type for this test
    with pytest.raises(
        ValueError,
        match=f"Invalid target date type: {type(as_of_date_invalid)}. Must be a string or a datetime.",
    ):
        sample_time_series.as_of(as_of_date_invalid)


def test_as_of_date_parsing_no_vintages_in_past(sample_time_series):
    # Simulate the user looking too far back in time
    as_of_date = "2000-01-01"
    with pytest.raises(
        ValueError,
        match="No vintages available. Are you sure the target date is valid?",
    ):
        sample_time_series.as_of(as_of_date)


def test_as_of_in_future(sample_time_series):
    future_date = (datetime.now() + timedelta(days=10)).astimezone()
    with pytest.raises(
        ValueError,
        match="The target date cannot be in the future.",
    ):
        sample_time_series.as_of(future_date)


def test_as_of_datetime_no_tz(sample_time_series, caplog):
    """Test that as_of raises a warning when given a naive datetime (no timezone)."""
    as_of_date = datetime(2024, 12, 10)  # No timezone info
    sample_time_series.as_of(as_of_date)

    assert (
        "Datetime object provided without timezone info. Assuming UTC." in caplog.text
    )


def test_to_darts_timeseries(sample_time_series):

    darts_ts = sample_time_series.to_darts_timeseries()

    assert isinstance(darts_ts, TimeSeries)
    assert len(darts_ts) == len(sample_time_series.current_observations)
    assert [i[0] for i in darts_ts.values()] == [
        i.value for i in sample_time_series.current_observations
    ]


def test_to_dataframe_tz_source_returns_naive_local_wall_clock():
    """`tz="source"` should hand back tz-naive stamps anchored on the source's
    wall-clock calendar — no UTC offset shift, even for non-UTC tz observations.
    """
    import pytz

    eastern = pytz.timezone("America/New_York")
    timestamps = [eastern.localize(datetime(2024, m, 1)) for m in (1, 2, 3)]
    release_date = eastern.localize(datetime(2024, 3, 15))
    observations = [
        MTObservation(timestamp=ts, value=float(i + 1), release_date=release_date)
        for i, ts in enumerate(timestamps)
    ]
    ts = MTTimeSeries._from_data(
        dataset_id="TZ_TEST",
        release_date=release_date,
        current_observations=observations,
        vintages=[],
        source="TEST_SOURCE",
        units="Units",
        frequency="MS",
        title="Tz Test",
        seasonal_adjustment="Not Applicable",
    )

    utc_df = ts.to_dataframe()  # default
    src_df = ts.to_dataframe(tz="source")

    # Default still UTC-anchored: midnight Eastern → 05:00 UTC.
    assert utc_df["timestamp"].dt.tz is not None
    assert utc_df["timestamp"].iloc[0].hour == 5

    # Source-local: tz-naive, hour 0, calendar dates match the source.
    assert src_df["timestamp"].dt.tz is None
    assert all(t.hour == 0 for t in src_df["timestamp"])
    assert [t.date() for t in src_df["timestamp"]] == [
        datetime(2024, 1, 1).date(),
        datetime(2024, 2, 1).date(),
        datetime(2024, 3, 1).date(),
    ]


def test_to_dataframe_invalid_tz_raises():
    ts = MTTimeSeries._from_data(
        dataset_id="TZ_TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=1.0,
                release_date=datetime(2024, 1, 2, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST_SOURCE",
        units="Units",
        frequency="MS",
        title="Tz Test",
        seasonal_adjustment="Not Applicable",
    )
    with pytest.raises(ValueError, match="Invalid tz"):
        ts.to_dataframe(tz="local")


def test_to_darts_timeseries_preserves_wall_clock_for_non_utc_source():
    """Sources like FRED store stamps in non-UTC tzs (e.g. America/New_York).
    The Darts conversion must drop the offset without shifting the wall clock —
    otherwise a midnight-local stamp lands on hour 5 UTC and falls off freq='MS'.
    """
    import pytz

    eastern = pytz.timezone("America/New_York")
    timestamps = [
        eastern.localize(datetime(2024, 1, 1)),
        eastern.localize(datetime(2024, 2, 1)),
        eastern.localize(datetime(2024, 3, 1)),
    ]
    release_date = eastern.localize(datetime(2024, 3, 15))
    observations = [
        MTObservation(timestamp=ts, value=float(i + 1), release_date=release_date)
        for i, ts in enumerate(timestamps)
    ]

    ts = MTTimeSeries._from_data(
        dataset_id="TZ_TEST",
        release_date=release_date,
        current_observations=observations,
        vintages=[],
        source="TEST_SOURCE",
        units="Units",
        frequency="MS",
        title="Tz Test",
        seasonal_adjustment="Not Applicable",
    )

    darts_ts = ts.to_darts_timeseries()

    assert [t.date() for t in pd.DatetimeIndex(darts_ts.time_index)] == [
        datetime(2024, 1, 1).date(),
        datetime(2024, 2, 1).date(),
        datetime(2024, 3, 1).date(),
    ]
    assert all(t.hour == 0 for t in pd.DatetimeIndex(darts_ts.time_index))


def test_get_historical_metadata_no_changes(sample_time_series):
    """Test that when metadata doesn't change, only one entry is returned."""
    historical_metadata = sample_time_series.get_historical_metadata()

    # Should only have one entry - the first time this metadata appeared
    assert len(historical_metadata) == 1
    # The key should be the earliest vintage date
    earliest_vintage_date = min(
        v.release_date for v in sample_time_series._vintages_including_current_series()
    )
    assert earliest_vintage_date in historical_metadata
    assert historical_metadata[earliest_vintage_date] == sample_time_series.metadata
    assert (
        historical_metadata[earliest_vintage_date].realtime_start
        == earliest_vintage_date
    )


def test_get_historical_metadata_title_change(empty_timeseries):
    """Test that title changes are detected."""
    # Create vintages with changing titles
    vintage1 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST",
        title="Original Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    vintage2 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
                value=101.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[vintage1],
        source="TEST",
        title="New Title",  # Changed
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    historical_metadata = vintage2.get_historical_metadata()

    # Should have two entries
    assert len(historical_metadata) == 2
    assert (
        historical_metadata[datetime(2024, 2, 1, tzinfo=timezone.utc)].title
        == "New Title"
    )
    assert (
        historical_metadata[datetime(2024, 1, 1, tzinfo=timezone.utc)].title
        == "Original Title"
    )


def test_get_historical_metadata_units_change(empty_timeseries):
    """Test that units changes are detected."""
    vintage1 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST",
        title="Title",
        units="Dollars",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    vintage2 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
                value=101.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[vintage1],
        source="TEST",
        title="Title",
        units="Billions of Dollars",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    historical_metadata = vintage2.get_historical_metadata()

    assert len(historical_metadata) == 2
    assert (
        historical_metadata[datetime(2024, 2, 1, tzinfo=timezone.utc)].units
        == "Billions of Dollars"
    )
    assert (
        historical_metadata[datetime(2024, 1, 1, tzinfo=timezone.utc)].units
        == "Dollars"
    )


def test_get_historical_metadata_frequency_change(empty_timeseries):
    """Test that frequency changes are detected."""
    vintage1 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST",
        title="Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    vintage2 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
                value=101.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[vintage1],
        source="TEST",
        title="Title",
        units="Units",
        frequency="MS",
        seasonal_adjustment="Not Adjusted",
    )

    historical_metadata = vintage2.get_historical_metadata()

    assert len(historical_metadata) == 2
    assert (
        historical_metadata[datetime(2024, 2, 1, tzinfo=timezone.utc)].frequency == "MS"
    )
    assert (
        historical_metadata[datetime(2024, 1, 1, tzinfo=timezone.utc)].frequency == "D"
    )


def test_get_historical_metadata_seasonal_adjustment_change(empty_timeseries):
    """Test that seasonal adjustment changes are detected."""
    vintage1 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST",
        title="Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    vintage2 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
                value=101.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[vintage1],
        source="TEST",
        title="Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Seasonally Adjusted",
    )

    historical_metadata = vintage2.get_historical_metadata()

    assert len(historical_metadata) == 2
    assert (
        historical_metadata[
            datetime(2024, 2, 1, tzinfo=timezone.utc)
        ].seasonal_adjustment
        == "Seasonally Adjusted"
    )
    assert (
        historical_metadata[
            datetime(2024, 1, 1, tzinfo=timezone.utc)
        ].seasonal_adjustment
        == "Not Adjusted"
    )


def test_get_historical_metadata_ignores_temporal_changes(empty_timeseries):
    """Test that temporal field changes (realtime_start, realtime_end, observation_start, observation_end) are ignored."""
    # Create vintages where only temporal fields change
    vintage1 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST",
        title="Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    # Second vintage has different temporal fields but same substantive metadata
    vintage2 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            ),
            MTObservation(
                timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
                value=101.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            ),
        ],
        vintages=[vintage1],
        source="TEST",
        title="Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    historical_metadata = vintage2.get_historical_metadata()

    # Should only have one entry since substantive metadata didn't change
    # (even though realtime_end and observation_end would be different).
    # The key should be the first time this metadata appeared (vintage1's date),
    # but the metadata value should reflect the latest temporal range in the epoch.
    assert len(historical_metadata) == 1
    assert datetime(2024, 1, 1, tzinfo=timezone.utc) in historical_metadata
    assert (
        historical_metadata[datetime(2024, 1, 1, tzinfo=timezone.utc)]
        == vintage2.metadata
    )


def test_get_historical_metadata_updates_latest_temporal_fields_within_epoch():
    """Test that unchanged metadata epochs are keyed by first appearance but carry the latest temporal fields."""
    vintage1 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST",
        title="Original Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    vintage2 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            ),
            MTObservation(
                timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
                value=101.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            ),
        ],
        vintages=[vintage1],
        source="TEST",
        title="New Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    vintage3 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
            ),
            MTObservation(
                timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
                value=101.0,
                release_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
            ),
            MTObservation(
                timestamp=datetime(2024, 3, 1, tzinfo=timezone.utc),
                value=102.0,
                release_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
            ),
        ],
        vintages=[vintage1, vintage2],
        source="TEST",
        title="New Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    historical_metadata = vintage3.get_historical_metadata()

    assert set(historical_metadata.keys()) == {
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 2, 1, tzinfo=timezone.utc),
    }
    assert (
        historical_metadata[datetime(2024, 2, 1, tzinfo=timezone.utc)].title
        == vintage3.metadata.title
    )
    assert (
        historical_metadata[datetime(2024, 2, 1, tzinfo=timezone.utc)].observation_end
        == vintage3.metadata.observation_end
    )
    assert historical_metadata[
        datetime(2024, 2, 1, tzinfo=timezone.utc)
    ].realtime_start == datetime(2024, 2, 1, tzinfo=timezone.utc)
    assert (
        historical_metadata[datetime(2024, 2, 1, tzinfo=timezone.utc)].realtime_end
        == vintage3.metadata.realtime_end
    )


def test_get_historical_metadata_multiple_changes():
    """Test tracking multiple metadata changes across several vintages."""
    vintage1 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST",
        title="V1 Title",
        units="Dollars",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    # No change in vintage 2
    vintage2 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 2, 1, tzinfo=timezone.utc),
                value=101.0,
                release_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[vintage1],
        source="TEST",
        title="V1 Title",
        units="Dollars",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    # Title change in vintage 3
    vintage3 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 3, 1, tzinfo=timezone.utc),
                value=102.0,
                release_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[vintage1, vintage2],
        source="TEST",
        title="V3 Title",
        units="Dollars",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    # Units change in vintage 4
    vintage4 = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 4, 1, tzinfo=timezone.utc),
                value=103.0,
                release_date=datetime(2024, 4, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[vintage1, vintage2, vintage3],
        source="TEST",
        title="V3 Title",
        units="Billions",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    historical_metadata = vintage4.get_historical_metadata()

    # Should have 3 entries: v4 (current), v3 (title changed), v1 (original metadata)
    # Note: v2 is not included because it has the same metadata as v1
    assert len(historical_metadata) == 3
    assert datetime(2024, 4, 1, tzinfo=timezone.utc) in historical_metadata
    assert datetime(2024, 3, 1, tzinfo=timezone.utc) in historical_metadata
    assert datetime(2024, 1, 1, tzinfo=timezone.utc) in historical_metadata

    # Verify the metadata values
    assert (
        historical_metadata[datetime(2024, 4, 1, tzinfo=timezone.utc)].units
        == "Billions"
    )
    assert (
        historical_metadata[datetime(2024, 4, 1, tzinfo=timezone.utc)].title
        == "V3 Title"
    )

    assert (
        historical_metadata[datetime(2024, 3, 1, tzinfo=timezone.utc)].units
        == "Dollars"
    )
    assert (
        historical_metadata[datetime(2024, 3, 1, tzinfo=timezone.utc)].title
        == "V3 Title"
    )

    assert (
        historical_metadata[datetime(2024, 1, 1, tzinfo=timezone.utc)].units
        == "Dollars"
    )
    assert (
        historical_metadata[datetime(2024, 1, 1, tzinfo=timezone.utc)].title
        == "V1 Title"
    )


def test_get_historical_metadata_empty_vintages(empty_timeseries):
    """Test get_historical_metadata with no vintages (only current series)."""
    ts = MTTimeSeries._from_data(
        dataset_id="TEST",
        release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        current_observations=[
            MTObservation(
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                value=100.0,
                release_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        vintages=[],
        source="TEST",
        title="Title",
        units="Units",
        frequency="D",
        seasonal_adjustment="Not Adjusted",
    )

    historical_metadata = ts.get_historical_metadata()

    # Should have exactly one entry (the current series)
    assert len(historical_metadata) == 1
    assert datetime(2024, 1, 1, tzinfo=timezone.utc) in historical_metadata
    assert historical_metadata[datetime(2024, 1, 1, tzinfo=timezone.utc)] == ts.metadata


def test_return_first_vintages(sample_time_series_with_revisions):
    """Test that return_first_vintages returns the correct first vintage for each observation."""
    first_vintages = sample_time_series_with_revisions.return_first_vintages()

    # Should return a DataFrame with timestamp, first_vintage_date, and value columns
    assert isinstance(first_vintages, pd.DataFrame)
    assert set(first_vintages.columns) == {"timestamp", "first_vintage_date", "value"}

    # Each observation should have exactly one first vintage
    assert len(first_vintages) == len(
        first_vintages["timestamp"].unique()
    ), "Each observation should have exactly one first vintage"

    # All first_vintage_dates should be unique or repeated for different timestamps
    # but each timestamp should only appear once
    assert (
        first_vintages.duplicated(subset=["timestamp"]).sum() == 0
    ), "No duplicate timestamps should exist"


def test_return_first_vintages_values(empty_timeseries):
    """Test that return_first_vintages returns the correct values."""
    # Mock vintage matrix with specific pattern
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=pd.DataFrame(
            {
                "2024-01-01": [100.0, pd.NA, pd.NA],
                "2024-02-01": [101.0, 200.0, pd.NA],
                "2024-03-01": [102.0, 201.0, 300.0],
            },
            index=[
                datetime(2024, 1, 1),
                datetime(2024, 2, 1),
                datetime(2024, 3, 1),
            ],
        )
    )

    first_vintages = empty_timeseries.return_first_vintages()

    # Check first observation appeared in first vintage
    row_1 = first_vintages[first_vintages["timestamp"] == datetime(2024, 1, 1)]
    assert len(row_1) == 1
    assert row_1["first_vintage_date"].iloc[0] == "2024-01-01"
    assert row_1["value"].iloc[0] == 100.0

    # Check second observation appeared in second vintage
    row_2 = first_vintages[first_vintages["timestamp"] == datetime(2024, 2, 1)]
    assert len(row_2) == 1
    assert row_2["first_vintage_date"].iloc[0] == "2024-02-01"
    assert row_2["value"].iloc[0] == 200.0

    # Check third observation appeared in third vintage
    row_3 = first_vintages[first_vintages["timestamp"] == datetime(2024, 3, 1)]
    assert len(row_3) == 1
    assert row_3["first_vintage_date"].iloc[0] == "2024-03-01"
    assert row_3["value"].iloc[0] == 300.0


def test_return_first_vintages_with_filters_warning(
    sample_time_series_with_revisions, caplog
):
    """Test that a warning is logged when vintage filters are applied."""
    # Set vintage filters
    sample_time_series_with_revisions.vintage_start_date = datetime(
        2024, 12, 10, tzinfo=timezone.utc
    )

    first_vintages = sample_time_series_with_revisions.return_first_vintages()

    # Check that warning was logged
    assert (
        "Vintage date filters are currently applied" in caplog.text
    ), "Warning should be logged when vintage filters are set"


def test_return_first_vintages_empty_matrix(empty_timeseries):
    """Test that return_first_vintages with an empty vintage matrix raises a ValueError."""
    # Mock empty vintage matrix
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=pd.DataFrame(columns=[], index=[])
    )

    with pytest.raises(
        ValueError,
        match="No vintage data available for selection.",
    ):
        empty_timeseries.return_first_vintages()


def test_return_first_vintages_all_na(empty_timeseries):
    """Test return_first_vintages when all values are NaN for an observation."""
    # Mock vintage matrix where one observation is all NaN
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=pd.DataFrame(
            {
                "2024-01-01": [100.0, pd.NA],
                "2024-02-01": [101.0, pd.NA],
                "2024-03-01": [102.0, pd.NA],
            },
            index=[
                datetime(2024, 1, 1),
                datetime(2024, 2, 1),
            ],
        )
    )

    first_vintages = empty_timeseries.return_first_vintages()

    # Only the first observation should be in the result (second has all NaN)
    assert len(first_vintages) == 1
    assert first_vintages["timestamp"].iloc[0] == datetime(2024, 1, 1)
    assert first_vintages["first_vintage_date"].iloc[0] == "2024-01-01"
    assert first_vintages["value"].iloc[0] == 100.0
