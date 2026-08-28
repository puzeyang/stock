"""Market Regime v5.1 — TRENDING (part of module 4.10) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_trending.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.direction import DirectionStructure  # noqa: E402
from v5_1.trending import (  # noqa: E402
    TrendingQualificationInputs,
    TrendingConfig,
    TrendingState,
    qualifies,
)


def _config(tq_floor=0.7, dmg_ceiling=0.3, ra_floor=0.4, stab_floor=0.4, entry=3, exit=3):
    return TrendingConfig(
        trend_quality_floor=tq_floor,
        price_damage_ceiling=dmg_ceiling,
        risk_appetite_floor=ra_floor,
        stability_floor=stab_floor,
        entry_bars=entry,
        exit_bars=exit,
    )


def _qualifying_inputs(structure=DirectionStructure.STRONG_BULL):
    return TrendingQualificationInputs(
        direction_structure=structure,
        trend_quality=0.9,
        price_damage=0.1,
        risk_appetite_score=0.8,
        stability_score=0.8,
    )


# ---------------------------------------------------------------------------
# TrendingConfig validation
# ---------------------------------------------------------------------------

class TestTrendingConfigValidation:
    def test_valid_config_constructs(self):
        _config()

    def test_zero_or_negative_entry_bars_rejected(self):
        with pytest.raises(ValueError, match=">= 1"):
            _config(entry=0)

    def test_zero_or_negative_exit_bars_rejected(self):
        with pytest.raises(ValueError, match=">= 1"):
            _config(exit=-1)


# ---------------------------------------------------------------------------
# qualifies() — per-bar predicate
# ---------------------------------------------------------------------------

class TestQualifies:
    def test_all_gates_pass_qualifies(self):
        assert qualifies(_qualifying_inputs(), _config()) is True

    def test_bearish_structure_never_qualifies(self):
        for structure in (DirectionStructure.DAMAGED_BULL, DirectionStructure.BEAR):
            inputs = _qualifying_inputs(structure=structure)
            assert qualifies(inputs, _config()) is False

    def test_bull_pullback_is_bullish_and_can_qualify(self):
        """DIRECTION_SIGN[BULL_PULLBACK] == 1 (bullish) per Direction's own
        CLOSED sign table — BULL_PULLBACK must be eligible for TRENDING
        qualification on the direction-structure gate alone (subject to
        the other gates still passing), not excluded just because it is
        not STRONG_BULL/BULL."""
        inputs = _qualifying_inputs(structure=DirectionStructure.BULL_PULLBACK)
        assert qualifies(inputs, _config()) is True

    def test_low_trend_quality_fails(self):
        inputs = TrendingQualificationInputs(
            direction_structure=DirectionStructure.STRONG_BULL,
            trend_quality=0.5,  # below default floor 0.7
            price_damage=0.1, risk_appetite_score=0.8, stability_score=0.8,
        )
        assert qualifies(inputs, _config()) is False

    def test_trend_quality_exactly_at_floor_qualifies(self):
        inputs = TrendingQualificationInputs(
            direction_structure=DirectionStructure.STRONG_BULL,
            trend_quality=0.7, price_damage=0.1, risk_appetite_score=0.8, stability_score=0.8,
        )
        assert qualifies(inputs, _config(tq_floor=0.7)) is True

    def test_price_damage_above_ceiling_fails(self):
        inputs = TrendingQualificationInputs(
            direction_structure=DirectionStructure.STRONG_BULL,
            trend_quality=0.9, price_damage=0.5, risk_appetite_score=0.8, stability_score=0.8,
        )
        assert qualifies(inputs, _config(dmg_ceiling=0.3)) is False

    def test_price_damage_exactly_at_ceiling_qualifies(self):
        """price_damage is adverse-positive (higher = more damage), so the
        ceiling comparison must be inclusive at the exact boundary — 'at or
        below' shallow, not strictly below."""
        inputs = TrendingQualificationInputs(
            direction_structure=DirectionStructure.STRONG_BULL,
            trend_quality=0.9, price_damage=0.3, risk_appetite_score=0.8, stability_score=0.8,
        )
        assert qualifies(inputs, _config(dmg_ceiling=0.3)) is True

    def test_risk_appetite_below_floor_fails(self):
        inputs = TrendingQualificationInputs(
            direction_structure=DirectionStructure.STRONG_BULL,
            trend_quality=0.9, price_damage=0.1, risk_appetite_score=0.2, stability_score=0.8,
        )
        assert qualifies(inputs, _config(ra_floor=0.4)) is False

    def test_stability_below_floor_fails(self):
        inputs = TrendingQualificationInputs(
            direction_structure=DirectionStructure.STRONG_BULL,
            trend_quality=0.9, price_damage=0.1, risk_appetite_score=0.8, stability_score=0.1,
        )
        assert qualifies(inputs, _config(stab_floor=0.4)) is False

    def test_any_missing_input_fails_closed(self):
        base = dict(direction_structure=DirectionStructure.STRONG_BULL, trend_quality=0.9, price_damage=0.1, risk_appetite_score=0.8, stability_score=0.8)
        for key in base:
            kwargs = dict(base)
            kwargs[key] = None
            inputs = TrendingQualificationInputs(**kwargs)
            assert qualifies(inputs, _config()) is False, f"expected fail-closed when {key} is None"


# ---------------------------------------------------------------------------
# TrendingState.advance — entry/exit persistence
# ---------------------------------------------------------------------------

class TestTrendingEntry:
    def test_starts_inactive_never_seeded(self):
        s = TrendingState()
        assert s.trending_active is False
        assert s.trending_entry_count == 0

    def test_single_qualifying_bar_does_not_immediately_enter(self):
        """Unlike CRISIS's immediate entry, TRENDING requires
        config.entry_bars CONSECUTIVE qualifying bars — a single bar must
        not activate it."""
        s = TrendingState()
        result = s.advance(True, _config(entry=3))
        assert result is False

    def test_entry_confirms_after_exact_consecutive_count(self):
        s = TrendingState()
        config = _config(entry=3)
        for i in range(2):
            result = s.advance(True, config)
            assert result is False, f"entered too early at bar {i+1}"
        result = s.advance(True, config)
        assert result is True

    def test_entry_count_resets_on_a_single_non_qualifying_bar(self):
        s = TrendingState()
        config = _config(entry=3)
        s.advance(True, config)
        s.advance(True, config)
        assert s.trending_entry_count == 2
        s.advance(False, config)  # breaks the streak
        assert s.trending_entry_count == 0
        assert s.trending_active is False


class TestTrendingExit:
    def _active_state(self, config) -> TrendingState:
        s = TrendingState()
        for _ in range(config.entry_bars):
            s.advance(True, config)
        assert s.trending_active is True
        return s

    def test_single_non_qualifying_bar_does_not_immediately_exit(self):
        config = _config(exit=3)
        s = self._active_state(config)
        result = s.advance(False, config)
        assert result is True

    def test_exit_confirms_after_exact_consecutive_count(self):
        config = _config(exit=3)
        s = self._active_state(config)
        for i in range(2):
            result = s.advance(False, config)
            assert result is True, f"exited too early at bar {i+1}"
        result = s.advance(False, config)
        assert result is False

    def test_exit_count_resets_on_renewed_qualification(self):
        """Mirrors CRISIS's own 'renewed confirmation resets the count'
        principle, applied to TRENDING's exit side."""
        config = _config(exit=3)
        s = self._active_state(config)
        s.advance(False, config)
        s.advance(False, config)
        assert s.trending_exit_count == 2
        s.advance(True, config)  # renewed qualification
        assert s.trending_exit_count == 0
        assert s.trending_active is True

    def test_after_exit_re_entry_requires_full_entry_count_again(self):
        config = _config(entry=3, exit=2)
        s = self._active_state(config)
        s.advance(False, config)
        s.advance(False, config)
        assert s.trending_active is False
        assert s.trending_entry_count == 0

        s.advance(True, config)
        s.advance(True, config)
        assert s.trending_active is False  # still needs a 3rd bar
        s.advance(True, config)
        assert s.trending_active is True


class TestDeterministicReplay:
    def test_identical_sequence_produces_identical_final_state(self):
        config = _config(entry=2, exit=2)
        sequence = [True, True, False, True, True, False, False]
        s1, s2 = TrendingState(), TrendingState()
        for v in sequence:
            r1 = s1.advance(v, config)
            r2 = s2.advance(v, config)
            assert r1 == r2
        assert s1.trending_active == s2.trending_active
        assert s1.trending_entry_count == s2.trending_entry_count
        assert s1.trending_exit_count == s2.trending_exit_count
