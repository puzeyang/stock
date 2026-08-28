"""Market Regime v5.1 — Slice 1: Contracts & Primitives, causal 504-session
empirical midrank primitive.

Design §5.1, exact tie formula:

    less  = count(window_value < current_value)
    equal = count(window_value == current_value)
    percentile = 100 * (less + 0.5 * equal) / 504

Requirements (§5.1, all enforced here):
- exactly 504 valid expected-session observations (including the current one);
- ties use the formula above;
- no expanding-window shortcut;
- no hidden winsorization, forward fill, neutral fill, or interpolation;
- causal only — the window never includes any observation after the current one.

This is a shared primitive (design §16.10, CLOSED): normalize each canonical
raw feature once and reuse it; never rerank a combined score. Callers are
responsible for that discipline; this function only guarantees a single
correct midrank computation.
"""
from __future__ import annotations

REQUIRED_WINDOW_SIZE = 504


class InsufficientHistoryError(Exception):
    """Raised when fewer than REQUIRED_WINDOW_SIZE valid observations are
    available. Per design §5.1, there is no expanding-window shortcut — an
    incomplete window is not a smaller-window approximation, it is an
    unavailable normalization, and callers must treat this as such (fail
    closed per §4.1), never silently proceed with fewer observations."""


def causal_midrank(window: list[float], current_value: float) -> float:
    """Compute the causal 504-session empirical midrank percentile for
    `current_value` within `window`.

    `window` MUST be exactly the 504 valid expected-session observations
    ending at and including the current session (i.e. `window[-1]` should
    equal `current_value`, and every element must be causal — no lookahead).
    This function does not itself enforce the causality of the window's
    construction (that is the caller's responsibility, verified by the
    conformance suite's path-dependence checks per plan §7.5); it enforces
    only the exact size and the exact tie formula.
    """
    if len(window) != REQUIRED_WINDOW_SIZE:
        raise InsufficientHistoryError(
            f"causal_midrank requires exactly {REQUIRED_WINDOW_SIZE} valid observations, got {len(window)}"
        )

    # Design §5.1: the midrank is computed "including the current valid
    # observation," meaning current_value MUST be a member of window — not
    # merely a same-length coincidence. Found during solo self-review
    # (ChatGPT unavailable): the original version never checked this, so a
    # caller passing a current_value absent from window would silently get
    # a formula-shaped but semantically meaningless result (e.g. `equal=0`
    # when it should have been >=1). Uses the exact `==` the formula itself
    # uses for the equal-count, not a tolerance-based membership check.
    if not any(v == current_value for v in window):
        raise ValueError(
            f"current_value {current_value!r} is not a member of window — design §5.1 requires the "
            f"midrank to include the current observation within the 504-observation window itself"
        )

    less = sum(1 for v in window if v < current_value)
    equal = sum(1 for v in window if v == current_value)
    percentile = 100.0 * (less + 0.5 * equal) / REQUIRED_WINDOW_SIZE
    return percentile
