import pytest
from unittest.mock import MagicMock, patch
import datetime

import numpy as np
import pandas as pd
from tests.models.mt.utils import (
    sample_time_series,
    sample_time_series_with_revisions,
    empty_timeseries,
)
from macrotrace.models.mt.analysis import MTTimeSeriesAnalysis, VintageComparison
from tests.models.mt.utils import UTC
from darts.utils.utils import ModelMode


@pytest.fixture
def sample_vintage_matrix():
    return pd.DataFrame(
        {
            "2024-01-01": [100.0, 99.0, 98.0, 102.0],
            "2024-02-01": [102.0, 98.0, 103.0, 104.0],
            "2024-03-01": [101.0, 100.0, 105.0, 106.0],
            "2024-04-01": [103.0, 97.0, 106.0, 107.0],
        },
        index=[
            datetime.datetime(2024, 1, 1, tzinfo=UTC),
            datetime.datetime(2024, 2, 1, tzinfo=UTC),
            datetime.datetime(2024, 3, 1, tzinfo=UTC),
            datetime.datetime(2024, 4, 1, tzinfo=UTC),
        ],
    )


@pytest.fixture
def mock_regression_result():
    class DummyFTest:
        def __init__(self, fvalue, pvalue, df_num, df_denom):
            self.fvalue = fvalue
            self.pvalue = pvalue
            self.df_num = df_num
            self.df_denom = df_denom

    class DummyResult:
        def __init__(
            self,
            alpha_hat=2.0,
            beta_hat=1.05,
            se_alpha=0.5,
            se_beta=0.5,
            df_resid=10,
            fvalue=5.0,
            f_pvalue=0.04,
            ssr=4.0,
            mse_resid=0.4,
            rsquared=0.9,
            nobs=12,
            conf_int=None,
        ):
            self.params = np.array([alpha_hat, beta_hat])
            self.bse = np.array([se_alpha, se_beta])
            self.df_resid = df_resid
            self.resid = np.array([1.0, -1.0, 0.5, -0.5])
            self.ssr = ssr
            self.mse_resid = mse_resid
            self.rsquared = rsquared
            self.nobs = nobs
            self._f_test = DummyFTest(fvalue, f_pvalue, 2, df_resid)
            if conf_int is None:
                conf_int = np.array([[0.9, 3.1], [0.8, 1.2]])
            self._conf_int = conf_int

        def conf_int(self, alpha):
            return self._conf_int

        def f_test(self, *_args, **_kwargs):
            return self._f_test

    return DummyResult


def test_assess_revision_success_matrix(empty_timeseries, sample_vintage_matrix):
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=sample_vintage_matrix
    )

    expected_df = pd.DataFrame(
        {
            "2024-01-01": [pd.NA, pd.NA, pd.NA, pd.NA],
            "2024-02-01": [True, True, True, True],
            "2024-03-01": [False, False, True, True],
            "2024-04-01": [pd.NA, pd.NA, pd.NA, pd.NA],
        },
        index=[
            datetime.datetime(2024, 1, 1, tzinfo=UTC),
            datetime.datetime(2024, 2, 1, tzinfo=UTC),
            datetime.datetime(2024, 3, 1, tzinfo=UTC),
            datetime.datetime(2024, 4, 1, tzinfo=UTC),
        ],
    )

    df, success_rate = empty_timeseries.analysis.assess_revision_success()

    assert df.values.flatten().tolist() == expected_df.values.flatten().tolist()
    assert success_rate == 6 / 8


def test_assess_revision_success_with_nulls_and_no_change(empty_timeseries):
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=pd.DataFrame(
            {
                "2024-01-01": [100.0, 99.0, 98.0, 102.0],
                "2024-02-01": [100.0, 98.0, 103.0, 104.0],
                "2024-03-01": [100.0, pd.NA, 105.0, 106.0],
                "2024-04-01": [100.0, 103.0, 103.0, 107.0],
            },
            index=[
                datetime.datetime(2024, 1, 1, tzinfo=UTC),
                datetime.datetime(2024, 2, 1, tzinfo=UTC),
                datetime.datetime(2024, 3, 1, tzinfo=UTC),
                datetime.datetime(2024, 4, 1, tzinfo=UTC),
            ],
        )
    )

    expected_df = pd.DataFrame(
        {
            "2024-01-01": [pd.NA, pd.NA, pd.NA, pd.NA],
            "2024-02-01": [pd.NA, False, True, True],
            "2024-03-01": [pd.NA, pd.NA, False, True],
            "2024-04-01": [pd.NA, pd.NA, pd.NA, pd.NA],
        },
        index=[
            datetime.datetime(2024, 1, 1, tzinfo=UTC),
            datetime.datetime(2024, 2, 1, tzinfo=UTC),
            datetime.datetime(2024, 3, 1, tzinfo=UTC),
            datetime.datetime(2024, 4, 1, tzinfo=UTC),
        ],
    )

    df, success_rate = empty_timeseries.analysis.assess_revision_success()

    assert df.values.flatten().tolist() == expected_df.values.flatten().tolist()
    assert success_rate == 3 / 5


def test_revision_success_no_changes(empty_timeseries):
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=pd.DataFrame(
            {
                "2024-01-01": [100.0, 100.0, 100.0],
                "2024-02-01": [100.0, 100.0, 100.0],
                "2024-03-01": [100.0, 100.0, 100.0],
            },
            index=[
                datetime.datetime(2024, 1, 1),
                datetime.datetime(2024, 2, 1),
                datetime.datetime(2024, 3, 1),
            ],
        )
    )

    expected_df = pd.DataFrame(
        {
            "2024-01-01": [pd.NA, pd.NA, pd.NA],
            "2024-02-01": [pd.NA, pd.NA, pd.NA],
            "2024-03-01": [pd.NA, pd.NA, pd.NA],
        },
        index=[
            datetime.datetime(2024, 1, 1),
            datetime.datetime(2024, 2, 1),
            datetime.datetime(2024, 3, 1),
        ],
    )

    df, success_rate = empty_timeseries.analysis.assess_revision_success()

    assert df.values.flatten().tolist() == expected_df.values.flatten().tolist()
    assert success_rate is pd.NA


def test_vintage_comparison_all_strategy(sample_time_series):
    vintage_dates = [
        sample_time_series.vintages[0].release_date.isoformat(),
        sample_time_series.release_date.isoformat(),
    ]

    comparison = sample_time_series.analysis.vintage_comparison(
        vintage_dates=vintage_dates,
        strategy="all",
    )

    result = comparison[f"vintage_{vintage_dates[0]}_to_{vintage_dates[1]}"]
    assert "bias" in result
    assert "dispersion" in result
    assert "counts" in result


def test_vintage_comparison_repr_and_getitem_errors(sample_time_series):
    """VintageComparison.__repr__ describes mode/strategy and __getitem__ raises on miss."""
    vintage_dates = [
        sample_time_series.vintages[0].release_date.isoformat(),
        sample_time_series.release_date.isoformat(),
    ]

    comparison = sample_time_series.analysis.vintage_comparison(
        vintage_dates=vintage_dates,
        strategy="all",
    )

    rendered = repr(comparison)
    assert "VintageComparison" in rendered
    assert comparison.strategy in rendered

    with pytest.raises(KeyError):
        comparison["not-a-real-vintage-pair"]


def test_vintage_comparison_invalid_mode_raises():
    """Constructing a VintageComparison with an unknown mode raises ValueError."""
    with pytest.raises(ValueError, match="Invalid mode"):
        VintageComparison(
            vintages={"a": MagicMock(), "b": MagicMock()},
            mode="not-a-mode",
            strategy="all",
        )


def test_vintage_comparison_invalid_strategy_raises():
    """Constructing a VintageComparison with an unknown strategy raises ValueError."""
    with pytest.raises(ValueError, match="Invalid strategy"):
        VintageComparison(
            vintages={"a": MagicMock(), "b": MagicMock()},
            mode="growth",
            strategy="not-a-strategy",
        )


def test_compare_vintages_requires_two_value_columns(empty_timeseries):
    """_compare_vintages raises when the merge yields the wrong column count."""
    vc = VintageComparison.__new__(VintageComparison)
    df_a = pd.DataFrame({"timestamp": [1, 2], "v_a": [1.0, 2.0], "extra": [3.0, 4.0]})
    df_b = pd.DataFrame({"timestamp": [1, 2], "v_b": [1.1, 2.1]})

    with pytest.raises(ValueError, match="exactly two value columns"):
        vc._compare_vintages(df_a, df_b)


def test_biasedness_regression_result_repr_falls_back_to_class_name():
    """Empty `table` falls back to the class-name repr."""
    from macrotrace.models.mt.analysis import BiasednessRegressionResult

    result = BiasednessRegressionResult(
        n_total=0,
        vintage_indices={},
        data_notes={},
        model={},
        tests={},
        assumptions={},
        table="",
    )
    assert repr(result) == "BiasednessRegressionResult()"


def test_compare_vintages_metric_values():
    timestamps = pd.to_datetime(
        ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]
    )
    initial = pd.DataFrame(
        {"timestamp": timestamps, "vintage_initial": [0.02, 0.05, 0.01, -0.03]}
    )
    latest = pd.DataFrame(
        {"timestamp": timestamps, "vintage_latest": [0.04, 0.03, 0.06, -0.02]}
    )

    vc = VintageComparison.__new__(VintageComparison)
    vc.mode = "growth"

    result = VintageComparison._compare_vintages(vc, initial, latest)

    # revisions = initial - latest = [-0.02, 0.02, -0.05, -0.01]
    assert result["bias"] == pytest.approx(-0.015)
    assert result["dispersion"] == pytest.approx(0.025)
    # latest at 2024-03 was 0.06 vs initial 0.01 -> biggest upward revision (-0.05)
    assert result["largest_upward_revision"] == pytest.approx(-0.05)
    # latest at 2024-02 was 0.03 vs initial 0.05 -> biggest downward revision (+0.02)
    assert result["largest_downward_revision"] == pytest.approx(0.02)
    assert result["largest_upward_revision"] < result["largest_downward_revision"]
    assert result["counts"] == {"upward": 3, "downward": 1, "no_change": 0}


def test_vintage_comparison_final_strategy(sample_time_series):
    vintage_dates = [
        sample_time_series.vintages[0].release_date.isoformat(),
        sample_time_series.vintages[1].release_date.isoformat(),
        sample_time_series.release_date.isoformat(),
    ]

    comparison = sample_time_series.analysis.vintage_comparison(
        vintage_dates=vintage_dates,
        strategy="final",
    )

    expected_keys = {
        f"vintage_{vintage_dates[0]}_to_{vintage_dates[2]}",
        f"vintage_{vintage_dates[1]}_to_{vintage_dates[2]}",
    }
    assert expected_keys.issubset(comparison.comparison.keys())


def test_compare_vintages_levels_mode_metric_values():
    """
    Pin numeric values for levels mode. Levels mode reports both
    directional_misses_sign (sign flip of the level) and
    directional_misses_trend (sign flip of the first difference).
    """
    timestamps = pd.to_datetime(
        ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"]
    )
    # initial trend: up, down, up;  latest trend: up, up, down
    initial = pd.DataFrame(
        {"timestamp": timestamps, "vintage_initial": [100.0, 105.0, 103.0, 107.0]}
    )
    latest = pd.DataFrame(
        {"timestamp": timestamps, "vintage_latest": [101.0, 103.0, 106.0, 105.0]}
    )

    vc = VintageComparison.__new__(VintageComparison)
    vc.mode = "levels"

    result = VintageComparison._compare_vintages(vc, initial, latest)

    # revisions = initial - latest = [-1.0, 2.0, -3.0, 2.0]
    assert result["bias"] == pytest.approx(0.0)
    assert result["dispersion"] == pytest.approx(2.0)
    assert result["largest_upward_revision"] == pytest.approx(-3.0)
    assert result["largest_downward_revision"] == pytest.approx(2.0)
    assert result["counts"] == {"upward": 2, "downward": 2, "no_change": 0}

    # All levels are positive so no sign flips on the level itself.
    assert result["directional_misses_sign"] == pytest.approx(0.0)
    # First diffs: initial=[NaN,5,-2,4], latest=[NaN,2,3,-1]; products at
    # t=Mar (-6) and t=Apr (-4) are negative -> 2 misses out of 4 rows.
    assert result["directional_misses_trend"] == pytest.approx(0.5)


def test_compare_vintages_levels_directional_misses_sign_flip():
    """directional_misses_sign should fire when the level crosses zero."""
    timestamps = pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"])
    initial = pd.DataFrame(
        {"timestamp": timestamps, "vintage_initial": [-1.0, 1.0, -2.0]}
    )
    latest = pd.DataFrame({"timestamp": timestamps, "vintage_latest": [1.0, -1.0, 2.0]})

    vc = VintageComparison.__new__(VintageComparison)
    vc.mode = "levels"

    result = VintageComparison._compare_vintages(vc, initial, latest)

    # Every timestamp the level flips sign -> 3/3 = 1.0
    assert result["directional_misses_sign"] == pytest.approx(1.0)


def test_vintage_comparison_levels_mode_through_public_api(sample_time_series):
    """End-to-end: mode='levels' is accepted and produces level-mode keys."""
    vintage_dates = [
        sample_time_series.vintages[0].release_date.isoformat(),
        sample_time_series.release_date.isoformat(),
    ]
    comparison = sample_time_series.analysis.vintage_comparison(
        vintage_dates=vintage_dates,
        mode="levels",
        strategy="all",
    )
    pair = comparison[f"vintage_{vintage_dates[0]}_to_{vintage_dates[1]}"]
    assert "bias" in pair
    assert "directional_misses_sign" in pair
    assert "directional_misses_trend" in pair


def test_vintage_comparison_rejects_invalid_mode(sample_time_series):
    vintage_dates = [
        sample_time_series.vintages[0].release_date.isoformat(),
        sample_time_series.release_date.isoformat(),
    ]
    with pytest.raises(ValueError, match="Must be 'growth' or 'levels'"):
        sample_time_series.analysis.vintage_comparison(
            vintage_dates=vintage_dates,
            mode="bogus",
        )


def test_vintage_comparison_keys_use_resolved_release_date(sample_time_series, caplog):
    """
    When the requested date does not match a release exactly, the comparison
    output should be labeled with the resolved release_date and an INFO log
    should record the resolution.
    """
    earliest = sample_time_series.vintages[0].release_date.isoformat()
    latest = sample_time_series.release_date.isoformat()
    # Sample fixture has daily vintages Dec 2-15 (UTC midnight). A timestamp
    # at noon on Dec 4 falls between the Dec 4 and Dec 5 releases, so as_of
    # should resolve it back to the Dec 4 vintage.
    inexact_request = "2024-12-04T12:00:00"
    expected_resolved = "2024-12-04T00:00:00+00:00"

    caplog.set_level("INFO", logger="macrotrace.models.mt.analysis")
    comparison = sample_time_series.analysis.vintage_comparison(
        vintage_dates=[earliest, inexact_request, latest],
        strategy="sequential",
    )

    assert list(comparison.comparison.keys()) == [
        f"vintage_{earliest}_to_{expected_resolved}",
        f"vintage_{expected_resolved}_to_{latest}",
    ]
    assert (
        f"requested {inexact_request} resolved to release {expected_resolved}"
        in caplog.text
    )


def test_vintage_comparison_dedupes_and_warns_on_collapse(sample_time_series, caplog):
    """
    Two distinct requested dates that resolve to the same vintage must
    collapse into a single entry, and the user must be warned.
    """
    earliest = sample_time_series.vintages[0].release_date.isoformat()
    # Both timestamps fall on Dec 4 between the Dec 4 and Dec 5 vintage
    # releases, so they both resolve to the Dec 4 vintage.
    collapse_a = "2024-12-04T01:00:00"
    collapse_b = "2024-12-04T23:00:00"
    collapsed_resolved = "2024-12-04T00:00:00+00:00"

    caplog.set_level("WARNING", logger="macrotrace.models.mt.analysis")
    comparison = sample_time_series.analysis.vintage_comparison(
        vintage_dates=[earliest, collapse_a, collapse_b],
        strategy="all",
    )

    # 3 requested -> 2 unique resolved vintages.
    assert len(comparison.vintages) == 2
    assert collapsed_resolved in comparison.vintages
    # Only one pairwise comparison since only two unique vintages remain.
    assert list(comparison.comparison.keys()) == [
        f"vintage_{earliest}_to_{collapsed_resolved}"
    ]
    assert "3 requested dates collapsed to 2 unique vintages" in caplog.text
    assert collapse_a in caplog.text
    assert collapse_b in caplog.text


@pytest.mark.parametrize("strategy", ["sequential", "final", "all"])
def test_vintage_comparison_rejects_too_few_vintages(sample_time_series, strategy):
    """All strategies need at least 2 vintages; empty or single-element input
    must raise ValueError instead of crashing or silently returning nothing."""
    with pytest.raises(ValueError, match="at least 2 vintages"):
        sample_time_series.analysis.vintage_comparison(
            vintage_dates=[], strategy=strategy
        )

    only = [sample_time_series.vintages[0].release_date.isoformat()]
    with pytest.raises(ValueError, match="at least 2 vintages"):
        sample_time_series.analysis.vintage_comparison(
            vintage_dates=only, strategy=strategy
        )


def test_vintage_comparison_sequential_sorts_unsorted_input(sample_time_series):
    chrono = [
        sample_time_series.vintages[0].release_date.isoformat(),
        sample_time_series.vintages[1].release_date.isoformat(),
        sample_time_series.release_date.isoformat(),
    ]
    shuffled = [chrono[2], chrono[0], chrono[1]]

    comparison = sample_time_series.analysis.vintage_comparison(
        vintage_dates=shuffled,
        strategy="sequential",
    )

    assert list(comparison.comparison.keys()) == [
        f"vintage_{chrono[0]}_to_{chrono[1]}",
        f"vintage_{chrono[1]}_to_{chrono[2]}",
    ]


@patch("macrotrace.models.mt.analysis.ARIMA")
def test_revision_uncertainty_skips_undersized_arima_windows(
    mock_arima, empty_timeseries, sample_vintage_matrix
):
    class FakeSeries:
        def __init__(self, values):
            self._values = list(values)

        def __len__(self):
            return len(self._values)

        def __getitem__(self, item):
            if isinstance(item, slice):
                return FakeSeries(self._values[item])
            return self._values[item]

        def values(self):
            return np.array(self._values, dtype=float).reshape(-1, 1, 1)

    class FakeARIMA:
        def __init__(self, **_kwargs):
            self._forecast_value = None

        def fit(self, train):
            if len(train) < 3:
                raise ValueError("need at least 3 observations")
            self._forecast_value = train.values()[-1][0][0] + (len(train) * 0.1)
            return self

        def predict(self, n):
            return FakeSeries([self._forecast_value] * n)

    mock_arima.side_effect = lambda **kwargs: FakeARIMA(**kwargs)

    empty_timeseries.to_darts_timeseries = MagicMock(
        return_value=FakeSeries([1.0, 2.0, 3.0, 4.0, 5.0])
    )
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=sample_vintage_matrix
    )

    result = empty_timeseries.analysis.revision_uncertainty(
        forecast_method="ARIMA",
        min_train_size=1,
    )

    assert result["std_dev_forecast_errors"] > 0
    assert result["std_dev_revisions"] > 0
    assert result["ratio"] > 0


@patch("macrotrace.models.mt.analysis.extract_trend_and_seasonality")
def test_decompose_vintage(mock_extract, empty_timeseries):
    empty_timeseries.to_darts_timeseries = MagicMock(return_value="mock_darts_ts")
    empty_timeseries.metadata.get_frequency_as_numeric = MagicMock(return_value=12)
    mock_extract.return_value = ("trend_component", "seasonal_component")

    result = empty_timeseries.analysis.decompose_vintage(
        model="additive",
        method="STL",
        to_darts_timeseries_kwargs={"fill_missing_dates": True},
        robust=True,
    )

    empty_timeseries.to_darts_timeseries.assert_called_once_with(
        fill_missing_dates=True
    )
    empty_timeseries.metadata.get_frequency_as_numeric.assert_called_once_with()
    mock_extract.assert_called_once_with(
        ts="mock_darts_ts",
        freq=12,
        model=ModelMode.ADDITIVE,
        method="STL",
        robust=True,
    )
    assert result["release_date"] == empty_timeseries.release_date
    assert result["trend"] == "trend_component"
    assert result["seasonal"] == "seasonal_component"


@patch("macrotrace.models.mt.analysis.extract_trend_and_seasonality")
def test_decompose_vintage_invalid_model_string_raises(mock_extract, empty_timeseries):
    empty_timeseries.to_darts_timeseries = MagicMock(return_value="mock_darts_ts")
    empty_timeseries.metadata.get_frequency_as_numeric = MagicMock(return_value=12)

    with pytest.raises(
        ValueError,
        match="Invalid model string. Supported values are 'additive' and 'multiplicative'.",
    ):
        empty_timeseries.analysis.decompose_vintage(
            model="invalid_model",
        )

    mock_extract.assert_not_called()


def test_revision_cross_correlogram_shape_and_labels(
    empty_timeseries, sample_vintage_matrix
):
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=sample_vintage_matrix
    )

    result = empty_timeseries.analysis.revision_cross_correlogram()

    assert result["correlogram"].shape == (4, 3)
    assert result["observation_lags"] == [0, 1, 2, 3]
    assert result["vintage_lags"] == [0, 1, 2]
    assert result["pair_counts"].shape == (4, 3)


def test_revision_cross_correlogram_expected_values(empty_timeseries):
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=pd.DataFrame(
            {
                "2024-01-01": [0.0, 0.0, 0.0, 0.0],
                "2024-02-01": [1.0, 2.0, 3.0, 4.0],
                "2024-03-01": [3.0, 5.0, 7.0, 9.0],
                "2024-04-01": [6.0, 9.0, 12.0, 15.0],
            }
        )
    )

    result = empty_timeseries.analysis.revision_cross_correlogram()
    corr = result["correlogram"]
    counts = result["pair_counts"]

    assert corr[0, 0] == pytest.approx(1.0)
    assert corr[1, 0] == pytest.approx(1.0)
    assert corr[0, 1] == pytest.approx(1.0)
    assert corr[1, 1] == pytest.approx(1.0)
    assert counts[0, 0] == 12
    assert counts[1, 0] == 9
    assert counts[0, 1] == 8


def test_revision_cross_correlogram_with_empty_vintage_matrix(
    empty_timeseries,
):
    empty_timeseries.generate_vintage_matrix = MagicMock(return_value=pd.DataFrame())

    with pytest.raises(
        ValueError, match="Vintage matrix is empty, cannot compute correlogram"
    ):
        empty_timeseries.analysis.revision_cross_correlogram()


def test_revision_cross_correlogram_requires_two_release_dates(empty_timeseries):
    empty_timeseries.generate_vintage_matrix = MagicMock(
        return_value=pd.DataFrame({"2024-01-01": [1.0, 2.0, 3.0]})
    )

    with pytest.raises(
        ValueError,
        match="At least two release dates are required to compute revision series",
    ):
        empty_timeseries.analysis.revision_cross_correlogram()


def test_revision_cross_correlogram_negative_lags_raise(empty_timeseries):
    with pytest.raises(ValueError, match="max_vintage_lag must be >= 0"):
        empty_timeseries.analysis.revision_cross_correlogram(max_vintage_lag=-1)

    with pytest.raises(ValueError, match="max_observation_lag must be >= 0"):
        empty_timeseries.analysis.revision_cross_correlogram(max_observation_lag=-1)


def test_ljung_box_insufficient_obs(empty_timeseries):
    resid = [1.0, -1.0]  # n < 3
    result = empty_timeseries.analysis._ljung_box(resid, lags=5, alpha=0.05)

    assert result["stat"] is None
    assert result["pvalue"] is None
    assert result["lags"] == 1
    assert result["pass"] is False
    assert result["note"] == "Insufficient observations for Ljung-Box test"


@patch("macrotrace.models.mt.analysis.acorr_ljungbox")
def test_ljung_box_effective_lags_and_pass_flag(mock_lb, empty_timeseries):
    resid = [1.0, -1.0, 0.5, -0.5]

    # Not true values, just need to test that we are correctly interpreting the output and passing the effective lags
    mock_df = pd.DataFrame({"lb_stat": [2.0], "lb_pvalue": [0.2]})
    mock_lb.return_value = mock_df

    result = empty_timeseries.analysis._ljung_box(resid, lags=10, alpha=0.05)

    mock_lb.assert_called_once()
    _, kwargs = mock_lb.call_args

    # Lags requested is 10, but effective lags should be min(10, n-1) = 3
    # Make sure we are passing the effective lags to acorr_ljungbox
    assert kwargs["lags"] == [3]

    # Check that the result is correctly interpreted
    assert result["stat"] == 2.0
    assert result["pvalue"] == 0.2

    # With p-value of 0.2 and alpha of 0.05, the test should pass (fail to reject null of no autocorrelation)
    assert result["pass"] is True


@patch("macrotrace.models.mt.analysis.acorr_ljungbox")
def test_ljung_box_fails_when_pvalue_below_alpha(mock_lb, empty_timeseries):
    resid = [1.0, -1.0, 0.5, -0.5]

    # Not true values, just need to test that we are correctly interpreting the output and passing the effective lags
    mock_df = pd.DataFrame({"lb_stat": [5.0], "lb_pvalue": [0.01]})

    mock_lb.return_value = mock_df
    result = empty_timeseries.analysis._ljung_box(resid, lags=1, alpha=0.05)

    assert result["pass"] is False


def test_durbin_watson_with_less_than_two_residuals(empty_timeseries):
    """Tests that _durbin_watson returns None when there are less than 2 residuals."""

    result = empty_timeseries.analysis._durbin_watson([1.0])
    assert result is None

    result = empty_timeseries.analysis._durbin_watson([])
    assert result is None


def test_durbin_watson_none_when_infinite(empty_timeseries):
    """Tests that _durbin_watson returns None when the sum of squared residuals is zero (infinite statistic)."""

    result = empty_timeseries.analysis._durbin_watson([0.0, 0.0, 0.0])
    assert result is None


def test_durbin_watson_calculation(empty_timeseries):
    """Tests that _durbin_watson calculates the statistic correctly for a known set of residuals."""

    residuals = [1.0, -1.0, 1.0, -1.0]
    result = empty_timeseries.analysis._durbin_watson(residuals)
    assert result == 3.0


def test_normalize_index_valid_values(empty_timeseries):
    assert empty_timeseries.analysis._normalize_index(1) == 1
    assert empty_timeseries.analysis._normalize_index(5) == 5
    assert empty_timeseries.analysis._normalize_index(-1) == "latest"
    assert empty_timeseries.analysis._normalize_index("latest") == "latest"
    assert empty_timeseries.analysis._normalize_index("LaTeSt") == "latest"


def test_normalize_index_invalid_values(empty_timeseries):
    with pytest.raises(ValueError, match=">= 1"):
        empty_timeseries.analysis._normalize_index(0)
    with pytest.raises(ValueError, match=">= 1"):
        empty_timeseries.analysis._normalize_index(-2)
    with pytest.raises(ValueError, match="must be 'latest'"):
        empty_timeseries.analysis._normalize_index("first")
    with pytest.raises(ValueError, match="must be an int or 'latest'"):
        empty_timeseries.analysis._normalize_index(1.5)


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_prepare_indexed_vintage_regression_data_base_case(mock_vm, empty_timeseries):
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, 10.0],
            datetime.datetime(2024, 2, 1): [2.0, 11.0],
            datetime.datetime(2024, 3, 1): [3.0, 12.0],
        },
        index=[datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)],
    )

    merged, data_notes = (
        empty_timeseries.analysis._prepare_indexed_vintage_regression_data(
            independent_vintage_index=1,
            dependent_vintage_index="latest",
        )
    )

    assert merged[["x", "y"]].values.tolist() == [[1.0, 3.0], [10.0, 12.0]]
    assert data_notes["missing_x"] == 0
    assert data_notes["missing_y"] == 0
    assert data_notes["dropped_rows"] == 0
    assert data_notes["vintage_filters_applied"] is False


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_prepare_indexed_vintage_regression_data_drops_and_logs(
    mock_vm, empty_timeseries, caplog
):
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, 10.0, 100.0],
            datetime.datetime(2024, 2, 1): [pd.NA, 11.0, pd.NA],
            datetime.datetime(2024, 3, 1): [pd.NA, 12.0, pd.NA],
        },
        index=[
            datetime.datetime(2024, 1, 1),
            datetime.datetime(2024, 2, 1),
            datetime.datetime(2024, 3, 1),
        ],
    )

    caplog.set_level("DEBUG")
    merged, data_notes = (
        empty_timeseries.analysis._prepare_indexed_vintage_regression_data(
            independent_vintage_index=2,
            dependent_vintage_index="latest",
        )
    )

    # Only the second row has at least 2 non-NaN values; others drop
    assert merged[["x", "y"]].values.tolist() == [[11.0, 12.0]]
    assert data_notes["missing_x"] == 2
    assert data_notes["missing_y"] == 0
    assert data_notes["dropped_rows"] == 2
    assert "Dropped 2 rows due to missing indexed vintages" in caplog.text


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_prepare_indexed_vintage_regression_data_warns_on_filters(
    mock_vm, empty_timeseries, caplog
):
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, 10.0],
            datetime.datetime(2024, 2, 1): [2.0, 11.0],
        },
        index=[datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)],
    )

    empty_timeseries.vintage_start_date = datetime.datetime(2024, 1, 1)

    caplog.set_level("WARNING")
    _, data_notes = empty_timeseries.analysis._prepare_indexed_vintage_regression_data(
        independent_vintage_index=1,
        dependent_vintage_index="latest",
    )

    assert data_notes["vintage_filters_applied"] is True
    assert "Vintage date filters are currently applied" in caplog.text


@patch("macrotrace.models.mt.analysis.MTTimeSeriesAnalysis._durbin_watson")
@patch("macrotrace.models.mt.analysis.MTTimeSeriesAnalysis._ljung_box")
def test_prepare_biasedness_regression_output(
    mock_lj, mock_dw, empty_timeseries, mock_regression_result
):
    """Tests that _prepare_biasedness_regression_output correctly processes the regression result and test results into the expected output format, including handling of data notes and assumptions."""
    data_notes = {
        "missing_x": 1,
        "missing_y": 0,
        "dropped_rows": 1,
        "vintage_filters_applied": False,
    }

    mock_lj.return_value = {
        "stat": 1.0,
        "pvalue": 0.5,
        "lags": 1,
        "alpha": 0.05,
        "pass": True,
    }
    mock_dw.return_value = 2.0

    output = empty_timeseries.analysis._prepare_biasedness_regression_output(
        result=mock_regression_result(),
        alpha=0.05,
        independent_vintage_index=1,
        dependent_vintage_index="latest",
        data_notes=data_notes,
    )

    expected = {
        "n_total": 12,
        "vintage_indices": {"independent": 1, "dependent": "latest", "index_base": 1},
        "data_notes": data_notes,
        "model": {
            "alpha": 2.0,
            "beta": 1.05,
            "alpha_ci": {"low": 0.9, "high": 3.1},
            "beta_ci": {"low": 0.8, "high": 1.2},
            "rss": 4.0,
            "s2": 0.4,
            "r2": 0.9,
            "n": 12,
            "durbin_watson": 2.0,
        },
        "tests": {
            "alpha_eq_0": {"t": 4.0, "pvalue": 0.0025},
            "beta_eq_1": {"t": 0.1, "pvalue": 0.9223},
            "unbiasedness": {
                "f_stat": 5.0,
                "pvalue": 0.04,
                "df_num": 2,
                "df_den": 10,
                "alpha": 0.05,
                "reject": True,
            },
        },
        "assumptions": {
            "random_residuals": {
                "test": "ljung_box",
                "stat": 1.0,
                "pvalue": 0.5,
                "lags": 1,
                "alpha": 0.05,
                "pass": True,
            },
        },
    }

    actual = output.to_dict()

    for key, value in expected.items():
        actual_value = actual[key]
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                assert sub_key in actual_value
                actual_sub = actual_value[sub_key]
                if isinstance(sub_value, dict):
                    for k, v in sub_value.items():
                        assert k in actual_sub
                        if isinstance(v, float):
                            assert actual_sub[k] == pytest.approx(v, abs=1e-4)
                        else:
                            assert actual_sub[k] == v
                elif isinstance(sub_value, float):
                    assert actual_sub == pytest.approx(sub_value, abs=1e-4)
                else:
                    assert actual_sub == sub_value
        elif isinstance(value, float):
            assert actual_value == pytest.approx(value, abs=1e-4)
        else:
            assert actual_value == value


@patch("macrotrace.models.mt.analysis.MTTimeSeriesAnalysis._durbin_watson")
@patch("macrotrace.models.mt.analysis.MTTimeSeriesAnalysis._ljung_box")
def test_prepare_biasedness_regression_output_table(
    mock_lj, mock_dw, empty_timeseries, mock_regression_result
):
    """Test that the _prepare_biasedness_regression_output method's table correctly formats the coefficients, standard errors, confidence intervals, and significance stars based on the regression results and alpha level."""
    result = mock_regression_result(f_pvalue=0.01)

    mock_dw.return_value = 2.0
    mock_lj.return_value = {
        "stat": 1.0,
        "pvalue": 0.5,
        "lags": 1,
        "alpha": 0.05,
        "pass": True,
    }

    output = empty_timeseries.analysis._prepare_biasedness_regression_output(
        result=result,
        alpha=0.05,
        independent_vintage_index=1,
        dependent_vintage_index="latest",
        data_notes={},
    )

    table = output.table
    alpha_line = next(line for line in table.splitlines() if "alpha (const)" in line)
    beta_line = next(line for line in table.splitlines() if "beta (x)" in line)
    assert "*" in alpha_line
    assert "*" not in beta_line


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_select_vintage_df_base_case_1(mock_vm, empty_timeseries):
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, 10.0],
            datetime.datetime(2024, 2, 1): [2.0, 11.0],
            datetime.datetime(2024, 3, 1): [3.0, 12.0],
        },
        index=[datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)],
    )

    df = empty_timeseries.analysis._select_vintage_df(vintage_index=1)
    expected_df = pd.DataFrame(
        {
            "timestamp": [datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)],
            "value": [1.0, 10.0],
            "vintage_date": [
                datetime.datetime(2024, 1, 1),
                datetime.datetime(2024, 1, 1),
            ],
        }
    )

    pd.testing.assert_frame_equal(df, expected_df)


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_select_vintage_df_base_case_2(mock_vm, empty_timeseries):
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, 10.0],
            datetime.datetime(2024, 2, 1): [2.0, 11.0],
            datetime.datetime(2024, 3, 1): [3.0, 12.0],
        },
        index=[datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)],
    )

    df = empty_timeseries.analysis._select_vintage_df(vintage_index=2)
    expected_df = pd.DataFrame(
        {
            "timestamp": [datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)],
            "value": [2.0, 11.0],
            "vintage_date": [
                datetime.datetime(2024, 2, 1),
                datetime.datetime(2024, 2, 1),
            ],
        }
    )
    pd.testing.assert_frame_equal(df, expected_df)


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_select_vintage_df_latest_equals_minus_one(mock_vm, empty_timeseries):
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, 10.0],
            datetime.datetime(2024, 2, 1): [2.0, 11.0],
            datetime.datetime(2024, 3, 1): [3.0, 12.0],
        },
        index=[datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)],
    )

    df_latest = empty_timeseries.analysis._select_vintage_df(vintage_index="latest")
    df_minus_one = empty_timeseries.analysis._select_vintage_df(vintage_index=-1)

    pd.testing.assert_frame_equal(df_latest, df_minus_one)


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_select_vintage_df_missing_and_dropna(mock_vm, empty_timeseries):
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, pd.NA, 100.0],
            datetime.datetime(2024, 2, 1): [2.0, pd.NA, pd.NA],
        },
        index=[
            datetime.datetime(2024, 1, 1),
            datetime.datetime(2024, 2, 1),
            datetime.datetime(2024, 3, 1),
        ],
    )

    df_keep = empty_timeseries.analysis._select_vintage_df(
        vintage_index=2, dropna=False
    )
    df_drop = empty_timeseries.analysis._select_vintage_df(vintage_index=2, dropna=True)

    expected_df_keep = pd.DataFrame(
        {
            "timestamp": [
                datetime.datetime(2024, 1, 1),
                datetime.datetime(2024, 2, 1),
                datetime.datetime(2024, 3, 1),
            ],
            "value": [2.0, pd.NA, pd.NA],
            "vintage_date": [
                datetime.datetime(2024, 2, 1),
                pd.NaT,
                pd.NaT,
            ],
        }
    )

    expected_df_drop = pd.DataFrame(
        {
            "timestamp": [datetime.datetime(2024, 1, 1)],
            "value": [2.0],
            "vintage_date": [datetime.datetime(2024, 2, 1)],
        }
    )

    pd.testing.assert_frame_equal(df_keep, expected_df_keep, check_dtype=False)
    pd.testing.assert_frame_equal(df_drop, expected_df_drop, check_dtype=False)


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_select_vintage_df_no_vintage_date_column(mock_vm, empty_timeseries):
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, 10.0],
            datetime.datetime(2024, 2, 1): [2.0, 11.0],
        },
        index=[datetime.datetime(2024, 1, 1), datetime.datetime(2024, 2, 1)],
    )

    df = empty_timeseries.analysis._select_vintage_df(
        vintage_index=1, include_vintage_date=False
    )

    assert "vintage_date" not in df.columns


def test_warn_if_vintage_filters_false_when_none(empty_timeseries, caplog):
    empty_timeseries.vintage_start_date = None
    empty_timeseries.vintage_end_date = None

    caplog.set_level("WARNING")
    result = empty_timeseries.analysis._warn_if_vintage_filters()

    assert result is False
    assert "Vintage date filters are currently applied" not in caplog.text


def test_warn_if_vintage_start_date_filter_true_and_logs(empty_timeseries, caplog):
    empty_timeseries.vintage_start_date = datetime.datetime(2024, 1, 1)
    empty_timeseries.vintage_end_date = None

    caplog.set_level("WARNING")
    result = empty_timeseries.analysis._warn_if_vintage_filters()

    assert result is True
    assert "Vintage date filters are currently applied" in caplog.text


def test_warn_if_vintage_end_date_filter_true_and_logs(empty_timeseries, caplog):
    empty_timeseries.vintage_start_date = None
    empty_timeseries.vintage_end_date = datetime.datetime(2024, 1, 1)

    caplog.set_level("WARNING")
    result = empty_timeseries.analysis._warn_if_vintage_filters()

    assert result is True
    assert "Vintage date filters are currently applied" in caplog.text


def test_warn_if_vintage_both_date_filter_true_and_logs(empty_timeseries, caplog):
    empty_timeseries.vintage_start_date = datetime.datetime(2024, 1, 1)
    empty_timeseries.vintage_end_date = datetime.datetime(2025, 1, 1)

    caplog.set_level("WARNING")
    result = empty_timeseries.analysis._warn_if_vintage_filters()

    assert result is True
    assert "Vintage date filters are currently applied" in caplog.text


@patch("macrotrace.models.mt.analysis.granger_causality_tests")
def test_granger_causality_test_invokes_helper_with_darts_series(
    mock_granger, empty_timeseries
):
    """granger_causality_test forwards Darts conversions and resolved max_lags."""
    mock_granger.return_value = {1: {"ssr_ftest": (1.0, 0.5)}}

    cause = empty_timeseries
    effect = MagicMock()
    effect.to_darts_timeseries.return_value = "effect-darts"

    cause.to_darts_timeseries = MagicMock(return_value="cause-darts")
    cause.metadata = MagicMock()
    cause.metadata.get_frequency_as_numeric.return_value = 4

    res = cause.analysis.granger_causality_test(ts_effect=effect)

    mock_granger.assert_called_once_with(
        ts_cause="cause-darts",
        ts_effect="effect-darts",
        maxlag=4,
        addconst=True,
    )
    assert res == {1: {"ssr_ftest": (1.0, 0.5)}}


@patch("macrotrace.models.mt.analysis.granger_causality_tests")
def test_granger_causality_test_uses_explicit_max_lags(mock_granger, empty_timeseries):
    """An explicit max_lags overrides the metadata-derived default."""
    mock_granger.return_value = {}

    effect = MagicMock()
    effect.to_darts_timeseries.return_value = "e"
    empty_timeseries.to_darts_timeseries = MagicMock(return_value="c")
    empty_timeseries.metadata = MagicMock()
    empty_timeseries.metadata.get_frequency_as_numeric.return_value = 12

    empty_timeseries.analysis.granger_causality_test(ts_effect=effect, max_lags=2)

    assert mock_granger.call_args.kwargs["maxlag"] == 2


def test_revision_biasedness_regression_requires_both_indices(empty_timeseries):
    """revision_biasedness_regression raises when either index is None."""
    with pytest.raises(ValueError, match="Both independent_vintage_index"):
        empty_timeseries.analysis.revision_biasedness_regression(
            independent_vintage_index=None,
            dependent_vintage_index=2,
        )

    with pytest.raises(ValueError, match="Both independent_vintage_index"):
        empty_timeseries.analysis.revision_biasedness_regression(
            independent_vintage_index=1,
            dependent_vintage_index=None,
        )


@patch("macrotrace.models.mt.time_series.MTTimeSeries.generate_vintage_matrix")
def test_revision_biasedness_regression_runs_ols_and_formats_output(
    mock_vm, empty_timeseries
):
    """End-to-end: prepares data, fits OLS, and returns BiasednessRegressionResult."""
    mock_vm.return_value = pd.DataFrame(
        {
            datetime.datetime(2024, 1, 1): [1.0, 2.0, 3.0, 4.0, 5.0],
            datetime.datetime(2024, 2, 1): [1.1, 2.2, 3.05, 4.1, 5.05],
        },
        index=[
            datetime.datetime(2024, 1, 1),
            datetime.datetime(2024, 2, 1),
            datetime.datetime(2024, 3, 1),
            datetime.datetime(2024, 4, 1),
            datetime.datetime(2024, 5, 1),
        ],
    )

    result = empty_timeseries.analysis.revision_biasedness_regression(
        independent_vintage_index=1,
        dependent_vintage_index="latest",
    )

    assert result.n_total == 5
    assert "alpha" in result.model
    assert "beta" in result.model
    assert result.vintage_indices["independent"] == 1
    assert result.vintage_indices["dependent"] == "latest"
