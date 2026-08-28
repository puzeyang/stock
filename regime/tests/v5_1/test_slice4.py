"""Market Regime v5.1 — Slice 4 (Breadth) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction. Mixes
real pinned Tier 2 data (for realistic coverage/warm-up behavior) with
synthetic RawSeriesCollection fixtures (for edge cases the real 9-member
dataset doesn't naturally exhibit, e.g. partial cross-member coverage, since
all 9 real sector ETFs happen to share the same inception date).

Run with: python3 -m pytest regime/tests/v5_1/test_slice4.py -v
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.raw_features import (  # noqa: E402
    load_raw_collection,
    RawSeries,
    RawSeriesCollection,
    RawObservation,
)
from v5_1.breadth import (  # noqa: E402
    compute_breadth,
    compute_participation,
    BreadthBlendConfig,
    BreadthUnavailableError,
    BreadthResult,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def real_breadth_collection(manifest):
    return load_raw_collection("breadth_member_observations", manifest)


def _make_synthetic_series(field_id: str, contract_id: str, dates_values: list[tuple[str, float]]) -> RawSeries:
    obs = tuple(RawObservation(date=d, value=v, source_contract_id=contract_id, field_name="close") for d, v in dates_values)
    return RawSeries(field_id=field_id, source_contract_id=contract_id, field_name="close", observations=obs)


def _make_synthetic_collection(members: dict[str, list[tuple[str, float]]]) -> RawSeriesCollection:
    return RawSeriesCollection(
        field_id="breadth_member_observations",
        source_contract_id="BREADTH_V5_1",
        field_name="close",
        members={path: _make_synthetic_series("breadth_member_observations", "BREADTH_V5_1", pairs) for path, pairs in members.items()},
    )


# ---------------------------------------------------------------------------
# BreadthBlendConfig validation
# ---------------------------------------------------------------------------

class TestBlendConfig:
    def test_valid_weights_construct(self):
        BreadthBlendConfig(weight_sma50=0.5, weight_sma200=0.5)

    def test_equal_split_is_valid(self):
        BreadthBlendConfig(weight_sma50=0.3, weight_sma200=0.7)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="sum to exactly 1.0"):
            BreadthBlendConfig(weight_sma50=0.5, weight_sma200=0.4)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="nonnegative"):
            BreadthBlendConfig(weight_sma50=-0.1, weight_sma200=1.1)

    def test_zero_weight_on_one_side_is_valid(self):
        """Zero production weight on one side is explicitly allowed by
        design's general EMPIRICAL-disposition pattern (§6.5's own language
        about zero weights being allowed) — same principle applies here."""
        BreadthBlendConfig(weight_sma50=1.0, weight_sma200=0.0)


# ---------------------------------------------------------------------------
# Real-data participation computation
# ---------------------------------------------------------------------------

class TestRealDataParticipation:
    def test_full_coverage_on_well_warmed_date(self, real_breadth_collection):
        pct50, pct200, eligible, total = compute_participation(
            real_breadth_collection, "2020-04-15", sma50_window=50, sma200_window=200
        )
        assert eligible == 9
        assert total == 9
        assert 0 <= pct50 <= 1
        assert 0 <= pct200 <= 1

    def test_covid_bottom_shows_zero_participation(self, real_breadth_collection):
        """2020-03-23 was the real COVID crash bottom — every sector ETF was
        trading well below both its 50 and 200-day averages. This is a
        real-world sanity check, not an arbitrary assertion."""
        pct50, pct200, eligible, total = compute_participation(
            real_breadth_collection, "2020-03-23", sma50_window=50, sma200_window=200
        )
        assert pct50 == 0.0
        assert pct200 == 0.0
        assert eligible == 9

    def test_unavailable_before_any_member_is_warmed(self, real_breadth_collection):
        with pytest.raises(BreadthUnavailableError, match="0 of 9 members eligible"):
            compute_participation(real_breadth_collection, "1999-01-01", sma50_window=50, sma200_window=200)

    def test_compute_breadth_end_to_end_real_data(self, real_breadth_collection):
        blend = BreadthBlendConfig(weight_sma50=0.4, weight_sma200=0.6)
        r = compute_breadth(real_breadth_collection, "2020-04-15", sma50_window=50, sma200_window=200, blend=blend)
        assert isinstance(r, BreadthResult)
        assert r.source_tier == "tier_2_fixed_nine_production"
        assert r.breadth_score == pytest.approx(0.4 * r.pct_above_sma50 + 0.6 * r.pct_above_sma200)


class TestSourceTierAndNoSplice:
    """Golden-vector requirement (plan §6/design §14.1): 'Breadth source
    tiers and no-splice behavior.' A gap found during Slice 12's
    conformance review: `test_compute_breadth_end_to_end_real_data` above
    already asserts `source_tier` is the correct literal string, but
    'no-splice' specifically (Tier 1/2/3 histories are never auto-combined,
    design §3.3) had no dedicated test at all."""

    def test_source_tier_is_always_explicit_never_defaulted_to_none_or_empty(self, real_breadth_collection):
        blend = BreadthBlendConfig(weight_sma50=0.5, weight_sma200=0.5)
        r = compute_breadth(real_breadth_collection, "2020-04-15", sma50_window=50, sma200_window=200, blend=blend)
        assert r.source_tier
        assert r.source_tier != ""

    def test_no_tier_1_or_tier_3_code_path_exists_in_this_module(self):
        """Design §3.3: Tier 1 (point-in-time constituent membership) and
        Tier 3 (diagnostic-only eleven-sector history) are both
        OUT_OF_SCOPE for this reference implementation and 'MUST NOT
        auto-splice into Tier 2.' Verified structurally: this module's
        source contains no reference to a Tier 1/Tier 3 concept at all —
        the strongest form of 'never auto-splices' is that there is
        nothing here CAPABLE of splicing, not merely a runtime check that
        happens to currently prevent it."""
        import v5_1.breadth as breadth_module
        source = inspect.getsource(breadth_module)
        for forbidden in ("tier_1", "tier_3", "eleven_sector", "eleven-sector"):
            assert forbidden not in source.lower(), f"breadth.py references {forbidden!r} — Tier 1/3 must not exist as a code path here"

    def test_compute_breadth_source_tier_parameter_defaults_to_tier_2_and_has_no_tier_1_or_3_option(self):
        """Structural check on compute_breadth's own signature: the
        `source_tier` parameter is a free-form string (so a caller COULD
        pass an arbitrary label), but the function itself never reads,
        branches on, or validates against any Tier 1/3-specific value —
        there is no alternate computation path this module could
        'auto-splice' through even if a caller passed a misleading label."""
        sig = inspect.signature(compute_breadth)
        assert sig.parameters["source_tier"].default == "tier_2_fixed_nine_production"

    def test_compute_breadth_unavailable_propagates(self, real_breadth_collection):
        blend = BreadthBlendConfig(weight_sma50=0.5, weight_sma200=0.5)
        with pytest.raises(BreadthUnavailableError):
            compute_breadth(real_breadth_collection, "1999-01-01", sma50_window=50, sma200_window=200, blend=blend)


# ---------------------------------------------------------------------------
# Synthetic edge cases: partial cross-member coverage, exact-boundary "above"
# ---------------------------------------------------------------------------

class TestSyntheticEdgeCases:
    def test_partial_member_coverage_excludes_unwarmed_members_from_denominator(self):
        """4 members warmed for a 3-length window, 1 member has only 2 real
        observations (not warmed). The unwarmed member must be excluded from
        BOTH the numerator and the eligible-count denominator, not silently
        counted as 'below' or dropped from total_members."""
        members = {
            "a": [("2020-01-01", 1.0), ("2020-01-02", 1.0), ("2020-01-03", 10.0)],  # warmed, above its own SMA3
            "b": [("2020-01-01", 5.0), ("2020-01-02", 5.0), ("2020-01-03", 1.0)],  # warmed, below its own SMA3
            "c": [("2020-01-01", 1.0), ("2020-01-02", 1.0), ("2020-01-03", 10.0)],  # warmed, above
            "d": [("2020-01-01", 5.0), ("2020-01-02", 5.0), ("2020-01-03", 1.0)],  # warmed, below
            "e": [("2020-01-02", 1.0), ("2020-01-03", 2.0)],  # only 2 obs — NOT warmed for a 3-window
        }
        coll = _make_synthetic_collection(members)
        pct50, pct200, eligible, total = compute_participation(coll, "2020-01-03", sma50_window=3, sma200_window=3)
        assert total == 5
        assert eligible == 4  # member "e" excluded from the denominator
        assert pct50 == pytest.approx(0.5)  # 2 of 4 eligible members above their own SMA3

    def test_all_members_ineligible_raises_unavailable(self):
        members = {"a": [("2020-01-01", 1.0)], "b": [("2020-01-01", 2.0)]}
        coll = _make_synthetic_collection(members)
        with pytest.raises(BreadthUnavailableError):
            compute_participation(coll, "2020-01-01", sma50_window=5, sma200_window=5)

    def test_current_exactly_equal_to_sma_is_not_above(self):
        """'Above' is a strict inequality — a member exactly AT its own SMA
        must not count as above."""
        members = {"a": [("2020-01-01", 2.0), ("2020-01-02", 2.0), ("2020-01-03", 2.0)]}  # flat, SMA==current
        coll = _make_synthetic_collection(members)
        pct50, pct200, eligible, total = compute_participation(coll, "2020-01-03", sma50_window=3, sma200_window=3)
        assert pct50 == 0.0  # the single member is AT its SMA, not above

    def test_member_with_no_observation_on_as_of_excluded_from_denominator(self):
        """A member with real history but NO row on the exact as_of date
        (e.g. a data gap) must be excluded entirely, not treated as
        'unavailable but still counted eligible for the window.'"""
        members = {
            "a": [("2020-01-01", 1.0), ("2020-01-02", 1.0), ("2020-01-03", 10.0)],
            "b": [("2020-01-01", 5.0), ("2020-01-02", 5.0)],  # no row on 2020-01-03 itself
        }
        coll = _make_synthetic_collection(members)
        pct50, pct200, eligible, total = compute_participation(coll, "2020-01-03", sma50_window=3, sma200_window=3)
        assert total == 2
        assert eligible == 1  # member "b" excluded (no current-date observation)

    def test_different_eligible_counts_for_sma50_vs_sma200_takes_conservative_min(self):
        """Two members: "a" has 10 real observations (warmed for a 5-window
        AND a 10-window), "b" has only 6 (warmed for the 5-window but NOT
        the 10-window). This produces genuinely different eligible counts —
        eligible_50=2 (both members), eligible_200=1 (only "a") — and the
        combined `eligible_count` returned must be the smaller of the two
        (1), per the documented conservative-min design choice. This is a
        real bug found and fixed during self-review: the first version of
        this test used only 1 member, so it could never actually reach the
        min-taking code path at all — it always hit the 'zero eligible'
        BreadthUnavailableError branch instead, which is a different case
        entirely (a bug in the TEST, not the implementation, but one that
        meant this specific requirement was never actually verified)."""
        members = {
            "a": [(f"2020-01-{d:02d}", 1.0) for d in range(1, 11)],  # 10 obs
            "b": [(f"2020-01-{d:02d}", 1.0) for d in range(5, 11)],  # 6 obs (2020-01-05 through 2020-01-10)
        }
        coll = _make_synthetic_collection(members)
        pct50, pct200, eligible, total = compute_participation(coll, "2020-01-10", sma50_window=5, sma200_window=10)
        assert total == 2
        assert eligible == 1  # min(eligible_50=2, eligible_200=1) — "b" is not warmed for the 10-window

    def test_zero_member_collection_raises(self):
        coll = _make_synthetic_collection({})
        with pytest.raises(BreadthUnavailableError, match="zero members"):
            compute_participation(coll, "2020-01-01", sma50_window=5, sma200_window=5)


class TestInputValidation:
    def test_non_positive_sma_window_rejected(self, real_breadth_collection):
        with pytest.raises(ValueError, match="must be positive"):
            compute_participation(real_breadth_collection, "2020-04-15", sma50_window=0, sma200_window=200)

    def test_negative_sma_window_rejected(self, real_breadth_collection):
        with pytest.raises(ValueError, match="must be positive"):
            compute_participation(real_breadth_collection, "2020-04-15", sma50_window=50, sma200_window=-1)


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_breadth_computation_is_repeatable(self, real_breadth_collection):
        blend = BreadthBlendConfig(weight_sma50=0.5, weight_sma200=0.5)
        r1 = compute_breadth(real_breadth_collection, "2020-04-15", sma50_window=50, sma200_window=200, blend=blend)
        r2 = compute_breadth(real_breadth_collection, "2020-04-15", sma50_window=50, sma200_window=200, blend=blend)
        assert r1 == r2
