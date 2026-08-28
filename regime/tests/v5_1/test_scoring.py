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

class TestSummarizeByState:
    def test_groups_and_averages_correctly(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                ScoredDate(as_of="2024-01-01", state="RISK_OFF", condition_score=0.2, forward_return=-0.05),
                ScoredDate(as_of="2024-01-02", state="RISK_OFF", condition_score=0.25, forward_return=-0.03),
                ScoredDate(as_of="2024-01-03", state="RISK_ON", condition_score=0.8, forward_return=0.08),
                ScoredDate(as_of="2024-01-04", state="RISK_ON", condition_score=0.85, forward_return=0.04),
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
                ScoredDate(as_of="2024-01-01", state=None, condition_score=None, forward_return=0.05),
                ScoredDate(as_of="2024-01-02", state="NEUTRAL", condition_score=0.5, forward_return=0.01),
            ),
        )
        stats = summarize_by_state(result)
        assert len(stats) == 1
        assert stats[0].state == "NEUTRAL"

    def test_excludes_none_forward_return_dates(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                ScoredDate(as_of="2024-01-01", state="NEUTRAL", condition_score=0.5, forward_return=None),
                ScoredDate(as_of="2024-01-02", state="NEUTRAL", condition_score=0.5, forward_return=0.02),
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
                ScoredDate(as_of="2024-01-01", state=None, condition_score=None, forward_return=None),
            ),
        )
        stats = summarize_by_state(result)
        assert stats == ()

    def test_median_for_even_count_averages_middle_two(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                ScoredDate(as_of="2024-01-01", state="NEUTRAL", condition_score=0.5, forward_return=0.01),
                ScoredDate(as_of="2024-01-02", state="NEUTRAL", condition_score=0.5, forward_return=0.03),
                ScoredDate(as_of="2024-01-03", state="NEUTRAL", condition_score=0.5, forward_return=0.05),
                ScoredDate(as_of="2024-01-04", state="NEUTRAL", condition_score=0.5, forward_return=0.07),
            ),
        )
        stats = summarize_by_state(result)
        assert stats[0].median_forward_return == pytest.approx(0.04)

    def test_results_sorted_by_state_label_deterministically(self):
        result = ScoredReplayResult(
            horizon_sessions=20,
            scored_dates=(
                ScoredDate(as_of="2024-01-01", state="RISK_ON", condition_score=0.8, forward_return=0.01),
                ScoredDate(as_of="2024-01-02", state="CRISIS", condition_score=0.1, forward_return=-0.1),
                ScoredDate(as_of="2024-01-03", state="NEUTRAL", condition_score=0.5, forward_return=0.0),
            ),
        )
        stats = summarize_by_state(result)
        assert [s.state for s in stats] == ["CRISIS", "NEUTRAL", "RISK_ON"]


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
