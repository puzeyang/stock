"""Market Regime v5.1 — Slice 8d: State Machine top-level combiner (module 4.10).

Combines the three independently-built sub-machines (`crisis.py`,
`ordinary_state.py`, `trending.py`) into ONE exclusive `state` output per
design §8's "Exactly one state is emitted" (C2). Each sub-machine already
advances its own persisted state independently in this module's `advance()`
— this file's only job is picking exactly one label from among their three
outputs and assembling the `state`/`pending_state`/`pending_state_count`
triple.

**Precedence, made explicit rather than silently assumed** (the design
doc never states a combiner precedence order verbatim, since §8/§9/§10 are
each written as if their own state were the only one that mattered — this
is a genuine synthesis this module must get right, not something copied
from one design section):

1. **CRISIS wins over everything.** §9.2: CRISIS entry is immediate and
   "without ordinary downgrade delay" — it is explicitly a safety circuit
   that supersedes the ordinary hysteresis machine's own pace. Nothing in
   §10 suggests TRENDING can coexist with or override CRISIS either (a
   "persistent unusually clean bull trend," by definition, cannot be
   simultaneously an "acute multi-domain stress" episode — the two
   qualification sets are practically disjoint, but precedence is still
   made a hard rule here rather than left to be an accident of how the
   injected EMPIRICAL thresholds happen to be tuned).
2. **TRENDING wins over ordinary hysteresis, when active and not in
   CRISIS.** §10 describes TRENDING as "the fifth exclusive state," which
   only makes sense if, once TRENDING's own persistence rules confirm it
   active, it is REPORTED instead of whatever the ordinary machine
   independently computed for the same bar (both machines run
   independently underneath — TRENDING does not suppress or reset the
   ordinary machine's own hysteresis bookkeeping, it only wins the label).
3. **Otherwise, the ordinary hysteresis machine's confirmed state is
   reported** (RISK_OFF / NEUTRAL / RISK_ON).

`pending_state`/`pending_state_count` (design §4.3's persisted fields)
report the ORDINARY machine's own pending candidate — CRISIS and TRENDING
each have their own separately-published counters (`crisis_exit_count`;
`trending_entry_count`/`trending_exit_count`) per their own manifest
fields, so `pending_state` is specifically the ordinary-hysteresis
dead-band candidate, not a fourth combined concept.

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`,
the remaining module 4.10 fields not already covered by the three
sub-machine files): `state`, `pending_state`, `pending_state_count`,
`state_is_current`, `reason_codes` (as they relate to state availability).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .crisis import CrisisBarEvaluation, CrisisState, ConditionForExit
from .ordinary_state import OrdinaryHysteresisState, OrdinaryState, StateBoundaries, ConfirmationBars
from .trending import TrendingState, TrendingQualificationInputs, TrendingConfig, qualifies as trending_qualifies


_ORDINARY_STATE_LABELS = {
    OrdinaryState.RISK_OFF: "RISK_OFF",
    OrdinaryState.NEUTRAL: "NEUTRAL",
    OrdinaryState.RISK_ON: "RISK_ON",
}


@dataclass
class EngineState:
    """Bundles the STATE-MACHINE portion of design §4.3's persisted-state
    record (CRISIS exit count, ordinary hysteresis pending state/count,
    TRENDING active flag/counters) — three sub-machines' mutable state.

    **Naming caveat found during an independent senior-dev review
    (2026-08-27)**: despite the name, this class does NOT contain
    Direction's own persisted state (`confirmed_structure`,
    `pending_upgrade`, `pending_count`), which §4.3 lists as part of the
    SAME persisted record. That state lives on `direction.py`'s
    `DirectionConfirmationState`, tracked as a SIBLING field on
    `engine.py`'s `RunningEngineState`, not inside this class. Nothing is
    lost or mishandled by this split (both objects really do get
    persisted/restored together by any caller that keeps both), but a
    reader expecting `EngineState` alone to be the complete `§4.3`/
    `ENGINE_STATE_V5_1` record, as this docstring previously implied,
    would be wrong — the complete record is `RunningEngineState`
    (`engine.py`), which bundles both.

    Every sub-state starts at its own documented cold-start default (never
    seeded into any non-neutral state) — this dataclass does not add a
    second seeding point; it only aggregates the three sub-machines, each
    of which already enforces its own cold-start discipline.
    """

    crisis: CrisisState = field(default_factory=CrisisState)
    ordinary: OrdinaryHysteresisState = field(default_factory=OrdinaryHysteresisState)
    trending: TrendingState = field(default_factory=TrendingState)


@dataclass(frozen=True)
class StateResult:
    as_of: str
    state: str | None
    pending_state: str | None
    pending_state_count: int | None
    state_is_current: bool
    crisis_active: bool
    trending_active: bool
    ordinary_state: OrdinaryState | None


def advance_state(
    as_of: str,
    engine_state: EngineState,
    crisis_bar: CrisisBarEvaluation,
    crisis_exit_ctx: ConditionForExit,
    condition_score: float | None,
    ordinary_boundaries: StateBoundaries,
    ordinary_confirmation_bars: ConfirmationBars,
    hard_veto_active: bool,
    trending_inputs: TrendingQualificationInputs,
    trending_config: TrendingConfig,
) -> StateResult:
    """Advance all three sub-machines by exactly one bar (each is advanced
    unconditionally, regardless of which one ends up winning the label —
    per this module's own docstring, TRENDING and ordinary hysteresis both
    keep running underneath even when CRISIS is the reported state, so
    that a CRISIS exit doesn't require artificially replaying bars the
    other two machines silently skipped), then resolve exactly one
    `state` label per the precedence documented in this module's
    docstring.

    `state_is_current` is True whenever this bar produced a real,
    non-degenerate resolution (i.e., `condition_score` was available OR
    CRISIS/TRENDING resolution did not itself depend on the missing
    value) — see the field-level logic below; §4.1 permits retaining the
    last categorical state with `state_is_current = False` when data is
    genuinely missing, rather than emitting no state at all, so this
    function still returns the RESOLVED label from whichever sub-machine
    last had valid input, with `state_is_current` flagging staleness
    rather than nulling `state` itself.
    """
    engine_state.crisis.advance(crisis_bar, crisis_exit_ctx)
    ordinary_result = engine_state.ordinary.advance(
        condition_score, ordinary_boundaries, ordinary_confirmation_bars, hard_veto_active
    )
    trending_bar_qualifies = trending_qualifies(trending_inputs, trending_config)
    engine_state.trending.advance(trending_bar_qualifies, trending_config)

    crisis_active = engine_state.crisis.in_crisis
    trending_active = engine_state.trending.trending_active

    if crisis_active:
        state_label = "CRISIS"
    elif trending_active:
        state_label = "TRENDING"
    elif ordinary_result is not None:
        state_label = _ORDINARY_STATE_LABELS[ordinary_result]
    else:
        state_label = None

    # state_is_current: False specifically when the CURRENT bar's own
    # condition_score was unavailable AND neither CRISIS nor TRENDING is
    # active (i.e., the reported label is purely a carried-over ordinary
    # state, per §4.1's "last categorical state may be retained only with
    # state_is_current=false"). If CRISIS or TRENDING IS active, their own
    # bar evaluation is what determined that (not condition_score), so the
    # state is genuinely current even if condition_score itself happened
    # to be unavailable this same bar.
    state_is_current = crisis_active or trending_active or condition_score is not None

    pending_state_label = (
        _ORDINARY_STATE_LABELS[engine_state.ordinary.pending_state]
        if engine_state.ordinary.pending_state is not None
        else None
    )
    pending_state_count = engine_state.ordinary.pending_count if engine_state.ordinary.pending_state is not None else None

    return StateResult(
        as_of=as_of,
        state=state_label,
        pending_state=pending_state_label,
        pending_state_count=pending_state_count,
        state_is_current=state_is_current,
        crisis_active=crisis_active,
        trending_active=trending_active,
        ordinary_state=ordinary_result,
    )
