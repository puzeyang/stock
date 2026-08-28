"""Market Regime v5.1 — Slice 6: Stability (module 4.7).

Design §6.6 (C9): a supportive-positive bounded convex combination of four
separately published domains — implied-vol, vol-curve, realized-vol, and
price-stability — each a monotone-decreasing (or, for price_stability, a
supportive) transform of its own raw input. Nonnegative weights sum to one.

Canonical `price_damage` is computed ONCE HERE and shared downstream with
CRISIS (module 4.10) and diagnostics — never a private copy, never
re-derived elsewhere (design's own explicit instruction, confirmed in the
implementation plan's topology diagram after round-2 corrections in
Message[164]).

**CLOSED invariant this module must never violate:** "A VIX decline MUST
NOT lower Stability; the inherited `abs(VIX change)` implementation is
polarity-wrong." Enforced STRUCTURALLY, not by a runtime check: every
transform in this module is a function of a raw LEVEL (VIX level, VIX9D/VIX
ratio, realized volatility, price_damage), never of a signed or
absolute-valued CHANGE — there is no `vix_change` or `abs(...)` computation
anywhere in this module's transform interfaces, so the specific inherited
bug (computing stability from `abs(VIX_t - VIX_{t-1})`, which makes a VIX
DECLINE look identical to a VIX RISE of the same magnitude and therefore can
lower "stability" on a calming day) is structurally impossible to reintroduce
through this module's own API — a caller would have to actively misuse a
level-only interface to reproduce it, not merely follow the interface as
designed.

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`):
`implied_vol_stability`, `vol_curve_raw`, `vol_curve_stability`,
`realized_volatility`, `realized_vol_stability`, `benchmark_drawdown`,
`benchmark_return_shock`, `price_damage`, `price_stability`,
`stability_contributions`, `stability_score`.

**EMPIRICAL scope (same injectable-interface pattern as Slices 2/4/5,
human-approved):** design §17.7 marks stability transforms, horizons,
realized-vol estimator, and price-damage construction all EMPIRICAL — none
of these formulas are CLOSED anywhere in the design. This module defines
each transform as an injected `MonotoneDecreasingTransform`/
`PriceDamageEstimator` Protocol; it never embeds or defaults to a specific
formula.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .raw_features import RawSeries


class StabilityUnavailableError(Exception):
    """Signals Stability is genuinely unavailable for this as_of date per
    design §4.1's fail-closed rule — never neutralized to a default."""


class MonotoneDecreasingTransform(Protocol):
    """EMPIRICAL — the shape a "raw level -> supportive-positive stability
    domain" transform MUST have. Implementers MUST be monotone-decreasing
    in the raw level (higher raw stress level => lower or equal stability
    output) and MUST operate on the LEVEL only, never a signed/absolute
    change — this is what keeps the "VIX decline must not lower Stability"
    invariant structurally satisfiable through this interface."""

    def __call__(self, raw_level: float) -> float:
        """Return the supportive-positive transformed value for one raw
        level, on [0,1] — matching the manifest's declared range for
        implied_vol_stability/vol_curve_stability/realized_vol_stability/
        price_stability (each `{"minimum": 0, "maximum": 1}`). This is a
        contract on the injected transform's OUTPUT, not a formula choice:
        implementers choose how a raw level becomes a stability value, but
        MUST express it on [0,1], not 0-100. Must not raise for any level a
        real market has produced; availability (missing/stale data) is
        handled by the CALLER before this is invoked, not by this function
        returning a sentinel."""
        ...


class PriceDamageEstimator(Protocol):
    """EMPIRICAL — the shape the canonical price_damage computation MUST
    have, once a concrete formula is chosen (design §6.6: "price-damage
    construction... EMPIRICAL"). Adverse-positive: HIGHER price_damage means
    MORE damage (the opposite polarity convention from the stability
    domains, per design §6.6's "adverse-positive canonical price_damage")."""

    def __call__(self, benchmark_series: RawSeries, as_of: str) -> float | None:
        """Return the adverse-positive price_damage value as of `as_of`, or
        None if unavailable — implementers MUST fail closed."""
        ...


class RealizedVolEstimator(Protocol):
    """EMPIRICAL — the shape the realized-benchmark-volatility estimator
    MUST have. Design §17.7: "realized-vol estimator... EMPIRICAL"."""

    def __call__(self, benchmark_series: RawSeries, as_of: str) -> float | None:
        ...


@dataclass(frozen=True)
class StabilityWeights:
    """EMPIRICAL (§17.7) — injected. Nonnegative weights summing to one."""

    weight_implied_vol: float
    weight_vol_curve: float
    weight_realized_vol: float
    weight_price: float

    def __post_init__(self) -> None:
        weights = (self.weight_implied_vol, self.weight_vol_curve, self.weight_realized_vol, self.weight_price)
        if any(w < 0 for w in weights):
            raise ValueError("StabilityWeights: all weights must be nonnegative")
        total = sum(weights)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"StabilityWeights: weights must sum to exactly 1.0, got {total}")


@dataclass(frozen=True)
class StabilityResult:
    as_of: str
    implied_vol_stability: float
    vol_curve_raw: float
    vol_curve_stability: float
    realized_volatility: float
    realized_vol_stability: float
    price_damage: float
    price_stability: float
    stability_score: float


def compute_vol_curve_raw(vix9d_series: RawSeries, vix_series: RawSeries, as_of: str) -> float | None:
    """VIX9D/VIX ratio as of `as_of`. Returns None if either is unavailable
    on that date, or if VIX itself is exactly zero (undefined ratio)."""
    vix9d = vix9d_series.value_on(as_of)
    vix = vix_series.value_on(as_of)
    if vix9d is None or vix is None:
        return None
    if vix == 0:
        raise StabilityUnavailableError(f"VIX is exactly zero on {as_of} — vol_curve_raw undefined")
    return vix9d / vix


def compute_stability(
    as_of: str,
    vix_series: RawSeries,
    vix9d_series: RawSeries,
    benchmark_series: RawSeries,
    implied_vol_transform: MonotoneDecreasingTransform,
    vol_curve_transform: MonotoneDecreasingTransform,
    realized_vol_transform: MonotoneDecreasingTransform,
    realized_vol_estimator: "RealizedVolEstimator",
    price_damage_estimator: PriceDamageEstimator,
    price_stability_transform: MonotoneDecreasingTransform,
    weights: StabilityWeights,
) -> StabilityResult:
    """Full Stability computation for one as_of date. Raises
    StabilityUnavailableError if any required component is unavailable —
    fail-closed per C16, never a partial/neutralized score.

    `price_damage_estimator` is called exactly once per invocation — this
    IS the canonical, shared computation design §6.6 requires ("computed
    once... Stability MUST NOT create a private copy"); callers needing
    price_damage elsewhere (CRISIS, diagnostics) MUST reuse this same
    returned `price_damage` value, never call the estimator again
    independently for the same as_of date.
    """
    vix = vix_series.value_on(as_of)
    if vix is None:
        raise StabilityUnavailableError(f"VIX unavailable as of {as_of}")
    implied_vol_stability = implied_vol_transform(vix)

    vol_curve_raw = compute_vol_curve_raw(vix9d_series, vix_series, as_of)
    if vol_curve_raw is None:
        raise StabilityUnavailableError(f"vol_curve_raw unavailable as of {as_of}")
    vol_curve_stability = vol_curve_transform(vol_curve_raw)

    realized_volatility = realized_vol_estimator(benchmark_series, as_of)
    if realized_volatility is None:
        raise StabilityUnavailableError(f"realized_volatility unavailable as of {as_of}")
    realized_vol_stability = realized_vol_transform(realized_volatility)

    price_damage = price_damage_estimator(benchmark_series, as_of)
    if price_damage is None:
        raise StabilityUnavailableError(f"price_damage unavailable as of {as_of}")
    price_stability = price_stability_transform(price_damage)

    # Each domain output is on [0,1] per MonotoneDecreasingTransform's
    # documented contract; a weighted sum with nonnegative weights summing
    # to one stays on [0,1], matching stability_score's own declared range.
    score = (
        weights.weight_implied_vol * implied_vol_stability
        + weights.weight_vol_curve * vol_curve_stability
        + weights.weight_realized_vol * realized_vol_stability
        + weights.weight_price * price_stability
    )

    return StabilityResult(
        as_of=as_of,
        implied_vol_stability=implied_vol_stability,
        vol_curve_raw=vol_curve_raw,
        vol_curve_stability=vol_curve_stability,
        realized_volatility=realized_volatility,
        realized_vol_stability=realized_vol_stability,
        price_damage=price_damage,
        price_stability=price_stability,
        stability_score=score,
    )
