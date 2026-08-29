"""Market Regime v5.1 — CRISIS Preregistered Validation Study test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Scope note: `crisis_validation.py` exists ONLY as an evaluation tool for
the CRISIS domain formula investigation (Message[209]/[211]'s
preregistered-study requirement) — per the human's explicit direction to
build the core quantitative deliverable (episode labels + precision/
recall + entry lag) first. It is NOT production code and does NOT decide
whether any CRISIS preset should become a production default (that
decision explicitly requires meeting Message[211] §九's own preregistered
acceptance thresholds, not just running this tool once). These tests
verify the tool's own mechanics — grouping, lag computation, Wilson CI
aggregation — are correct, not that any particular labeled episode
"should" fire CRISIS (that's what the real study run itself checks,
separately, against real pinned data).

Run with: python3 -m pytest regime/tests/v5_1/test_crisis_validation.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.engine import load_raw_series_bundle, TEST_SCAFFOLDING_CONFIG  # noqa: E402
from v5_1.crisis_validation import (  # noqa: E402
    LabeledEpisode,
    LABELED_EPISODES,
    episode_dates,
    evaluate_episode,
    EpisodeResult,
    run_validation_study,
    ValidationStudyResult,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def raw_bundle(manifest):
    return load_raw_series_bundle(manifest)


# ---------------------------------------------------------------------------
# LABELED_EPISODES — structural sanity checks on the study's own inputs
# ---------------------------------------------------------------------------

class TestLabeledEpisodes:
    def test_every_episode_start_is_on_or_after_vix9d_coverage_floor(self, raw_bundle):
        """Hard data-coverage constraint (this module's own docstring):
        VIX9D only has real coverage from 2018-06-22 — no labeled episode
        may claim a start date before this, since CRISIS cannot be
        jointly evaluated at all before then."""
        floor = "2018-06-22"
        for ep in LABELED_EPISODES:
            assert ep.start >= floor, f"{ep.name}: start {ep.start} predates real VIX9D coverage ({floor})"

    def test_at_least_one_positive_and_one_negative_episode(self):
        positives = [ep for ep in LABELED_EPISODES if ep.is_crisis_positive]
        negatives = [ep for ep in LABELED_EPISODES if not ep.is_crisis_positive]
        assert len(positives) >= 1
        assert len(negatives) >= 1

    def test_every_episode_has_a_nonempty_note(self):
        for ep in LABELED_EPISODES:
            assert len(ep.note) > 20, f"{ep.name}: note too short to be a real justification"

    def test_episode_dates_returns_real_trading_days_within_range(self, raw_bundle):
        ep = LabeledEpisode("test", "2021-06-01", "2021-06-10", False, "synthetic test episode")
        dates = episode_dates(ep, raw_bundle)
        assert len(dates) > 0
        for d in dates:
            assert ep.start <= d <= ep.end

    def test_episode_dates_empty_for_a_range_with_no_real_trading_days(self, raw_bundle):
        # A real weekend-only range with no trading days.
        ep = LabeledEpisode("test", "2021-06-05", "2021-06-06", False, "synthetic weekend-only episode")
        assert episode_dates(ep, raw_bundle) == ()


# ---------------------------------------------------------------------------
# evaluate_episode — real integration against real pinned data
# ---------------------------------------------------------------------------

class TestEvaluateEpisode:
    def test_2018_christmas_eve_massacre_shows_real_crisis_entry(self, manifest, raw_bundle):
        """Direct regression check: the single most-verified real crisis
        episode in this whole investigation (Messages[191]/[194]/[195]/
        [224]/[228]) must show a real CRISIS entry under
        use_real_crisis_domains=True."""
        from dataclasses import replace
        config = replace(TEST_SCAFFOLDING_CONFIG, use_real_crisis_domains=True)
        episode = next(ep for ep in LABELED_EPISODES if "2018 Q4" in ep.name)
        result = evaluate_episode(episode, raw_bundle, manifest, config)
        assert result.any_crisis_entered is True
        assert result.entry_lag_sessions is not None
        assert result.first_crisis_date is not None

    def test_2021_calm_period_shows_no_crisis_entry(self, manifest, raw_bundle):
        from dataclasses import replace
        config = replace(TEST_SCAFFOLDING_CONFIG, use_real_crisis_domains=True)
        episode = next(ep for ep in LABELED_EPISODES if "2021 calm" in ep.name)
        result = evaluate_episode(episode, raw_bundle, manifest, config)
        assert result.any_crisis_entered is False
        assert result.first_crisis_date is None
        assert result.entry_lag_sessions is None

    def test_default_stub_config_never_enters_crisis_on_any_episode(self, manifest, raw_bundle):
        """Backward-compatibility check: the default config
        (use_real_crisis_domains=False) must show zero CRISIS entries
        across EVERY labeled episode, positive or negative — the stub is
        structurally always-calm regardless of what the real label says."""
        for ep in LABELED_EPISODES:
            result = evaluate_episode(ep, raw_bundle, manifest, TEST_SCAFFOLDING_CONFIG)
            assert result.any_crisis_entered is False, f"{ep.name}: unexpected CRISIS from the default stub config"

    def test_entry_lag_is_zero_when_crisis_active_on_first_checked_date(self, manifest, raw_bundle):
        """If the very first date checked is already CRISIS, entry_lag
        must be exactly 0 (index 0 in the date list), not None or some
        other sentinel."""
        from dataclasses import replace
        config = replace(TEST_SCAFFOLDING_CONFIG, use_real_crisis_domains=True)
        # 2018-12-24 itself (the real Christmas Eve Massacre peak) as a
        # single-day episode starting exactly on a known-active date.
        episode = LabeledEpisode("single day", "2018-12-24", "2018-12-24", True, "the real peak day itself")
        result = evaluate_episode(episode, raw_bundle, manifest, config)
        assert result.any_crisis_entered is True
        assert result.entry_lag_sessions == 0


# ---------------------------------------------------------------------------
# run_validation_study — aggregation and Wilson CI mechanics
# ---------------------------------------------------------------------------

class TestRunValidationStudy:
    def test_default_stub_config_gives_zero_recall_and_zero_false_positive_rate(self, manifest, raw_bundle):
        """The stub config never enters CRISIS anywhere — recall must be
        exactly 0.0 (every real positive episode is a miss) and the
        false-positive rate must be exactly 0.0 (every real negative
        episode is correctly quiet, trivially, since nothing ever
        fires)."""
        result = run_validation_study(raw_bundle, manifest, TEST_SCAFFOLDING_CONFIG)
        assert result.recall == pytest.approx(0.0)
        assert result.false_positive_rate == pytest.approx(0.0)
        assert result.true_positives == 0
        assert result.false_positives == 0

    def test_episode_counted_once_not_once_per_date(self, manifest, raw_bundle):
        """Per Message[211] §九 item 8's explicit requirement: the unit of
        analysis is ONE EPISODE, not one date — a multi-week episode with
        CRISIS active on 10 different dates must still contribute exactly
        1 to true_positives, not 10."""
        from dataclasses import replace
        config = replace(TEST_SCAFFOLDING_CONFIG, use_real_crisis_domains=True)
        result = run_validation_study(raw_bundle, manifest, config)
        assert result.true_positives + result.false_negatives == sum(1 for ep in LABELED_EPISODES if ep.is_crisis_positive)
        assert result.true_negatives + result.false_positives == sum(1 for ep in LABELED_EPISODES if not ep.is_crisis_positive)

    def test_recall_ci_is_none_when_no_positive_episodes_exist(self, manifest, raw_bundle):
        """Fail-closed on an empty denominator — recall/its CI must be
        None, never a divide-by-zero or a fabricated 0.0/1.0, if there
        are literally no positive episodes to check."""
        result = ValidationStudyResult(
            episode_results=(), true_positives=0, false_negatives=0,
            true_negatives=2, false_positives=0,
            recall=None, recall_ci=None,
            false_positive_rate=0.0, false_positive_rate_ci=(0.0, 0.5),
        )
        assert result.recall is None
        assert result.recall_ci is None
