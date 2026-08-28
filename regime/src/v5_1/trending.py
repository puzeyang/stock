"""Market Regime v5.1 — Slice 8c: TRENDING (part of module 4.10).

Design §10 (C2): TRENDING is the fifth exclusive state — "not a badge,
entry signal, or leverage mechanism." Qualification requires ALL of:

- a bullish `direction_structure` (module 4.3);
- sufficiently high TrendQuality (module 4.4);
- shallow canonical `price_damage` (module 4.7's shared canonical feature);
- Risk Appetite and Stability veto floors (both pillars must clear their
  own EMPIRICAL floor — this is separate from Condition's own hard vetoes,
  a TRENDING-specific additional qualification gate per §10's own wording);
- persistent state rules (an entry/exit hysteresis, like ordinary states
  and CRISIS, not an instantaneous flip).

When active: `state = TRENDING`, `condition_score <= 1.0` always (no
special TRENDING scaling), and — critically — **no leverage bonus is
added**. This module computes ONLY `trending_active`/counters; it never
touches `condition_score` itself (module 4.8 already finalized that value
before this module runs, per the plan's dependency order — TRENDING is a
STATE label, not a Condition modifier).

The inherited `74.3` threshold (v4.4's own retained TrendQuality bar for
its no-longer-existent TRENDING-equivalent concept) is explicitly NOT
retained by rescaling anywhere in this module — the design says so
verbatim ("The inherited `74.3` threshold is not retained by rescaling").
No numeric default here is derived from it.

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`,
module 4.10 subset relevant to TRENDING): `trending_active`,
`trending_entry_count`, `trending_exit_count`.

**EMPIRICAL scope (§17.13):** qualification thresholds (TrendQuality floor,
price_damage ceiling, Risk Appetite floor, Stability floor), and the
entry/exit persistence bar counts, are all EMPIRICAL — injected
configuration, never hardcoded, and specifically never the inherited 74.3.
"""
from __future__ import annotations

from dataclasses import dataclass

from .direction import DirectionStructure, DIRECTION_SIGN


@dataclass(frozen=True)
class TrendingQualificationInputs:
    """One bar's raw facts needed to evaluate TRENDING qualification. Any
    None value means that input is itself unavailable this bar — handled
    explicitly by `qualifies()` as "does not qualify" (fail-closed: TRENDING
    can never qualify from a genuinely missing input, the same C16
    discipline as everywhere else in this engine)."""

    direction_structure: DirectionStructure | None
    trend_quality: float | None
    price_damage: float | None
    risk_appetite_score: float | None
    stability_score: float | None


@dataclass(frozen=True)
class TrendingConfig:
    """EMPIRICAL (§17.13) — injected. `trend_quality_floor`: minimum
    sufficiently-high TrendQuality (on [0,1], matching TrendQuality's own
    manifest-boundary rescale, per Message[177]). `price_damage_ceiling`:
    maximum shallow price_damage (price_damage is adverse-positive per
    Stability's own convention — HIGHER means MORE damage — so
    qualification requires price_damage to be AT OR BELOW this ceiling,
    never above). `risk_appetite_floor`/`stability_floor`: minimum
    Risk-Appetite/Stability pillar scores TRENDING additionally requires,
    separate from Condition's own hard vetoes. `entry_bars`/`exit_bars`:
    persistence confirmation counts (§10's "persistent state rules") —
    intentionally independent of ordinary hysteresis's ConfirmationBars
    and CRISIS's fixed 5-bar exit, since TRENDING's own persistence
    requirement is a distinct EMPIRICAL decision (§17.13), not required to
    match either of the other two state machines' counts.
    """

    trend_quality_floor: float
    price_damage_ceiling: float
    risk_appetite_floor: float
    stability_floor: float
    entry_bars: int
    exit_bars: int

    def __post_init__(self) -> None:
        if self.entry_bars < 1 or self.exit_bars < 1:
            raise ValueError("TrendingConfig: entry_bars and exit_bars must both be >= 1")


def qualifies(inputs: TrendingQualificationInputs, config: TrendingConfig) -> bool:
    """Whether this single bar's raw facts satisfy every TRENDING
    qualification gate (§10) — a pure per-bar predicate, independent of
    any persisted entry/exit state (persistence is applied separately by
    `TrendingState.advance()`, mirroring CRISIS's own bar-eval/state-
    advance split in `crisis.py`).

    "Bullish direction_structure" is evaluated via DIRECTION_SIGN's CLOSED
    sign mapping (design §6.1) rather than a hardcoded structure-name
    comparison — DIRECTION_SIGN[structure] == 1 for STRONG_BULL/BULL/
    BULL_PULLBACK, matching "bullish" in the same sense Direction's own
    sign field already defines it, so this module does not invent a
    second, potentially inconsistent notion of "bullish."
    """
    if inputs.direction_structure is None or inputs.trend_quality is None:
        return False
    if inputs.price_damage is None or inputs.risk_appetite_score is None or inputs.stability_score is None:
        return False

    is_bullish = DIRECTION_SIGN[inputs.direction_structure] == 1
    if not is_bullish:
        return False
    if inputs.trend_quality < config.trend_quality_floor:
        return False
    if inputs.price_damage > config.price_damage_ceiling:
        return False
    if inputs.risk_appetite_score < config.risk_appetite_floor:
        return False
    if inputs.stability_score < config.stability_floor:
        return False
    return True


@dataclass
class TrendingState:
    """Mutable persisted TRENDING state (design §4.3's "TRENDING active
    flag and counters"). `trending_active` starts False — never seeded
    into TRENDING at cold start, same discipline as every other state
    machine in this engine."""

    trending_active: bool = False
    trending_entry_count: int = 0
    trending_exit_count: int = 0

    def advance(self, bar_qualifies: bool, config: TrendingConfig) -> bool:
        """Advance TRENDING persistence by one bar. Returns the resulting
        `trending_active`. `config` is supplied fresh each call — same
        pattern as OrdinaryHysteresisState.advance's boundaries/
        confirmation_bars parameters — since TrendingConfig is caller-owned
        EMPIRICAL configuration, not part of TRENDING's own persisted state
        (design §4.3's persisted-state list is "TRENDING active flag and
        counters" only).

        Entry: `config.entry_bars` CONSECUTIVE qualifying bars are required
        before TRENDING activates — a single qualifying bar does not
        immediately enter TRENDING (unlike CRISIS's immediate 2-of-4
        entry; §10 explicitly calls for "persistent state rules," not an
        instantaneous flip, distinguishing TRENDING's entry from CRISIS's).
        A single NON-qualifying bar resets the entry count to zero (must
        be consecutive).

        Exit: once active, `config.exit_bars` CONSECUTIVE NON-qualifying
        bars are required before TRENDING deactivates — symmetric
        consecutive-bar discipline to entry, using its own independently
        configured `exit_bars`. A single qualifying bar while counting
        toward exit resets the exit count to zero (renewed qualification
        cancels a pending exit, mirroring CRISIS's own "renewed
        confirmation resets the count" principle applied to TRENDING's
        exit side).
        """
        if not self.trending_active:
            if bar_qualifies:
                self.trending_entry_count += 1
            else:
                self.trending_entry_count = 0
            if self.trending_entry_count >= config.entry_bars:
                self.trending_active = True
                self.trending_entry_count = 0
                self.trending_exit_count = 0
            return self.trending_active

        # Currently active: track consecutive NON-qualifying bars toward exit.
        if not bar_qualifies:
            self.trending_exit_count += 1
        else:
            self.trending_exit_count = 0
        if self.trending_exit_count >= config.exit_bars:
            self.trending_active = False
            self.trending_exit_count = 0
            self.trending_entry_count = 0
        return self.trending_active
