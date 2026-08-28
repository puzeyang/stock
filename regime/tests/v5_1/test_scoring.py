"""Market Regime v5.1 — Forward-Looking Scoring Tool test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Scope note: `scoring.py` exists ONLY as an evaluation tool for the
ongoing EMPIRICAL-parameter investigation (window lengths, blend
weights) — per the human's explicit direction (AskUserQuestion,
following discussion Message[200]). It is NOT production code, NOT a
trading signal, and NOT an extension of `replay.py`'s scope (see
`scoring.py`'s module docstring). These tests verify the tool's own
mechanics (forward-return lookup, grouping/aggregation) are correct —
they do not assert any particular EMPIRICAL config is "better."

Run with: python3 -m pytest regime/tests/v5_1/test_scoring.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.engine import load_raw_series_bundle, TEST_SCAFFOLDING_CONFIG  # noqa: E402
from v5_1.raw_features import RawObservation, RawSeries  # noqa: E402
from v5_1.scoring import (  # noqa: E402
    forward_return,
    vol_normalized_forward_return,
    wilson_score_interval,
    hit_rates_distinguishable,
    run_scored_replay,
    summarize_by_state,
    ScoredDate,
    ScoredReplayResult,
    StateForwardStats,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def raw_bundle(manifest):
    return load_raw_series_bundle(manifest)


def _series(dates_values, field_id="test", contract_id="TEST"):
    obs = tuple(RawObservation(date=d, value=v, source_contract_id=contract_id, field_name="close") for d, v in dates_values)
    return RawSeries(field_id=field_id, source_contract_id=contract_id, field_name="close", observations=obs)


# ---------------------------------------------------------------------------
# forward_return
# ---------------------------------------------------------------------------

class TestForwardReturn:
    def test_computes_real_trading_day_horizon_return(self):
        # 5 sessions after 2024-01-01 (2024-01-02..01-08), horizon=5 lands
        # exactly on 2024-01-08 (110.0): 110/100 - 1 = 0.10
        series = _series([
            ("2024-01-01", 100.0), ("2024-01-02", 101.0), ("2024-01-03", 102.0),
            ("2024-01-04", 103.0), ("2024-01-05", 104.0), ("2024-01-08", 110.0),
            ("2024-01-09", 111.0),
        ])
        result = forward_return(series, "2024-01-01", horizon_sessions=5)
        assert result == pytest.approx(0.10)

    def test_uses_point_in_time_as_of_anchor_not_exact_date(self):
        # as_of falls on a non-observation date (e.g. a holiday) — anchor
        # should be the most recent PRIOR observation, same as every other
        # module's as_of() convention.
        series = _series([
            ("2024-01-01", 100.0), ("2024-01-03", 102.0), ("2024-01-04", 103.0),
            ("2024-01-05", 104.0), ("2024-01-08", 110.0),
        ])
        # as_of="2024-01-02" (no observation that day) anchors to 2024-01-01
        # (100.0); horizon=3 lands on 2024-01-05 (104.0): 104/100 - 1 = 0.04
        result = forward_return(series, "2024-01-02", horizon_sessions=3)
        assert result == pytest.approx(0.04)

    def test_returns_none_when_anchor_unavailable(self):
        series = _series([("2024-01-05", 100.0), ("2024-01-08", 110.0)])
        assert forward_return(series, "2024-01-01", horizon_sessions=1) is None

    def test_returns_none_when_horizon_exceeds_available_future_observations(self):
        series = _series([("2024-01-01", 100.0), ("2024-01-02", 101.0), ("2024-01-03", 102.0)])
        # Only 2 observations exist after 2024-01-01; horizon=5 is unmet.
        assert forward_return(series, "2024-01-01", horizon_sessions=5) is None

    def test_fails_closed_rather_than_truncating_partial_horizon(self):
        series = _series([("2024-01-01", 100.0), ("2024-01-02", 105.0)])
        # Exactly 1 future observation exists; horizon=2 must fail closed,
        # never silently fall back to the 1-session return instead.
        assert forward_return(series, "2024-01-01", horizon_sessions=2) is None

    def test_negative_return_computed_correctly(self):
        series = _series([("2024-01-01", 100.0), ("2024-01-02", 90.0)])
        result = forward_return(series, "2024-01-01", horizon_sessions=1)
        assert result == pytest.approx(-0.10)


# ---------------------------------------------------------------------------
# run_scored_replay + summarize_by_state — synthetic mechanics
# ---------------------------------------------------------------------------

def _sd(as_of, state, condition_score, forward_return, vol_normalized_forward_return=None):
    """Helper: builds a ScoredDate, defaulting the new (Message[203])
    vol_normalized_forward_return field to None for tests that only care
    about the original forward_return-based mechanics."""
    return ScoredDate(
        as_of=as_of, state=state, condition_score=condition_score,
        forward_return=forward_return, vol_normalized_forward_return=vol_normalized_forward_return,
    )


class TestSummarizeByState:
    def test_groups_and_averages_correctly(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", "RISK_OFF", 0.2, -0.05),
                _sd("2024-01-02", "RISK_OFF", 0.25, -0.03),
                _sd("2024-01-03", "RISK_ON", 0.8, 0.08),
                _sd("2024-01-04", "RISK_ON", 0.85, 0.04),
            ),
        )
        stats = summarize_by_state(result)
        by_label = {s.state: s for s in stats}
        assert by_label["RISK_OFF"].count == 2
        assert by_label["RISK_OFF"].mean_forward_return == pytest.approx(-0.04)
        assert by_label["RISK_ON"].count == 2
        assert by_label["RISK_ON"].mean_forward_return == pytest.approx(0.06)

    def test_excludes_none_state_dates(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", None, None, 0.05),
                _sd("2024-01-02", "NEUTRAL", 0.5, 0.01),
            ),
        )
        stats = summarize_by_state(result)
        assert len(stats) == 1
        assert stats[0].state == "NEUTRAL"

    def test_excludes_none_forward_return_dates(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", "NEUTRAL", 0.5, None),
                _sd("2024-01-02", "NEUTRAL", 0.5, 0.02),
            ),
        )
        stats = summarize_by_state(result)
        assert len(stats) == 1
        assert stats[0].count == 1
        assert stats[0].mean_forward_return == pytest.approx(0.02)

    def test_state_with_zero_qualifying_dates_is_absent_not_zero(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", None, None, None),
            ),
        )
        stats = summarize_by_state(result)
        assert stats == ()

    def test_median_for_even_count_averages_middle_two(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", "NEUTRAL", 0.5, 0.01),
                _sd("2024-01-02", "NEUTRAL", 0.5, 0.03),
                _sd("2024-01-03", "NEUTRAL", 0.5, 0.05),
                _sd("2024-01-04", "NEUTRAL", 0.5, 0.07),
            ),
        )
        stats = summarize_by_state(result)
        assert stats[0].median_forward_return == pytest.approx(0.04)

    def test_results_sorted_by_state_label_deterministically(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", "RISK_ON", 0.8, 0.01),
                _sd("2024-01-02", "CRISIS", 0.1, -0.1),
                _sd("2024-01-03", "NEUTRAL", 0.5, 0.0),
            ),
        )
        stats = summarize_by_state(result)
        assert [s.state for s in stats] == ["CRISIS", "NEUTRAL", "RISK_ON"]

    def test_hit_rate_counts_strictly_positive_returns(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", "RISK_ON", 0.8, 0.05),
                _sd("2024-01-02", "RISK_ON", 0.8, -0.02),
                _sd("2024-01-03", "RISK_ON", 0.8, 0.03),
                _sd("2024-01-04", "RISK_ON", 0.8, 0.0),  # exactly zero — not a hit
            ),
        )
        stats = summarize_by_state(result)
        # 2 of 4 strictly positive (0.0 does not count as a hit)
        assert stats[0].hit_rate == pytest.approx(0.5)

    def test_hit_rate_can_diverge_from_mean_return_sign(self):
        # Reproduces the Message[202] shape at small scale: mostly-positive
        # hit rate but a mean pulled negative by one large outlier.
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", "RISK_ON", 0.8, 0.01),
                _sd("2024-01-02", "RISK_ON", 0.8, 0.01),
                _sd("2024-01-03", "RISK_ON", 0.8, 0.01),
                _sd("2024-01-04", "RISK_ON", 0.8, -0.30),
            ),
        )
        stats = summarize_by_state(result)
        assert stats[0].hit_rate == pytest.approx(0.75)
        assert stats[0].mean_forward_return < 0

    def test_vol_normalized_mean_excludes_none_independently_of_forward_return(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", "NEUTRAL", 0.5, 0.02, vol_normalized_forward_return=1.5),
                _sd("2024-01-02", "NEUTRAL", 0.5, 0.03, vol_normalized_forward_return=None),
                _sd("2024-01-03", "NEUTRAL", 0.5, 0.01, vol_normalized_forward_return=0.5),
            ),
        )
        stats = summarize_by_state(result)
        # count=3 (all have forward_return), but vol_normalized_count=2
        # (one date's vol-normalized value is None) — reported separately,
        # not silently assumed equal to count.
        assert stats[0].count == 3
        assert stats[0].vol_normalized_count == 2
        assert stats[0].mean_vol_normalized_forward_return == pytest.approx(1.0)

    def test_mean_vol_normalized_is_none_when_no_date_has_a_computable_value(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                _sd("2024-01-01", "NEUTRAL", 0.5, 0.02, vol_normalized_forward_return=None),
            ),
        )
        stats = summarize_by_state(result)
        assert stats[0].mean_vol_normalized_forward_return is None
        assert stats[0].vol_normalized_count == 0


# ---------------------------------------------------------------------------
# vol_normalized_forward_return
# ---------------------------------------------------------------------------

class TestVolNormalizedForwardReturn:
    def test_returns_none_when_raw_forward_return_is_none(self, raw_bundle):
        result = vol_normalized_forward_return(raw_bundle.benchmark, "2018-12-24", 20, None)
        assert result is None

    def test_returns_none_when_insufficient_trailing_history(self):
        # Only 3 observations — _realized_vol_estimator needs 21 (20
        # return periods) ending at as_of, so this must fail closed.
        series = _series([("2024-01-01", 100.0), ("2024-01-02", 101.0), ("2024-01-03", 102.0)])
        result = vol_normalized_forward_return(series, "2024-01-03", 20, 0.05)
        assert result is None

    def test_scales_raw_return_by_horizon_vol_against_real_data(self, raw_bundle):
        raw_fwd = forward_return(raw_bundle.benchmark, "2018-12-24", 20)
        assert raw_fwd is not None
        result = vol_normalized_forward_return(raw_bundle.benchmark, "2018-12-24", 20, raw_fwd)
        assert result is not None
        # 2018-12-24 (Christmas Eve Massacre) was a genuinely high-vol
        # period — the vol-normalized value should be meaningfully
        # smaller in magnitude than the raw percent return, since dividing
        # by an elevated trailing vol shrinks the ratio.
        assert abs(result) < abs(raw_fwd) * 100  # sanity: not wildly inflated



# ---------------------------------------------------------------------------
# run_scored_replay — real engine + real pinned data integration
# ---------------------------------------------------------------------------

class TestRunScoredReplayIntegration:
    def test_runs_end_to_end_against_real_pinned_data(self, raw_bundle, manifest):
        # A short, real date range from the 2018 Christmas Eve Massacre
        # window, far enough from the pinned dataset's end that a 20-session
        # forward return is always computable.
        dates = ("2018-12-20", "2018-12-21", "2018-12-24", "2018-12-26", "2018-12-27")
        result = run_scored_replay(dates, raw_bundle, manifest, config=TEST_SCAFFOLDING_CONFIG, horizon_sessions=20)
        assert result.horizon_sessions == 20
        assert len(result.scored_dates) == 5
        for sd in result.scored_dates:
            assert sd.as_of in dates
            # This far from the data's end, a 20-session forward return
            # must be computable (fails the test loudly if pinned data
            # coverage ever regresses to not reach this far).
            assert sd.forward_return is not None
            # Same for the vol-normalized value — plenty of trailing
            # history exists this far into the pinned dataset.
            assert sd.vol_normalized_forward_return is not None

    def test_forward_return_matches_direct_computation(self, raw_bundle, manifest):
        dates = ("2018-12-24",)
        result = run_scored_replay(dates, raw_bundle, manifest, config=TEST_SCAFFOLDING_CONFIG, horizon_sessions=20)
        direct = forward_return(raw_bundle.benchmark, "2018-12-24", horizon_sessions=20)
        assert result.scored_dates[0].forward_return == direct

    def test_near_dataset_end_returns_none_forward_return_fail_closed(self, raw_bundle, manifest):
        # The most recent date any series in the bundle has — a 20-session
        # forward return cannot exist beyond the end of pinned data.
        last_date = raw_bundle.benchmark.observations[-1].date
        result = run_scored_replay((last_date,), raw_bundle, manifest, config=TEST_SCAFFOLDING_CONFIG, horizon_sessions=20)
        assert result.scored_dates[0].forward_return is None


# ---------------------------------------------------------------------------
# wilson_score_interval + hit_rates_distinguishable (Message[206])
# ---------------------------------------------------------------------------

class TestWilsonScoreInterval:
    def test_returns_zero_zero_for_n_zero(self):
        assert wilson_score_interval(0, 0) == (0.0, 0.0)

    def test_interval_contains_the_point_estimate(self):
        low, high = wilson_score_interval(hits=30, n=45)  # 66.7%
        assert low <= 30 / 45 <= high

    def test_interval_never_exceeds_zero_one_bounds(self):
        # Extreme case: all hits, small n — the naive normal approximation
        # can push above 1.0 here; Wilson must not.
        low, high = wilson_score_interval(hits=5, n=5)
        assert 0.0 <= low <= high <= 1.0
        # Extreme case: all misses.
        low, high = wilson_score_interval(hits=0, n=5)
        assert 0.0 <= low <= high <= 1.0

    def test_interval_narrows_as_n_grows_at_the_same_proportion(self):
        low_small, high_small = wilson_score_interval(hits=70, n=100)   # 70%
        low_large, high_large = wilson_score_interval(hits=700, n=1000)  # 70%
        assert (high_small - low_small) > (high_large - low_large)

    def test_matches_known_reference_value(self):
        # Textbook example: n=100, hits=50 (p=0.5) -> Wilson 95% CI is
        # approximately (0.404, 0.596) (standard reference value, e.g.
        # Newcombe 1998 Table I / any Wilson-interval calculator).
        low, high = wilson_score_interval(hits=50, n=100)
        assert low == pytest.approx(0.404, abs=0.001)
        assert high == pytest.approx(0.596, abs=0.001)


class TestHitRatesDistinguishable:
    def _stats(self, hits, n):
        low, high = wilson_score_interval(hits, n)
        return StateForwardStats(
            state="X", count=n, mean_forward_return=0.0, median_forward_return=0.0,
            min_forward_return=0.0, max_forward_return=0.0, hit_rate=hits / n if n else 0.0,
            hit_rate_ci_low=low, hit_rate_ci_high=high,
            mean_vol_normalized_forward_return=None, vol_normalized_count=0,
        )

    def test_small_sample_gap_is_not_distinguishable(self):
        # Reproduces the Message[201]/[204] scale directly: RISK_OFF
        # 66.7% (n=81) vs RISK_ON 73.3% (n=45) — a real gap reported
        # throughout Messages[201]-[205] as a bare point estimate, never
        # checked against noise until now.
        a = self._stats(hits=54, n=81)   # 66.7%
        b = self._stats(hits=33, n=45)   # 73.3%
        assert hit_rates_distinguishable(a, b) is False

    def test_large_clearly_separated_gap_is_distinguishable(self):
        a = self._stats(hits=200, n=1000)  # 20%
        b = self._stats(hits=800, n=1000)  # 80%
        assert hit_rates_distinguishable(a, b) is True

    def test_identical_rates_are_never_distinguishable(self):
        a = self._stats(hits=50, n=100)
        b = self._stats(hits=50, n=100)
        assert hit_rates_distinguishable(a, b) is False


class TestSummarizeByStateConfidenceIntervals:
    def test_ci_bounds_are_populated_and_contain_hit_rate(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=tuple(
                _sd(f"2024-01-{i:02d}", "RISK_ON", 0.8, 0.01 if i % 3 else -0.01)
                for i in range(1, 11)
            ),
        )
        stats = summarize_by_state(result)
        s = stats[0]
        assert s.hit_rate_ci_low <= s.hit_rate <= s.hit_rate_ci_high
        assert 0.0 <= s.hit_rate_ci_low <= s.hit_rate_ci_high <= 1.0
