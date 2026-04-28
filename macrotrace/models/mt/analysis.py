from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING, Union
import logging

import numpy as np
import pandas as pd
from tabulate import tabulate
from darts.models import (
    ExponentialSmoothing,
    NaiveDrift,
    LinearRegressionModel,
    ARIMA,
)
from darts.utils.statistics import (
    extract_trend_and_seasonality,
    granger_causality_tests,
)
from darts.utils.utils import ModelMode, SeasonalityMode
import statsmodels.api as sm
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.stats.stattools import durbin_watson
from scipy.stats import t as t_dist

if TYPE_CHECKING:  # pragma: no cover
    from macrotrace.models.mt.time_series import MTTimeSeries

logger = logging.getLogger(__name__)


@dataclass
class BiasednessRegressionResult:
    """
    Container for biasedness regression output where __repr__ renders the table.
    """

    n_total: int
    vintage_indices: Dict[str, Any]
    data_notes: Dict[str, Any]
    model: Dict[str, Any]
    tests: Dict[str, Any]
    assumptions: Dict[str, Any]
    table: str

    def __repr__(self) -> str:
        return self.table or "BiasednessRegressionResult()"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_total": self.n_total,
            "vintage_indices": self.vintage_indices,
            "data_notes": self.data_notes,
            "model": self.model,
            "tests": self.tests,
            "assumptions": self.assumptions,
            "table": self.table,
        }


@dataclass
class VintageComparison:
    vintages: Dict[str, "MTTimeSeries"]
    mode: str
    strategy: str

    def __post_init__(self):
        if self.mode not in ("growth", "levels"):
            raise ValueError(
                f"Invalid mode: {self.mode}. Must be 'growth' or 'levels'."
            )
        if self.strategy not in ["sequential", "final", "all"]:
            raise ValueError(
                f"Invalid strategy: {self.strategy}. Must be 'sequential', 'final', or 'all'."
            )

        if len(self.vintages) < 2:
            raise ValueError(
                f"VintageComparison requires at least 2 vintages, got {len(self.vintages)}."
            )

        # Sort by the resolved vintage's release_date so strategies that depend
        # on chronological order ("sequential", "final") behave correctly
        # regardless of the order in which the user supplied vintage dates.
        self.vintages = dict(
            sorted(self.vintages.items(), key=lambda item: item[1].release_date)
        )

        self.comparison = self._calculate_comparison_metrics()
        # set the attributes for each of the items in the comparison so we can access them like a dict
        for key, value in self.comparison.items():
            setattr(self, key, value)

    def __getitem__(self, key: str):
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(f"{key} not found in {self.__class__.__name__}")

    def __repr__(self) -> str:
        return f"VintageComparison(mode={self.mode}, strategy={self.strategy})"

    def _calculate_comparison_metrics(self) -> Dict[str, Any]:
        processed_vintages = self._process_vintages()
        vintage_items = list(processed_vintages.items())
        comparisons = {}

        # The 'sequential' comparison strategy compares vintage 0 to 1, 1 to 2, etc.
        if self.strategy == "sequential":
            for idx, (current_key, current_df) in enumerate(vintage_items[:-1]):
                next_key, next_df = vintage_items[idx + 1]
                comparison = self._compare_vintages(current_df, next_df)
                comparisons[f"vintage_{current_key}_to_{next_key}"] = comparison

        # The 'final' comparison strategy compares all vintages to the last one
        elif self.strategy == "final":
            final_key, final_df = vintage_items[-1]
            for current_key, current_df in vintage_items[:-1]:
                comparison = self._compare_vintages(current_df, final_df)
                comparisons[f"vintage_{current_key}_to_{final_key}"] = comparison

        # The 'all' comparison strategy compares all vintages to each other
        elif self.strategy == "all":
            for idx, (current_key, current_df) in enumerate(vintage_items):
                for next_key, next_df in vintage_items[idx + 1 :]:
                    comparison = self._compare_vintages(current_df, next_df)
                    comparisons[f"vintage_{current_key}_to_{next_key}"] = comparison

        return comparisons

    def _compare_vintages(
        self, current: pd.DataFrame, next_: pd.DataFrame
    ) -> Dict[str, Any]:

        merged = current.merge(next_, on="timestamp").sort_values("timestamp")
        value_columns = [col for col in merged.columns if col != "timestamp"]
        if len(value_columns) != 2:
            raise ValueError(
                "Vintage comparison requires exactly two value columns after merge."
            )

        col_0, col_1 = value_columns
        revisions = merged[col_0] - merged[col_1]

        # In growth mode col_0/col_1 are within-vintage growth rates and
        # `revisions` is the cross-vintage revision *to the growth rate*.
        # In levels mode col_0/col_1 are level values and `revisions` is the
        # revision *to the level itself*. Bias, dispersion, extremes, std,
        # and counts have parallel interpretations in both modes; the
        # directional-miss measures differ, see below.
        comparison = {
            "bias": revisions.mean(),
            "relative_bias": revisions.mean() / merged[col_1].mean(),
            "dispersion": revisions.abs().mean(),
            "relative_dispersion": revisions.abs().mean() / merged[col_1].abs().mean(),
            "largest_upward_revision": revisions.min(),
            "largest_downward_revision": revisions.max(),
            "standard_deviation_of_revisions_difference": revisions.std(),
            "counts": {
                # Under the Young (1974) convention
                # `revisions = preliminary - final`
                # a negative revision means that 'final > preliminary'
                # i.e. the series was revised UP between vintages.
                "upward": (revisions < 0).sum(),
                "downward": (revisions > 0).sum(),
                "no_change": (revisions == 0).sum(),
            },
        }

        if self.mode == "growth":
            # Growth rates: a sign flip in the growth rate itself means the
            # vintages disagree on whether the series rose or fell.
            comparison["directional_misses_trend"] = (
                merged[col_0] * merged[col_1] < 0
            ).mean()
        else:
            # Levels: two distinct directional-miss notions.
            # (1) Sign of the level (e.g. trade balance crossing zero).
            comparison["directional_misses_sign"] = (
                merged[col_0] * merged[col_1] < 0
            ).mean()
            # (2) Sign of the period-over-period change (rose vs fell).
            diffs0 = merged[col_0].diff()
            diffs1 = merged[col_1].diff()
            comparison["directional_misses_trend"] = (diffs0 * diffs1 < 0).mean()

        return comparison

    def _process_vintages(self) -> Dict[str, pd.DataFrame]:
        processed_vintages = {}
        for as_of_date, vintage in self.vintages.items():
            df = vintage.to_dataframe(mode="default")
            df = df[["timestamp", "value"]].rename(
                columns={"value": f"vintage_{as_of_date}"}
            )
            df = df.set_index("timestamp")
            if self.mode == "growth":
                df = df.pct_change()
            df = df.dropna().reset_index()
            processed_vintages[as_of_date] = df

        return processed_vintages


class MTTimeSeriesAnalysis:
    def __init__(self, ts: "MTTimeSeries") -> None:
        self.ts = ts

    def assess_revision_success(self) -> Tuple[pd.DataFrame, float]:
        """
        "A successful revision is defined as one which reduced the absolute value of the error between the estimate and the final figure."
        Stekler (1967)

        Assess the success of revisions of time series data.
        This function compares each revision of the time series to the final value
        and determines if the revision was successful based on whether it brought
        the value closer to the final value.

        Returns:
            Tuple[pd.DataFrame, float]: A tuple containing:
                - A DataFrame with success flags for each revision.
                - The overall success rate of revisions as a float.
        """
        df = self.ts.generate_vintage_matrix()

        flags_df = pd.DataFrame(index=df.index, columns=df.columns, dtype="boolean")
        # set all flags to None to start
        flags_df[:] = None

        # With the vintage matrix, each row is a observation timestamp,
        # and each column is a vintage date.

        for obs_timestamp in df.index:
            # Get the final value for this observation timestamp
            final_value = df.loc[obs_timestamp].iloc[-1]

            for i, vintage_date in enumerate(df.columns):
                current_vintage_value = df.loc[obs_timestamp, df.columns[i]]
                prior_vintage_value = df.loc[obs_timestamp, df.columns[i - 1]]

                if pd.isna(current_vintage_value) or pd.isna(prior_vintage_value):
                    # If either value is NaN, we cannot assess revision success
                    continue
                elif current_vintage_value == prior_vintage_value:
                    # If the current vintage value is the same as the prior, we cannot assess revision success (nothing changed)
                    continue
                elif i == 0:
                    # If this is the first vintage, we cannot assess revision success (no prior value to compare to)
                    continue
                elif i == len(df.columns) - 1:
                    # If this is the last vintage, we cannot assess revision success (no final value to compare to)
                    # Calling this revision a success would be disingenuous as it cannot be not successful.
                    continue

                # Determine if the revision was successful
                flags_df.loc[obs_timestamp, vintage_date] = (
                    self.ts._is_successful_revision(
                        current_vintage_value, prior_vintage_value, final_value
                    )
                )

        revision_success_rate = flags_df.stack().mean()
        return flags_df, revision_success_rate

    def granger_causality_test(
        self,
        ts_effect: MTTimeSeries,
        add_const: bool = True,
        ts_effect_to_darts_ts_kwargs: Dict[Any, Any] = {},
        ts_cause_to_darts_ts_kwargs: Dict[Any, Any] = {},
        max_lags: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Provides four tests for granger non causality of 2 time series
        using statsmodels.tsa.stattools.grangercausalitytests().

        The current series (i.e. self.ts) is the causal series and the
        provided ts_effect is the effect series. The null hypothesis is
        that the causal series does not granger cause the effect series.

        Args:
            ts_effect (MTTimeSeries): The time series to test as the effect.
            to_effect_df_kwargs (Dict[str, Any]): Arguments to pass to the effect time series when converting to a DataFrame prior to converting to a Darts time series.
            ts_effect_to_darts_ts_kwargs (Dict[Any, Any]): Arguments to pass to the effect time series when converting to a Darts time series.
            to_cause_df_kwargs (Dict[str, Any]): Arguments to pass to the causal time series when converting to a DataFrame prior to converting to a Darts time series.
            ts_cause_to_darts_ts_kwargs (Dict[Any, Any]): Arguments to pass to the causal time series when converting to a Darts time series.
            add_const (bool): Whether to add a constant term to the regression. Defaults to True.
            max_lags (Optional[int]): The maximum number of lags to test for granger causality. Defaults to None, which utilizes the frequency of the MTTimeSeries.

        Returns:
            Dict[str, Any]: A dictionary containing the results of the
            granger causality tests for each lag, including test statistics
            and p-values.
        """
        effect_ts = ts_effect.to_darts_timeseries(**ts_effect_to_darts_ts_kwargs)
        causal_ts = self.ts.to_darts_timeseries(**ts_cause_to_darts_ts_kwargs)
        max_lags = max_lags or self.ts.metadata.get_frequency_as_numeric()

        res = granger_causality_tests(
            ts_cause=causal_ts,
            ts_effect=effect_ts,
            maxlag=max_lags,
            addconst=add_const,
        )

        return res

    def revision_cross_correlogram(
        self,
        max_vintage_lag: Optional[int] = None,
        max_observation_lag: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Compute revision cross-correlogram over vintage and observation lags.

        Cell (observation_lag=b, vintage_lag=a) is the Pearson correlation between:
            R[t, v] and R[t-b, v-a]
        where R is the revision matrix (diff across release-date columns).

        Args:
            max_vintage_lag (Optional[int]): Maximum lag across vintage columns.
                Defaults to full feasible range.
            max_observation_lag (Optional[int]): Maximum lag across observation rows.
                Defaults to full feasible range.

        Returns:
            Dict[str, Any]: A dictionary containing:
                - correlogram: ndarray with shape (observation_lags, vintage_lags)
                - observation_lags: Observation lag indices (y-axis)
                - vintage_lags: Vintage lag indices (x-axis)
                - pair_counts: Number of valid revision pairs used per cell
        """
        if max_vintage_lag is not None and max_vintage_lag < 0:
            raise ValueError("max_vintage_lag must be >= 0")
        if max_observation_lag is not None and max_observation_lag < 0:
            raise ValueError("max_observation_lag must be >= 0")

        vm = self.ts.generate_vintage_matrix()
        if vm.empty or vm.shape[1] == 0:
            raise ValueError("Vintage matrix is empty, cannot compute correlogram")

        revisions = vm.diff(axis=1).iloc[:, 1:]
        if revisions.shape[1] == 0 or revisions.shape[0] == 0:
            raise ValueError(
                "At least two release dates are required to compute revision series"
            )

        revision_values = revisions.to_numpy(dtype=float)
        n_obs, n_vintage = revision_values.shape

        max_vintage_lag = (
            n_vintage - 1
            if max_vintage_lag is None
            else min(max_vintage_lag, n_vintage - 1)
        )
        max_observation_lag = (
            n_obs - 1
            if max_observation_lag is None
            else min(max_observation_lag, n_obs - 1)
        )

        correlogram = np.full(
            (max_observation_lag + 1, max_vintage_lag + 1), np.nan, dtype=float
        )
        pair_counts = np.zeros(
            (max_observation_lag + 1, max_vintage_lag + 1), dtype=int
        )

        for obs_lag in range(max_observation_lag + 1):
            for vintage_lag in range(max_vintage_lag + 1):
                current = revision_values[obs_lag:, vintage_lag:]
                lagged = revision_values[: n_obs - obs_lag, : n_vintage - vintage_lag]

                x = current.reshape(-1)
                y = lagged.reshape(-1)
                valid_mask = np.isfinite(x) & np.isfinite(y)
                n_pairs = int(valid_mask.sum())
                pair_counts[obs_lag, vintage_lag] = n_pairs
                if n_pairs < 2:
                    continue

                x_valid = x[valid_mask]
                y_valid = y[valid_mask]
                if x_valid.std(ddof=0) == 0.0 or y_valid.std(ddof=0) == 0.0:
                    continue
                correlogram[obs_lag, vintage_lag] = np.corrcoef(x_valid, y_valid)[0, 1]

        return {
            "correlogram": correlogram,
            "observation_lags": list(range(max_observation_lag + 1)),
            "vintage_lags": list(range(max_vintage_lag + 1)),
            "pair_counts": pair_counts,
        }

    def revision_biasedness_regression(
        self,
        independent_vintage_index: int | str,
        dependent_vintage_index: int | str,
        alpha: float = 0.05,
    ) -> BiasednessRegressionResult:
        """
        Regresses the dependent vintage (Y) on the independent vintage (X):
            Y = alpha + beta * X + u

        If the independent vintage is an unbiased predictor of the dependent vintage,
        then alpha should be close to zero and beta should be close to one.

        If unbiasedness cannot be rejected, then alpha_hat and beta_hat should be a
        a better estimator of Y than X alone.

        args:
            independent_vintage_index (int | str): Vintage index used as the independent variable (X).
                1-based indexing. Use -1 or "latest" for last non-NaN vintage.
            dependent_vintage_index (int | str): Vintage index used as the dependent variable (Y).
                1-based indexing. Use -1 or "latest" for last non-NaN vintage.
            alpha (float): Significance level for tests.

        returns:
            BiasednessRegressionResult: Results including OLS estimates and tests of unbiasedness.

        """

        if independent_vintage_index is None or dependent_vintage_index is None:
            raise ValueError(
                "Both independent_vintage_index and dependent_vintage_index are required."
            )

        merged, data_notes = self._prepare_indexed_vintage_regression_data(
            independent_vintage_index=independent_vintage_index,
            dependent_vintage_index=dependent_vintage_index,
        )

        y = merged["y"].to_numpy(dtype=float)
        x = merged["x"].to_numpy(dtype=float)

        X = sm.add_constant(x, has_constant="add")
        model = sm.OLS(y, X)
        result = model.fit()

        return self._prepare_biasedness_regression_output(
            result=result,
            alpha=alpha,
            independent_vintage_index=independent_vintage_index,
            dependent_vintage_index=dependent_vintage_index,
            data_notes=data_notes,
        )

    def revision_uncertainty(
        self,
        forecast_method: str = "ARIMA",
        min_train_size: int = 4,
        model_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """
        Revision uncertainty calculation from Runkle (1998).

        Args:
            forecast_method (str): The method to use for forecasting. Supported methods are
                "ExponentialSmoothing", "Naive", "ARIMA", and "LinearRegression".
                Defaults to AR(2). I.e. ARIMA with order (2, 0, 0).
            min_train_size (int): Minimum number of observations required to fit the model
                in the rolling forecast loop. Defaults to 3.
            model_kwargs (Optional[Dict[str, Any]]): Optional keyword arguments to pass to the
                forecasting model upon initialization. For ARIMA models, you can specify
                {'order': (p, d, q)} to customize the model order. Defaults to None.

        Returns:
            Dict[str, float]: A dictionary containing:
                - "std_dev_forecast_errors": Standard deviation of rolling forecast errors.
                - "std_dev_revisions": Standard deviation of final-minus-initial revisions.
                - "ratio": Ratio of std_dev_revisions to std_dev_forecast_errors.

        Note:
            ARIMA requires at least 30 observations per training window (darts
            limitation, see https://github.com/unit8co/darts/pull/2353). Rolling
            steps with shorter windows are skipped, which can yield an empty
            forecast-error sample and a NaN ratio on short series.
        """
        forecast_methods = {
            "ExponentialSmoothing": ExponentialSmoothing,
            "Naive": NaiveDrift,
            "LinearRegression": LinearRegressionModel,
            "ARIMA": ARIMA,
        }

        if forecast_method not in forecast_methods.keys():
            raise ValueError(
                f"Invalid forecast method: {forecast_method}. Supported methods are: {forecast_methods}"
            )

        # Initialize model_kwargs if not provided
        if model_kwargs is None:
            model_kwargs = {}

        # Set ARIMA default to AR(2) if not specified.
        # TODO: darts enforces a 30-observation minimum on ARIMA training windows,
        # so rolling steps below that are silently skipped via the ValueError handler
        # in the loop below. Remove this note once unit8co/darts#2353 lands and the
        # minimum is configurable. https://github.com/unit8co/darts/pull/2353
        if forecast_method == "ARIMA":
            model_kwargs.setdefault("p", 2)
            model_kwargs.setdefault("d", 0)
            model_kwargs.setdefault("q", 0)
            model_kwargs.setdefault("seasonal_order", (0, 0, 0, 0))
            model_kwargs.setdefault("trend", "n")

        model_class = forecast_methods[forecast_method]

        # Rolling one-step-ahead forecast errors across time using the latest vintage.
        forecast_errors = []
        darts_ts = self.ts.to_darts_timeseries()

        if len(darts_ts) >= (min_train_size + 1):

            for i in range(min_train_size, len(darts_ts)):
                train = darts_ts[:i]
                test = darts_ts[i : i + 1]
                model = model_class(**model_kwargs)
                try:
                    model.fit(train)
                except ValueError as exc:
                    logger.info(
                        "Skipping rolling forecast step with training window %s: %s",
                        len(train),
                        exc,
                    )
                    continue
                forecast = model.predict(1)
                forecast_value = float(forecast.values().reshape(-1)[0])
                actual_value = float(test.values().reshape(-1)[0])
                forecast_errors.append(forecast_value - actual_value)
        else:
            logger.info(
                "Not enough observations to perform rolling forecast; "
                f"need at least {min_train_size + 1}, have {len(darts_ts)}."
            )

        std_dev_forecast_errors = pd.Series(forecast_errors).std()

        # Final-minus-initial revisions for each timestamp.
        vm = self.ts.generate_vintage_matrix()

        def _final_minus_initial(row: pd.Series) -> Optional[float]:
            non_na = row.dropna()
            if len(non_na) < 2:
                return None
            return non_na.iloc[-1] - non_na.iloc[0]

        final_initial_revisions = vm.apply(_final_minus_initial, axis=1).dropna()
        std_revisions = final_initial_revisions.std()

        return {
            "std_dev_forecast_errors": std_dev_forecast_errors,
            "std_dev_revisions": std_revisions,
            "ratio": std_revisions / std_dev_forecast_errors,
        }

    def decompose_vintage(
        self,
        model: Union[str, SeasonalityMode, ModelMode] = ModelMode.MULTIPLICATIVE,
        method: str = "naive",
        to_darts_timeseries_kwargs: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Decompose the current vintage into trend and seasonal components.

        Args:
            model (Union[str, SeasonalityMode, ModelMode]): Decomposition type. Accepts
                "additive"/"multiplicative" strings or Darts enum values.
            method (str): Decomposition method ("naive", "STL", or "MSTL").
            to_darts_timeseries_kwargs (Optional[Dict[str, Any]]): Keyword arguments passed to ``self.ts.to_darts_timeseries``.
            **kwargs (Any): Additional keyword arguments passed to Darts decomposition.

        Returns:
            Dict[str, Any]: Dictionary with release_date, trend TimeSeries, and seasonal TimeSeries.
        """
        if to_darts_timeseries_kwargs is None:
            to_darts_timeseries_kwargs = {}

        if isinstance(model, str):
            normalized_model = model.strip().lower()
            if normalized_model == "additive":
                model = ModelMode.ADDITIVE
            elif normalized_model == "multiplicative":
                model = ModelMode.MULTIPLICATIVE
            else:
                raise ValueError(
                    "Invalid model string. Supported values are 'additive' and 'multiplicative'."
                )

        seasonal_period = self.ts.metadata.get_frequency_as_numeric()
        darts_ts = self.ts.to_darts_timeseries(**to_darts_timeseries_kwargs)
        trend, seasonal = extract_trend_and_seasonality(
            ts=darts_ts,
            freq=seasonal_period,
            model=model,
            method=method,
            **kwargs,
        )

        return {
            "release_date": self.ts.release_date,
            "trend": trend,
            "seasonal": seasonal,
        }

    def select_vintage_by_index(
        self,
        vintage_index: int | str,
        include_vintage_date: bool = True,
        dropna: bool = True,
    ) -> pd.DataFrame:
        """
        Select the vintage value by 1-based index (or -1/"latest") for each timestamp.

        Args:
            vintage_index (int | str): 1-based index, -1, or "latest".
            include_vintage_date (bool): Include the release date of the selected vintage.
            dropna (bool): Drop rows where the indexed vintage is missing.

        Returns:
            pd.DataFrame: Columns include 'timestamp', 'value', and optionally 'vintage_date'.
        """
        self._warn_if_vintage_filters()
        return self._select_vintage_df(
            vintage_index=vintage_index,
            include_vintage_date=include_vintage_date,
            dropna=dropna,
        )

    def vintage_comparison(
        self, vintage_dates: List[str], mode: str = "growth", strategy: str = "all"
    ) -> "VintageComparison":
        """
        Compare vintages across summary measures describing revisions of a
        time series, adapted from Young (1974). Comparison uses only
        observations present in both vintages (inner join on timestamp).

        For each pair of vintages, let **I** denote the value at each
        timestamp in the initial (earlier) vintage and **L** denote the
        value at the same timestamp in the latest (later) vintage. The
        meaning of "value" depends on ``mode``:

        - ``mode="growth"``: I and L are within-vintage period-over-period
          growth rates (computed via ``pct_change`` on each vintage
          independently before comparison). Metrics describe revisions to
          the **growth rate**.
        - ``mode="levels"``: I and L are the raw level values themselves.
          Metrics describe revisions to the **level**.

        **Sign convention.** Following Young (1974), revisions are computed
        as ``I - L`` (preliminary minus final). A NEGATIVE revision therefore
        means the series was revised UP between vintages (L > I), and a
        POSITIVE revision means it was revised DOWN. The metric *names*
        ("upward", "downward") describe what happened to the underlying
        series; the *sign* of the corresponding number is the opposite.

        Common measures (both modes):
            - bias: mean(I - L)
            - relative_bias: mean(I - L) / mean(L)
            - dispersion: mean(|I - L|)
            - relative_dispersion: mean(|I - L|) / mean(|L|)
            - largest_upward_revision: min(I - L)   (most negative since I-L<0 means L>I)
            - largest_downward_revision: max(I - L)
            - standard_deviation_of_revisions_difference: sample std(I - L)
            - counts: number of upward, downward, and no-change revisions.

        Mode-specific directional-miss measures:
            - growth mode:
                - directional_misses_trend: fraction of timestamps where the
                  growth rate changes sign between vintages (rose vs fell).
            - levels mode:
                - directional_misses_sign: fraction of timestamps where the
                  level itself changes sign between vintages
                  (e.g. a trade balance crossing zero).
                - directional_misses_trend: fraction of timestamps where the
                  period-over-period change in the level changes sign between vintages.

        Args:
            vintage_dates (List[str]): A list of vintage identifiers to compare.
            mode (str): The mode of comparison ("growth" or "levels").
            strategy (str): The strategy for comparison ("sequential", "final", or "all").

        Returns:
            VintageComparison: Object whose ``comparison`` attribute maps pair labels to per-pair metric dicts.
        """
        # Resolve each requested date via as_of() and key on the resolved
        # vintage's release_date so output labels reflect what we actually compared.
        vintage_objs: Dict[str, "MTTimeSeries"] = {}
        resolutions: Dict[str, List[str]] = {}
        for requested in vintage_dates:
            resolved = self.ts.as_of(requested)
            resolved_key = resolved.release_date.isoformat()
            logger.info(
                "vintage_comparison: requested %s resolved to release %s",
                requested,
                resolved_key,
            )
            resolutions.setdefault(resolved_key, []).append(requested)
            vintage_objs[resolved_key] = resolved

        # Two requested dates that resolve to the same release will collapse to a single entry here.
        collapsed = {k: v for k, v in resolutions.items() if len(v) > 1}
        if collapsed:
            logger.warning(
                "vintage_comparison: %s requested dates collapsed to %s unique "
                "vintages. Collapses (resolved_release -> requested_dates): %s",
                len(vintage_dates),
                len(vintage_objs),
                collapsed,
            )

        comparison = VintageComparison(
            vintages=vintage_objs,
            mode=mode,
            strategy=strategy,
        )
        return comparison

    def _durbin_watson(self, resid: np.ndarray) -> Optional[float]:
        if len(resid) < 2:
            return None
        stat = float(durbin_watson(resid))
        if not np.isfinite(stat):
            return None
        return stat

    def _ljung_box(self, resid: np.ndarray, lags: int, alpha: float) -> Dict[str, Any]:
        n = len(resid)
        effective_lags = max(1, min(lags, n - 1))
        if n < 3:
            return {
                "stat": None,
                "pvalue": None,
                "lags": effective_lags,
                "alpha": alpha,
                "pass": False,
                "note": "Insufficient observations for Ljung-Box test",
            }
        lb = acorr_ljungbox(resid, lags=[effective_lags], return_df=True)
        stat = float(lb["lb_stat"].iloc[0])
        pvalue = float(lb["lb_pvalue"].iloc[0])
        return {
            "stat": stat,
            "pvalue": pvalue,
            "lags": effective_lags,
            "alpha": alpha,
            "pass": pvalue >= alpha,
        }

    def _normalize_index(self, value: int | str) -> int | str:
        if isinstance(value, str):
            if value.lower() != "latest":
                raise ValueError(
                    "Vintage index string must be 'latest' if provided as text."
                )
            return "latest"
        if isinstance(value, int):
            if value == -1:
                return "latest"
            if value < 1:
                raise ValueError("Vintage index must be >= 1 or use -1/'latest'.")
            return value
        raise ValueError("Vintage index must be an int or 'latest'.")

    def _prepare_indexed_vintage_regression_data(
        self,
        independent_vintage_index: int | str,
        dependent_vintage_index: int | str,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        vintage_filters_applied = self._warn_if_vintage_filters()

        vm = self.ts.generate_vintage_matrix()
        if vm.empty:
            raise ValueError("No vintage data available for regression.")
        vm = vm.sort_index(axis=1)

        x_df = self._select_vintage_df(
            vintage_index=independent_vintage_index,
            include_vintage_date=False,
            dropna=False,
            vm=vm,
        ).rename(columns={"value": "x"})
        y_df = self._select_vintage_df(
            vintage_index=dependent_vintage_index,
            include_vintage_date=False,
            dropna=False,
            vm=vm,
        ).rename(columns={"value": "y"})

        df = pd.merge(x_df, y_df, on="timestamp", how="inner")
        df = df.sort_values("timestamp").reset_index(drop=True)

        missing_x = int(df["x"].isna().sum())
        missing_y = int(df["y"].isna().sum())
        merged = df.dropna().reset_index(drop=True)
        dropped = int(len(df) - len(merged))

        if dropped > 0:
            logger.debug(
                "Dropped %s rows due to missing indexed vintages (x missing=%s, y missing=%s).",
                dropped,
                missing_x,
                missing_y,
            )

        if merged.empty:
            raise ValueError(
                "No overlapping observations after applying vintage index selection."
            )

        data_notes = {
            "missing_x": missing_x,
            "missing_y": missing_y,
            "dropped_rows": dropped,
            "vintage_filters_applied": vintage_filters_applied,
        }

        return merged, data_notes

    def _prepare_biasedness_regression_output(
        self,
        result: sm.regression.linear_model.RegressionResultsWrapper,
        alpha: float,
        independent_vintage_index: int | str,
        dependent_vintage_index: int | str,
        data_notes: Dict[str, Any],
    ) -> BiasednessRegressionResult:
        alpha_hat = float(result.params[0])
        beta_hat = float(result.params[1])
        se_alpha = float(result.bse[0])
        se_beta = float(result.bse[1])

        t_alpha = alpha_hat / se_alpha if se_alpha != 0 else None
        t_beta = (beta_hat - 1.0) / se_beta if se_beta != 0 else None
        df_resid = int(result.df_resid)

        p_alpha = (
            float(2 * t_dist.sf(abs(t_alpha), df_resid))
            if t_alpha is not None
            else None
        )
        p_beta = (
            float(2 * t_dist.sf(abs(t_beta), df_resid)) if t_beta is not None else None
        )

        conf_int = result.conf_int(alpha=alpha)
        alpha_ci = (float(conf_int[0][0]), float(conf_int[0][1]))
        beta_ci = (float(conf_int[1][0]), float(conf_int[1][1]))

        f_test = result.f_test("const = 0, x1 = 1")
        f_stat = float(np.asarray(f_test.fvalue).item())
        f_pvalue = float(np.asarray(f_test.pvalue).item())
        df_num = int(f_test.df_num)
        df_den = int(f_test.df_denom)

        dw = self._durbin_watson(result.resid)
        lb = self._ljung_box(result.resid, lags=1, alpha=alpha)

        def _stars(pvalue: Optional[float]) -> str:
            if pvalue is None:
                return ""
            return "*" if pvalue < alpha else ""

        def _fmt(value: Optional[float], digits: int = 4) -> str:
            if value is None or not np.isfinite(value):
                return "NA"
            return f"{value:.{digits}f}"

        coef_table = tabulate(
            [
                [
                    "alpha (const)",
                    f"{_fmt(alpha_hat)}{_stars(p_alpha)}",
                    _fmt(se_alpha),
                    _fmt(t_alpha),
                    _fmt(p_alpha),
                    _fmt(alpha_ci[0]),
                    _fmt(alpha_ci[1]),
                ],
                [
                    "beta (x)",
                    f"{_fmt(beta_hat)}{_stars(p_beta)}",
                    _fmt(se_beta),
                    _fmt(t_beta),
                    _fmt(p_beta),
                    _fmt(beta_ci[0]),
                    _fmt(beta_ci[1]),
                ],
            ],
            headers=[
                "Param",
                "Estimate",
                "Std Err",
                "t (H0)",
                "p (H0)",
                f"CI Low ({int((1 - alpha) * 100)}%)",
                f"CI High ({int((1 - alpha) * 100)}%)",
            ],
            tablefmt="pretty",
        )

        return BiasednessRegressionResult(
            n_total=int(result.nobs),
            vintage_indices={
                "independent": independent_vintage_index,
                "dependent": dependent_vintage_index,
                "index_base": 1,
            },
            data_notes=data_notes,
            model={
                "alpha": alpha_hat,
                "beta": beta_hat,
                "alpha_ci": {"low": alpha_ci[0], "high": alpha_ci[1]},
                "beta_ci": {"low": beta_ci[0], "high": beta_ci[1]},
                "rss": float(result.ssr),
                "s2": float(result.mse_resid),
                "r2": float(result.rsquared),
                "n": int(result.nobs),
                "durbin_watson": dw,
            },
            tests={
                "alpha_eq_0": {"t": t_alpha, "pvalue": p_alpha},
                "beta_eq_1": {"t": t_beta, "pvalue": p_beta},
                "unbiasedness": {
                    "f_stat": f_stat,
                    "pvalue": f_pvalue,
                    "df_num": df_num,
                    "df_den": df_den,
                    "alpha": alpha,
                    "reject": f_pvalue < alpha,
                },
            },
            assumptions={
                "random_residuals": {
                    "test": "ljung_box",
                    **lb,
                }
            },
            table=coef_table,
        )

    def _select_vintage_df(
        self,
        vintage_index: int | str,
        include_vintage_date: bool = True,
        dropna: bool = True,
        vm: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        idx = self._normalize_index(vintage_index)
        if vm is None:
            vm = self.ts.generate_vintage_matrix()
            if vm.empty:
                raise ValueError("No vintage data available for selection.")
        vm = vm.sort_index(axis=1)

        def _select_row(row: pd.Series) -> Tuple[float, pd.Timestamp]:
            non_na = row.dropna()
            if non_na.empty:
                return np.nan, pd.NaT
            if idx == "latest":
                return float(non_na.iloc[-1]), non_na.index[-1]
            pos = idx - 1
            if pos >= len(non_na):
                return np.nan, pd.NaT
            return float(non_na.iloc[pos]), non_na.index[pos]

        selected = vm.apply(_select_row, axis=1, result_type="expand")
        selected.columns = ["value", "vintage_date"]
        selected.index.name = "timestamp"
        df = selected.reset_index()

        if not include_vintage_date:
            df = df.drop(columns=["vintage_date"])

        if dropna:
            df = df.dropna(subset=["value"]).reset_index(drop=True)

        return df

    def _warn_if_vintage_filters(self) -> bool:
        applied = (
            self.ts.vintage_start_date is not None
            or self.ts.vintage_end_date is not None
        )
        if applied:
            logger.warning(
                "Vintage date filters are currently applied. This may affect indexed vintage selection."
            )
        return applied
