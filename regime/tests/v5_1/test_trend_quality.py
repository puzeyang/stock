"""Market Regime v5.1 — TrendQuality (module 4.4) test suite.

Gap-fill delivery per Message[175]: TrendQuality was referenced but never
actually implemented in the original Slice 3 delivery. Built and tested
here, before Slice 7 (Condition) needs it.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_trend_quality.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.raw_features import load_raw_series, RawSeries, RawObservation  # noqa: E402
from v5_1.trend_quality import (  # noqa: E402
    compute_regression_r_squared,
    compute_path_efficiency_raw,
    compute_trend_quality,
    TrendQualityWeights,
    TrendQualityUnavailableError,
    TrendQualityResult,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def spy_series(manifest):
    return load_raw_series("benchmark_total_return_close", manifest)


def _default_weights():
    return TrendQualityWeights(weight_linearity=0.5, weight_path_efficiency=0.5)


def _make_series(dates_values: list[tuple[str, float]]) -> RawSeries:
    obs = tuple(RawObservation(date=d, value=v, source_contract_id="TEST", field_name="close") for d, v in dates_values)
    return RawSeries(field_id="test", source_contract_id="TEST", field_name="close", observations=obs)


# ---------------------------------------------------------------------------
# TrendQualityWeights validation
# ---------------------------------------------------------------------------

class TestWeights:
    def test_valid_weights_construct(self):
        TrendQualityWeights(weight_linearity=0.6, weight_path_efficiency=0.4)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="sum to exactly 1.0"):
            TrendQualityWeights(weight_linearity=0.5, weight_path_efficiency=0.4)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="nonnegative"):
            TrendQualityWeights(weight_linearity=-0.1, weight_path_efficiency=1.1)


# ---------------------------------------------------------------------------
# Regression R² — known-value cases
# ---------------------------------------------------------------------------

class TestRegressionRSquared:
    def test_perfectly_linear_gives_r_squared_near_one(self):
        r2 = compute_regression_r_squared([1.0, 2.0, 3.0, 4.0, 5.0])
        assert r2 == pytest.approx(1.0, abs=1e-9)

    def test_perfectly_linear_negative_slope_also_gives_one(self):
        """R² doesn't care about slope direction, only linearity."""
        r2 = compute_regression_r_squared([5.0, 4.0, 3.0, 2.0, 1.0])
        assert r2 == pytest.approx(1.0, abs=1e-9)

    def test_flat_window_gives_zero_not_an_error(self):
        """EMPIRICAL zero-movement disposition: 0.0, not a ZeroDivisionError."""
        r2 = compute_regression_r_squared([5.0, 5.0, 5.0, 5.0])
        assert r2 == 0.0

    def test_noisy_data_gives_r_squared_strictly_between_zero_and_one(self):
        r2 = compute_regression_r_squared([1.0, 3.0, 2.0, 5.0, 4.0, 7.0])
        assert 0.0 < r2 < 1.0

    def test_requires_at_least_two_points(self):
        with pytest.raises(ValueError, match="at least 2"):
            compute_regression_r_squared([1.0])

    def test_two_points_always_gives_r_squared_of_one(self):
        """A line through exactly 2 points is always a perfect fit."""
        r2 = compute_regression_r_squared([3.0, 7.0])
        assert r2 == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Path efficiency — known-value cases
# ---------------------------------------------------------------------------

class TestPathEfficiency:
    def test_perfectly_monotone_gives_efficiency_of_one(self):
        pe = compute_path_efficiency_raw([1.0, 2.0, 3.0, 4.0, 5.0])
        assert pe == pytest.approx(1.0)

    def test_perfectly_monotone_descending_also_gives_one(self):
        pe = compute_path_efficiency_raw([5.0, 4.0, 3.0, 2.0, 1.0])
        assert pe == pytest.approx(1.0)

    def test_round_trip_to_start_gives_zero(self):
        """Net movement is zero (ends where it started), so efficiency
        must be exactly 0.0, not undefined."""
        pe = compute_path_efficiency_raw([1.0, 5.0, 1.0, 5.0, 1.0])
        assert pe == 0.0

    def test_flat_window_gives_zero_not_an_error(self):
        pe = compute_path_efficiency_raw([3.0, 3.0, 3.0])
        assert pe == 0.0

    def test_partial_efficiency_between_zero_and_one(self):
        """Net movement 4 (1->5), cumulative movement 1+1+1+1+4=... let's
        compute directly: [1,2,1,2,5] -> net=|5-1|=4, cumulative=1+1+1+3=6,
        efficiency = 4/6."""
        pe = compute_path_efficiency_raw([1.0, 2.0, 1.0, 2.0, 5.0])
        assert pe == pytest.approx(4.0 / 6.0)

    def test_requires_at_least_two_points(self):
        with pytest.raises(ValueError, match="at least 2"):
            compute_path_efficiency_raw([1.0])


# ---------------------------------------------------------------------------
# Full computation — real data
# ---------------------------------------------------------------------------

class TestFullComputationRealData:
    def test_end_to_end_real_data(self, spy_series):
        r = compute_trend_quality("2020-04-15", spy_series, regression_window=21, path_efficiency_window=21, weights=_default_weights())
        assert isinstance(r, TrendQualityResult)
        assert 0.0 <= r.linearity_pct <= 1.0
        assert 0.0 <= r.path_efficiency_pct <= 1.0
        expected = 0.5 * r.linearity_pct + 0.5 * r.path_efficiency_pct
        assert r.trend_quality == pytest.approx(expected)

    def test_strong_clean_uptrend_shows_high_trend_quality(self, spy_series):
        """Real-world sanity check: the 2020-04 through 2020-06 recovery was
        a well-documented unusually clean, low-volatility uptrend — a
        canonical real-world 'high TrendQuality' period. This just checks
        the components are internally consistent and produce a real,
        non-degenerate result; not asserting a specific numeric threshold
        since the exact percentile depends on the EMPIRICAL window choice."""
        r = compute_trend_quality("2020-05-15", spy_series, regression_window=21, path_efficiency_window=21, weights=_default_weights())
        assert r.linearity_raw > 0.0  # some real linear structure present
        assert r.path_efficiency_raw > 0.0

    def test_unavailable_insufficient_regression_domain_history(self, spy_series):
        with pytest.raises(TrendQualityUnavailableError, match="regression-domain"):
            compute_trend_quality("1993-02-01", spy_series, regression_window=21, path_efficiency_window=21, weights=_default_weights())

    def test_unavailable_insufficient_midrank_window_history(self, spy_series):
        """Even with enough history for the regression/path domains
        themselves, the 504-session ROLLING midrank window needs
        substantially more total history — an intermediate date should
        show this distinct unavailability mode."""
        with pytest.raises(TrendQualityUnavailableError, match="linearity_pct 504-session midrank"):
            compute_trend_quality("1993-06-01", spy_series, regression_window=21, path_efficiency_window=21, weights=_default_weights())


class TestInputValidation:
    def test_non_positive_regression_window_rejected(self, spy_series):
        with pytest.raises(ValueError, match="must be positive"):
            compute_trend_quality("2020-04-15", spy_series, regression_window=0, path_efficiency_window=21, weights=_default_weights())

    def test_non_positive_path_efficiency_window_rejected(self, spy_series):
        with pytest.raises(ValueError, match="must be positive"):
            compute_trend_quality("2020-04-15", spy_series, regression_window=21, path_efficiency_window=-5, weights=_default_weights())


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_computation_is_repeatable(self, spy_series):
        r1 = compute_trend_quality("2020-04-15", spy_series, regression_window=21, path_efficiency_window=21, weights=_default_weights())
        r2 = compute_trend_quality("2020-04-15", spy_series, regression_window=21, path_efficiency_window=21, weights=_default_weights())
        assert r1 == r2
