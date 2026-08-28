"""Market Regime v5.1 — Ordinary hysteresis (part of module 4.10) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_ordinary_state.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.ordinary_state import (  # noqa: E402
    OrdinaryState,
    StateBoundaries,
    ConfirmationBars,
    OrdinaryHysteresisState,
    ORDINARY_STATE_ORDER,
)


def _boundaries(risk_off_neutral=0.35, neutral_risk_on=0.65, buf_lo=0.05, buf_hi=0.05):
    return StateBoundaries(
        risk_off_neutral_boundary=risk_off_neutral,
        neutral_risk_on_boundary=neutral_risk_on,
        risk_off_neutral_buffer=buf_lo,
        neutral_risk_on_buffer=buf_hi,
    )


def _bars(upgrade=3, downgrade=1):
    return ConfirmationBars(upgrade_bars=upgrade, downgrade_bars=downgrade)


# ---------------------------------------------------------------------------
# StateBoundaries validation
# ---------------------------------------------------------------------------

class TestStateBoundariesValidation:
    def test_valid_boundaries_construct(self):
        _boundaries()

    def test_boundaries_must_be_strictly_ordered(self):
        with pytest.raises(ValueError, match="strictly less than"):
            StateBoundaries(risk_off_neutral_boundary=0.6, neutral_risk_on_boundary=0.4, risk_off_neutral_buffer=0.0, neutral_risk_on_buffer=0.0)

    def test_equal_boundaries_rejected(self):
        with pytest.raises(ValueError, match="strictly less than"):
            StateBoundaries(risk_off_neutral_boundary=0.5, neutral_risk_on_boundary=0.5, risk_off_neutral_buffer=0.0, neutral_risk_on_buffer=0.0)

    def test_negative_buffer_rejected(self):
        with pytest.raises(ValueError, match="nonnegative"):
            StateBoundaries(risk_off_neutral_boundary=0.3, neutral_risk_on_boundary=0.6, risk_off_neutral_buffer=-0.1, neutral_risk_on_buffer=0.0)


# ---------------------------------------------------------------------------
# ConfirmationBars validation — asymmetry requirement
# ---------------------------------------------------------------------------

class TestConfirmationBarsValidation:
    def test_valid_asymmetric_bars_construct(self):
        ConfirmationBars(upgrade_bars=5, downgrade_bars=1)

    def test_symmetric_bars_are_allowed(self):
        """'Downgrades are at least as fast as upgrades' permits equality,
        not only strict asymmetry — design says 'faster,' but this
        dataclass's own stated contract is downgrade <= upgrade, and a
        symmetric 1/1 or 3/3 config is a legitimate (if empirically
        unusual) point in that space, not a construction-time error."""
        ConfirmationBars(upgrade_bars=3, downgrade_bars=3)

    def test_downgrade_slower_than_upgrade_rejected(self):
        with pytest.raises(ValueError, match="must not exceed"):
            ConfirmationBars(upgrade_bars=2, downgrade_bars=5)

    def test_zero_or_negative_bars_rejected(self):
        with pytest.raises(ValueError, match=">= 1"):
            ConfirmationBars(upgrade_bars=0, downgrade_bars=0)


# ---------------------------------------------------------------------------
# classify_raw — dead-band boundary classification
# ---------------------------------------------------------------------------

class TestClassifyRaw:
    def test_cold_start_uses_bare_boundaries_no_buffer(self):
        b = _boundaries()
        assert b.classify_raw(0.34, None) == OrdinaryState.RISK_OFF
        assert b.classify_raw(0.35, None) == OrdinaryState.NEUTRAL
        assert b.classify_raw(0.64, None) == OrdinaryState.NEUTRAL
        assert b.classify_raw(0.65, None) == OrdinaryState.RISK_ON

    def test_deep_values_classify_correctly_regardless_of_current(self):
        b = _boundaries()
        assert b.classify_raw(0.0, OrdinaryState.RISK_ON) == OrdinaryState.RISK_OFF
        assert b.classify_raw(1.0, OrdinaryState.RISK_OFF) == OrdinaryState.RISK_ON

    def test_dead_band_holds_current_state_within_buffer_zone(self):
        """A value that re-enters the buffer zone around the CURRENT raw
        state's own boundary must not flip the raw classification — this
        is the entire point of the buffer (avoid chatter right at a bare
        boundary)."""
        b = _boundaries(risk_off_neutral=0.35, buf_lo=0.05)
        # Currently NEUTRAL; condition_score dips to 0.33 (below the bare
        # 0.35 boundary but still within [0.35-0.05, 0.35) — must NOT
        # immediately reclassify to RISK_OFF at the dead-band level.
        assert b.classify_raw(0.33, OrdinaryState.NEUTRAL) == OrdinaryState.NEUTRAL
        # Genuinely below the buffered floor: does reclassify.
        assert b.classify_raw(0.29, OrdinaryState.NEUTRAL) == OrdinaryState.RISK_OFF

    def test_dead_band_symmetric_for_upgrade_direction(self):
        b = _boundaries(risk_off_neutral=0.35, buf_lo=0.05)
        # Currently RISK_OFF; condition_score rises to 0.37 (above bare
        # 0.35 but within [0.35, 0.35+0.05) — must NOT immediately
        # reclassify to NEUTRAL at the dead-band level.
        assert b.classify_raw(0.37, OrdinaryState.RISK_OFF) == OrdinaryState.RISK_OFF
        assert b.classify_raw(0.41, OrdinaryState.RISK_OFF) == OrdinaryState.NEUTRAL


# ---------------------------------------------------------------------------
# OrdinaryHysteresisState.advance — the full asymmetric confirmation machine
# ---------------------------------------------------------------------------

class TestAdvanceColdStart:
    def test_starts_unavailable_never_seeded(self):
        s = OrdinaryHysteresisState()
        assert s.confirmed_state is None
        assert s.pending_state is None
        assert s.pending_count == 0

    def test_first_valid_bar_initializes_immediately(self):
        s = OrdinaryHysteresisState()
        result = s.advance(0.9, _boundaries(), _bars(), hard_veto_active=False)
        assert result == OrdinaryState.RISK_ON
        assert s.confirmed_state == OrdinaryState.RISK_ON

    def test_missing_condition_score_before_any_confirmation_stays_unavailable(self):
        s = OrdinaryHysteresisState()
        result = s.advance(None, _boundaries(), _bars(), hard_veto_active=False)
        assert result is None
        assert s.confirmed_state is None


class TestAdvanceDowngrade:
    def test_downgrade_confirms_in_downgrade_bars_count(self):
        s = OrdinaryHysteresisState()
        s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert s.confirmed_state == OrdinaryState.RISK_ON
        result = s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert result == OrdinaryState.RISK_OFF  # downgrade_bars=1: confirms same bar

    def test_downgrade_with_downgrade_bars_greater_than_one_requires_confirmation(self):
        s = OrdinaryHysteresisState()
        s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=2), hard_veto_active=False)
        result = s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=2), hard_veto_active=False)
        assert result == OrdinaryState.RISK_ON  # not yet confirmed (1 of 2 bars)
        result = s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=2), hard_veto_active=False)
        assert result == OrdinaryState.RISK_OFF  # confirmed on 2nd bar


class TestAdvanceUpgrade:
    def test_upgrade_requires_exact_consecutive_count(self):
        s = OrdinaryHysteresisState()
        s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert s.confirmed_state == OrdinaryState.RISK_OFF
        for i in range(2):
            result = s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
            assert result == OrdinaryState.RISK_OFF, f"upgraded too early at bar {i+1}"
        result = s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert result == OrdinaryState.RISK_ON

    def test_upgrade_candidate_resets_on_return_to_confirmed(self):
        s = OrdinaryHysteresisState()
        s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert s.pending_count == 1
        s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)  # back to confirmed RISK_OFF
        assert s.pending_count == 0
        assert s.pending_state is None

    def test_multi_step_upgrade_still_requires_full_count_not_skipped(self):
        """RISK_OFF -> RISK_ON (a 2-step jump on ORDINARY_STATE_ORDER) must
        still require the full upgrade_bars count, exactly like a 1-step
        upgrade — jump size doesn't bypass confirmation."""
        s = OrdinaryHysteresisState()
        s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert s.confirmed_state == OrdinaryState.RISK_OFF
        s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert s.confirmed_state == OrdinaryState.RISK_OFF  # still not confirmed
        result = s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert result == OrdinaryState.RISK_ON


class TestHardVetoBypass:
    def test_hard_veto_makes_downgrade_immediate_even_with_multi_bar_downgrade_config(self):
        """§8: 'A hard veto bypasses ordinary downgrade delay' — even a
        downgrade_bars > 1 config must confirm on the SAME bar when a hard
        veto is active.

        Found a real bug in my own first version of this test during
        self-review: it used `_bars(upgrade=3, downgrade=5)`, which
        ConfirmationBars.__post_init__ correctly rejects — downgrade_bars
        may never exceed upgrade_bars (§8's own 'downgrades are at least as
        fast as upgrades' CLOSED invariant, enforced at construction). That
        rejection is CORRECT behavior in the implementation, not a bug to
        route around by loosening the validator — fixed by using a valid
        downgrade_bars=3 (still > 1, so the test still proves the bypass
        skips real multi-bar delay, just without violating the asymmetry
        invariant)."""
        s = OrdinaryHysteresisState()
        s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=3), hard_veto_active=False)
        assert s.confirmed_state == OrdinaryState.RISK_ON
        result = s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=3), hard_veto_active=True)
        assert result == OrdinaryState.RISK_OFF  # immediate despite downgrade_bars=3

    def test_hard_veto_does_not_affect_an_upgrade_move(self):
        """The bypass is specifically for DOWNGRADES — a hard veto active
        during what would otherwise be an upgrade move must not make the
        upgrade immediate too (that would be a completely different,
        unstated behavior)."""
        s = OrdinaryHysteresisState()
        s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        result = s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=True)
        assert result == OrdinaryState.RISK_OFF  # still gated by upgrade_bars, veto irrelevant here

    def test_hard_veto_with_no_actual_downgrade_move_has_no_effect(self):
        """A hard veto active while already at RISK_OFF, or while
        remaining in the same raw state, should not do anything unusual —
        the bypass only matters when there IS a downgrade move to make
        immediate."""
        s = OrdinaryHysteresisState()
        s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        result = s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=True)
        assert result == OrdinaryState.RISK_OFF
        assert s.pending_count == 0


class TestMissingBarDuringConfirmation:
    def test_missing_condition_score_does_not_reset_pending_candidate(self):
        s = OrdinaryHysteresisState()
        s.advance(0.1, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert s.pending_count == 1
        s.advance(None, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert s.pending_count == 1  # unaffected by the missing bar
        s.advance(0.9, _boundaries(), _bars(upgrade=3, downgrade=1), hard_veto_active=False)
        assert s.pending_count == 2


class TestExhaustiveOrderedTransitions:
    def test_all_6_ordered_state_pair_transitions_are_correctly_immediate_or_delayed(self):
        """Same exhaustive discipline established for Direction's 20
        structure-pair transitions (Message[172]) — here there are only 3
        states, giving 3*2=6 ordered (confirmed, raw) pairs, but the same
        directional-bug risk applies: a single inverted comparison in
        'is this an upgrade or downgrade' could silently flip behavior for
        roughly half of all real transitions."""
        bars = _bars(upgrade=3, downgrade=1)
        boundaries = _boundaries()
        score_for_state = {OrdinaryState.RISK_OFF: 0.1, OrdinaryState.NEUTRAL: 0.5, OrdinaryState.RISK_ON: 0.9}

        for confirmed in ORDINARY_STATE_ORDER:
            for raw in ORDINARY_STATE_ORDER:
                if confirmed == raw:
                    continue
                s = OrdinaryHysteresisState()
                s.advance(score_for_state[confirmed], boundaries, bars, hard_veto_active=False)
                assert s.confirmed_state == confirmed

                result = s.advance(score_for_state[raw], boundaries, bars, hard_veto_active=False)
                confirmed_idx = ORDINARY_STATE_ORDER.index(confirmed)
                raw_idx = ORDINARY_STATE_ORDER.index(raw)
                is_upgrade = raw_idx > confirmed_idx

                if is_upgrade:
                    assert result == confirmed, f"{confirmed.name}->{raw.name}: expected upgrade delay, got immediate move"
                else:
                    assert result == raw, f"{confirmed.name}->{raw.name}: expected immediate downgrade, got delay"


class TestDeterministicReplay:
    def test_identical_sequence_produces_identical_final_state(self):
        boundaries = _boundaries()
        bars = _bars(upgrade=3, downgrade=1)
        sequence = [0.9, 0.5, 0.1, 0.9, 0.9, 0.9]
        s1, s2 = OrdinaryHysteresisState(), OrdinaryHysteresisState()
        for v in sequence:
            r1 = s1.advance(v, boundaries, bars, hard_veto_active=False)
            r2 = s2.advance(v, boundaries, bars, hard_veto_active=False)
            assert r1 == r2
        assert s1.confirmed_state == s2.confirmed_state
        assert s1.pending_state == s2.pending_state
        assert s1.pending_count == s2.pending_count
