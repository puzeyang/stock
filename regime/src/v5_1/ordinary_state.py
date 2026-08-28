"""Market Regime v5.1 — Slice 8b: Ordinary hysteresis (part of module 4.10).

Design §8 (C2): among the three "ordinary" states (RISK_OFF, NEUTRAL,
RISK_ON — CRISIS and TRENDING are exclusive states decided by their own
dedicated machines in `crisis.py`/`trending.py`, never by this module),
transitions use ASYMMETRIC hysteresis: downgrades are faster than upgrades.
Exact boundaries, buffers, and confirmation counts are EMPIRICAL (§17.11).
`decision_margin` (module 4.11, Confidence) is diagnostic only and MUST
NEVER be read by this module to change a counter or a label. A hard veto
bypasses the ordinary downgrade delay entirely — a downgrade caused by an
active hard veto is immediate, exactly like CRISIS entry has no delay.

This module's asymmetric-confirmation SHAPE mirrors Direction's
confirmation state machine (`direction.py`'s `DirectionConfirmationState`:
immediate on a less-supportive move, N-consecutive-bar confirmation
required on a more-supportive move) — the same immediate-downgrade/
delayed-upgrade principle, applied here to condition_score-derived ordinary
states instead of Direction's raw structure classification. It is a
distinct implementation (different domain, different input shape, its own
hard-veto-bypass rule), not a reuse of DirectionConfirmationState itself.

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`,
module 4.10 subset relevant to ordinary hysteresis): `state`,
`pending_state`, `pending_state_count` (the three ordinary-state-machine
fields; `state`/`pending_state` are also written by CRISIS/TRENDING when
those machines are exclusively active — module 4.10's top-level combiner,
not this file, owns picking among all three sub-machines' outputs).

**EMPIRICAL scope (§17.11):** state boundaries (the condition_score
thresholds separating RISK_OFF/NEUTRAL/RISK_ON), buffers (hysteresis
margin around each boundary), and confirmation bar counts (separately for
upgrade vs. downgrade, and potentially per-transition) are all EMPIRICAL —
injected configuration, never hardcoded.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class OrdinaryState(IntEnum):
    """The three ordinary states, ordered least to most supportive — used
    the same way DirectionStructure's STRUCTURE_ORDER is used: to decide
    whether a raw-state move is an upgrade (more supportive, delayed) or a
    downgrade (less supportive, immediate)."""

    RISK_OFF = 1
    NEUTRAL = 2
    RISK_ON = 3


ORDINARY_STATE_ORDER = (OrdinaryState.RISK_OFF, OrdinaryState.NEUTRAL, OrdinaryState.RISK_ON)


@dataclass(frozen=True)
class StateBoundaries:
    """EMPIRICAL (§17.11) — injected. The two condition_score thresholds
    separating RISK_OFF|NEUTRAL and NEUTRAL|RISK_ON, each with its own
    buffer (hysteresis margin) used to avoid raw-classification chatter
    exactly at a boundary. `risk_off_neutral_boundary` MUST be strictly
    less than `neutral_risk_on_boundary` (a real ordering requirement, not
    an arbitrary one — RISK_OFF's upper edge cannot be at or above RISK_ON's
    lower edge, or the NEUTRAL band would be empty or inverted).

    Buffers are nonnegative; a raw classification uses `boundary + buffer`
    on the upgrade side and `boundary - buffer` on the downgrade side (a
    classic dead-band construction), so the same instantaneous
    condition_score does not flicker a raw classification back and forth
    across a bare boundary.
    """

    risk_off_neutral_boundary: float
    neutral_risk_on_boundary: float
    risk_off_neutral_buffer: float
    neutral_risk_on_buffer: float

    def __post_init__(self) -> None:
        if not (self.risk_off_neutral_boundary < self.neutral_risk_on_boundary):
            raise ValueError(
                f"risk_off_neutral_boundary ({self.risk_off_neutral_boundary}) must be strictly less than "
                f"neutral_risk_on_boundary ({self.neutral_risk_on_boundary})"
            )
        if self.risk_off_neutral_buffer < 0 or self.neutral_risk_on_buffer < 0:
            raise ValueError("StateBoundaries buffers must be nonnegative")

    def classify_raw(self, condition_score: float, current_raw: OrdinaryState | None) -> OrdinaryState:
        """Deterministic dead-band classification. When `current_raw` is
        None (cold start / first bar), the buffer is not applied — there is
        no prior raw state to hold onto, so the bare boundary decides.
        Otherwise, a value must cross `boundary +/- buffer` in the
        direction AWAY from the current raw state to actually move; a
        value that has merely re-entered the buffer zone around the
        current raw state's own edge stays at `current_raw`.
        """
        if current_raw is None:
            if condition_score < self.risk_off_neutral_boundary:
                return OrdinaryState.RISK_OFF
            if condition_score < self.neutral_risk_on_boundary:
                return OrdinaryState.NEUTRAL
            return OrdinaryState.RISK_ON

        if current_raw == OrdinaryState.RISK_OFF:
            if condition_score >= self.neutral_risk_on_boundary + self.neutral_risk_on_buffer:
                return OrdinaryState.RISK_ON
            if condition_score >= self.risk_off_neutral_boundary + self.risk_off_neutral_buffer:
                return OrdinaryState.NEUTRAL
            return OrdinaryState.RISK_OFF

        if current_raw == OrdinaryState.NEUTRAL:
            if condition_score >= self.neutral_risk_on_boundary + self.neutral_risk_on_buffer:
                return OrdinaryState.RISK_ON
            if condition_score < self.risk_off_neutral_boundary - self.risk_off_neutral_buffer:
                return OrdinaryState.RISK_OFF
            return OrdinaryState.NEUTRAL

        # current_raw == RISK_ON
        if condition_score < self.risk_off_neutral_boundary - self.risk_off_neutral_buffer:
            return OrdinaryState.RISK_OFF
        if condition_score < self.neutral_risk_on_boundary - self.neutral_risk_on_buffer:
            return OrdinaryState.NEUTRAL
        return OrdinaryState.RISK_ON


@dataclass(frozen=True)
class ConfirmationBars:
    """EMPIRICAL (§17.11) — injected. Separate confirmation-bar counts for
    upgrade vs. downgrade moves, per §8's "downgrades are faster than
    upgrades." `downgrade_bars` MAY be 1 (i.e. effectively immediate) or
    larger; this module does not assume downgrade is ALWAYS instantaneous
    in the ordinary (non-veto) case — only that it is faster than (i.e.
    `<=`) the upgrade count, since "faster" is a relative, not absolute,
    requirement, and a hard-veto-triggered downgrade is separately made
    unconditionally immediate regardless of this count (see `advance`)."""

    upgrade_bars: int
    downgrade_bars: int

    def __post_init__(self) -> None:
        if self.upgrade_bars < 1 or self.downgrade_bars < 1:
            raise ValueError("ConfirmationBars: both counts must be >= 1")
        if self.downgrade_bars > self.upgrade_bars:
            raise ValueError(
                f"ConfirmationBars: downgrade_bars ({self.downgrade_bars}) must not exceed "
                f"upgrade_bars ({self.upgrade_bars}) — design §8 requires downgrades to be at least as fast as upgrades"
            )


@dataclass
class OrdinaryHysteresisState:
    """Mutable persisted ordinary-hysteresis state (design §4.3's "regime
    displayed state, pending state, and count"). `confirmed_state` starts
    None (never seeded — same cold-start discipline as Direction and
    CrisisState)."""

    confirmed_state: OrdinaryState | None = None
    pending_state: OrdinaryState | None = None
    pending_count: int = 0
    _raw_state: OrdinaryState | None = None  # internal: feeds classify_raw's own dead-band memory

    def advance(
        self,
        condition_score: float | None,
        boundaries: StateBoundaries,
        confirmation_bars: ConfirmationBars,
        hard_veto_active: bool,
    ) -> OrdinaryState | None:
        """Advance ordinary-state hysteresis by one bar. Returns the
        resulting confirmed_state (or None if still unavailable).

        `condition_score=None` (Condition itself unavailable this bar) does
        NOT reset or advance any pending candidate — same fail-closed
        missing-bar handling as DirectionConfirmationState.advance — and
        leaves confirmed_state at whatever it already was (None at cold
        start, or the last confirmed value)."""
        if condition_score is None:
            return self.confirmed_state

        raw = boundaries.classify_raw(condition_score, self._raw_state)
        self._raw_state = raw

        if self.confirmed_state is None:
            self.confirmed_state = raw
            self.pending_state = None
            self.pending_count = 0
            return self.confirmed_state

        if raw == self.confirmed_state:
            self.pending_state = None
            self.pending_count = 0
            return self.confirmed_state

        is_downgrade = ORDINARY_STATE_ORDER.index(raw) < ORDINARY_STATE_ORDER.index(self.confirmed_state)

        if hard_veto_active and is_downgrade:
            # §8: "A hard veto bypasses ordinary downgrade delay" — an
            # active hard veto makes ANY downgrade immediate, regardless of
            # confirmation_bars.downgrade_bars, even if that count is > 1.
            self.confirmed_state = raw
            self.pending_state = None
            self.pending_count = 0
            return self.confirmed_state

        required_bars = confirmation_bars.downgrade_bars if is_downgrade else confirmation_bars.upgrade_bars

        if raw != self.pending_state:
            self.pending_state = raw
            self.pending_count = 1
        else:
            self.pending_count += 1

        if self.pending_count >= required_bars:
            self.confirmed_state = self.pending_state
            self.pending_state = None
            self.pending_count = 0

        return self.confirmed_state
