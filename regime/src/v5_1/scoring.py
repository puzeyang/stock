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

**Hit rate + vol-normalized return (added per Message[203], following
Message[202]'s finding)**: a full-history, non-crisis-selected run
found RISK_OFF's higher raw mean forward return was almost entirely a
MAGNITUDE effect — RISK_ON and RISK_OFF had nearly identical hit rates
(fraction of dates with a positive forward return), meaning raw mean
percent return alone is not a fair way to rank configs (a config could
score higher just by spending more time in RISK_OFF near real washed-out
lows, a different property than classifying regime more accurately).
`summarize_by_state` now also reports `hit_rate` (direction, independent
of size) and `mean_vol_normalized_forward_return` (the forward return
divided by trailing realized volatility scaled to the same horizon,
reusing `_realized_vol_estimator` unchanged — asks whether a state's
moves are still large after accounting for how volatile the market
already was), so a config comparison can separate "predicts direction
better," "predicts a bigger-than-typical move," and "just happens to
occur near naturally larger swings" instead of conflating all three.

**Confidence intervals (added per Message[206], closing the gap
Message[205] itself flagged as open)**: every `hit_rate` comparison in
Messages[201]-[205] was a bare point estimate on sample sizes as small
as n=45 per state group — no check that a reported gap (e.g. "71.1% vs
73.6%") was distinguishable from what random noise alone could produce
at that sample size. `summarize_by_state` now also reports
`hit_rate_ci_low`/`hit_rate_ci_high` (a 95% Wilson score interval, the
standard textbook choice for small/moderate-n binomial proportions —
see `wilson_score_interval`), and `hit_rates_distinguishable` gives a
conservative (non-overlapping-CIs) check for whether two groups'
hit rates actually differ at the 95% level.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .engine import (
    RawSeriesBundle,
    TestScaffoldingConfig,
    TEST_SCAFFOLDING_CONFIG,
    new_running_engine_state,
    run_engine_for_date,
    _realized_vol_estimator,
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


def vol_normalized_forward_return(
    benchmark: RawSeries, as_of: str, horizon_sessions: int, raw_forward_return: float | None,
) -> float | None:
    """`raw_forward_return` divided by the TRAILING realized volatility
    scaled to the same `horizon_sessions` horizon — answers "how many
    trailing-vol-units did the market move," not just "how many percent."
    Added per Message[202]'s finding: RISK_OFF's higher raw mean forward
    return turned out to be almost entirely a MAGNITUDE effect (hit rate
    was nearly identical between RISK_OFF/RISK_ON), consistent with
    RISK_OFF disproportionately being called in choppier/higher-vol
    periods where a 20-session move is mechanically larger in percent
    terms regardless of direction. Dividing by trailing vol asks whether
    a state's forward moves are still large AFTER accounting for how
    volatile the market already was at the time — a fairer basis for
    comparing configs than raw percent return.

    Reuses `_realized_vol_estimator` (`engine.py`) UNCHANGED — the same
    real, trailing-20-session annualized realized-vol formula already
    used in Stability's own pillar computation, not a new formula
    invented for this comparison. De-annualized via `/ sqrt(252)` then
    re-scaled to `horizon_sessions` via `* sqrt(horizon_sessions)`,
    standard volatility time-scaling (variance scales linearly with time
    under the i.i.d.-returns assumption `_realized_vol_estimator` itself
    already makes).

    Fail-closed: returns `None` if `raw_forward_return` is `None`, the
    realized-vol estimator is unavailable (insufficient trailing
    history), or the estimated vol is exactly 0.0 (would divide by zero
    — a real, if rare, edge case worth failing closed on rather than
    returning +/-inf)."""
    if raw_forward_return is None:
        return None
    annualized_vol = _realized_vol_estimator(benchmark, as_of)
    if annualized_vol is None or annualized_vol == 0.0:
        return None
    horizon_vol = annualized_vol / (252.0 ** 0.5) * (horizon_sessions ** 0.5)
    if horizon_vol == 0.0:
        return None
    return raw_forward_return / horizon_vol


@dataclass(frozen=True)
class ScoredDate:
    as_of: str
    state: str | None
    condition_score: float | None
    forward_return: float | None
    vol_normalized_forward_return: float | None


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
        vol_norm = vol_normalized_forward_return(raw.benchmark, as_of, horizon_sessions, fwd)
        scored.append(ScoredDate(
            as_of=as_of,
            state=record.get("state"),
            condition_score=record.get("condition_score"),
            forward_return=fwd,
            vol_normalized_forward_return=vol_norm,
        ))
    return ScoredReplayResult(horizon_sessions=horizon_sessions, scored_dates=tuple(scored))


_WILSON_Z_95 = 1.959963984540054  # z-score for a 95% two-sided normal CI, standard constant (Abramowitz & Stegun 26.2.23 / any statistics reference), not fit to this data


def wilson_score_interval(hits: int, n: int, z: float = _WILSON_Z_95) -> tuple[float, float]:
    """95% (by default) Wilson score confidence interval for a binomial
    proportion `hits/n`. Added per Message[205]'s own flagged gap: every
    `hit_rate` comparison in Messages[201]-[205] was reported as a bare
    point estimate (e.g. "71.1% vs 73.6%") on sample sizes as small as
    n=45-180 per group, with no check that the gap exceeds what random
    noise alone could produce.

    Wilson score, not the naive normal approximation (`p +/- z*sqrt(p(1-p)/n)`):
    the naive interval can extend outside [0,1] and is known to behave
    poorly at the sample sizes and hit rates seen throughout this
    investigation (n in the tens to low hundreds, hit rates 60-80%) —
    Wilson score stays within [0,1] by construction and is the standard
    textbook recommendation for exactly this regime (Wilson 1927; e.g.
    Brown/Cai/DasGupta 2001 recommends Wilson over the normal
    approximation for small-to-moderate n). Not a novel formula — the
    standard closed-form:
    `(p + z^2/(2n) +/- z*sqrt(p(1-p)/n + z^2/(4n^2))) / (1 + z^2/n)`.

    Returns `(0.0, 0.0)` if `n == 0` (fail-closed — no data means no
    interval, not a degenerate [0,1] or [nan,nan])."""
    if n == 0:
        return (0.0, 0.0)
    p = hits / n
    denom = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    spread = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    low = (center - spread) / denom
    high = (center + spread) / denom
    return (max(0.0, low), min(1.0, high))


@dataclass(frozen=True)
class StateForwardStats:
    state: str
    count: int
    mean_forward_return: float
    median_forward_return: float
    min_forward_return: float
    max_forward_return: float
    hit_rate: float
    hit_rate_ci_low: float
    hit_rate_ci_high: float
    mean_vol_normalized_forward_return: float | None
    vol_normalized_count: int


def summarize_by_state(result: ScoredReplayResult) -> tuple[StateForwardStats, ...]:
    """Group scored dates by `state` label, computing descriptive stats
    of the REAL forward return within each group.

    Dates with `state=None` (engine unavailable — e.g. insufficient
    history) or `forward_return=None` (too close to the data's edge for
    a full horizon) are excluded from every group, not counted as zero —
    this is a fail-closed exclusion, consistent with the rest of this
    engine's None-handling, not a silent substitution. Groups are
    returned sorted by state label for deterministic output; a state
    with zero qualifying dates in the input is simply absent from the
    result (never fabricated as a zero-count row).

    `hit_rate` (added per Message[202]/[203]): fraction of the group's
    dates with a STRICTLY POSITIVE forward return — separates DIRECTION
    (did the market go up) from MAGNITUDE (mean/median return), since
    Message[202] found these can tell very different stories for the
    same state (RISK_OFF/RISK_ON had nearly identical hit rates despite
    a large mean-return gap).

    `hit_rate_ci_low`/`hit_rate_ci_high` (added per Message[206],
    addressing the gap Message[205] itself flagged as open): a 95%
    Wilson score confidence interval around `hit_rate` (see
    `wilson_score_interval`) — every hit-rate comparison in
    Messages[201]-[205] reported bare point estimates on sample sizes as
    small as n=45; these bounds let a caller check whether two configs'
    hit rates are actually distinguishable from noise at this sample
    size, rather than assuming any nonzero gap is meaningful.

    `mean_vol_normalized_forward_return`/`vol_normalized_count` (added
    per Message[203]): mean of `vol_normalized_forward_return` within
    the group, a separate, smaller-count exclusion (a date needs BOTH a
    computable forward return AND a computable trailing realized vol —
    `vol_normalized_count` is reported explicitly alongside `count`
    rather than silently assumed equal, since the two exclusion sets are
    not identical). `None` if zero dates in the group have a computable
    vol-normalized value."""
    by_state: dict[str, list[ScoredDate]] = {}
    for sd in result.scored_dates:
        if sd.state is None or sd.forward_return is None:
            continue
        by_state.setdefault(sd.state, []).append(sd)

    stats: list[StateForwardStats] = []
    for state_label in sorted(by_state):
        group = by_state[state_label]
        returns = sorted(sd.forward_return for sd in group)
        n = len(returns)
        mid = n // 2
        median = returns[mid] if n % 2 == 1 else (returns[mid - 1] + returns[mid]) / 2.0
        hits = sum(1 for r in returns if r > 0.0)

        vol_norm_values = [sd.vol_normalized_forward_return for sd in group if sd.vol_normalized_forward_return is not None]
        mean_vol_norm = sum(vol_norm_values) / len(vol_norm_values) if vol_norm_values else None

        ci_low, ci_high = wilson_score_interval(hits, n)

        stats.append(StateForwardStats(
            state=state_label,
            count=n,
            mean_forward_return=sum(returns) / n,
            median_forward_return=median,
            min_forward_return=returns[0],
            max_forward_return=returns[-1],
            hit_rate=hits / n,
            hit_rate_ci_low=ci_low,
            hit_rate_ci_high=ci_high,
            mean_vol_normalized_forward_return=mean_vol_norm,
            vol_normalized_count=len(vol_norm_values),
        ))
    return tuple(stats)


def hit_rates_distinguishable(a: StateForwardStats, b: StateForwardStats) -> bool:
    """Cheap, honest check for whether two groups' hit rates are
    distinguishable from noise at the 95% level: True if their Wilson
    score confidence intervals do NOT overlap. This is a conservative
    (non-overlapping-CIs) check, not a proper two-proportion hypothesis
    test (e.g. a chi-squared or Fisher's exact test on the 2x2 table
    would have more power and could find a significant difference even
    when the individual CIs slightly overlap) — deliberately the
    simpler, more conservative tool: it never claims two groups differ
    unless their individual uncertainty ranges are already clearly
    separated, at the cost of sometimes calling a real difference
    "not distinguishable" when a sharper test would detect it. Given
    this investigation's history of overgeneralizing point estimates
    (Message[203]'s correction of Message[202]), erring conservative is
    the right default here; a caller wanting more power can compare
    `hit_rate_ci_low`/`hit_rate_ci_high` directly instead."""
    return a.hit_rate_ci_high < b.hit_rate_ci_low or b.hit_rate_ci_high < a.hit_rate_ci_low
