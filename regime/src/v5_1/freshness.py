"""Market Regime v5.1 — Slice 1: Contracts & Primitives, module 4.1's
freshness/as-of evaluator.

Implements design §2's "Alignment / freshness / warm-up" stage and §4.1's
fail-closed rule using the boundary-semantics vocabulary already CLOSED in
`Freshness_Threshold_Experiment_v1.0.md` §2 — CURRENT/STALE/MISSING/MISALIGNED
states with the exact reason-code mapping. This module deliberately does NOT
reinvent that vocabulary; per implementation plan §5, this is "the single
most important cross-artifact consistency requirement in this plan" — a
divergent definition here would silently invalidate the frozen freshness
experiment's own preregistration.

Accepts `N` (the allowance, in missed expected sessions/business days) as an
injected per-call parameter, never a hardcoded constant — the frozen
freshness experiment supplies candidate values from its own grid (spec §1);
this evaluator has no opinion on what N should be, only on how to apply it.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import Enum


class FreshnessState(str, Enum):
    """Mutually exclusive; exactly one applies. Verbatim from
    Freshness_Threshold_Experiment_v1.0.md §2."""

    CURRENT = "CURRENT"
    STALE = "STALE"
    MISSING = "MISSING"
    MISALIGNED = "MISALIGNED"


class ReasonCode(str, Enum):
    """Closed vocabulary; no other code is valid. Verbatim from
    Freshness_Threshold_Experiment_v1.0.md §2's state->reason mapping."""

    SOURCE_LATE_WITHIN_GRACE = "SOURCE_LATE_WITHIN_GRACE"
    SOURCE_STALE = "SOURCE_STALE"
    SOURCE_MISSING = "SOURCE_MISSING"
    SOURCE_MISALIGNED = "SOURCE_MISALIGNED"


# Exact state -> allowed-reason-code mapping, mirroring
# freshness_injection_registry.v1.0.json's `reason_code_contract` and
# verify_freshness_registry.py's EXPECTED_REASON_MAPPING — the same closed
# vocabulary, not a re-derived one.
ALLOWED_REASONS: dict[FreshnessState, tuple[ReasonCode | None, ...]] = {
    FreshnessState.CURRENT: (None, ReasonCode.SOURCE_LATE_WITHIN_GRACE),
    FreshnessState.STALE: (ReasonCode.SOURCE_STALE,),
    FreshnessState.MISSING: (ReasonCode.SOURCE_MISSING,),
    FreshnessState.MISALIGNED: (ReasonCode.SOURCE_MISALIGNED,),
}


@dataclass(frozen=True)
class FreshnessResult:
    """The evaluator's output for one (as_of, observation) pair. `usable`
    mirrors design §4.1's fail-closed rule: only CURRENT observations are
    usable for measurement; STALE/MISSING/MISALIGNED all make the dependent
    pillar/Condition unavailable (never neutral-filled or zeroed)."""

    state: FreshnessState
    reason: ReasonCode | None
    missed_sessions: int | None  # None when MISSING (nothing to count from)

    @property
    def usable(self) -> bool:
        return self.state == FreshnessState.CURRENT

    def __post_init__(self) -> None:
        allowed = ALLOWED_REASONS[self.state]
        if self.reason not in allowed:
            raise ValueError(
                f"FreshnessResult: state={self.state} paired with disallowed reason={self.reason} "
                f"(allowed: {allowed})"
            )


def evaluate_freshness(
    *,
    as_of: str,
    last_observation_date: str | None,
    expected_sessions_since: list[str],
    n_allowance: int,
    point_in_time_violation: bool = False,
) -> FreshnessResult:
    """Evaluate one observation's freshness state as of `as_of`.

    Parameters
    ----------
    as_of:
        ISO date, the required as-of session/business day.
    last_observation_date:
        ISO date of the most recent usable observation, or None if no prior
        usable observation exists at all (-> MISSING).
    expected_sessions_since:
        The exact list of expected sessions/business days strictly AFTER
        `last_observation_date` and up to and including `as_of`, per the
        family's own calendar (XNYS/Cboe expected-session count, or FRED
        business-day count applied after the T+1 floor). This is what the
        caller computes from the pinned expected-session calendar artifact —
        this function does no calendar arithmetic of its own, per plan §5's
        "reuse the pinned artifact, never recompute a calendar inline."
    n_allowance:
        The injected candidate N (missed expected sessions/business days
        allowed before STALE). Per spec §2's boundary arithmetic: CURRENT
        through N missed sessions inclusive; STALE at N+1 or more.
    point_in_time_violation:
        True if the observation would otherwise be CURRENT by count but
        fails the family's point_in_time_join_rule (e.g. same-day lookahead).
        Checked LAST per spec §2 (an observation is "otherwise CURRENT" first).

    Returns
    -------
    FreshnessResult with the applicable state and reason code.
    """
    if n_allowance < 0:
        raise ValueError(f"n_allowance must be nonnegative, got {n_allowance}")

    if last_observation_date is None:
        return FreshnessResult(FreshnessState.MISSING, ReasonCode.SOURCE_MISSING, None)

    try:
        as_of_date = datetime.date.fromisoformat(as_of)
        last_date = datetime.date.fromisoformat(last_observation_date)
    except ValueError as exc:
        raise ValueError(f"as_of and last_observation_date must be ISO dates: {exc}") from exc

    if last_date > as_of_date:
        raise ValueError(
            f"last_observation_date {last_observation_date} is after as_of {as_of} "
            f"— this would be a lookahead, not a freshness question; caller error"
        )

    # Validate expected_sessions_since itself rather than trusting a bare
    # length count — a caller could pass a malformed, out-of-range, or
    # duplicated list, and a silent len() would corrupt the resulting state
    # with no error (found during self-review: the original version trusted
    # this input unconditionally, which fails plan §7.3's fail-closed gate
    # for a primitive callable independently of its usual calendar producer).
    seen: set[str] = set()
    for d in expected_sessions_since:
        try:
            parsed = datetime.date.fromisoformat(d)
        except ValueError as exc:
            raise ValueError(f"expected_sessions_since contains a non-ISO date {d!r}: {exc}") from exc
        if not (last_date < parsed <= as_of_date):
            raise ValueError(
                f"expected_sessions_since entry {d!r} is outside the required range "
                f"(strictly after {last_observation_date}, up to and including {as_of}) — caller error"
            )
        if d in seen:
            raise ValueError(f"expected_sessions_since contains a duplicate date: {d!r}")
        seen.add(d)

    missed = len(expected_sessions_since)

    # Boundary arithmetic per spec §2: CURRENT through N missed sessions
    # inclusive of N itself; STALE at N+1 or more — never at exactly N.
    if missed > n_allowance:
        return FreshnessResult(FreshnessState.STALE, ReasonCode.SOURCE_STALE, missed)

    # Within allowance (0 <= missed <= n_allowance): otherwise CURRENT.
    # Now check the point-in-time join rule LAST, per spec §2's own
    # ordering ("would otherwise be CURRENT ... but fails ...").
    if point_in_time_violation:
        return FreshnessResult(FreshnessState.MISALIGNED, ReasonCode.SOURCE_MISALIGNED, missed)

    if missed == 0:
        return FreshnessResult(FreshnessState.CURRENT, None, missed)
    return FreshnessResult(FreshnessState.CURRENT, ReasonCode.SOURCE_LATE_WITHIN_GRACE, missed)
