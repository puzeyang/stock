"""Market Regime v5.1 — Slice 9b: Confidence diagnostics (module 4.11).

Design §12 (C15): four diagnostics only — explicitly "no aggregate
confidence scalar," and any future aggregate requires a new design
decision/version (§17.15), which this module does not attempt to
anticipate or half-implement.

- `pillar_agreement`: common-polarity pillar dispersion; more disagreement
  cannot improve it (monotone constraint on the OUTPUT direction, not a
  formula).
- `data_completeness`: optional/tier coverage and freshness; restoring
  data cannot reduce it. A REQUIRED (not optional) failure makes Condition
  itself unavailable (module 4.8's own fail-closed behavior) rather than
  degrading this diagnostic — so `data_completeness` is specifically about
  OPTIONAL/tier coverage gaps, never a stand-in for "Condition is
  unavailable."
- `decision_margin`: distance from the applicable decision surface
  (including TRENDING's own qualification boundary, not just ordinary
  hysteresis's); explicitly diagnostic-only — "it never drives
  transitions" (C15, enforced the same by-omission way Impulse's C14
  no-feedback invariant is: no state-machine module reads this module's
  output).
- `temporal_stability`: recent Condition noise and label fragility.

Every formula is ENTIRELY EMPIRICAL (§17.15) — unlike every prior slice,
there is no CLOSED arithmetic anywhere in §12 for any of the four
diagnostics, only their OUTPUT CONTRACTS (bounds, monotonicity direction,
"never drives transitions"). This module therefore defines each
diagnostic purely as an injected Protocol matching its own documented
contract; it embeds no default computation for any of them, not even a
"reasonable-looking" placeholder shape beyond the Protocol signature
itself — there is nothing CLOSED here to build against.

**Confidence never rescales Condition or state** — this module has no
output type any of `condition.py`/`state_machine.py`/`crisis.py`/
`ordinary_state.py`/`trending.py` import, mirroring Impulse's own
structural no-feedback enforcement (verified by an equivalent grep-based
test to `test_impulse.py`'s).

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`):
`pillar_agreement`, `data_completeness`, `decision_margin`,
`temporal_stability`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ConfidenceUnavailableError(Exception):
    """Signals a specific Confidence diagnostic is genuinely unavailable
    for this as_of date — e.g. insufficient history for
    `temporal_stability`'s own required window. Per §12, a REQUIRED data
    failure makes CONDITION unavailable (module 4.8's own job, not this
    module's) — this exception is for a diagnostic's OWN insufficient
    input (e.g. not enough historical Condition values yet), never a
    substitute for Condition's own required-failure handling."""


class PillarAgreementEstimator(Protocol):
    """EMPIRICAL (§17.15/§12) — the shape `pillar_agreement` MUST have.
    Implementers MUST return a value on [0,1] where MORE pillar
    disagreement can never INCREASE the returned value (§12's own
    monotonicity constraint) — this module does not enforce that
    monotonicity at runtime (it would require re-deriving the
    implementer's own dispersion formula to check), it is a contract the
    implementer owns, same as every other injected EMPIRICAL seam's
    documented-not-enforced contracts throughout this engine (e.g.
    MonotoneDecreasingTransform in stability.py)."""

    def __call__(self, as_of: str) -> float | None:
        """Return pillar_agreement on [0,1], or None if unavailable this
        bar (e.g. fewer than the minimum pillars needed for a dispersion
        measure are themselves available)."""
        ...


class DataCompletenessEstimator(Protocol):
    """EMPIRICAL (§17.15/§12) — the shape `data_completeness` MUST have.
    Implementers MUST return a value on [0,1] where restoring OPTIONAL/
    tier data can never DECREASE the returned value. Scope is explicitly
    optional/tier coverage — a REQUIRED failure is module 4.8's job
    (Condition itself becomes unavailable), never routed through this
    diagnostic as a degraded score."""

    def __call__(self, as_of: str) -> float | None:
        ...


class DecisionMarginEstimator(Protocol):
    """EMPIRICAL (§17.15/§12) — the shape `decision_margin` MUST have.
    "Distance from the applicable decision surface, including TRENDING" —
    implementers decide which surface is "applicable" for a given bar
    (the nearest ordinary-hysteresis boundary, or a TRENDING qualification
    threshold, whichever is closer/relevant) and return a value on [0,1].
    This diagnostic MUST NEVER be read by any state-transition logic
    (C15) — enforced structurally by this module having no output type
    imported by crisis.py/ordinary_state.py/trending.py/state_machine.py,
    verified by a dedicated grep-based test."""

    def __call__(self, as_of: str) -> float | None:
        ...


class TemporalStabilityEstimator(Protocol):
    """EMPIRICAL (§17.15/§12) — the shape `temporal_stability` MUST have.
    "Recent Condition noise and label fragility" — implementers decide the
    concrete lookback/formula; this module does not embed one. Returns a
    value on [0,1], or None if unavailable (e.g. insufficient history for
    whatever recent-noise window the implementer's own formula requires)."""

    def __call__(self, as_of: str) -> float | None:
        ...


@dataclass(frozen=True)
class ConfidenceResult:
    as_of: str
    pillar_agreement: float | None
    data_completeness: float | None
    decision_margin: float | None
    temporal_stability: float | None


def compute_confidence(
    as_of: str,
    pillar_agreement_estimator: PillarAgreementEstimator,
    data_completeness_estimator: DataCompletenessEstimator,
    decision_margin_estimator: DecisionMarginEstimator,
    temporal_stability_estimator: TemporalStabilityEstimator,
) -> ConfidenceResult:
    """Compute all four Confidence diagnostics for one as_of date.

    Deliberately does NOT raise when an individual diagnostic estimator
    returns None — unlike every pillar/Condition/Impulse computation in
    this engine, Confidence's four fields are each independently nullable
    diagnostics with NO aggregate combining them (§12's own "publish no
    aggregate confidence scalar"), so one diagnostic's unavailability has
    no arithmetic dependency for any other diagnostic to inherit — there
    is no weighted sum here that a None value would corrupt. Each
    estimator is solely responsible for its own None-vs-value decision.
    """
    return ConfidenceResult(
        as_of=as_of,
        pillar_agreement=pillar_agreement_estimator(as_of),
        data_completeness=data_completeness_estimator(as_of),
        decision_margin=decision_margin_estimator(as_of),
        temporal_stability=temporal_stability_estimator(as_of),
    )
