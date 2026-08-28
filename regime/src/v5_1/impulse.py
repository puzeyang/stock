"""Market Regime v5.1 — Slice 9a: Impulse (module 4.9).

Design §11 (C14): Impulse describes motion in the FINAL post-veto/post-cap
`condition_score`, before categorical state hysteresis — it consumes
Condition's own already-finalized output (module 4.8), never a pillar or
pre-cap value as its own headline signal (pre-cap/pillar impulses are
published separately for attribution only, per §11's own "do not replace
headline Condition Impulse").

**Corrected input contract per Message[162] item 3** (carried into the
approved implementation plan §4.9): Impulse is NOT a pure function of the
bare numeric `condition_score` series. §11's own "missing/stale endpoints
or invalid required interior sessions make the horizon and aggregate
unavailable" means a horizon's real input is the aligned condition_score
series PLUS its per-observation freshness/validity metadata (from module
4.1's `evaluate_freshness()`) and expected-session coverage over the
horizon's own interior window — a numeric gap and an "invalid but present"
observation are different failure modes and both must be caught, so this
module accepts `ImpulseEndpoint`/interior-validity flags rather than bare
floats for its horizon inputs.

The no-feedback invariant (C14: Impulse never feeds Condition, caps,
vetoes, counters, or state) is a ONE-WAY data-flow constraint — nothing
computed by this module may be read back by contracts.py/condition.py/
state_machine.py. This module enforces it by omission (it has no output
type any of those modules import), not by a runtime check; a dedicated
structural test confirms none of those modules imports from this one.

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`):
`impulse_fast`, `impulse_slow`, `impulse_score`,
`pre_cap_and_pillar_impulses`, `binding_event_changes`.

**EMPIRICAL scope (§17.14):** horizons, the scale estimator (window,
floor), fast/slow weights, and the odd squashing transform are all
EMPIRICAL — injected, never hardcoded (v4.4's 5/20 horizons, 0.6/0.4
weights, rolling z-score estimator, and tanh transform are explicitly
named as benchmark-only, never a shipped default).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ImpulseUnavailableError(Exception):
    """Signals a specific Impulse horizon (or the aggregate) is genuinely
    unavailable for this as_of date per design §4.1's fail-closed rule —
    never neutralized to a default."""


@dataclass(frozen=True)
class ImpulseEndpoint:
    """One horizon endpoint's condition_score value plus whether it is
    USABLE (per module 4.1's freshness contract — CURRENT only; STALE/
    MISSING/MISALIGNED are all not usable). `value` may be present even
    when `usable=False` (e.g. a stale-but-present observation) — callers
    of this module MUST NOT pass a usable value computed from an unusable
    endpoint; `usable=False` is authoritative regardless of whether
    `value` itself looks numerically fine."""

    value: float | None
    usable: bool


@dataclass(frozen=True)
class ImpulseHorizonInputs:
    """One horizon's full input contract per Message[162]'s correction:
    both endpoints (current bar `t` and the bar `h` sessions back) plus
    whether EVERY required interior expected session in between is valid.
    `interior_all_valid=False` makes the horizon unavailable even if both
    endpoints are individually usable — a gap or invalid observation
    strictly between the two endpoints still poisons the horizon per §11's
    own "invalid required interior sessions make the horizon... unavailable."
    """

    endpoint_t: ImpulseEndpoint
    endpoint_t_minus_h: ImpulseEndpoint
    interior_all_valid: bool


class ScaleEstimator(Protocol):
    """EMPIRICAL (§17.14) — the shape the causal, zero-anchored scale
    estimator MUST have. Design §11: 'scaling is causal and anchored at
    zero, never recentered on a rolling mean' — this module does not
    embed a concrete estimator (v4.4's rolling z-score is explicitly
    benchmark-only); implementers own the causal/zero-anchor contract."""

    def __call__(self, raw_change: float) -> float:
        """Return the scaled (but not yet squashed) change for one raw
        `condition_t - condition_t_minus_h` value."""
        ...


class OddSquashingTransform(Protocol):
    """EMPIRICAL (§17.14) — the shape the "at most one declared odd
    squashing transform" MUST have. Design §11 requires the transform be
    continuous, odd (`f(-x) == -f(x)`), monotone, zero-preserving
    (`f(0) == 0`), and symmetrically bounded (output in [-1,1]).
    Implementers own this contract; v4.4's tanh is explicitly
    benchmark-only, never a shipped default."""

    def __call__(self, scaled_change: float) -> float:
        ...


@dataclass(frozen=True)
class ImpulseWeights:
    """EMPIRICAL (§17.14) — injected. Nonnegative fast/slow weights
    summing to one, combining the two already-transformed per-horizon
    impulses into impulse_score. Per §11's "at most one declared odd
    squashing transform is applied," the transform is applied ONCE, at
    the per-horizon level (producing impulse_fast/impulse_slow) — this
    aggregate combination is a plain weighted SUM of already-bounded
    values, never a second transform application, which is what keeps
    the aggregate itself within [-1,1] (a convex combination of two
    values each in [-1,1] stays in [-1,1])."""

    weight_fast: float
    weight_slow: float

    def __post_init__(self) -> None:
        if self.weight_fast < 0 or self.weight_slow < 0:
            raise ValueError("ImpulseWeights: weights must be nonnegative")
        total = self.weight_fast + self.weight_slow
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"ImpulseWeights: weights must sum to exactly 1.0, got {total}")


@dataclass(frozen=True)
class ImpulseResult:
    as_of: str
    impulse_fast: float
    impulse_slow: float
    impulse_score: float


def compute_horizon_impulse(
    horizon: ImpulseHorizonInputs,
    scale_estimator: ScaleEstimator,
    transform: OddSquashingTransform,
) -> float:
    """Compute one horizon's transformed impulse value. Raises
    ImpulseUnavailableError if either endpoint is unusable/missing or any
    required interior session is invalid — fail-closed per C16, never a
    partial/neutralized value.

    Sign-consistency (§11's `sign(impulse_h) = sign(condition_t -
    condition_t-h)` when nonzero) is satisfied structurally here: the raw
    change is computed once and passed through `scale_estimator` then
    `transform` in sequence, with no sign-altering step in between — as
    long as both injected callables are themselves sign-preserving (part
    of their own documented EMPIRICAL contract), this function introduces
    no additional sign inversion of its own. An exact-zero raw change maps
    to exactly zero output whenever both injected callables satisfy their
    own documented zero-preserving contracts (§11's "unchanged maps
    exactly to zero") — this function does not special-case zero itself,
    since forcing a special case here could silently mask an injected
    transform that fails its own zero-preservation contract.
    """
    if not horizon.endpoint_t.usable or horizon.endpoint_t.value is None:
        raise ImpulseUnavailableError("horizon unavailable: endpoint_t is not usable")
    if not horizon.endpoint_t_minus_h.usable or horizon.endpoint_t_minus_h.value is None:
        raise ImpulseUnavailableError("horizon unavailable: endpoint_t_minus_h is not usable")
    if not horizon.interior_all_valid:
        raise ImpulseUnavailableError("horizon unavailable: one or more required interior sessions are invalid")

    raw_change = horizon.endpoint_t.value - horizon.endpoint_t_minus_h.value
    scaled = scale_estimator(raw_change)
    return transform(scaled)


def compute_impulse(
    as_of: str,
    fast_horizon: ImpulseHorizonInputs,
    slow_horizon: ImpulseHorizonInputs,
    scale_estimator: ScaleEstimator,
    transform: OddSquashingTransform,
    weights: ImpulseWeights,
) -> ImpulseResult:
    """Full Impulse computation for one as_of date. Raises
    ImpulseUnavailableError if EITHER horizon is unavailable — the
    aggregate impulse_score cannot be a meaningful weighted sum of a
    missing term, same fail-closed discipline as Condition's own pillar
    weighted sum (condition.py)."""
    impulse_fast = compute_horizon_impulse(fast_horizon, scale_estimator, transform)
    impulse_slow = compute_horizon_impulse(slow_horizon, scale_estimator, transform)

    impulse_score = weights.weight_fast * impulse_fast + weights.weight_slow * impulse_slow

    return ImpulseResult(
        as_of=as_of,
        impulse_fast=impulse_fast,
        impulse_slow=impulse_slow,
        impulse_score=impulse_score,
    )
