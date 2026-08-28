"""Market Regime v5.1 — Slice 3: Direction (module 4.3).

Design §6.1-6.2 (C4, C5): a deterministic, exhaustive, first-match structure
partition over the pinned benchmark, plus asymmetric confirmation logic
(immediate downgrade to a less-supportive structure, consecutive-bar
confirmation required to upgrade to a more-supportive one).

**Legacy cold-start defect, confirmed against real code (design §6.2's
"known STRONG_BULL cold-start defect"):** `research/technical-analysis/
ta_backtest/market.py:36` initializes `confirmed_ts = 1`, where `1` is the
numeric code for STRONG_BULL (the MOST supportive structure) — i.e. the
legacy implementation silently seeds the confirmed state to the single most
bullish possible classification before a single real bar has ever been
observed, which is exactly the "never seed a semantic constant" violation
§6.2 names. This module's `DirectionConfirmationState` starts with
`confirmed_structure = None` (unavailable) and initializes from the FIRST
real valid raw classification only — never a hardcoded structure.

EMPIRICAL scope: horizons (21/65/200), base scores (0.90/0.80/0.78/0.55/0.15),
and confirmation bar count(s) are all EMPIRICAL (§17.1, §17.2) — injected
parameters here, never hardcoded defaults. This module does not choose them;
the v4.4 values referenced above are cited only to describe the confirmed
legacy bug, not adopted as this module's defaults.

**Gap closed per Message[177]**: `compute_direction_result()` assembles the
final owned fields of module 4.3 — `direction_structure` (the confirmed
structure), `direction_sign` (CLOSED lookup via `DIRECTION_SIGN`), and
`direction_score` (EMPIRICAL: the confirmed structure's base score passed
through an injected `DirectionAdjustment` coefficient together with the
current bar's TrendQuality value, per design §6.3's "Direction adjustment
coefficient... EMPIRICAL"). No specific adjustment formula is embedded here
— same injected-interface pattern as every other EMPIRICAL seam in this
engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol


class DirectionStructure(IntEnum):
    """The five mutually exclusive structures, ordered most to least
    supportive (design §6.1's partial order) — the ordering itself is what
    "more/less supportive" means for §6.2's confirmation asymmetry."""

    STRONG_BULL = 5
    BULL = 4
    BULL_PULLBACK = 3
    DAMAGED_BULL = 2
    BEAR = 1


# Design §6.1: "STRONG_BULL > BULL >= BULL_PULLBACK > DAMAGED_BULL > BEAR".
# BULL and BULL_PULLBACK are explicitly allowed to tie in base score (while
# remaining distinct structures) — enforced at DirectionScoreConfig
# construction time, not here (this ordering is about supportiveness/
# confirmation-direction, not the score values themselves).
STRUCTURE_ORDER = (
    DirectionStructure.STRONG_BULL,
    DirectionStructure.BULL,
    DirectionStructure.BULL_PULLBACK,
    DirectionStructure.DAMAGED_BULL,
    DirectionStructure.BEAR,
)

DIRECTION_SIGN = {
    DirectionStructure.STRONG_BULL: 1,
    DirectionStructure.BULL: 1,
    DirectionStructure.BULL_PULLBACK: 1,
    DirectionStructure.DAMAGED_BULL: 0,
    DirectionStructure.BEAR: -1,
}


@dataclass(frozen=True)
class DirectionHorizons:
    """EMPIRICAL (§17.1) — injected, never hardcoded. Field names match the
    design's own EMA21/SMA65/SMA200 roles without asserting those exact
    windows are correct; a caller supplies real values."""

    ema_fast: int
    sma_mid: int
    sma_long: int

    def __post_init__(self) -> None:
        for name, val in (("ema_fast", self.ema_fast), ("sma_mid", self.sma_mid), ("sma_long", self.sma_long)):
            if val <= 0:
                raise ValueError(f"DirectionHorizons.{name} must be positive, got {val}")


@dataclass(frozen=True)
class DirectionBaseScores:
    """EMPIRICAL (§17.1) — injected. Enforces design §6.1's exact partial
    order at construction time: STRONG_BULL > BULL >= BULL_PULLBACK >
    DAMAGED_BULL > BEAR, with equality permitted ONLY between BULL and
    BULL_PULLBACK."""

    strong_bull: float
    bull: float
    bull_pullback: float
    damaged_bull: float
    bear: float

    def __post_init__(self) -> None:
        if not (self.strong_bull > self.bull):
            raise ValueError(f"STRONG_BULL score ({self.strong_bull}) must be strictly greater than BULL ({self.bull})")
        if not (self.bull >= self.bull_pullback):
            raise ValueError(f"BULL score ({self.bull}) must be >= BULL_PULLBACK ({self.bull_pullback})")
        if not (self.bull_pullback > self.damaged_bull):
            raise ValueError(f"BULL_PULLBACK score ({self.bull_pullback}) must be strictly greater than DAMAGED_BULL ({self.damaged_bull})")
        if not (self.damaged_bull > self.bear):
            raise ValueError(f"DAMAGED_BULL score ({self.damaged_bull}) must be strictly greater than BEAR ({self.bear})")

    def score_for(self, structure: DirectionStructure) -> float:
        return {
            DirectionStructure.STRONG_BULL: self.strong_bull,
            DirectionStructure.BULL: self.bull,
            DirectionStructure.BULL_PULLBACK: self.bull_pullback,
            DirectionStructure.DAMAGED_BULL: self.damaged_bull,
            DirectionStructure.BEAR: self.bear,
        }[structure]


@dataclass(frozen=True)
class DirectionInputs:
    """One bar's inputs to the structure classifier — pre-computed EMA21/
    SMA65/SMA200 values plus the benchmark close, all as-of the same date.
    None for any field means that moving average is not yet warmed/valid,
    which makes classification unavailable for this bar (fail-closed)."""

    close: float | None
    ema_fast: float | None
    sma_mid: float | None
    sma_long: float | None


def classify_structure(inputs: DirectionInputs) -> DirectionStructure | None:
    """Deterministic, exhaustive, first-match classification per design
    §6.1's exact table. Returns None if any required input is unavailable
    (fail-closed per design §4.1 — never guesses a structure from partial
    data).

    Evaluated in exactly this order (STRONG_BULL first, BEAR last), each
    check implicitly excluding all prior matches per the table's own
    "excluding prior match(es)" language:

        STRONG_BULL:    close > ema_fast > sma_mid > sma_long
        BULL:           close > ema_fast and ema_fast > sma_long        (excl. STRONG_BULL)
        BULL_PULLBACK:  close <= ema_fast, sma_mid > sma_long, close > sma_long
        DAMAGED_BULL:   close > sma_long                                (excl. all above)
        BEAR:           close <= sma_long
    """
    if inputs.close is None or inputs.ema_fast is None or inputs.sma_mid is None or inputs.sma_long is None:
        return None

    close, ema_fast, sma_mid, sma_long = inputs.close, inputs.ema_fast, inputs.sma_mid, inputs.sma_long

    if close > ema_fast > sma_mid > sma_long:
        return DirectionStructure.STRONG_BULL
    if close > ema_fast and ema_fast > sma_long:
        return DirectionStructure.BULL
    if close <= ema_fast and sma_mid > sma_long and close > sma_long:
        return DirectionStructure.BULL_PULLBACK
    if close > sma_long:
        return DirectionStructure.DAMAGED_BULL
    # close <= sma_long: exhaustive final case, BEAR always matches here.
    return DirectionStructure.BEAR


@dataclass
class DirectionConfirmationState:
    """Mutable confirmation state machine per design §6.2's asymmetric rule:
    a LESS-supportive raw structure confirms immediately; a MORE-supportive
    one requires `confirmation_bars` consecutive matching raw observations.

    **Cold-start fix (the confirmed legacy defect, see module docstring):**
    `confirmed_structure` starts as None (unavailable) and is initialized
    from the FIRST real valid raw classification only — never a hardcoded
    semantic constant like the legacy `confirmed_ts = 1` (STRONG_BULL) seed.
    """

    confirmation_bars: int
    confirmed_structure: DirectionStructure | None = None
    _pending_target: DirectionStructure | None = None
    _pending_count: int = 0

    def __post_init__(self) -> None:
        if self.confirmation_bars < 1:
            raise ValueError(f"confirmation_bars must be >= 1, got {self.confirmation_bars}")

    def advance(self, raw: DirectionStructure | None) -> DirectionStructure | None:
        """Feed one bar's raw classification (or None if this bar's
        classification was unavailable) and return the resulting confirmed
        structure (or None if still unavailable / no confirmed structure
        exists yet)."""
        if raw is None:
            # An unavailable bar does not reset or advance any pending
            # candidate — design §6.2 says nothing about missing raw bars
            # explicitly, but §4.1's fail-closed rule means we must not
            # silently treat a missing raw classification as any particular
            # structure (neither confirming nor resetting the candidate).
            return self.confirmed_structure

        if self.confirmed_structure is None:
            # Cold start: initialize directly from the first real valid
            # raw classification — never a hardcoded constant.
            self.confirmed_structure = raw
            self._pending_target = None
            self._pending_count = 0
            return self.confirmed_structure

        if raw == self.confirmed_structure:
            # Raw returned to the already-confirmed structure: candidate resets.
            self._pending_target = None
            self._pending_count = 0
            return self.confirmed_structure

        is_more_supportive = STRUCTURE_ORDER.index(raw) < STRUCTURE_ORDER.index(self.confirmed_structure)

        if not is_more_supportive:
            # Less-supportive (a real downgrade in supportiveness): confirms
            # immediately, per §6.2's "a less-supportive raw structure
            # becomes confirmed immediately."
            self.confirmed_structure = raw
            self._pending_target = None
            self._pending_count = 0
            return self.confirmed_structure

        # More-supportive: requires consecutive confirmation.
        if raw != self._pending_target:
            # A new (or first) upgrade candidate — candidate resets to this
            # target, per §6.2's "changes to another upgrade target."
            self._pending_target = raw
            self._pending_count = 1
        else:
            self._pending_count += 1

        if self._pending_count >= self.confirmation_bars:
            self.confirmed_structure = self._pending_target
            self._pending_target = None
            self._pending_count = 0

        return self.confirmed_structure

    @property
    def pending_state(self) -> DirectionStructure | None:
        """Read-only view of the current upgrade candidate (manifest field
        `direction_pending_state`, CLOSED, shape scalar) — None when no
        upgrade is currently pending (cold start, just-confirmed, or a
        downgrade/no-change bar). Exposed as a property rather than a
        public field so external callers cannot mutate the pending
        candidate directly (only `advance()` may change it)."""
        return self._pending_target

    @property
    def pending_count(self) -> int:
        """Read-only view of the current upgrade candidate's consecutive-
        bar count (manifest field `direction_pending_count`, CLOSED, shape
        scalar) — always 0 when `pending_state` is None."""
        return self._pending_count


class DirectionAdjustment(Protocol):
    """EMPIRICAL (§6.3/§17.3) — "Direction adjustment coefficient" is named
    but never formula-specified anywhere in the design doc (no shape, no
    sign convention, no bounds beyond direction_score's own manifest range)
    — the gap flagged at the end of Message[175]/[176]/[177]. This module
    does not choose or embed a specific base-score/TrendQuality combination
    formula, per the same human-approved injected-interface pattern used
    for every other EMPIRICAL seam in this engine (Slices 2/4/5/6).

    Implementers MUST return a value on [0,1] — matching the manifest's
    declared range for direction_score (`{"minimum": 0, "maximum": 1}`)."""

    def __call__(self, base_score: float, trend_quality: float | None) -> float:
        """Return the final direction_score given the structure's base
        score (already on [0,1] per DirectionBaseScores) and the current
        bar's trend_quality (already on [0,1] per TrendQuality's own
        manifest-boundary rescale), or None if TrendQuality itself is
        unavailable for this bar — implementers decide whether/how a
        missing TrendQuality value affects the adjustment; this Protocol
        does not presume TrendQuality is required for direction_score to
        exist (§6.3 does not state that dependency either way)."""
        ...


@dataclass(frozen=True)
class DirectionResult:
    """One bar's full Direction computation. `confirmed_structure`
    (manifest `direction_structure`), `raw_structure` (manifest
    `direction_structure_raw`), `direction_sign`, `pending_state`
    (manifest `direction_pending_state`), and `pending_count` (manifest
    `direction_pending_count`) are all CLOSED (design §6.1/§6.2's exact
    partition, sign table, and confirmation-state fields); `direction_score`
    is EMPIRICAL (the base score passed through the injected
    DirectionAdjustment).

    **Gap closed per Slice 10 self-review**: `raw_structure`/
    `pending_state`/`pending_count` were CLOSED-status manifest fields
    (`direction_structure_raw`/`direction_pending_state`/
    `direction_pending_count`) with no engine output producing them at
    all until now — Slice 3's original `DirectionResult` published only
    the CONFIRMED structure. Found while building Slice 10's output
    assembler, which needs every CLOSED field to have a genuine source."""

    confirmed_structure: DirectionStructure
    raw_structure: DirectionStructure | None
    direction_sign: int
    pending_state: DirectionStructure | None
    pending_count: int
    direction_score: float


def compute_direction_result(
    confirmed_structure: DirectionStructure,
    raw_structure: DirectionStructure | None,
    confirmation_state: DirectionConfirmationState,
    base_scores: DirectionBaseScores,
    trend_quality: float | None,
    adjustment: DirectionAdjustment,
) -> DirectionResult:
    """Assemble one bar's DirectionResult from an already-confirmed
    structure (via DirectionConfirmationState.advance), that SAME bar's
    raw (unconfirmed) classification, the confirmation_state object itself
    (read via its `pending_state`/`pending_count` properties — passed
    separately from `confirmed_structure` since a caller may have already
    extracted the confirmed value from `advance()`'s return before calling
    this function), the injected base scores, the current bar's
    trend_quality (or None if TrendQuality itself is unavailable), and the
    injected EMPIRICAL adjustment coefficient.

    direction_sign is a pure CLOSED lookup (DIRECTION_SIGN, design §6.1) —
    never affected by TrendQuality or the adjustment. direction_score is
    whatever the injected `adjustment` returns; this function does not
    clip or otherwise post-process it, since the injected implementation
    already owns the [0,1] contract (per DirectionAdjustment's docstring).
    """
    base = base_scores.score_for(confirmed_structure)
    score = adjustment(base, trend_quality)
    return DirectionResult(
        confirmed_structure=confirmed_structure,
        raw_structure=raw_structure,
        direction_sign=DIRECTION_SIGN[confirmed_structure],
        pending_state=confirmation_state.pending_state,
        pending_count=confirmation_state.pending_count,
        direction_score=score,
    )
