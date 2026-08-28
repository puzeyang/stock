"""Market Regime v5.1 — Slice 3 (continued): TrendQuality (module 4.4).

**Gap found during solo self-review** (Message[175]): the original Slice 3
delivery (`direction.py`) implemented Direction's structure/confirmation
logic but never actually built TrendQuality's own computation — it only
referenced TrendQuality conceptually as an internal Direction input. This
module fills that gap before Slice 7 (Condition) needs it, since design
§6.3 requires a "Direction adjustment coefficient" — TrendQuality feeding
INTO direction_score — which cannot exist without TrendQuality itself
existing.

Design §6.3 (C6): direction-neutral benchmark-price path quality, two
separately published components:

- `linearity_raw`/`linearity_pct`: causal midrank of rolling regression R²;
- `path_efficiency_raw`/`path_efficiency_pct`: causal midrank of absolute
  net movement divided by cumulative absolute movement.

Combined with nonnegative weights summing to one. No reranking or smoothing
of the combination. `concentration_pct` is explicitly removed (participation
belongs exclusively to Breadth); EMA-crossing-count is a separate challenger
diagnostic, never conflated with path efficiency.

Both `linearity_pct` and `path_efficiency_pct` reuse Slice 1's exact CLOSED
`causal_midrank` primitive — the same pattern as Slice 5's rotation
percentiles, not a reimplementation.

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`):
`linearity_raw`, `linearity_pct`, `path_efficiency_raw`,
`path_efficiency_pct`, `trend_quality`.

**EMPIRICAL scope:** regression domain, horizons, zero-movement handling,
weights, and the Direction adjustment coefficient are all EMPIRICAL
(§17.3) — injected, never hardcoded.
"""
from __future__ import annotations

from dataclasses import dataclass

from .normalization import causal_midrank, InsufficientHistoryError, REQUIRED_WINDOW_SIZE
from .raw_features import RawSeries


class TrendQualityUnavailableError(Exception):
    """Signals TrendQuality is genuinely unavailable for this as_of date
    per design §4.1's fail-closed rule — never neutralized to a default."""


@dataclass(frozen=True)
class TrendQualityWeights:
    """EMPIRICAL (§17.3) — injected. Nonnegative weights summing to one,
    combining linearity_pct and path_efficiency_pct into trend_quality."""

    weight_linearity: float
    weight_path_efficiency: float

    def __post_init__(self) -> None:
        if self.weight_linearity < 0 or self.weight_path_efficiency < 0:
            raise ValueError("TrendQualityWeights: weights must be nonnegative")
        total = self.weight_linearity + self.weight_path_efficiency
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"TrendQualityWeights: weights must sum to exactly 1.0, got {total}")


@dataclass(frozen=True)
class TrendQualityResult:
    as_of: str
    linearity_raw: float
    linearity_pct: float
    path_efficiency_raw: float
    path_efficiency_pct: float
    trend_quality: float


def compute_regression_r_squared(window: list[float]) -> float:
    """R² of a simple linear (OLS) regression of `window`'s values against
    their own index (0, 1, 2, ..., len(window)-1) — "rolling regression R²"
    per design §6.3. `window` MUST already be the caller's chosen causal
    regression domain (a fixed-length trailing window of benchmark closes,
    per whatever EMPIRICAL horizon is chosen); this function only computes
    R² for whatever window it's given, it does not choose the window length
    or domain itself.

    Handles the zero-movement/constant-window edge case explicitly (design
    §6.3: "zero-movement handling... EMPIRICAL") — returns 0.0 when the
    window is perfectly flat (zero variance), since a flat line technically
    has an undefined R² (0/0) but zero-movement is the definitionally
    "least linear-trend" case, not an error.
    """
    n = len(window)
    if n < 2:
        raise ValueError(f"compute_regression_r_squared requires at least 2 points, got {n}")

    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(window) / n

    ss_xx = sum((xi - x_mean) ** 2 for xi in x)
    ss_yy = sum((yi - y_mean) ** 2 for yi in window)
    ss_xy = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, window))

    if ss_yy == 0:
        # Perfectly flat window: zero-movement edge case, EMPIRICAL
        # disposition chosen here as 0.0 (least linear-trend), not an error.
        return 0.0
    if ss_xx == 0:
        # Cannot happen for n >= 2 with x = 0..n-1, but guarded explicitly
        # rather than allowing a ZeroDivisionError to leak through.
        raise TrendQualityUnavailableError("regression domain has zero index variance — malformed window")

    r = ss_xy / (ss_xx ** 0.5 * ss_yy ** 0.5)
    return r ** 2


def compute_path_efficiency_raw(window: list[float]) -> float:
    """Absolute net movement divided by cumulative absolute movement, per
    design §6.3. `window` is the caller's chosen causal domain (ascending,
    ending at the current observation).

    Zero-movement handling (EMPIRICAL disposition, §6.3): if cumulative
    absolute movement is zero (a perfectly flat window — every step is
    exactly zero), path efficiency is defined as 0.0 (no discernible path
    at all, not "perfectly efficient"), rather than raising a division
    error or asserting 1.0 (which would misleadingly suggest a clean, fully
    efficient trend when there was no movement to be efficient about).
    """
    n = len(window)
    if n < 2:
        raise ValueError(f"compute_path_efficiency_raw requires at least 2 points, got {n}")

    net_movement = abs(window[-1] - window[0])
    cumulative_movement = sum(abs(window[i] - window[i - 1]) for i in range(1, n))

    if cumulative_movement == 0:
        return 0.0
    return net_movement / cumulative_movement


def compute_trend_quality(
    as_of: str,
    benchmark_series: RawSeries,
    regression_window: int,
    path_efficiency_window: int,
    weights: TrendQualityWeights,
) -> TrendQualityResult:
    """Full TrendQuality computation for one as_of date. Raises
    TrendQualityUnavailableError if either component lacks sufficient
    history — fail-closed per C16, never a partial/neutralized score.
    """
    if regression_window <= 0 or path_efficiency_window <= 0:
        raise ValueError(
            f"regression_window and path_efficiency_window must be positive, "
            f"got {regression_window}, {path_efficiency_window}"
        )

    regression_domain_window = benchmark_series.window_ending(as_of, regression_window)
    if regression_domain_window is None:
        raise TrendQualityUnavailableError(f"insufficient regression-domain history as of {as_of}")
    regression_values = [o.value for o in regression_domain_window]
    linearity_raw = compute_regression_r_squared(regression_values)

    path_domain_window = benchmark_series.window_ending(as_of, path_efficiency_window)
    if path_domain_window is None:
        raise TrendQualityUnavailableError(f"insufficient path-efficiency-domain history as of {as_of}")
    path_values = [o.value for o in path_domain_window]
    path_efficiency_raw = compute_path_efficiency_raw(path_values)

    # Both raw values go through Slice 1's exact causal 504-session midrank
    # — this requires a 504-length window of the RAW linearity/path-
    # efficiency values themselves (a rolling series of R²/path-efficiency
    # values, one per session), not a window of benchmark prices. Building
    # that rolling series requires recomputing linearity_raw/path_efficiency_raw
    # at every one of the prior 503 sessions too.
    linearity_pct = _rolling_midrank(
        benchmark_series, as_of, regression_window,
        lambda w: compute_regression_r_squared(w), linearity_raw,
    )
    if linearity_pct is None:
        raise TrendQualityUnavailableError(f"insufficient history for linearity_pct 504-session midrank as of {as_of}")

    path_efficiency_pct = _rolling_midrank(
        benchmark_series, as_of, path_efficiency_window,
        lambda w: compute_path_efficiency_raw(w), path_efficiency_raw,
    )
    if path_efficiency_pct is None:
        raise TrendQualityUnavailableError(f"insufficient history for path_efficiency_pct 504-session midrank as of {as_of}")

    trend_quality = weights.weight_linearity * linearity_pct + weights.weight_path_efficiency * path_efficiency_pct

    return TrendQualityResult(
        as_of=as_of,
        linearity_raw=linearity_raw,
        linearity_pct=linearity_pct,
        path_efficiency_raw=path_efficiency_raw,
        path_efficiency_pct=path_efficiency_pct,
        trend_quality=trend_quality,
    )


def _rolling_midrank(
    benchmark_series: RawSeries,
    as_of: str,
    domain_window: int,
    raw_fn,
    current_raw: float,
) -> float | None:
    """Build the 504-session rolling series of `raw_fn`'s output (each
    computed over its own `domain_window`-length trailing window of
    benchmark values, ending at each of the prior 503 sessions plus the
    current one) and midrank `current_raw` within it. Returns None if
    there isn't enough history for either the 504-session midrank window
    itself, or for any individual session's own `domain_window`-length
    regression/path domain within that range.
    """
    midrank_window = benchmark_series.window_ending(as_of, REQUIRED_WINDOW_SIZE)
    if midrank_window is None:
        return None

    rolling_raw_values: list[float] = []
    for obs in midrank_window:
        session_domain = benchmark_series.window_ending(obs.date, domain_window)
        if session_domain is None:
            return None
        session_values = [o.value for o in session_domain]
        rolling_raw_values.append(raw_fn(session_values))

    # Rescaled to [0,1] here, at this manifest-field boundary —
    # causal_midrank() itself returns its literal CLOSED-formula 0-100 scale
    # (design §5.1) and is deliberately left unchanged; linearity_pct/
    # path_efficiency_pct are manifest-declared [0,1].
    try:
        return causal_midrank(rolling_raw_values, current_raw) / 100.0
    except InsufficientHistoryError:
        return None
