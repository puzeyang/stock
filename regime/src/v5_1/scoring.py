"""Market Regime v5.1 — Forward-Looking Scoring Tool (evaluation-only,
NOT part of the 4.1-4.13 module set, NOT production code).

**Why this exists**: Messages[199]/[200] (discussion log) both independently
concluded the same thing from two different angles — Breadth's blend
weight (Message[199]) and Breadth's/Direction's SMA/MA window lengths
(Message[200]) cannot be calibrated by "does this match real history"
checks alone, because multiple window/weight choices are each internally
consistent and each have real, verified trade-offs (faster reaction vs.
more noise-resistant). Deciding which trade-off point is BETTER requires
an objective, forward-looking target function this engine never had. Per
the human's explicit direction (AskUserQuestion, following Message[200]),
this module builds that target function: for each `as_of` date a config
produces a `state`/`condition_score` for, look up what the real S&P 500
ACTUALLY did over the following 20 trading sessions, and report the
statistical relationship between the two — e.g. does RISK_OFF really
precede lower forward returns than RISK_ON, on the real historical data
this engine has access to.

**Explicitly NOT an extension of `replay.py`'s scope.** `replay.py`
(module 4.13) states its own non-goal verbatim: "does NOT compute
portfolio outcomes." This module IS a portfolio/forward-outcome
computation — deliberately kept in a separate file, under a separate
name, so that non-goal statement remains true of `replay.py` itself.

**NOT production code, NOT a trading signal, NOT a backtest with P&L.**
This computes a single descriptive statistic (mean/median forward
return, grouped by state) over the SAME 3 real historical stress
episodes already used throughout this investigation (2018 Christmas Eve
Massacre, 2020 COVID crash, 2022 bear market) plus whatever other date
range a caller supplies — it does not simulate a strategy, position
sizing, transaction costs, or a portfolio in any sense. Its entire
purpose is to give the ongoing EMPIRICAL-parameter investigation
(window lengths, blend weights, pillar weights) an objective way to ask
"does config A's regime classification correspond to real forward
market behavior better than config B's," which no prior tool in this
codebase could answer.

**Forward return convention**: TRADING-DAY horizon, not calendar days —
`horizon_sessions=20` means "the 20th observation in `benchmark.observations`
strictly after `as_of`," matching how every other EMPIRICAL window in
this engine (Direction's MA windows, Breadth's SMA windows) already
counts sessions, not calendar time. Fail-closed: if fewer than
`horizon_sessions` future observations exist after `as_of` (e.g. `as_of`
is too close to the end of the pinned dataset), returns `None` rather
than truncating the window — silently truncating would quietly change
what a 20-session return means near the data's edge.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .engine import (
    RawSeriesBundle,
    TestScaffoldingConfig,
    TEST_SCAFFOLDING_CONFIG,
    new_running_engine_state,
    run_engine_for_date,
)
from .contracts import Manifest
from .raw_features import RawSeries


def forward_return(benchmark: RawSeries, as_of: str, horizon_sessions: int) -> float | None:
    """Real forward total return over the next `horizon_sessions` TRADING
    days after `as_of` (not including `as_of` itself), i.e.
    `future_close / as_of_close - 1`. `as_of_close` uses the same
    point-in-time `as_of()` lookup every other module in this engine uses
    (most recent observation on or before `as_of`) — never assumes an
    exact-date row exists. Returns `None` (fail-closed, never a
    truncated/partial-horizon estimate) if either the `as_of` anchor or
    the `horizon_sessions`-th future observation is unavailable.
    """
    anchor = benchmark.as_of(as_of)
    if anchor is None:
        return None
    future = [o for o in benchmark.observations if o.date > anchor.date]
    if len(future) < horizon_sessions:
        return None
    target = future[horizon_sessions - 1]
    return target.value / anchor.value - 1.0


@dataclass(frozen=True)
class ScoredDate:
    as_of: str
    state: str | None
    condition_score: float | None
    forward_return: float | None


@dataclass(frozen=True)
class ScoredReplayResult:
    horizon_sessions: int
    scored_dates: tuple[ScoredDate, ...]


def run_scored_replay(
    dates: tuple[str, ...],
    raw: RawSeriesBundle,
    manifest: Manifest,
    config: TestScaffoldingConfig = TEST_SCAFFOLDING_CONFIG,
    horizon_sessions: int = 20,
) -> ScoredReplayResult:
    """Run the full engine across `dates` (ascending, same ordering
    requirement as `replay.replay()` — state is order-dependent) for
    `config`, pairing each date's `state`/`condition_score` with the REAL
    forward return over the following `horizon_sessions` trading days.
    One fresh `RunningEngineState` per call, never shared across configs
    (same discipline as `replay.replay()`, for the same reason — shared
    state would let one config's persisted counters leak into another
    config's run)."""
    state = new_running_engine_state(config)
    scored: list[ScoredDate] = []
    for as_of in dates:
        record = run_engine_for_date(as_of, raw, state, manifest, config=config)
        fwd = forward_return(raw.benchmark, as_of, horizon_sessions)
        scored.append(ScoredDate(
            as_of=as_of,
            state=record.get("state"),
            condition_score=record.get("condition_score"),
            forward_return=fwd,
        ))
    return ScoredReplayResult(horizon_sessions=horizon_sessions, scored_dates=tuple(scored))


@dataclass(frozen=True)
class StateForwardStats:
    state: str
    count: int
    mean_forward_return: float
    median_forward_return: float
    min_forward_return: float
    max_forward_return: float


def summarize_by_state(result: ScoredReplayResult) -> tuple[StateForwardStats, ...]:
    """Group scored dates by `state` label, computing descriptive stats
    (mean/median/min/max) of the REAL forward return within each group.
    Dates with `state=None` (engine unavailable — e.g. insufficient
    history) or `forward_return=None` (too close to the data's edge for
    a full horizon) are excluded from every group, not counted as zero —
    this is a fail-closed exclusion, consistent with the rest of this
    engine's None-handling, not a silent substitution. Groups are
    returned sorted by state label for deterministic output; a state
    with zero qualifying dates in the input is simply absent from the
    result (never fabricated as a zero-count row)."""
    by_state: dict[str, list[float]] = {}
    for sd in result.scored_dates:
        if sd.state is None or sd.forward_return is None:
            continue
        by_state.setdefault(sd.state, []).append(sd.forward_return)

    stats: list[StateForwardStats] = []
    for state_label in sorted(by_state):
        returns = sorted(by_state[state_label])
        n = len(returns)
        mid = n // 2
        median = returns[mid] if n % 2 == 1 else (returns[mid - 1] + returns[mid]) / 2.0
        stats.append(StateForwardStats(
            state=state_label,
            count=n,
            mean_forward_return=sum(returns) / n,
            median_forward_return=median,
            min_forward_return=returns[0],
            max_forward_return=returns[-1],
        ))
    return tuple(stats)
