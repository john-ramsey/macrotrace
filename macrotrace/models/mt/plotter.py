from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union
from datetime import datetime
import warnings

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from darts.utils.utils import ModelMode, SeasonalityMode

from macrotrace.graphing import MACROTRACE_PLOTLY_LAYOUT_TEMPLATE

if TYPE_CHECKING:
    from macrotrace.models.mt.time_series import MTTimeSeries


class MTTimeSeriesPlotter:
    """
    A plotter class for visualizing MTTimeSeries data and revisions.

    This class provides various plotting methods for time series analysis,
    including revision analysis, vintage comparisons, and standard time series plots.
    """

    def __init__(self, time_series: "MTTimeSeries"):
        """
        Initialize the plotter with a time series object.

        Args:
            time_series: An MTTimeSeries instance to plot.
        """
        self.ts = time_series

    def _find_nearest_observation_datetime(
        self, target_datetime: datetime, index: pd.DatetimeIndex
    ) -> datetime:
        """
        Find the nearest observation datetime in the index that matches the target.

        For daily or lower frequency data (monthly, quarterly, etc.), finds the
        observation with the same date. For sub-daily data (hourly, minute, second, etc.),
        finds the nearest timestamp.

        Args:
            target_datetime: The target datetime to find
            index: The DatetimeIndex to search in

        Returns:
            datetime: The matching datetime from the index

        Raises:
            ValueError: If no matching datetime is found within a reasonable range
        """
        # Determine if data is subdaily by checking actual time differences
        # If min time between observations is < 1 day, it's subdaily
        if len(index) > 1:
            time_diffs = index[1:] - index[:-1]
            min_diff = time_diffs.min()
            is_subdaily = min_diff < pd.Timedelta(days=1)
        else:
            # If only one observation, assume not subdaily
            is_subdaily = False

        if is_subdaily:
            # For sub-daily data, find the nearest timestamp
            time_diffs = abs(index - target_datetime)
            nearest_idx = time_diffs.argmin()
            nearest = index[nearest_idx]

            typical_interval = (index[1:] - index[:-1]).median()
            tolerance = typical_interval * 2  # Allow 2x the typical interval

            if time_diffs[nearest_idx] > tolerance:
                raise ValueError(
                    f"No observation found within {tolerance} of {target_datetime.strftime('%Y-%m-%d %H:%M:%S')}. "
                    f"Nearest is {nearest.strftime('%Y-%m-%d %H:%M:%S')}."
                )
            return nearest
        else:
            # For daily or lower frequency, match by date only
            target_date = target_datetime.date()

            # Find all timestamps with matching date
            matching = [dt for dt in index if dt.date() == target_date]

            if not matching:
                # Find nearest dates for helpful error message
                dates_before = [dt for dt in index if dt.date() < target_date]
                dates_after = [dt for dt in index if dt.date() > target_date]

                nearest_before = max(dates_before).date() if dates_before else None
                nearest_after = min(dates_after).date() if dates_after else None

                raise ValueError(
                    f"No observation found for date {target_date}. "
                    f"Nearest dates: {nearest_before} and {nearest_after}."
                )

            # We might match on multiple datetimes if we split the difference perfectly (12 hours before and after)
            # Just return the first match
            return matching[0]

    def _format_revision_acf_feature_label(self, feature_name: str) -> str:
        """
        Format revision ACF feature label as a readable date-like string.

        Examples:
            2024-01-01 -> 2024-01-01
            revision_2024-02-01 -> 2024-02-01
        """
        if feature_name.startswith("revision_"):
            raw_name = feature_name.removeprefix("revision_")
        else:
            raw_name = feature_name

        parsed = pd.to_datetime(raw_name, errors="coerce")
        if pd.notna(parsed):
            if parsed.time() == datetime.min.time():
                display_name = parsed.strftime("%Y-%m-%d")
            else:
                display_name = parsed.strftime("%Y-%m-%d %H:%M")
        else:
            display_name = raw_name

        return display_name

    def observation_over_time(
        self,
        observation_datetime: str | datetime,
        first_difference: bool = False,
        chart_type: str = "bar",
        fuzzy_datetime_match: bool = True,
    ) -> go.Figure:
        """
        Given a specific observation datetime, plot how the observation developed over time.

        Args:
            observation_datetime (str | datetime): The observation datetime to plot.
            first_difference (bool, optional): Whether to plot the first difference. Defaults to False.
            chart_type (str, optional): Type of chart to plot. One of "bar" or "line". Defaults to "bar".
            fuzzy_datetime_match (bool, optional): Whether to allow fuzzy matching of datetimes. Allows for simple datetime inputs.
                E.g. '2026-01-01' matches to '2026-01-01 01:00:00'
                Defaults to True.

        Returns:
            go.Figure: Plotly figure showing observation revisions over time.
        """
        if isinstance(observation_datetime, str):
            observation_datetime = self.ts._parse_string_date(
                observation_datetime
            )  # Returns UTC timezone
        elif not isinstance(observation_datetime, datetime):
            raise ValueError(
                f"Invalid observation datetime type: {type(observation_datetime)}. Must be a string or a datetime."
            )

        vm = self.ts.generate_vintage_matrix()

        if fuzzy_datetime_match:
            # Find the nearest matching observation datetime (handles date-only inputs and timezone mismatches)
            observation_datetime = self._find_nearest_observation_datetime(
                observation_datetime, vm.index
            )

        try:
            row = vm.loc[observation_datetime]
        except KeyError:
            upper_dates = vm.index[vm.index > observation_datetime]
            lower_dates = vm.index[vm.index < observation_datetime]
            nearest_upper = (
                upper_dates.min().strftime("%Y-%m-%d %H:%M:%S")
                if len(upper_dates) > 0
                else "N/A"
            )
            nearest_lower = (
                lower_dates.max().strftime("%Y-%m-%d %H:%M:%S")
                if len(lower_dates) > 0
                else "N/A"
            )

            raise ValueError(
                f"Observation datetime {observation_datetime.strftime('%Y-%m-%d %H:%M:%S')} not found in time series data.\nNearest available datetimes are: {nearest_lower} and {nearest_upper}."
            )

        # drop all NaN values
        row = row.dropna()

        if first_difference:
            row = row.diff().dropna()

        x_label = "Vintage Date"
        y_label = "Revision Value" if first_difference else "Value"

        # Plot the observation over time
        if chart_type == "bar":
            fig = px.bar(
                x=row.index,
                y=row.values,
                title=f"Observation Over Time - {observation_datetime}",
                labels={"x": x_label, "y": y_label},
                template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            )
        elif chart_type == "line":
            fig = px.line(
                x=row.index,
                y=row.values,
                title=f"Observation Over Time - {observation_datetime}",
                labels={"x": x_label, "y": y_label},
                template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            )
            fig.update_traces(mode="lines+markers")
        else:
            raise ValueError(
                f"Unknown chart type: {chart_type}. Accepted values are 'bar' or 'line'."
            )

        return fig

    def revision_cross_correlogram_heatmap(
        self,
        max_vintage_lag: Optional[int] = None,
        max_observation_lag: Optional[int] = None,
    ) -> go.Figure:
        """
        Plot the revision cross-correlogram heatmap.

        Args:
            max_vintage_lag (Optional[int]): Maximum vintage lag to include.
            max_observation_lag (Optional[int]): Maximum observation lag to include.

        Returns:
            go.Figure: Heatmap with x=vintage lag and y=observation lag.
        """
        corr_result = self.ts.analysis.revision_cross_correlogram(
            max_vintage_lag=max_vintage_lag,
            max_observation_lag=max_observation_lag,
        )
        vintage_lags = corr_result["vintage_lags"]
        observation_lags = corr_result["observation_lags"]
        heatmap_z = corr_result["correlogram"]
        pair_counts = corr_result["pair_counts"]
        pair_counts_customdata = np.asarray(pair_counts, dtype=int)[..., None]

        heatmap_colorscale = MACROTRACE_PLOTLY_LAYOUT_TEMPLATE["layout"]["colorscale"][
            "diverging"
        ]
        fig = go.Figure(
            data=[
                go.Heatmap(
                    z=heatmap_z,
                    x=vintage_lags,
                    y=observation_lags,
                    customdata=pair_counts_customdata,
                    colorscale=heatmap_colorscale,
                    zmin=-1,
                    zmax=1,
                    zmid=0,
                    colorbar={"title": "Pearson r"},
                    hovertemplate=(
                        "Vintage Lag: %{x}<br>"
                        "Observation Lag: %{y}<br>"
                        "Pearson Corr: %{z:.3f}<br>"
                        "Pairs: %{customdata[0]}<extra></extra>"
                    ),
                )
            ]
        )

        fig.update_layout(
            title=(
                "Revision Cross-Correlogram (Vintage Lag vs Observation Lag) - "
                f"{self.ts.metadata.title if self.ts.metadata else self.ts.dataset_id}"
            ),
            template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            height=560,
            showlegend=False,
        )
        fig.update_xaxes(title_text="Vintage Lag")
        fig.update_yaxes(title_text="Observation Lag")

        return fig

    def revision_success(
        self, chart_type: str = "line", show_overall_rate: bool = True
    ) -> go.Figure:
        """
        Plot how the cumulative revision success rate develops over time.

        A successful revision is one which reduced the absolute value of the error
        between the estimate and the final figure (Stekler, 1967).

        This shows the running success rate as vintages are released chronologically,
        allowing you to see how the quality of revisions evolves.

        Args:
            chart_type (str, optional): Type of chart to plot. Either "line" or "bar".
                Defaults to "line".
            show_overall_rate (bool, optional): Whether to show final overall success rate in title.
                Defaults to True.

        Returns:
            go.Figure: Plotly chart showing cumulative success rate over vintage dates.
        """
        if chart_type not in ["line", "bar"]:
            raise ValueError(
                f"Unknown chart type: {chart_type}. Accepted values are 'line' or 'bar'."
            )

        flags_df, success_rate = self.ts.analysis.assess_revision_success()

        # Calculate cumulative success rate for each vintage date
        cumulative_rates = []
        vintage_dates = []

        for i, vintage_date in enumerate(flags_df.columns):
            # Get all success flags up to and including this vintage
            cumulative_flags = flags_df.iloc[:, : i + 1].stack()
            # Calculate success rate (excluding NAs)
            valid_flags = cumulative_flags.dropna()
            if len(valid_flags) > 0:
                rate = valid_flags.mean() * 100
                cumulative_rates.append(rate)
                vintage_dates.append(vintage_date)

        title_base = f"Cumulative Revision Success Rate - {self.ts.metadata.title if self.ts.metadata else self.ts.dataset_id}"
        if show_overall_rate:
            title = (
                f"{title_base}<br><sup>Overall Success Rate: {success_rate:.1%}</sup>"
            )
        else:
            title = title_base

        formatted_dates = [
            vdate.strftime("%Y-%m-%d") if isinstance(vdate, datetime) else vdate
            for vdate in vintage_dates
        ]

        if chart_type == "line":
            fig = px.line(
                x=formatted_dates,
                y=cumulative_rates,
                title=title,
                labels={"x": "Vintage Date", "y": "Cumulative Success Rate (%)"},
                template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            )
            fig.update_traces(mode="lines+markers")
        else:  # bar
            fig = px.bar(
                x=formatted_dates,
                y=cumulative_rates,
                title=title,
                labels={"x": "Vintage Date", "y": "Cumulative Success Rate (%)"},
                template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            )

        fig.update_yaxes(range=[0, 100])
        fig.update_layout(
            xaxis_title="Vintage Date",
            yaxis_title="Cumulative Success Rate (%)",
        )

        return fig

    def decomposition_across_vintages(
        self,
        component: str = "seasonal",
        model: Union[str, SeasonalityMode, ModelMode] = ModelMode.MULTIPLICATIVE,
        method: str = "naive",
        to_darts_timeseries_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> go.Figure:
        """
        Plot the selected decomposition component across vintage release dates.

        For each vintage (including the current one), this runs seasonal decomposition,
        then plots the latest available value of the selected component at that vintage's
        release date. Vintages with fewer than ``2 * seasonal_period`` observations
        are skipped.

        Args:
            component (str): Component to plot; "seasonal" or "trend".
            model (Union[str, SeasonalityMode, ModelMode]): Decomposition type.
                Accepts "additive"/"multiplicative" strings or Darts enum values.
            method (str): Decomposition method ("naive", "STL", or "MSTL").
            to_darts_timeseries_kwargs (Optional[Dict[str, Any]]): Keyword args passed to ``to_darts_timeseries`` for each vintage.
            **kwargs (Any): Additional keyword args forwarded to Darts decomposition.

        Returns:
            go.Figure: Plotly line chart with x-axis as release date.
        """
        valid_components = {"seasonal", "trend"}
        if component not in valid_components:
            raise ValueError(
                f"Invalid component: {component}. Supported components are 'seasonal' and 'trend'."
            )

        rows = []
        for vintage in self.ts._vintages_including_current_series():
            seasonal_period = vintage.metadata.get_frequency_as_numeric()
            minimum_observations = 2 * seasonal_period
            if len(vintage.current_observations) < minimum_observations:
                continue

            decomposition = vintage.analysis.decompose_vintage(
                model=model,
                method=method,
                to_darts_timeseries_kwargs=to_darts_timeseries_kwargs,
                **kwargs,
            )
            component_ts = decomposition[component]
            if not hasattr(component_ts, "to_series"):
                raise TypeError(
                    f"Decomposition component must be a Darts TimeSeries-like object; got {type(component_ts)}."
                )
            component_series = component_ts.to_series().dropna()
            if component_series.empty:
                continue
            rows.append(
                {
                    "release_date": vintage.release_date,
                    "value": component_series.iloc[-1],
                    "observation_timestamp": component_series.index[-1],
                }
            )

        if not rows:
            raise ValueError(
                "No decomposition values available to plot across vintages."
            )

        df = pd.DataFrame(rows).sort_values("release_date")
        title = (
            f"{component.capitalize()} Decomposition Across Vintages - "
            f"{self.ts.metadata.title if self.ts.metadata else self.ts.dataset_id}"
        )
        fig = px.line(
            df,
            x="release_date",
            y="value",
            markers=True,
            title=title,
            labels={
                "release_date": "Release Date",
                "value": f"{component.capitalize()} Component",
                "observation_timestamp": "Observation Timestamp",
            },
            hover_data={"observation_timestamp": True},
            template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
        )
        fig.update_layout(
            xaxis_title="Release Date",
            yaxis_title=f"{component.capitalize()} Component",
        )

        return fig

    def revision_histogram(
        self,
        mode: str = "first_difference",
        normalization: Optional[str] = None,
        **kwargs: Any,
    ) -> go.Figure:
        """
        Plots a histogram of the revisions in the time series.

        Args:
            mode (str): The mode for which the dataframe is provided. Supports "first_difference" and "pct_change". Defaults to "first_difference".
            normalization (Optional[str], optional): The normalization method to use. Defaults to None.
                Options are 'percent', 'probability', 'density', or 'probability density'
            **kwargs: Additional keyword arguments to pass to plotly.express.histogram.

        Returns:
            go.Figure: Plotly histogram figure.
        """
        if mode not in ["first_difference", "pct_change"]:
            raise ValueError(
                f"Invalid mode: {mode}. Supported modes are 'first_difference' and 'pct_change'."
            )

        vm = self.ts.generate_vintage_matrix()

        if mode == "first_difference":
            diffs = vm.diff(axis=1)
        elif mode == "pct_change":
            diffs = vm.pct_change(axis=1, fill_method=None) * 100

        nonzero_non_nan_values = diffs.stack().replace(0, pd.NA).dropna().values

        title = f"Histogram of Revisions - {self.ts.metadata.title if self.ts.metadata else self.ts.dataset_id}"
        value_label = "Revision Value" if mode == "first_difference" else "Revision %"

        fig = px.histogram(
            nonzero_non_nan_values,
            title=title,
            labels={"value": value_label},
            histnorm=normalization,
            template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            **kwargs,
        )
        return fig

    def timeseries(self, show_vintage_range: bool = False) -> go.Figure:
        """
        Plot the current vintage of the time series.

        Args:
            show_vintage_range (bool, optional): Whether to show shaded bands indicating
                the range (min/max) of all vintage values for each observation.
                Defaults to False.

        Returns:
            go.Figure: Plotly line chart of the time series.
        """
        df = self.ts.to_dataframe()

        title = f"{self.ts.metadata.title if self.ts.metadata else ''} - {self.ts.dataset_id}"
        subtitle = (
            f"<br><sup>{self.ts.metadata.units if self.ts.metadata else 'Value'}</sup>"
        )
        y_label = self.ts.metadata.units if self.ts.metadata else "Value"

        if show_vintage_range:
            # Get vintage matrix to calculate min/max ranges
            vm = self.ts.generate_vintage_matrix()

            # Calculate min and max values for each observation timestamp
            y_upper = vm.max(axis=1)
            y_lower = vm.min(axis=1)

            # Get primary color from template
            primary_color = MACROTRACE_PLOTLY_LAYOUT_TEMPLATE["layout"]["colorway"][0]
            fill_color = (
                primary_color.replace("rgb", "rgba").replace(")", ",0.2)")
                if primary_color.startswith("rgb")
                else f"rgba({int(primary_color[1:3], 16)},{int(primary_color[3:5], 16)},{int(primary_color[5:7], 16)},0.2)"
            )

            # Create figure with range bands
            fig = go.Figure()

            # Add the shaded range band
            fig.add_trace(
                go.Scatter(
                    x=list(df["timestamp"]) + list(df["timestamp"][::-1]),
                    y=list(y_upper[df["timestamp"]])
                    + list(y_lower[df["timestamp"]][::-1]),
                    fill="toself",
                    fillcolor=fill_color,
                    line=dict(color="rgba(255,255,255,0)"),
                    hoverinfo="skip",
                    name="Vintage Range",
                )
            )

            # Add the main line (current vintage)
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"],
                    y=df["value"],
                    line=dict(color=primary_color),
                    mode="lines",
                    name="Current Vintage",
                )
            )

            fig.update_layout(
                title=title + subtitle,
                xaxis_title="Date",
                yaxis_title=y_label,
                template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            )
        else:
            fig = px.line(
                df,
                x="timestamp",
                y="value",
                title=title + subtitle,
                labels={"value": f"{y_label}"},  # Changes the hover label
                template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            )
            fig.update_layout(xaxis_title="Date", yaxis_title=y_label)

        # Remove the legend
        fig.update_layout(showlegend=False)

        return fig

    def timeseries_comparison(
        self,
        vintage_dates: List[str | datetime],
        chart_type: str = "bar",
        mode: str = "default",
        y_axis_zero_indexed: bool = False,
    ) -> go.Figure:
        """
        Plots a comparison of time series vintages.

        Args:
            vintage_dates (List[str | datetime]): List of vintage identifiers. Ex. '2025-11-01'
            chart_type (str, optional): Type of chart to plot. Either "bar" or "line". Defaults to "bar".
            mode (str, optional): The mode for which the dataframe is provided. Supports "default", "first_difference", and "pct_change". Defaults to "default".
            y_axis_zero_indexed (bool, optional): Sets base of the y-axis to zero.

        Returns:
            go.Figure: Plotly figure.
        """
        if mode not in ["default", "first_difference", "pct_change"]:
            raise ValueError(
                f"Invalid mode: {mode}. Supported modes are 'default', 'first_difference', and 'pct_change'."
            )

        for vintage_date in vintage_dates:
            if (not isinstance(vintage_date, str)) and (
                not isinstance(vintage_date, datetime)
            ):
                raise TypeError(
                    "Vintage dates must be provided as strings or datetime objects."
                )

        fig = go.Figure()
        all_values = []
        hoverinfo = "x+y+name"

        for vintage_date in vintage_dates:
            df = self.ts.as_of(vintage_date).to_dataframe(mode=mode)
            vintage_date = (
                vintage_date.strftime("%Y-%m-%d")
                if isinstance(vintage_date, datetime)
                else vintage_date
            )
            if chart_type == "bar":
                fig.add_trace(
                    go.Bar(
                        x=df["timestamp"],
                        y=df["value"],
                        name=f"As Of {vintage_date}",
                        hoverinfo=hoverinfo,
                    )
                )
            elif chart_type == "line":
                fig.add_trace(
                    go.Scatter(
                        x=df["timestamp"],
                        y=df["value"],
                        name=f"As Of {vintage_date}",
                        mode="lines+markers",
                        hoverinfo=hoverinfo,
                    )
                )
            else:
                raise ValueError(
                    f"Unknown chart type: {chart_type}. Accepted values are 'bar' or 'line'."
                )

            all_values.extend(df["value"])

        # Compute axis range
        vmin, vmax = min(all_values), max(all_values)
        if y_axis_zero_indexed:
            y_range = [0, vmax]
        else:
            margin = 0.05 * vmax
            y_range = [vmin - margin, vmax + margin]
        fig.update_yaxes(range=y_range)

        if mode == "first_difference":
            diff_title = " (Period over Period Change)"
            units = "△ " + self.ts.metadata.units
        elif mode == "pct_change":
            diff_title = " (Percentage Change)"
            units = "% Change"
        else:
            diff_title = ""
            units = self.ts.metadata.units
        title = f"Comparison of Vintages - {self.ts.metadata.title}{diff_title}"

        fig.update_layout(
            title=title,
            template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            xaxis_title="Date",
            yaxis_title=units,
        )

        return fig

    def time_component_breakdown(
        self,
        model: Union[str, SeasonalityMode, ModelMode] = ModelMode.ADDITIVE,
        style: str = "around_zero",
        method: str = "STL",
        to_darts_timeseries_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> go.Figure:
        """
        Decompose the current vintage into trend + seasonal + residual and render
        the breakdown as a stacked bar chart.

        For additive decomposition, components are in the source's units and
        ``observed = trend + seasonal + residual``. For multiplicative decomposition,
        ``observed = trend * seasonal * residual`` and the seasonal/residual bars
        are rendered as percent deviations from 1 (``(factor - 1) * 100``).

        Args:
            model (Union[str, SeasonalityMode, ModelMode]): Decomposition type.
                Accepts "additive"/"multiplicative" strings or Darts enum values.
            style (str): Layout style. ``"stacked"`` puts trend + seasonal + residual
                on a single y-axis (additive only — for multiplicative the layout
                falls back to around-zero, since trend levels can't share an axis
                with percent deviations). ``"around_zero"`` puts trend on a
                secondary axis as a line and stacks seasonal + residual on the
                primary axis around zero.
            method (str): Decomposition method ("naive", "STL", or "MSTL").
                Darts' STL/MSTL implementations are additive-only; passing a
                multiplicative model with STL/MSTL falls back to "naive" with a
                warning rather than raising.
            to_darts_timeseries_kwargs (Optional[Dict[str, Any]]): Forwarded to ``decompose_vintage``.
            **kwargs (Any): Forwarded to ``decompose_vintage``.

        Returns:
            go.Figure: A stacked bar chart showing the breakdown of time components.
        """
        if style not in ("stacked", "around_zero"):
            raise ValueError(
                f"Invalid style: {style}. Supported styles are 'stacked' and 'around_zero'."
            )

        is_multiplicative = (
            model == ModelMode.MULTIPLICATIVE
            or model == SeasonalityMode.MULTIPLICATIVE
            or (isinstance(model, str) and model.strip().lower() == "multiplicative")
        )

        if is_multiplicative and method.upper() in ("STL", "MSTL"):
            warnings.warn(
                f"Darts {method} only supports additive decomposition; "
                f"falling back to method='naive' for multiplicative.",
                stacklevel=2,
            )
            method = "naive"

        decomposition = self.ts.analysis.decompose_vintage(
            model=model,
            method=method,
            to_darts_timeseries_kwargs=to_darts_timeseries_kwargs,
            **kwargs,
        )
        trend = decomposition["trend"].to_series()
        seasonal = decomposition["seasonal"].to_series()

        observed = self.ts.to_dataframe(tz="source").set_index("timestamp")["value"]

        df = pd.DataFrame({"trend": trend, "seasonal": seasonal})
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df["observed"] = observed.reindex(df.index)

        if is_multiplicative:
            df["residual"] = df["observed"] / (df["trend"] * df["seasonal"])
            bar_seasonal = (df["seasonal"] - 1.0) * 100.0
            bar_residual = (df["residual"] - 1.0) * 100.0
            bar_units = "% deviation from trend"
        else:
            df["residual"] = df["observed"] - df["trend"] - df["seasonal"]
            bar_seasonal = df["seasonal"]
            bar_residual = df["residual"]
            bar_units = self.ts.metadata.units if self.ts.metadata else "Value"

        df = df.dropna()
        if df.empty:
            raise ValueError(
                "No overlapping observations between decomposition and source series."
            )
        bar_seasonal = bar_seasonal.reindex(df.index)
        bar_residual = bar_residual.reindex(df.index)

        title_base = self.ts.metadata.title if self.ts.metadata else self.ts.dataset_id
        trend_units = self.ts.metadata.units if self.ts.metadata else "Value"
        model_label = "multiplicative" if is_multiplicative else "additive"
        title = (
            f"Time Component Breakdown - {title_base}"
            f"<br><sup>({model_label}, {style})</sup>"
        )

        if style == "stacked" and not is_multiplicative:
            fig = go.Figure()
            fig.add_bar(x=df.index, y=df["trend"], name="Trend")
            fig.add_bar(x=df.index, y=bar_seasonal, name="Seasonal")
            fig.add_bar(x=df.index, y=bar_residual, name="Residual")
            fig.update_layout(
                barmode="relative",
                template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
                title=title,
                xaxis_title="Date",
                yaxis_title=bar_units,
            )
            return fig

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_bar(x=df.index, y=bar_seasonal, name="Seasonal", secondary_y=False)
        fig.add_bar(x=df.index, y=bar_residual, name="Residual", secondary_y=False)
        fig.add_scatter(
            x=df.index,
            y=df["trend"],
            name="Trend",
            mode="lines",
            line=dict(width=2),
            secondary_y=True,
        )
        fig.update_layout(
            barmode="relative",
            template=MACROTRACE_PLOTLY_LAYOUT_TEMPLATE,
            title=title,
            xaxis_title="Date",
        )
        fig.update_yaxes(title_text=bar_units, secondary_y=False)
        fig.update_yaxes(title_text=trend_units, secondary_y=True)
        return fig
