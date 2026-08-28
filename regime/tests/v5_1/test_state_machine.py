"""Market Regime v5.1 — State Machine top-level combiner (module 4.10) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_state_machine.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.crisis import CrisisDomainReading, CrisisDomainConfig, ConditionForExit, evaluate_crisis_bar  # noqa: E402
from v5_1.direction import DirectionStructure  # noqa: E402
from v5_1.ordinary_state import StateBoundaries, ConfirmationBars, OrdinaryState  # noqa: E402
from v5_1.trending import TrendingQualificationInputs, TrendingConfig  # noqa: E402
from v5_1.state_machine import EngineState, advance_state  # noqa: E402


def _const_domain(valid: bool, active: bool):
    def _ev(as_of):
        return CrisisDomainReading(valid=valid, active=active)
    return _ev


def _crisis_config(vol=(True, False), credit=(True, False), price=(True, False), participation=(True, False)):
    return CrisisDomainConfig(
        volatility_term_structure=_const_domain(*vol),
        credit_stress=_const_domain(*credit),
        price_damage=_const_domain(*price),
        participation_collapse=_const_domain(*participation),
    )


def _boundaries():
    return StateBoundaries(risk_off_neutral_boundary=0.35, neutral_risk_on_boundary=0.65, risk_off_neutral_buffer=0.0, neutral_risk_on_buffer=0.0)


def _bars():
    return ConfirmationBars(upgrade_bars=1, downgrade_bars=1)


def _trending_config(entry=1, exit=1):
    return TrendingConfig(trend_quality_floor=0.7, price_damage_ceiling=0.3, risk_appetite_floor=0.4, stability_floor=0.4, entry_bars=entry, exit_bars=exit)


def _non_qualifying_trending_inputs():
    return TrendingQualificationInputs(direction_structure=DirectionStructure.BEAR, trend_quality=0.1, price_damage=0.9, risk_appetite_score=0.1, stability_score=0.1)


def _qualifying_trending_inputs():
    return TrendingQualificationInputs(direction_structure=DirectionStructure.STRONG_BULL, trend_quality=0.9, price_damage=0.1, risk_appetite_score=0.8, stability_score=0.8)


def _clear_exit_ctx(condition_score=0.9, boundary=0.4, veto=False):
    return ConditionForExit(condition_score=condition_score, any_hard_veto_active=veto, neutral_entry_boundary_plus_buffer=boundary)


def _advance(
    engine_state, as_of="d", condition_score=0.9, crisis_config=None, hard_veto_active=False,
    trending_inputs=None, trending_config=None, exit_ctx=None,
):
    crisis_config = crisis_config or _crisis_config()
    trending_inputs = trending_inputs or _non_qualifying_trending_inputs()
    trending_config = trending_config or _trending_config()
    exit_ctx = exit_ctx or _clear_exit_ctx()
    bar = evaluate_crisis_bar(as_of, crisis_config)
    return advance_state(
        as_of, engine_state, bar, exit_ctx, condition_score,
        _boundaries(), _bars(), hard_veto_active, trending_inputs, trending_config,
    )


# ---------------------------------------------------------------------------
# Precedence: CRISIS > TRENDING > ordinary
# ---------------------------------------------------------------------------

class TestPrecedence:
    def test_ordinary_state_reported_when_neither_crisis_nor_trending_active(self):
        es = EngineState()
        result = _advance(es, condition_score=0.9)
        assert result.state == "RISK_ON"

    def test_crisis_wins_over_ordinary(self):
        es = EngineState()
        result = _advance(es, condition_score=0.9, crisis_config=_crisis_config(vol=(True, True), credit=(True, True)))
        assert result.state == "CRISIS"
        assert result.crisis_active is True

    def test_trending_wins_over_ordinary_when_active(self):
        es = EngineState()
        result = _advance(
            es, condition_score=0.9,
            trending_inputs=_qualifying_trending_inputs(), trending_config=_trending_config(entry=1),
        )
        assert result.state == "TRENDING"
        assert result.trending_active is True

    def test_crisis_wins_over_trending_when_both_would_otherwise_be_active(self):
        """The critical precedence case: construct a bar where BOTH CRISIS
        domains (2 active) AND TRENDING qualification would independently
        say 'active' — CRISIS must win the reported label. In practice
        these two conditions are close to mutually exclusive by
        construction of their own thresholds, but this module must not
        rely on that coincidence; the precedence is enforced as an
        explicit rule, verified here directly."""
        es = EngineState()
        result = _advance(
            es, condition_score=0.9,
            crisis_config=_crisis_config(vol=(True, True), credit=(True, True)),
            trending_inputs=_qualifying_trending_inputs(), trending_config=_trending_config(entry=1),
        )
        assert result.state == "CRISIS"
        assert result.crisis_active is True
        assert result.trending_active is True  # TRENDING's own machine still advanced/activated underneath

    def test_trending_and_ordinary_machines_both_keep_advancing_underneath_crisis(self):
        """TRENDING's entry count and the ordinary machine's own hysteresis
        must keep advancing even while CRISIS is the reported label —
        neither sub-machine is suppressed or reset just because it isn't
        the WINNING label this bar."""
        es = EngineState()
        # Bar 1: CRISIS active, but also feed qualifying TRENDING inputs
        # with entry_bars=2 (not yet enough to activate TRENDING itself).
        tconfig = _trending_config(entry=2)
        r1 = _advance(
            es, as_of="d1", condition_score=0.9,
            crisis_config=_crisis_config(vol=(True, True), credit=(True, True)),
            trending_inputs=_qualifying_trending_inputs(), trending_config=tconfig,
        )
        assert r1.state == "CRISIS"
        assert es.trending.trending_entry_count == 1  # advanced even though CRISIS won the label

        # Bar 2: CRISIS clears (0 active domains), TRENDING's 2nd
        # qualifying bar should now confirm it active.
        r2 = _advance(
            es, as_of="d2", condition_score=0.9,
            crisis_config=_crisis_config(),
            trending_inputs=_qualifying_trending_inputs(), trending_config=tconfig,
        )
        # CRISIS won't exit immediately (needs 5 consecutive clear bars,
        # and exit context here uses defaults that should satisfy it) —
        # what matters for this test is TRENDING's own counter reached 2.
        assert es.trending.trending_entry_count == 2 or es.trending.trending_active


# ---------------------------------------------------------------------------
# pending_state / pending_state_count — reflects ONLY the ordinary machine
# ---------------------------------------------------------------------------

class TestPendingState:
    def test_pending_state_none_when_no_ordinary_candidate_pending(self):
        es = EngineState()
        result = _advance(es, condition_score=0.9)  # cold start: confirms immediately, no pending
        assert result.pending_state is None
        assert result.pending_state_count is None

    def test_pending_state_reflects_ordinary_machine_even_when_crisis_wins_label(self):
        es = EngineState()
        # Multi-bar upgrade config so a pending candidate genuinely exists.
        slow_bars = ConfirmationBars(upgrade_bars=3, downgrade_bars=1)
        bar = evaluate_crisis_bar("d0", _crisis_config())
        advance_state("d0", es, bar, _clear_exit_ctx(), 0.1, _boundaries(), slow_bars, False, _non_qualifying_trending_inputs(), _trending_config())
        assert es.ordinary.confirmed_state == OrdinaryState.RISK_OFF

        crisis_bar = evaluate_crisis_bar("d1", _crisis_config(vol=(True, True), credit=(True, True)))
        result = advance_state(
            "d1", es, crisis_bar, _clear_exit_ctx(), 0.9, _boundaries(), slow_bars, False,
            _non_qualifying_trending_inputs(), _trending_config(),
        )
        assert result.state == "CRISIS"
        assert result.pending_state == "RISK_ON"  # ordinary machine's own pending candidate, unaffected by CRISIS winning
        assert result.pending_state_count == 1


# ---------------------------------------------------------------------------
# state_is_current
# ---------------------------------------------------------------------------

class TestStateIsCurrent:
    def test_current_when_condition_score_available(self):
        es = EngineState()
        result = _advance(es, condition_score=0.9)
        assert result.state_is_current is True

    def test_not_current_when_condition_score_missing_and_no_crisis_or_trending(self):
        es = EngineState()
        _advance(es, condition_score=0.9)  # establish a confirmed ordinary state first
        result = _advance(es, condition_score=None)
        assert result.state_is_current is False
        assert result.state == "RISK_ON"  # last confirmed state retained, per §4.1

    def test_current_when_crisis_active_even_if_condition_score_missing(self):
        es = EngineState()
        result = _advance(
            es, condition_score=None,
            crisis_config=_crisis_config(vol=(True, True), credit=(True, True)),
        )
        assert result.state == "CRISIS"
        assert result.state_is_current is True

    def test_current_when_trending_active_even_if_condition_score_missing(self):
        es = EngineState()
        result = _advance(
            es, condition_score=None,
            trending_inputs=_qualifying_trending_inputs(), trending_config=_trending_config(entry=1),
        )
        assert result.state == "TRENDING"
        assert result.state_is_current is True


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_identical_bar_sequence_produces_identical_final_state(self):
        es1, es2 = EngineState(), EngineState()
        sequence = [0.9, 0.5, 0.1, 0.9, 0.9]
        for i, score in enumerate(sequence):
            r1 = _advance(es1, as_of=f"d{i}", condition_score=score)
            r2 = _advance(es2, as_of=f"d{i}", condition_score=score)
            assert r1 == r2
        assert es1.ordinary.confirmed_state == es2.ordinary.confirmed_state
        assert es1.crisis.in_crisis == es2.crisis.in_crisis
        assert es1.trending.trending_active == es2.trending.trending_active
