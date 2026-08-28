"""Market Regime v5.1 — Slice 5: Risk Appetite (module 4.6).

Design §6.5 (C8): credit plus revealed rotation only — no price damage,
rates, curve, macro, or absolute benchmark momentum. `growth_rotation_pct`
(QQQ/SPY relative) and `small_cap_rotation_pct` (IWM/SPY relative), each one
causal-504-midrank (Slice 1's exact `causal_midrank` primitive — CLOSED,
reused here, never reimplemented). Combined with credit via a bounded convex
formula, nonnegative weights summing to one.

**CLOSED invariant this module must never violate:** "No gating or sign flip
by benchmark return is permitted" — rotation percentiles are computed
identically regardless of whether the benchmark itself is up or down on any
given day; this module contains NO conditional branch on benchmark direction
anywhere in the rotation computation path (a mechanically checkable property,
verified by a dedicated test comparing rotation output in a rising vs.
falling benchmark synthetic scenario with identical relative-performance
shape).

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`):
`oas_change`, `credit_level_pct`, `credit_change_score`,
`growth_rotation_raw`, `growth_rotation_pct`, `small_cap_rotation_raw`,
`small_cap_rotation_pct`, `risk_appetite_contributions`, `risk_appetite_score`.

**EMPIRICAL scope (same injectable-interface pattern as Slices 2 and 4,
human-approved):** design §17.5/§17.6 marks credit source/construction,
rotation horizons/transforms, and pillar weights EMPIRICAL. This module
computes the real rotation RAW ratio (QQQ/SPY, IWM/SPY) from real Slice 2
data and applies Slice 1's real, CLOSED midrank formula to it — that part is
not EMPIRICAL, it's exact. What IS left injectable: the credit level/change
transform (no formula is CLOSED anywhere in the design for how raw OAS
level/change becomes `credit_level_pct`/`credit_change_score`), and the
final convex-combination weights.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .normalization import causal_midrank, InsufficientHistoryError, REQUIRED_WINDOW_SIZE
from .raw_features import RawSeries


class RiskAppetiteUnavailableError(Exception):
    """Signals Risk Appetite is genuinely unavailable for this as_of date
    per design §4.1's fail-closed rule — never neutralized to a default."""


@dataclass(frozen=True)
class RiskAppetiteWeights:
    """EMPIRICAL (§17.6) — injected. Nonnegative weights summing to one,
    combining credit and rotation into risk_appetite_score. Design §6.5
    explicitly permits zero production weight on any component while
    diagnostics remain published — this dataclass allows zero on any single
    weight, it just requires the full set to sum to exactly one."""

    weight_credit: float
    weight_growth_rotation: float
    weight_small_cap_rotation: float

    def __post_init__(self) -> None:
        weights = (self.weight_credit, self.weight_growth_rotation, self.weight_small_cap_rotation)
        if any(w < 0 for w in weights):
            raise ValueError("RiskAppetiteWeights: all weights must be nonnegative")
        total = sum(weights)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"RiskAppetiteWeights: weights must sum to exactly 1.0, got {total}")


class CreditTransform(Protocol):
    """EMPIRICAL (§17.5) — the shape a credit level/change transform MUST
    have, once a concrete formula is chosen. This module defines the
    interface only; it does not choose or embed a specific OAS->percentile
    transform, per the same human-approved pattern as Slice 2/4."""

    def __call__(self, oas_series: RawSeries, as_of: str) -> tuple[float, float] | None:
        """Return (credit_level_pct, credit_change_score) as of `as_of`, or
        None if unavailable (insufficient history, missing OAS observation,
        etc.) — implementers MUST fail closed, never return a neutral fill.

        `credit_level_pct` MUST be on [0,1], matching the manifest's declared
        range (`{"minimum": 0, "maximum": 1}`) — this is a contract on the
        injected transform's OUTPUT, not a formula choice, so it stays
        EMPIRICAL-safe: implementers choose how OAS becomes a percentile,
        but MUST express that percentile on [0,1], not 0-100."""
        ...


@dataclass(frozen=True)
class RiskAppetiteResult:
    as_of: str
    credit_level_pct: float
    credit_change_score: float
    growth_rotation_raw: float
    growth_rotation_pct: float
    small_cap_rotation_raw: float
    small_cap_rotation_pct: float
    risk_appetite_score: float


def compute_rotation_raw(numerator_series: RawSeries, benchmark_series: RawSeries, as_of: str) -> float | None:
    """The raw relative-performance ratio (e.g. QQQ/SPY or IWM/SPY) as of
    `as_of`. Returns None if either series has no observation on `as_of`
    (fail-closed — never substitutes a neighbor).

    **CLOSED invariant, mechanically enforced by omission:** this function
    takes no benchmark-return-sign input and contains no conditional branch
    on whether the benchmark itself is rising or falling — "no gating or
    sign flip by benchmark return" is satisfied structurally, not by a
    runtime check, since there is nothing here for a sign-flip to hook into.
    """
    numerator = numerator_series.value_on(as_of)
    denominator = benchmark_series.value_on(as_of)
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        raise RiskAppetiteUnavailableError(f"benchmark value is exactly zero on {as_of} — relative ratio undefined")
    return numerator / denominator


def compute_rotation_pct(
    numerator_series: RawSeries,
    benchmark_series: RawSeries,
    as_of: str,
) -> tuple[float | None, float | None]:
    """(rotation_raw, rotation_pct) — rotation_pct is the causal 504-session
    midrank of rotation_raw, per design §6.5's "one causal 504-session
    midrank" requirement. Both are None if the current as_of's ratio itself
    is unavailable. rotation_pct alone is None (with rotation_raw populated)
    if there is insufficient history for the midrank window — a real,
    distinguishable partial-unavailability case: the raw ratio exists, but
    504 valid historical ratios to rank it against do not yet exist.

    `rotation_pct` is rescaled to [0,1] here, at this manifest-field
    boundary — `causal_midrank()` itself returns its literal CLOSED-formula
    0-100 scale (design §5.1: `percentile = 100 * (...)`) and is deliberately
    left unchanged; growth_rotation_pct/small_cap_rotation_pct are manifest-
    declared [0,1], so the /100 conversion happens here, once, rather than
    at every call site."""
    current_raw = compute_rotation_raw(numerator_series, benchmark_series, as_of)
    if current_raw is None:
        return None, None

    # Build the 504-observation window of the SAME ratio, ending at as_of.
    numerator_window = numerator_series.window_ending(as_of, REQUIRED_WINDOW_SIZE)
    benchmark_window = benchmark_series.window_ending(as_of, REQUIRED_WINDOW_SIZE)
    if numerator_window is None or benchmark_window is None:
        return current_raw, None

    numerator_dates = [o.date for o in numerator_window]
    benchmark_dates = [o.date for o in benchmark_window]
    if numerator_dates != benchmark_dates:
        # The two series' windows don't align date-for-date (e.g. one has a
        # gap the other doesn't) — the ratio series for the window can't be
        # constructed consistently. Fail closed rather than silently
        # pairing mismatched dates.
        return current_raw, None

    ratio_window = [n.value / b.value if b.value != 0 else None for n, b in zip(numerator_window, benchmark_window)]
    if any(r is None for r in ratio_window):
        return current_raw, None

    try:
        rotation_pct = causal_midrank(ratio_window, current_raw) / 100.0
    except InsufficientHistoryError:
        return current_raw, None

    return current_raw, rotation_pct


def compute_risk_appetite(
    as_of: str,
    oas_series: RawSeries,
    qqq_series: RawSeries,
    iwm_series: RawSeries,
    benchmark_series: RawSeries,
    credit_transform: CreditTransform,
    weights: RiskAppetiteWeights,
) -> RiskAppetiteResult:
    """Full Risk Appetite computation for one as_of date. Raises
    RiskAppetiteUnavailableError if any required component is unavailable —
    fail-closed per C16, never a partial/neutralized score."""
    credit_result = credit_transform(oas_series, as_of)
    if credit_result is None:
        raise RiskAppetiteUnavailableError(f"credit transform unavailable as of {as_of}")
    credit_level_pct, credit_change_score = credit_result

    growth_raw, growth_pct = compute_rotation_pct(qqq_series, benchmark_series, as_of)
    if growth_raw is None or growth_pct is None:
        raise RiskAppetiteUnavailableError(f"growth_rotation unavailable as of {as_of}")

    small_cap_raw, small_cap_pct = compute_rotation_pct(iwm_series, benchmark_series, as_of)
    if small_cap_raw is None or small_cap_pct is None:
        raise RiskAppetiteUnavailableError(f"small_cap_rotation unavailable as of {as_of}")

    # Bounded convex combination: credit_level_pct and both rotation
    # percentiles are all on [0,1] (credit_level_pct per the CreditTransform
    # Protocol's documented contract; both rotation percentiles rescaled at
    # compute_rotation_pct's own manifest-field boundary), so a weighted sum
    # with nonnegative weights summing to one stays on that same [0,1] scale
    # — no additive clipped adjustment, no smoothing.
    score = (
        weights.weight_credit * credit_level_pct
        + weights.weight_growth_rotation * growth_pct
        + weights.weight_small_cap_rotation * small_cap_pct
    )

    return RiskAppetiteResult(
        as_of=as_of,
        credit_level_pct=credit_level_pct,
        credit_change_score=credit_change_score,
        growth_rotation_raw=growth_raw,
        growth_rotation_pct=growth_pct,
        small_cap_rotation_raw=small_cap_raw,
        small_cap_rotation_pct=small_cap_pct,
        risk_appetite_score=score,
    )
