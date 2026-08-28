"""Market Regime v5.1 — Slice 3 (Direction) test suite.

Solo review context: ChatGPT is unavailable (out of credit); this suite is
the adversarial self-review pass in its place, per the human's Message[170]
direction. Synthetic fixtures only — golden-vector-style regression cases,
not real market data (Direction's classification logic is pure arithmetic
over precomputed MA values, so real-CSV loading is not required here the way
it was for Slice 2's raw-series loader).

Run with: python3 -m pytest regime/tests/v5_1/test_slice3.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.direction import (  # noqa: E402
    DirectionStructure,
    DirectionInputs,
    DirectionHorizons,
    DirectionBaseScores,
    DirectionConfirmationState,
    DirectionResult,
    classify_structure,
    compute_direction_result,
    STRUCTURE_ORDER,
    DIRECTION_SIGN,
)


# ---------------------------------------------------------------------------
# Structure partition — every structure and boundary (golden-vector requirement)
# ---------------------------------------------------------------------------

class TestStructureClassification:
    def test_strong_bull(self):
        r = classify_structure(DirectionInputs(close=110, ema_fast=105, sma_mid=100, sma_long=95))
        assert r == DirectionStructure.STRONG_BULL

    def test_bull_excludes_strong_bull(self):
        """close > ema, ema > sma_long, but sma_mid <= sma_long (not aligned) — BULL, not STRONG_BULL."""
        r = classify_structure(DirectionInputs(close=110, ema_fast=105, sma_mid=95, sma_long=100))
        assert r == DirectionStructure.BULL

    def test_bull_pullback(self):
        r = classify_structure(DirectionInputs(close=98, ema_fast=100, sma_mid=97, sma_long=90))
        assert r == DirectionStructure.BULL_PULLBACK

    def test_damaged_bull(self):
        r = classify_structure(DirectionInputs(close=91, ema_fast=100, sma_mid=85, sma_long=90))
        assert r == DirectionStructure.DAMAGED_BULL

    def test_bear(self):
        r = classify_structure(DirectionInputs(close=80, ema_fast=100, sma_mid=95, sma_long=90))
        assert r == DirectionStructure.BEAR

    def test_bear_boundary_close_exactly_equals_sma_long(self):
        """close <= sma_long per the table's <=, so equality must be BEAR."""
        r = classify_structure(DirectionInputs(close=90, ema_fast=100, sma_mid=95, sma_long=90))
        assert r == DirectionStructure.BEAR

    def test_bull_pullback_boundary_close_exactly_equals_ema(self):
        """BULL_PULLBACK's condition is close <= ema_fast; equality must qualify."""
        r = classify_structure(DirectionInputs(close=100, ema_fast=100, sma_mid=97, sma_long=90))
        assert r == DirectionStructure.BULL_PULLBACK

    def test_strong_bull_boundary_strict_inequalities(self):
        """STRONG_BULL requires strict > at every step; an exact tie anywhere
        must NOT qualify as STRONG_BULL (falls through to a later structure)."""
        # close == ema_fast: fails close > ema_fast
        r = classify_structure(DirectionInputs(close=105, ema_fast=105, sma_mid=100, sma_long=95))
        assert r != DirectionStructure.STRONG_BULL

    def test_exhaustive_every_structure_reachable(self):
        """Every one of the 5 structures must be reachable by SOME input —
        confirms the partition really is exhaustive, not accidentally
        missing a real-world case."""
        reached = set()
        reached.add(classify_structure(DirectionInputs(close=110, ema_fast=105, sma_mid=100, sma_long=95)))
        reached.add(classify_structure(DirectionInputs(close=110, ema_fast=105, sma_mid=95, sma_long=100)))
        reached.add(classify_structure(DirectionInputs(close=98, ema_fast=100, sma_mid=97, sma_long=90)))
        reached.add(classify_structure(DirectionInputs(close=91, ema_fast=100, sma_mid=85, sma_long=90)))
        reached.add(classify_structure(DirectionInputs(close=80, ema_fast=100, sma_mid=95, sma_long=90)))
        assert reached == set(DirectionStructure)

    @pytest.mark.parametrize("missing_field", ["close", "ema_fast", "sma_mid", "sma_long"])
    def test_any_missing_input_makes_classification_unavailable(self, missing_field):
        kwargs = dict(close=100.0, ema_fast=95.0, sma_mid=90.0, sma_long=85.0)
        kwargs[missing_field] = None
        r = classify_structure(DirectionInputs(**kwargs))
        assert r is None


# ---------------------------------------------------------------------------
# Direction sign mapping
# ---------------------------------------------------------------------------

class TestDirectionSign:
    def test_strong_bull_bull_pullback_are_positive(self):
        assert DIRECTION_SIGN[DirectionStructure.STRONG_BULL] == 1
        assert DIRECTION_SIGN[DirectionStructure.BULL] == 1
        assert DIRECTION_SIGN[DirectionStructure.BULL_PULLBACK] == 1

    def test_damaged_bull_is_zero(self):
        assert DIRECTION_SIGN[DirectionStructure.DAMAGED_BULL] == 0

    def test_bear_is_negative(self):
        assert DIRECTION_SIGN[DirectionStructure.BEAR] == -1


# ---------------------------------------------------------------------------
# Base score partial order (design §6.1's exact inequality chain)
# ---------------------------------------------------------------------------

class TestBaseScores:
    def test_valid_partial_order_constructs(self):
        s = DirectionBaseScores(strong_bull=0.90, bull=0.80, bull_pullback=0.78, damaged_bull=0.55, bear=0.15)
        assert s.score_for(DirectionStructure.STRONG_BULL) == 0.90

    def test_bull_equals_bull_pullback_allowed(self):
        """Design §6.1 explicitly permits BULL == BULL_PULLBACK."""
        s = DirectionBaseScores(strong_bull=0.90, bull=0.78, bull_pullback=0.78, damaged_bull=0.55, bear=0.15)
        assert s.score_for(DirectionStructure.BULL) == s.score_for(DirectionStructure.BULL_PULLBACK)

    def test_strong_bull_must_be_strictly_greater_than_bull(self):
        with pytest.raises(ValueError, match="STRONG_BULL"):
            DirectionBaseScores(strong_bull=0.80, bull=0.80, bull_pullback=0.78, damaged_bull=0.55, bear=0.15)

    def test_bull_pullback_must_be_strictly_greater_than_damaged_bull(self):
        with pytest.raises(ValueError, match="BULL_PULLBACK"):
            DirectionBaseScores(strong_bull=0.90, bull=0.80, bull_pullback=0.55, damaged_bull=0.55, bear=0.15)

    def test_damaged_bull_must_be_strictly_greater_than_bear(self):
        with pytest.raises(ValueError, match="DAMAGED_BULL"):
            DirectionBaseScores(strong_bull=0.90, bull=0.80, bull_pullback=0.78, damaged_bull=0.15, bear=0.15)

    def test_bull_less_than_bull_pullback_rejected(self):
        """BULL >= BULL_PULLBACK is required; BULL < BULL_PULLBACK must fail."""
        with pytest.raises(ValueError, match="BULL_PULLBACK"):
            DirectionBaseScores(strong_bull=0.90, bull=0.70, bull_pullback=0.78, damaged_bull=0.55, bear=0.15)


class TestHorizons:
    @pytest.mark.parametrize("field", ["ema_fast", "sma_mid", "sma_long"])
    def test_non_positive_horizon_rejected(self, field):
        kwargs = dict(ema_fast=21, sma_mid=65, sma_long=200)
        kwargs[field] = 0
        with pytest.raises(ValueError):
            DirectionHorizons(**kwargs)


# ---------------------------------------------------------------------------
# Confirmation logic: immediate downgrade, consecutive-bar upgrade,
# oscillation, target changes, nonadjacent jumps, restart parity
# ---------------------------------------------------------------------------

class TestConfirmation:
    def test_before_first_bar_confirmed_is_none(self):
        s = DirectionConfirmationState(confirmation_bars=3)
        assert s.confirmed_structure is None

    def test_first_valid_bar_initializes_immediately_not_via_confirmation_count(self):
        """This is the cold-start fix itself: the FIRST classification
        initializes confirmed_structure directly, regardless of
        confirmation_bars, and regardless of which structure it is
        (including STRONG_BULL — the legacy bug was seeding STRONG_BULL as
        a CONSTANT before any real observation; correctly seeding from a
        real STRONG_BULL observation is not the same bug)."""
        s = DirectionConfirmationState(confirmation_bars=5)
        result = s.advance(DirectionStructure.STRONG_BULL)
        assert result == DirectionStructure.STRONG_BULL
        assert s.confirmed_structure == DirectionStructure.STRONG_BULL

    def test_cold_start_never_uses_a_hardcoded_seed_when_first_bar_is_not_strong_bull(self):
        """The regression case design §6.2 specifically calls out: 'first
        valid non-STRONG_BULL after insufficient history.' The legacy bug
        would have shown STRONG_BULL even when the true first observation
        was, say, BEAR. This proves the fix: first-bar BEAR must confirm as
        BEAR, never STRONG_BULL."""
        s = DirectionConfirmationState(confirmation_bars=3)
        result = s.advance(DirectionStructure.BEAR)
        assert result == DirectionStructure.BEAR

    def test_cold_start_in_every_one_of_the_five_raw_structures(self):
        """Golden-vector requirement (plan §6/design §14.1): 'Direction
        cold start in EVERY raw structure' — not just STRONG_BULL (the
        legacy bug's own hardcoded value) and BEAR (the one specific
        regression case named in §6.2's own text). A gap found during
        Slice 12's conformance review: the two existing cold-start tests
        only exercised 2 of the 5 possible first-observation structures.
        Every one of the 5 must independently confirm to ITSELF on the
        very first bar, with a completely fresh state each time (so no
        structure's result could be influenced by a prior structure's
        cold-start in this same test)."""
        for structure in DirectionStructure:
            s = DirectionConfirmationState(confirmation_bars=3)
            result = s.advance(structure)
            assert result == structure, f"cold start from {structure.name} did not confirm as itself"
            assert s.confirmed_structure == structure
            assert s.pending_state is None
            assert s.pending_count == 0

    def test_immediate_downgrade(self):
        s = DirectionConfirmationState(confirmation_bars=3)
        s.advance(DirectionStructure.STRONG_BULL)
        result = s.advance(DirectionStructure.BEAR)
        assert result == DirectionStructure.BEAR  # confirms on the very next bar, no delay

    def test_upgrade_requires_exact_consecutive_count(self):
        s = DirectionConfirmationState(confirmation_bars=3)
        s.advance(DirectionStructure.BEAR)
        r1 = s.advance(DirectionStructure.BULL)
        assert r1 == DirectionStructure.BEAR  # not yet confirmed
        r2 = s.advance(DirectionStructure.BULL)
        assert r2 == DirectionStructure.BEAR  # still not confirmed
        r3 = s.advance(DirectionStructure.BULL)
        assert r3 == DirectionStructure.BULL  # confirms on the 3rd consecutive bar

    def test_upgrade_candidate_resets_on_deterioration(self):
        """'a candidate resets if raw returns to confirmed, deteriorates,
        or changes to another upgrade target' — deterioration mid-candidacy
        must reset the pending count entirely."""
        s = DirectionConfirmationState(confirmation_bars=3)
        s.advance(DirectionStructure.BEAR)
        s.advance(DirectionStructure.BULL)   # candidate count 1
        s.advance(DirectionStructure.BULL)   # candidate count 2
        s.advance(DirectionStructure.DAMAGED_BULL)  # deteriorates relative to BULL candidate but still less supportive than confirmed BEAR? No: DAMAGED_BULL is MORE supportive than BEAR.
        # DAMAGED_BULL is a different (less supportive than BULL, but still
        # more supportive than confirmed BEAR) upgrade target -> new candidate.
        assert s._pending_target == DirectionStructure.DAMAGED_BULL
        assert s._pending_count == 1

    def test_upgrade_candidate_resets_when_raw_returns_to_confirmed(self):
        s = DirectionConfirmationState(confirmation_bars=3)
        s.advance(DirectionStructure.BEAR)
        s.advance(DirectionStructure.BULL)  # candidate count 1
        result = s.advance(DirectionStructure.BEAR)  # returns to confirmed
        assert result == DirectionStructure.BEAR
        assert s._pending_target is None
        assert s._pending_count == 0

    def test_oscillation_never_confirms_without_reaching_the_count(self):
        """Alternating between two more-supportive targets, never reaching
        confirmation_bars consecutively on either, must never confirm."""
        s = DirectionConfirmationState(confirmation_bars=3)
        s.advance(DirectionStructure.BEAR)
        for _ in range(10):
            s.advance(DirectionStructure.BULL)
            r = s.advance(DirectionStructure.DAMAGED_BULL)
            assert r != DirectionStructure.BULL  # never confirms BULL via oscillation

    def test_nonadjacent_jump_upgrade_still_requires_confirmation(self):
        """Jumping from BEAR directly toward STRONG_BULL (skipping
        intermediate structures) is still an upgrade and still requires
        confirmation_bars consecutive matches — no special-casing for
        'large' jumps."""
        s = DirectionConfirmationState(confirmation_bars=2)
        s.advance(DirectionStructure.BEAR)
        r1 = s.advance(DirectionStructure.STRONG_BULL)
        assert r1 == DirectionStructure.BEAR
        r2 = s.advance(DirectionStructure.STRONG_BULL)
        assert r2 == DirectionStructure.STRONG_BULL

    def test_nonadjacent_jump_downgrade_is_still_immediate(self):
        s = DirectionConfirmationState(confirmation_bars=3)
        s.advance(DirectionStructure.STRONG_BULL)
        result = s.advance(DirectionStructure.BEAR)  # jumps past 3 intermediate structures
        assert result == DirectionStructure.BEAR  # still immediate, no partial credit

    def test_missing_raw_bar_does_not_reset_pending_candidate(self):
        """An unavailable bar (raw=None) — design §4.1's fail-closed rule
        means we must not treat a data gap as a real observation of any
        kind. This proves a None bar neither advances nor resets an
        in-progress upgrade candidacy."""
        s = DirectionConfirmationState(confirmation_bars=3)
        s.advance(DirectionStructure.BEAR)
        s.advance(DirectionStructure.BULL)  # candidate count 1
        r = s.advance(None)
        assert r == DirectionStructure.BEAR  # confirmed unchanged
        assert s._pending_target == DirectionStructure.BULL
        assert s._pending_count == 1  # NOT reset by the missing bar
        s.advance(DirectionStructure.BULL)  # candidate count 2 (continues from where it was)
        r_final = s.advance(DirectionStructure.BULL)  # candidate count 3, confirms
        assert r_final == DirectionStructure.BULL

    def test_missing_raw_bar_before_any_confirmation_stays_unavailable(self):
        s = DirectionConfirmationState(confirmation_bars=3)
        r = s.advance(None)
        assert r is None
        assert s.confirmed_structure is None

    def test_restart_parity_two_independent_states_behave_identically(self):
        """Two freshly-constructed states fed the identical sequence must
        produce byte-identical confirmed-structure sequences — a
        determinism/no-hidden-state check."""
        sequence = [
            DirectionStructure.BEAR, DirectionStructure.BULL, DirectionStructure.BULL,
            DirectionStructure.BULL, DirectionStructure.STRONG_BULL, DirectionStructure.STRONG_BULL,
            DirectionStructure.DAMAGED_BULL, None, DirectionStructure.DAMAGED_BULL,
        ]
        s1 = DirectionConfirmationState(confirmation_bars=3)
        s2 = DirectionConfirmationState(confirmation_bars=3)
        results1 = [s1.advance(r) for r in sequence]
        results2 = [s2.advance(r) for r in sequence]
        assert results1 == results2

    @pytest.mark.parametrize("bad_count", [0, -1, -5])
    def test_confirmation_bars_must_be_at_least_1(self, bad_count):
        with pytest.raises(ValueError):
            DirectionConfirmationState(confirmation_bars=bad_count)

    def test_confirmation_bars_of_1_confirms_on_first_upgrade_bar(self):
        """confirmation_bars=1 is a legitimate EMPIRICAL choice — an upgrade
        should confirm on the very first matching bar in that case (no
        multi-bar delay at all)."""
        s = DirectionConfirmationState(confirmation_bars=1)
        s.advance(DirectionStructure.BEAR)
        result = s.advance(DirectionStructure.BULL)
        assert result == DirectionStructure.BULL

    def test_all_20_ordered_structure_pair_transitions_are_correctly_immediate_or_delayed(self):
        """Exhaustive check across every (confirmed, raw) ordered pair
        (5*4=20 pairs, excluding self-transitions) that a raw structure MORE
        supportive than confirmed is correctly delayed (never confirms after
        just 1 bar when confirmation_bars=2), and a raw structure LESS
        supportive is correctly immediate (always confirms after exactly 1
        bar). Found and verified during solo adversarial self-review — a
        single directional bug in the more-supportive/less-supportive
        comparison would silently invert immediate-vs-delayed behavior for
        roughly half of all real transitions, which targeted unit tests
        alone might not catch if they happened to only exercise the
        non-buggy half."""
        for confirmed in STRUCTURE_ORDER:
            for raw in STRUCTURE_ORDER:
                if raw == confirmed:
                    continue
                confirmed_idx = STRUCTURE_ORDER.index(confirmed)
                raw_idx = STRUCTURE_ORDER.index(raw)
                expected_more_supportive = raw_idx < confirmed_idx

                s = DirectionConfirmationState(confirmation_bars=2)
                s.advance(confirmed)
                result_after_1_bar = s.advance(raw)
                confirmed_after_1_bar = result_after_1_bar == raw

                if expected_more_supportive:
                    assert not confirmed_after_1_bar, (
                        f"{confirmed.name} -> {raw.name}: raw is MORE supportive, "
                        f"expected upgrade delay (not confirmed after 1 bar), but it confirmed"
                    )
                else:
                    assert confirmed_after_1_bar, (
                        f"{confirmed.name} -> {raw.name}: raw is LESS supportive, "
                        f"expected immediate confirmation after 1 bar, but it did not confirm"
                    )


# ---------------------------------------------------------------------------
# Structure ordering sanity (used internally by the confirmation logic)
# ---------------------------------------------------------------------------

class TestStructureOrder:
    def test_order_is_most_to_least_supportive(self):
        assert STRUCTURE_ORDER == (
            DirectionStructure.STRONG_BULL,
            DirectionStructure.BULL,
            DirectionStructure.BULL_PULLBACK,
            DirectionStructure.DAMAGED_BULL,
            DirectionStructure.BEAR,
        )

    def test_all_five_structures_present_exactly_once(self):
        assert len(STRUCTURE_ORDER) == 5
        assert len(set(STRUCTURE_ORDER)) == 5
        assert set(STRUCTURE_ORDER) == set(DirectionStructure)


# ---------------------------------------------------------------------------
# compute_direction_result — direction_score/direction_sign assembly
# (gap closed per Message[177]: TrendQuality's "Direction adjustment
# coefficient" wired in via an injected EMPIRICAL DirectionAdjustment)
# ---------------------------------------------------------------------------

def _default_base_scores():
    return DirectionBaseScores(strong_bull=0.90, bull=0.80, bull_pullback=0.80, damaged_bull=0.55, bear=0.15)


def _stub_adjustment_identity(base_score, trend_quality):
    """Obviously-fake stub proving the injection seam: ignores
    trend_quality entirely and returns the base score unchanged. Asserts
    nothing about a real formula."""
    return base_score


def _stub_adjustment_uses_trend_quality(base_score, trend_quality):
    """A different obviously-fake stub that DOES read trend_quality, to
    prove the seam actually receives and can use it — not just that the
    parameter exists syntactically."""
    if trend_quality is None:
        return base_score
    return min(1.0, base_score * (0.5 + trend_quality))


def _fresh_confirmation_state(confirmation_bars=3) -> DirectionConfirmationState:
    return DirectionConfirmationState(confirmation_bars=confirmation_bars)


class TestComputeDirectionResult:
    def test_direction_sign_is_pure_closed_lookup_unaffected_by_adjustment(self):
        """direction_sign must equal DIRECTION_SIGN[confirmed_structure]
        regardless of what the injected adjustment does to direction_score
        — proven by using an adjustment that returns an arbitrary constant
        having nothing to do with the structure's natural sign."""
        def _weird_adjustment(base_score, trend_quality):
            return 0.01  # deliberately unrelated to the structure

        for structure in DirectionStructure:
            r = compute_direction_result(structure, structure, _fresh_confirmation_state(), _default_base_scores(), 0.5, _weird_adjustment)
            assert r.direction_sign == DIRECTION_SIGN[structure]
            assert r.confirmed_structure == structure

    def test_direction_score_is_whatever_the_injected_adjustment_returns(self):
        r = compute_direction_result(
            DirectionStructure.STRONG_BULL, DirectionStructure.STRONG_BULL, _fresh_confirmation_state(),
            _default_base_scores(), 0.5, _stub_adjustment_identity,
        )
        assert isinstance(r, DirectionResult)
        assert r.direction_score == pytest.approx(0.90)  # identity stub: unchanged base score

    def test_none_trend_quality_is_passed_through_to_the_injected_adjustment(self):
        """A missing TrendQuality value (None) must reach the injected
        adjustment as None, not be silently coerced to 0.0 or some other
        sentinel before the seam — this module does not decide what a
        missing TrendQuality means, the injected implementation does."""
        received = {}

        def _capturing_adjustment(base_score, trend_quality):
            received["trend_quality"] = trend_quality
            return base_score

        compute_direction_result(
            DirectionStructure.BULL, DirectionStructure.BULL, _fresh_confirmation_state(),
            _default_base_scores(), None, _capturing_adjustment,
        )
        assert received["trend_quality"] is None

    def test_adjustment_actually_receives_and_can_use_trend_quality(self):
        """Proves the seam isn't decorative: two calls with identical
        structure/base_score but different trend_quality values produce
        different direction_score outputs when the injected adjustment
        genuinely depends on trend_quality."""
        base_scores = _default_base_scores()
        r_low_tq = compute_direction_result(
            DirectionStructure.BULL, DirectionStructure.BULL, _fresh_confirmation_state(),
            base_scores, 0.1, _stub_adjustment_uses_trend_quality,
        )
        r_high_tq = compute_direction_result(
            DirectionStructure.BULL, DirectionStructure.BULL, _fresh_confirmation_state(),
            base_scores, 0.9, _stub_adjustment_uses_trend_quality,
        )
        assert r_low_tq.direction_score != r_high_tq.direction_score

    def test_result_is_frozen_dataclass(self):
        r = compute_direction_result(
            DirectionStructure.BEAR, DirectionStructure.BEAR, _fresh_confirmation_state(),
            _default_base_scores(), None, _stub_adjustment_identity,
        )
        with pytest.raises(Exception):
            r.direction_score = 0.99  # frozen dataclass must reject mutation

    def test_raw_structure_is_carried_through_independently_of_confirmed(self):
        """A real bug risk to guard against: raw_structure must reflect
        the CURRENT bar's raw classification, which can genuinely differ
        from confirmed_structure while an upgrade is still pending
        confirmation."""
        r = compute_direction_result(
            DirectionStructure.BULL, DirectionStructure.STRONG_BULL, _fresh_confirmation_state(),
            _default_base_scores(), 0.5, _stub_adjustment_identity,
        )
        assert r.confirmed_structure == DirectionStructure.BULL
        assert r.raw_structure == DirectionStructure.STRONG_BULL

    def test_raw_structure_may_be_none_when_unavailable(self):
        r = compute_direction_result(
            DirectionStructure.BULL, None, _fresh_confirmation_state(),
            _default_base_scores(), 0.5, _stub_adjustment_identity,
        )
        assert r.raw_structure is None

    def test_pending_state_and_count_reflect_the_confirmation_state_object(self):
        """pending_state/pending_count must come from the SAME
        confirmation_state object passed in, reflecting its real pending
        candidate — proven by actually advancing a real state machine
        toward a pending upgrade, then passing it in."""
        state = DirectionConfirmationState(confirmation_bars=3)
        state.advance(DirectionStructure.BULL)  # cold start: confirms BULL
        state.advance(DirectionStructure.STRONG_BULL)  # 1st bar toward an upgrade candidate
        assert state.pending_state == DirectionStructure.STRONG_BULL
        assert state.pending_count == 1

        r = compute_direction_result(
            state.confirmed_structure, DirectionStructure.STRONG_BULL, state,
            _default_base_scores(), 0.5, _stub_adjustment_identity,
        )
        assert r.confirmed_structure == DirectionStructure.BULL  # not yet upgraded
        assert r.pending_state == DirectionStructure.STRONG_BULL
        assert r.pending_count == 1

    def test_pending_state_is_none_and_count_is_zero_when_nothing_pending(self):
        state = DirectionConfirmationState(confirmation_bars=3)
        state.advance(DirectionStructure.BULL)
        r = compute_direction_result(
            state.confirmed_structure, DirectionStructure.BULL, state,
            _default_base_scores(), 0.5, _stub_adjustment_identity,
        )
        assert r.pending_state is None
        assert r.pending_count == 0
