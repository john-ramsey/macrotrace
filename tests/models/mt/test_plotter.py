import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from tests.models.mt.utils import (
    sample_time_series,
    sample_time_series_with_revisions,
    empty_timeseries,
)
from macrotrace.graphing import MACROTRACE_PLOTLY_LAYOUT_TEMPLATE
from macrotrace.models.mt.plotter import MTTimeSeriesPlotter
from tests.models.mt.utils import UTC


def test_find_nearest_observation_datetime_daily_exact_match(sample_time_series):
    """Test that exact date matches work for daily+ frequency data."""
    plotter = sample_time_series.plot
    vm = sample_time_series.generate_vintage_matrix()

    # Pick a date that exists in the index
    target_date = vm.index[5]

    # Should return the exact datetime
    result = plotter._find_nearest_observation_datetime(target_date, vm.index)
    assert result == target_date


def test_find_nearest_observation_datetime_daily_date_only_match(sample_time_series):
    """Test that date-only strings match correctly for daily+ frequency data."""
    plotter = sample_time_series.plot
    vm = sample_time_series.generate_vintage_matrix()

    # Get a datetime from the index and create a date-only version
    existing_dt = vm.index[5]
    date_only = existing_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    # Should find the matching date even with different time
    result = plotter._find_nearest_observation_datetime(date_only, vm.index)
    assert result.date() == existing_dt.date()


def test_find_nearest_observation_datetime_daily_no_match_raises_error(
    sample_time_series,
):
    """Test that non-existent dates raise helpful errors for daily+ frequency."""
    plotter = sample_time_series.plot
    vm = sample_time_series.generate_vintage_matrix()

    # Pick a date that doesn't exist
    target_date = datetime(2000, 1, 1, tzinfo=vm.index[0].tzinfo)

    with pytest.raises(ValueError, match="No observation found for date"):
        plotter._find_nearest_observation_datetime(target_date, vm.index)


def test_find_nearest_observation_datetime_subdaily_exact_match():
    """Test exact match for subdaily data."""
    # Create a subdaily index (hourly data)
    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")

    mock_ts = MagicMock()
    mock_ts.metadata.frequency = "Hourly"
    plotter = MTTimeSeriesPlotter(mock_ts)

    target = index[10]
    result = plotter._find_nearest_observation_datetime(target, index)
    assert result == target


def test_find_nearest_observation_datetime_subdaily_nearest_match():
    """Test nearest match for subdaily data within tolerance."""
    # Create hourly data
    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")

    mock_ts = MagicMock()
    mock_ts.metadata.frequency = "Hourly"
    plotter = MTTimeSeriesPlotter(mock_ts)

    # Target is 30 minutes after an observation (within tolerance)
    target = index[10] + pd.Timedelta(minutes=30)
    result = plotter._find_nearest_observation_datetime(target, index)

    # Should return the nearest hour
    assert result == index[10]


def test_find_nearest_observation_datetime_subdaily_outside_tolerance():
    """Test that subdaily data outside tolerance raises error."""
    # Create hourly data
    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")

    mock_ts = MagicMock()
    mock_ts.metadata.frequency = "Hourly"
    plotter = MTTimeSeriesPlotter(mock_ts)

    # Target is 5 hours away from any observation (outside 2x median tolerance)
    target = index[-1] + pd.Timedelta(hours=5)

    with pytest.raises(ValueError, match="No observation found within"):
        plotter._find_nearest_observation_datetime(target, index)


def test_find_nearest_observation_datetime_subdaily_minute():
    """Test nearest match for minute-level data within tolerance."""
    # Create minute-level data
    index = pd.date_range("2024-01-01", periods=60, freq="min", tz="UTC")

    mock_ts = MagicMock()
    mock_ts.metadata.frequency = "Minutely"
    plotter = MTTimeSeriesPlotter(mock_ts)

    # Target is 15 seconds after an observation (within tolerance)
    target = index[30] + pd.Timedelta(seconds=15)
    result = plotter._find_nearest_observation_datetime(target, index)

    # Should return the nearest minute
    assert result == index[30]


def test_find_nearest_observation_datetime_subdaily_outside_minute_tolerance():
    """Test that minute-level data outside tolerance raises error."""
    # Create minute-level data
    index = pd.date_range("2024-01-01", periods=60, freq="min", tz="UTC")

    mock_ts = MagicMock()
    mock_ts.metadata.frequency = "Minutely"
    plotter = MTTimeSeriesPlotter(mock_ts)

    # Target is 5 minutes away from any observation (outside 2x median tolerance)
    target = index[-1] + pd.Timedelta(minutes=5)

    with pytest.raises(ValueError, match="No observation found within"):
        plotter._find_nearest_observation_datetime(target, index)


def test_find_nearest_observation_datetime_subdaily_one_observation():
    """Test behavior with only one observation in subdaily data."""
    # Create single observation index
    index = pd.DatetimeIndex(["2024-01-01 12:00:00"], tz="UTC")

    mock_ts = MagicMock()
    mock_ts.metadata.frequency = "Hourly"
    plotter = MTTimeSeriesPlotter(mock_ts)

    # Exact match should work
    target = index[0]
    result = plotter._find_nearest_observation_datetime(target, index)
    assert result == target

    # Different date should raise error
    target_different = datetime(2024, 1, 2, 12, 0, 0, tzinfo=index[0].tzinfo)
    with pytest.raises(ValueError):
        plotter._find_nearest_observation_datetime(target_different, index)


def test_find_nearest_observation_datetime_single_observation():
    """Test behavior with only one observation in the index."""
    # Create single observation index
    index = pd.DatetimeIndex(["2024-01-01"], tz="UTC")

    mock_ts = MagicMock()
    plotter = MTTimeSeriesPlotter(mock_ts)

    # Exact match should work
    target = index[0]
    result = plotter._find_nearest_observation_datetime(target, index)
    assert result == target

    # Different date should raise error
    target_different = datetime(2024, 2, 1, tzinfo=index[0].tzinfo)
    with pytest.raises(ValueError):
        plotter._find_nearest_observation_datetime(target_different, index)


def test_plot_timeseries_title(sample_time_series):
    fig = sample_time_series.plot.timeseries()

    assert (
        fig.layout.title.text
        == f"{sample_time_series.metadata.title} - {sample_time_series.metadata.dataset_id}<br><sup>{sample_time_series.metadata.units}</sup>"
    )
    assert fig.layout.yaxis.title.text == f"{sample_time_series.metadata.units}"


def test_plot_timeseries_with_vintage_range(sample_time_series_with_revisions):
    """Test timeseries plot with vintage range bands enabled."""
    fig = sample_time_series_with_revisions.plot.timeseries(show_vintage_range=True)

    assert isinstance(fig, go.Figure)
    # Should have 2 traces: the shaded band and the main line
    assert len(fig.data) == 2

    # First trace should be the shaded range band (fill)
    assert fig.data[0].fill == "toself"
    assert fig.layout.showlegend is False
    assert "rgba" in fig.data[0].fillcolor  # Should have transparency

    # Second trace should be the main line
    assert fig.data[1].mode == "lines"
    assert fig.data[1].name == "Current Vintage"


def test_plot_timeseries_with_vintage_range_uses_template_colors(
    sample_time_series_with_revisions,
):
    """Test that vintage range bands use colors from the template."""
    fig = sample_time_series_with_revisions.plot.timeseries(show_vintage_range=True)

    primary_color = MACROTRACE_PLOTLY_LAYOUT_TEMPLATE["layout"]["colorway"][0]

    # Main line should use the primary color
    assert fig.data[1].line.color == primary_color


def test_plot_timeseries_without_vintage_range(sample_time_series):
    """Test timeseries plot with vintage range disabled (default)."""
    fig = sample_time_series.plot.timeseries(show_vintage_range=False)

    assert isinstance(fig, go.Figure)
    # Should have only 1 trace (the main line, no shaded band)
    assert len(fig.data) == 1
    assert fig.layout.showlegend is False
    assert fig.data[0].type == "scatter"


def test_plot_timeseries_comparison(sample_time_series):
    fig = sample_time_series.plot.timeseries_comparison(
        [v.release_date for v in sample_time_series.vintages],
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == len(sample_time_series.vintages)
    assert fig.layout.title.text.startswith(
        f"Comparison of Vintages - {sample_time_series.metadata.title}"
    )
    assert fig.layout.yaxis.title.text == f"{sample_time_series.metadata.units}"


def test_plot_timeseries_comparison_invalid_mode(sample_time_series):
    with pytest.raises(
        ValueError,
        match="Invalid mode: invalid_mode. Supported modes are 'default', 'first_difference', and 'pct_change'.",
    ):
        sample_time_series.plot.timeseries_comparison(
            [v.release_date for v in sample_time_series.vintages],
            mode="invalid_mode",
        )


def test_plot_timeseries_comparison_invalid_vintage_date_type(sample_time_series):
    with pytest.raises(
        TypeError,
        match="Vintage dates must be provided as strings or datetime objects.",
    ):
        sample_time_series.plot.timeseries_comparison(
            [v.release_date for v in sample_time_series.vintages] + [12345],
        )


def test_plot_timeseries_comparison_passes_first_difference(sample_time_series):
    vintages = [v.release_date for v in sample_time_series.vintages]

    # Create a map: release_date -> mock_vintage
    vintage_mocks = {}
    for i, release_date in enumerate(vintages):
        mock_vintage = MagicMock()
        mock_vintage.to_dataframe.return_value = {
            # different sample data and vintages than the sample_time_series
            # this is fine considering we aren't testing values
            "timestamp": [
                datetime(2024, 12, 10),
                datetime(2024, 12, 11),
                datetime(2024, 12, 12),
            ],
            "value": [i, i + 1, i + 2],
        }
        vintage_mocks[release_date] = mock_vintage

    # Patch as_of to return the right mock depending on release_date
    def fake_as_of(release_date):
        return vintage_mocks[release_date]

    sample_time_series.as_of = MagicMock(side_effect=fake_as_of)

    fig = sample_time_series.plot.timeseries_comparison(
        vintages,
        mode="first_difference",
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == len(vintages)
    assert fig.layout.title.text.startswith(
        f"Comparison of Vintages - {sample_time_series.metadata.title} (Period over Period Change)"
    )
    assert fig.layout.yaxis.title.text == f"△ {sample_time_series.metadata.units}"

    # Every mock vintage should have been called with mode="first_difference"
    for vdate, mock_vintage in vintage_mocks.items():
        mock_vintage.to_dataframe.assert_called_once_with(mode="first_difference")


def test_plot_timeseries_comparison_passes_percent_change(sample_time_series):
    vintages = [v.release_date for v in sample_time_series.vintages]

    # Create a map: release_date -> mock_vintage
    vintage_mocks = {}
    for i, release_date in enumerate(vintages):
        mock_vintage = MagicMock()
        mock_vintage.to_dataframe.return_value = {
            # different sample data and vintages than the sample_time_series
            # this is fine considering we aren't testing values
            "timestamp": [
                datetime(2024, 12, 10),
                datetime(2024, 12, 11),
                datetime(2024, 12, 12),
            ],
            "value": [i, i + 1, i + 2],
        }
        vintage_mocks[release_date] = mock_vintage

    # Patch as_of to return the right mock depending on release_date
    def fake_as_of(release_date):
        return vintage_mocks[release_date]

    sample_time_series.as_of = MagicMock(side_effect=fake_as_of)

    fig = sample_time_series.plot.timeseries_comparison(
        vintages,
        mode="pct_change",
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == len(vintages)
    assert fig.layout.title.text.startswith(
        f"Comparison of Vintages - {sample_time_series.metadata.title} (Percentage Change)"
    )
    assert fig.layout.yaxis.title.text == "% Change"

    # Every mock vintage should have been called with mode="pct_change"
    for _, mock_vintage in vintage_mocks.items():
        mock_vintage.to_dataframe.assert_called_once_with(mode="pct_change")


def test_plot_timeseries_comparison_line_chart(sample_time_series):
    fig = sample_time_series.plot.timeseries_comparison(
        [v.release_date for v in sample_time_series.vintages],
        chart_type="line",
    )

    # Check that the figure is a line chart
    assert fig.data[0].type == "scatter"
    assert fig.data[0].mode == "lines+markers"


def test_plot_timeseries_comparison_invalid_chart_type(sample_time_series):
    with pytest.raises(
        ValueError,
        match="Unknown chart type: invalid_example. Accepted values are 'bar' or 'line'.",
    ):
        sample_time_series.plot.timeseries_comparison(
            [v.release_date for v in sample_time_series.vintages],
            chart_type="invalid_example",
        )


def test_plot_revision_cross_correlogram_heatmap(sample_time_series_with_revisions):
    sample_time_series_with_revisions.analysis.revision_cross_correlogram = MagicMock(
        return_value={
            "correlogram": [[1.0, 0.5], [0.4, 0.2]],
            "vintage_lags": [0, 1],
            "observation_lags": [0, 1],
            "pair_counts": [[10, 8], [9, 7]],
        }
    )

    fig = sample_time_series_with_revisions.plot.revision_cross_correlogram_heatmap()

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "heatmap"
    assert fig.layout.title.text.startswith(
        "Revision Cross-Correlogram (Vintage Lag vs Observation Lag)"
    )
    assert list(fig.data[0].x) == [0, 1]
    assert list(fig.data[0].y) == [0, 1]
    assert fig.layout.xaxis.title.text == "Vintage Lag"
    assert fig.layout.yaxis.title.text == "Observation Lag"
    assert fig.data[0].z == ([1.0, 0.5], [0.4, 0.2])
    assert fig.data[0].colorscale == tuple(
        tuple(color_stop)
        for color_stop in MACROTRACE_PLOTLY_LAYOUT_TEMPLATE["layout"]["colorscale"][
            "diverging"
        ]
    )


def test_plot_revision_cross_correlogram_heatmap_calls_analysis(
    sample_time_series_with_revisions,
):
    correlation_mock = MagicMock(
        return_value={
            "correlogram": [[0.5]],
            "vintage_lags": [0],
            "observation_lags": [0],
            "pair_counts": [[10]],
        }
    )
    sample_time_series_with_revisions.analysis.revision_cross_correlogram = (
        correlation_mock
    )

    fig = sample_time_series_with_revisions.plot.revision_cross_correlogram_heatmap()

    assert isinstance(fig, go.Figure)
    correlation_mock.assert_called_once_with(
        max_vintage_lag=None, max_observation_lag=None
    )


def test_plot_revision_histogram_first_difference(sample_time_series_with_revisions):
    fig = sample_time_series_with_revisions.plot.revision_histogram(
        mode="first_difference"
    )

    assert isinstance(fig, go.Figure)

    # Assert the titles are correct
    assert fig.layout.title.text == (
        f"Histogram of Revisions - {sample_time_series_with_revisions.metadata.title}"
    )
    assert fig.layout.xaxis.title.text == "Revision Value"
    # All revisions should be 1.0 since the make_observations function just adds 1 each time
    assert len(fig.data[0].x) == 33
    assert all(x == 1.0 for x in fig.data[0].x)


def test_plot_revision_histogram_pct_change(sample_time_series_with_revisions):
    fig = sample_time_series_with_revisions.plot.revision_histogram(mode="pct_change")

    assert isinstance(fig, go.Figure)

    # Assert the titles are correct
    assert (
        fig.layout.title.text
        == f"Histogram of Revisions - {sample_time_series_with_revisions.metadata.title}"
    )
    assert fig.layout.xaxis.title.text == "Revision %"
    assert len(fig.data[0].x) == 33
    assert all(x > 0 for x in fig.data[0].x)
    assert all(round(x, 2) <= 1.0 for x in fig.data[0].x)


def test_plot_revision_histogram_invalid_mode(sample_time_series_with_revisions):
    invalid_mode = "ABC"

    with pytest.raises(
        ValueError,
        match=f"Invalid mode: {invalid_mode}. Supported modes are 'first_difference' and 'pct_change'.",
    ):
        sample_time_series_with_revisions.plot.revision_histogram(mode=invalid_mode)


def test_plot_observation_over_time_basic(sample_time_series_with_revisions):
    """Test basic observation over time plot with default parameters."""
    vm = sample_time_series_with_revisions.generate_vintage_matrix()
    observation_date = vm.index[5]
    expected_x = pd.to_datetime(vm.loc[observation_date].dropna().index).tz_localize(
        None
    )

    fig = sample_time_series_with_revisions.plot.observation_over_time(observation_date)

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "bar"
    assert fig.layout.title.text.startswith("Observation Over Time")
    assert pd.to_datetime(fig.data[0].x).tolist() == expected_x.tolist()
    assert fig.layout.xaxis.title.text == "Vintage Date"
    assert fig.layout.yaxis.title.text == "Value"


def test_plot_observation_over_time_string_input(sample_time_series_with_revisions):
    """Test observation over time with string datetime input."""
    vm = sample_time_series_with_revisions.generate_vintage_matrix()
    observation_date = vm.index[5]
    date_string = observation_date.strftime("%Y-%m-%d")

    fig = sample_time_series_with_revisions.plot.observation_over_time(date_string)

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "bar"


def test_plot_observation_over_time_first_difference(
    sample_time_series_with_revisions,
):
    """Test observation over time with first difference mode."""
    vm = sample_time_series_with_revisions.generate_vintage_matrix()
    observation_date = vm.index[5]

    fig = sample_time_series_with_revisions.plot.observation_over_time(
        observation_date, first_difference=True
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    # With first difference, we should have one fewer data point
    assert len(vm.loc[observation_date].dropna()) - 1 == len(fig.data[0].y)
    assert fig.layout.yaxis.title.text == "Revision Value"


def test_plot_observation_over_time_line_chart(sample_time_series_with_revisions):
    """Test observation over time with line chart type."""
    vm = sample_time_series_with_revisions.generate_vintage_matrix()
    observation_date = vm.index[5]

    fig = sample_time_series_with_revisions.plot.observation_over_time(
        observation_date, chart_type="line"
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "scatter"
    assert fig.data[0].mode == "lines+markers"
    assert fig.layout.xaxis.title.text == "Vintage Date"


def test_plot_observation_over_time_fuzzy_match_disabled(
    sample_time_series_with_revisions,
):
    """Test observation over time with fuzzy matching disabled."""
    vm = sample_time_series_with_revisions.generate_vintage_matrix()
    observation_date = vm.index[5]

    # With exact datetime, should work
    fig = sample_time_series_with_revisions.plot.observation_over_time(
        observation_date, fuzzy_datetime_match=False
    )
    assert isinstance(fig, go.Figure)

    # With date-only string and fuzzy disabled, should raise error
    date_string = observation_date.strftime("%Y-%m-%d")
    date_only = datetime.strptime(date_string, "%Y-%m-%d")
    date_only = date_only.replace(tzinfo=observation_date.tzinfo)

    # This should fail if the timestamp has a time component
    if observation_date.time() != date_only.time():
        with pytest.raises(ValueError, match="not found in time series data"):
            sample_time_series_with_revisions.plot.observation_over_time(
                date_only, fuzzy_datetime_match=False
            )


def test_plot_observation_over_time_invalid_datetime_type(
    sample_time_series_with_revisions,
):
    """Test observation over time with invalid datetime type."""
    with pytest.raises(
        ValueError,
        match="Invalid observation datetime type.*Must be a string or a datetime",
    ):
        sample_time_series_with_revisions.plot.observation_over_time(12345)


def test_plot_observation_over_time_nonexistent_date_fuzzy_enabled(
    sample_time_series_with_revisions,
):
    """Test observation over time with a date that doesn't exist in the data."""
    nonexistent_date = datetime(2000, 1, 1, tzinfo=UTC)

    with pytest.raises(
        ValueError, match=f"No observation found for date {nonexistent_date.date()}"
    ):
        sample_time_series_with_revisions.plot.observation_over_time(nonexistent_date)


def test_plot_observation_over_time_nonexistent_date_fuzzy_disabled(
    sample_time_series_with_revisions,
):
    """Test observation over time with a date that doesn't exist in the data."""
    nonexistent_date = datetime(2000, 1, 1, tzinfo=UTC)
    nonexistent_date_str = nonexistent_date.strftime("%Y-%m-%d %H:%M:%S")

    # N/A here returned in the error message because there are no earlier dates
    with pytest.raises(
        ValueError,
        match=f"Observation datetime {nonexistent_date_str} not found in time series data.\nNearest available datetimes are: N/A and 2024-12-01 00:00:00.",
    ):
        sample_time_series_with_revisions.plot.observation_over_time(
            nonexistent_date, fuzzy_datetime_match=False
        )


def test_plot_revision_success_default_line_chart(sample_time_series_with_revisions):
    """Test revision success plot with default line chart."""
    fig = sample_time_series_with_revisions.plot.revision_success()

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "scatter"
    assert fig.data[0].mode == "lines+markers"
    assert fig.layout.title.text.startswith("Cumulative Revision Success Rate")
    assert "Overall Success Rate" in fig.layout.title.text
    assert fig.layout.yaxis.title.text == "Cumulative Success Rate (%)"
    assert fig.layout.yaxis.range == (0, 100)


def test_plot_revision_success_bar_chart(sample_time_series_with_revisions):
    """Test revision success plot with bar chart type."""
    fig = sample_time_series_with_revisions.plot.revision_success(chart_type="bar")

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert fig.data[0].type == "bar"
    assert fig.layout.title.text.startswith("Cumulative Revision Success Rate")
    assert fig.layout.yaxis.range == (0, 100)


def test_plot_revision_success_hide_overall_rate(sample_time_series_with_revisions):
    """Test revision success plot with overall rate hidden."""
    fig = sample_time_series_with_revisions.plot.revision_success(
        show_overall_rate=False
    )

    assert isinstance(fig, go.Figure)
    assert "Overall Success Rate" not in fig.layout.title.text
    assert fig.layout.title.text.startswith("Cumulative Revision Success Rate")


def test_plot_revision_success_invalid_chart_type(sample_time_series_with_revisions):
    """Test revision success plot with invalid chart type."""
    with pytest.raises(
        ValueError,
        match="Unknown chart type: invalid. Accepted values are 'line' or 'bar'.",
    ):
        sample_time_series_with_revisions.plot.revision_success(chart_type="invalid")


def test_plot_revision_success_cumulative_calculation(
    sample_time_series_with_revisions,
):
    """Test that cumulative success rate is calculated correctly."""
    fig = sample_time_series_with_revisions.plot.revision_success()

    # The number of data points should equal the number of vintage dates
    flags_df, _ = sample_time_series_with_revisions.analysis.assess_revision_success()
    assert len(fig.data[0].x) == 12
    assert len(fig.data[0].y) == 12

    # All y-values should be between 0 and 100
    assert all(0 <= y <= 100 for y in fig.data[0].y)


def test_plot_decomposition_across_vintages(sample_time_series):
    all_vintages = sample_time_series._vintages_including_current_series()
    eligible_vintages = []

    for i, vintage in enumerate(all_vintages):
        vintage.metadata.get_frequency_as_numeric = MagicMock(return_value=1)
        component_series = MagicMock()
        component_series.to_series.return_value = pd.Series(
            [i, i + 0.5],
            index=pd.date_range("2024-01-01", periods=2, freq="D"),
        )
        vintage.analysis.decompose_vintage = MagicMock(
            return_value={"seasonal": component_series, "trend": component_series}
        )
        if len(vintage.current_observations) >= 2:
            eligible_vintages.append(vintage)

    fig = sample_time_series.plot.decomposition_across_vintages(
        model="additive",
        method="naive",
    )

    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert len(fig.data[0].x) == len(eligible_vintages)
    assert fig.layout.xaxis.title.text == "Release Date"
    assert fig.layout.yaxis.title.text == "Seasonal Component"

    for vintage in eligible_vintages:
        vintage.analysis.decompose_vintage.assert_called_once()
        _, kwargs = vintage.analysis.decompose_vintage.call_args
        assert kwargs["model"] == "additive"
        assert kwargs["method"] == "naive"
        assert kwargs["to_darts_timeseries_kwargs"] is None

    for vintage in all_vintages:
        if vintage not in eligible_vintages:
            vintage.analysis.decompose_vintage.assert_not_called()


def test_plot_decomposition_across_vintages_invalid_component(
    sample_time_series,
):
    with pytest.raises(
        ValueError,
        match="Invalid component: residual. Supported components are 'seasonal' and 'trend'.",
    ):
        sample_time_series.plot.decomposition_across_vintages(component="residual")


def test_format_revision_acf_feature_label_strips_revision_prefix(sample_time_series):
    """A 'revision_<date>' feature name strips the prefix and renders the date."""
    plotter = sample_time_series.plot
    assert (
        plotter._format_revision_acf_feature_label("revision_2024-02-01")
        == "2024-02-01"
    )


def test_format_revision_acf_feature_label_plain_date(sample_time_series):
    """A bare ISO date string is returned in YYYY-MM-DD form."""
    plotter = sample_time_series.plot
    assert plotter._format_revision_acf_feature_label("2024-01-01") == "2024-01-01"


def test_format_revision_acf_feature_label_preserves_time_when_nonzero(
    sample_time_series,
):
    """A datetime with a non-midnight time is rendered with HH:MM."""
    plotter = sample_time_series.plot
    assert (
        plotter._format_revision_acf_feature_label("revision_2024-02-01 13:45:00")
        == "2024-02-01 13:45"
    )


def test_format_revision_acf_feature_label_drops_midnight_time(sample_time_series):
    """Midnight times are formatted as date-only (no trailing 00:00)."""
    plotter = sample_time_series.plot
    assert (
        plotter._format_revision_acf_feature_label("revision_2024-02-01 00:00:00")
        == "2024-02-01"
    )


def test_format_revision_acf_feature_label_unparseable_returned_as_is(
    sample_time_series,
):
    """Non-date input falls through unchanged after stripping the optional prefix."""
    plotter = sample_time_series.plot
    assert plotter._format_revision_acf_feature_label("not-a-date") == "not-a-date"
    assert (
        plotter._format_revision_acf_feature_label("revision_not-a-date")
        == "not-a-date"
    )


def test_format_revision_acf_feature_label_empty_string(sample_time_series):
    """An empty input returns an empty string (pd.to_datetime returns NaT)."""
    plotter = sample_time_series.plot
    assert plotter._format_revision_acf_feature_label("") == ""


def _stub_decomposition(sample_time_series, trend_value=100.0, seasonal_value=0.0):
    """Mock decompose_vintage with constant trend/seasonal aligned to the
    sample fixture's daily timestamps. Returns the (trend, seasonal) MagicMocks."""
    timestamps = pd.date_range("2024-12-01", periods=14, freq="D")
    trend = MagicMock()
    trend.to_series.return_value = pd.Series([trend_value] * 14, index=timestamps)
    seasonal = MagicMock()
    seasonal.to_series.return_value = pd.Series([seasonal_value] * 14, index=timestamps)
    sample_time_series.analysis.decompose_vintage = MagicMock(
        return_value={"trend": trend, "seasonal": seasonal, "release_date": None}
    )
    return trend, seasonal


def test_time_component_breakdown_additive_around_zero(sample_time_series):
    """Default args produce around-zero layout: 2 bars + 1 line on a secondary axis."""
    _stub_decomposition(sample_time_series)

    fig = sample_time_series.plot.time_component_breakdown()

    assert isinstance(fig, go.Figure)
    bar_traces = [t for t in fig.data if t.type == "bar"]
    line_traces = [t for t in fig.data if t.type == "scatter"]
    assert len(bar_traces) == 2
    assert {t.name for t in bar_traces} == {"Seasonal", "Residual"}
    assert len(line_traces) == 1
    assert line_traces[0].name == "Trend"

    sample_time_series.analysis.decompose_vintage.assert_called_once()
    _, kwargs = sample_time_series.analysis.decompose_vintage.call_args
    assert kwargs["method"] == "STL"


def test_time_component_breakdown_additive_stacked(sample_time_series):
    """style='stacked' with additive: three bars on a single y-axis, no line."""
    _stub_decomposition(sample_time_series)

    fig = sample_time_series.plot.time_component_breakdown(
        model="additive", style="stacked"
    )

    bar_traces = [t for t in fig.data if t.type == "bar"]
    line_traces = [t for t in fig.data if t.type == "scatter"]
    assert len(bar_traces) == 3
    assert {t.name for t in bar_traces} == {"Trend", "Seasonal", "Residual"}
    assert len(line_traces) == 0
    assert fig.layout.barmode == "relative"


def test_time_component_breakdown_multiplicative_falls_back_to_naive_method(
    sample_time_series,
):
    """STL/MSTL + multiplicative warns and rewrites method to 'naive'."""
    _stub_decomposition(sample_time_series, trend_value=100.0, seasonal_value=1.0)

    with pytest.warns(UserWarning, match="falling back to method='naive'"):
        fig = sample_time_series.plot.time_component_breakdown(
            model="multiplicative", method="STL"
        )

    assert isinstance(fig, go.Figure)
    _, kwargs = sample_time_series.analysis.decompose_vintage.call_args
    assert kwargs["method"] == "naive"


def test_time_component_breakdown_multiplicative_stacked_collapses_to_around_zero(
    sample_time_series,
):
    """Multiplicative + stacked uses the around-zero layout (trend on secondary axis)."""
    _stub_decomposition(sample_time_series, trend_value=100.0, seasonal_value=1.0)

    fig = sample_time_series.plot.time_component_breakdown(
        model="multiplicative", method="naive", style="stacked"
    )

    bar_traces = [t for t in fig.data if t.type == "bar"]
    line_traces = [t for t in fig.data if t.type == "scatter"]
    assert len(bar_traces) == 2
    assert len(line_traces) == 1


def test_time_component_breakdown_invalid_style_raises(sample_time_series):
    with pytest.raises(ValueError, match="Invalid style"):
        sample_time_series.plot.time_component_breakdown(style="dotted")


def test_time_component_breakdown_renders_model_and_style_as_subtitle(
    sample_time_series,
):
    """`(model, style)` belongs in a <sup> subtitle, not the main title heading."""
    _stub_decomposition(sample_time_series)

    fig = sample_time_series.plot.time_component_breakdown(
        model="additive", style="around_zero"
    )

    title = fig.layout.title.text
    main_heading, _, subtitle_html = title.partition("<br>")
    assert "<sup>(additive, around_zero)</sup>" in subtitle_html
    assert "additive, around_zero" not in main_heading
    assert "Time Component Breakdown" in main_heading


def test_time_component_breakdown_multiplicative_units_are_percent_deviation(
    sample_time_series,
):
    """Multiplicative bars are rendered as % deviation from the trend, not raw factors."""
    _stub_decomposition(sample_time_series, trend_value=100.0, seasonal_value=1.0)

    fig = sample_time_series.plot.time_component_breakdown(
        model="multiplicative", method="naive"
    )

    primary_yaxis = fig.layout.yaxis.title.text
    assert primary_yaxis == "% deviation from trend"
