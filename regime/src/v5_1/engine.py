"""Market Regime v5.1 — Engine orchestrator, built to unblock Slice 11
(Replay Interface).

**Scope, per explicit human direction (AskUserQuestion, this slice)**:
Slice 10 (`output_assembly.py`) deliberately did NOT build an end-to-end
orchestrator, since every EMPIRICAL config value across all 11 modules was
(and remains) genuinely undecided — inventing one would misrepresent an
arbitrary placeholder as a production default. Slice 11 (Replay Interface)
cannot exist without one, though: its entire purpose is diffing what the
FULL ENGINE actually does under a clean vs. injected freshness scenario,
which is meaningless without genuinely running modules 4.1-4.12 twice. The
human explicitly reversed the no-placeholder stance for this specific,
narrower purpose: "Build a minimal orchestrator with placeholder config."

**`TEST_SCAFFOLDING_CONFIG` below is NOT a production default under any
circumstance.** Every single value in it is an arbitrary, clearly-labeled
placeholder chosen only so `run_engine_for_date()` can execute end-to-end
on synthetic/pinned-CSV data for the Replay Interface's own testing
purposes (per plan §8's "built and testable independently... with
synthetic fixtures, but do not apply it to the frozen development
injections"). No calibration, backtest, or production run of any kind may
use this config — every real EMPIRICAL decision (pillar weights, veto
thresholds, TrendQuality floors, Impulse transform, Confidence formulas,
direction adjustment, etc.) remains genuinely open, exactly as it was at
the end of Slice 9.

**Update (2026-08-27, Message[189]/[190] — measurement-only backtesting
phase)**: the credit transform and Stability's four domain transforms/
estimators are NO LONGER fixed-constant fakes — they were replaced with
real (if intentionally simple, uncalibrated) standard-finance formulas:
`_causal_midrank_credit_transform` (reuses the engine's own
`causal_midrank()` on real OAS data), `_realized_vol_estimator` (textbook
trailing-20-session annualized historical volatility),
`_drawdown_price_damage_estimator` (textbook drawdown-from-peak), and
four scale-appropriate `MonotoneDecreasingTransform` implementations (see
each function's own docstring below). These are genuinely computed from
real data now, not placeholders — but the specific caps/floors chosen
inside them (`_IMPLIED_VOL_CAP`, `_REALIZED_VOL_CAP`,
`_VOL_CURVE_FLOOR`/`_CEILING`) are still real-but-simple reference values,
not calibrated production thresholds, and `TEST_SCAFFOLDING_CONFIG`'s own
PILLAR WEIGHTS remain uncalibrated equal-weight placeholders regardless.

**KNOWN LIMITATIONS, found during an independent senior-dev review
(2026-08-27) and flagged here at the top rather than only in comments
further down** — these mean the orchestrator's own wiring is real and
sound, but two specific downstream computations it feeds are currently
STRUCTURALLY DEGENERATE, not merely "using placeholder numbers":

1. **CRISIS can never fire through this orchestrator.**
   `_stub_crisis_domain_never_active()` returns `active=False`
   unconditionally for all four domains, every bar. This means
   `replay.py`'s `crisis_entry_lag()` — one of the freshness spec's THREE
   headline engine-dependent metrics (plan §4.13) — can currently only
   ever return `None` (clean run never enters CRISIS) when run through
   this orchestrator. This is a real, consequential gap, not just an
   arbitrary-threshold placeholder: a real CRISIS domain evaluator would
   at least sometimes fire on real 2020 COVID-era or other stress data,
   and this stub is constructed so it structurally cannot, by any input.
2. **Impulse is always ~zero through this orchestrator.**
   `_impulse_horizon()`'s `t-h` endpoint is set to the SAME value as the
   `t` endpoint (`current_condition_score`) whenever no real historical
   `condition_score` series is tracked (which is always, in this
   orchestrator — it does not persist one). `raw_change` is therefore
   always exactly zero whenever the horizon window exists, making
   `impulse_score`/`impulse_fast`/`impulse_slow` structurally degenerate
   in every real run, not just numerically small.

Both limitations were previously disclosed only in the two functions' own
docstrings/comments (see `_stub_crisis_domain_never_active` and
`_impulse_horizon` below) — true, but not given the same prominence as
the smaller "known gaps" list in Message[181]/[183] of the discussion log
(`oas_change`, `binding_event_changes`, etc.). Fixing either limitation
for real (a genuine CRISIS domain formula; a genuine tracked
condition_score history feeding Impulse) is EMPIRICAL/calibration work
explicitly out of this engine's own scope (per every prior slice's
no-invented-defaults discipline) — it is not something this orchestrator
should silently paper over with a more "realistic-looking" but equally
arbitrary placeholder. Anyone using `replay.py`'s `crisis_entry_lag()` or
any Impulse field through THIS orchestrator should know neither is
currently capable of producing a real result — this is a real, not
cosmetic, limitation of the current build.

`run_engine_for_date()` wires together, in dependency order: Slice 2 (raw
series) -> Slice 3/3b (Direction + TrendQuality) -> Slices 4/5/6 (Breadth/
Risk Appetite/Stability) -> Slice 7 (Condition) -> Slice 8 (State Machine)
-> Slice 9 (Impulse + Confidence) -> Slice 10 (Output Assembly). It does
NOT implement any of the injected EMPIRICAL Protocols' internal formulas
itself — `TEST_SCAFFOLDING_CONFIG` supplies trivial, clearly-fake stub
implementations (the same "obviously-fake, proves the injection seam"
pattern already used throughout every module's own test suite), reused
here rather than reinvented.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from .contracts import Manifest, load_manifest
from .normalization import causal_midrank, InsufficientHistoryError, REQUIRED_WINDOW_SIZE
from .raw_features import RawSeries, RawSeriesCollection, load_raw_series, load_raw_collection
from .direction import (
    DirectionStructure, DirectionInputs, DirectionHorizons, DirectionBaseScores,
    DirectionConfirmationState, classify_structure, compute_direction_result, DirectionResult,
)
from .trend_quality import TrendQualityWeights, TrendQualityResult, TrendQualityUnavailableError, compute_trend_quality
from .breadth import BreadthBlendConfig, BreadthResult, BreadthUnavailableError, compute_breadth
from .risk_appetite import RiskAppetiteWeights, RiskAppetiteResult, RiskAppetiteUnavailableError, compute_risk_appetite
from .stability import StabilityWeights, StabilityResult, StabilityUnavailableError, compute_stability
from .condition import (
    PillarWeights, HardVetoRule, SoftCapRule, ConditionResult, ConditionUnavailableError, compute_condition,
)
from .impulse import (
    ImpulseEndpoint, ImpulseHorizonInputs, ImpulseWeights, ImpulseResult, ImpulseUnavailableError, compute_impulse,
)
from .confidence import ConfidenceResult, compute_confidence
from .crisis import CrisisDomainReading, CrisisDomainConfig, CrisisBarEvaluation, CrisisState, ConditionForExit, evaluate_crisis_bar
from .ordinary_state import StateBoundaries, ConfirmationBars, OrdinaryHysteresisState
from .trending import TrendingQualificationInputs, TrendingConfig, TrendingState
from .state_machine import EngineState, StateResult, advance_state
from .output_assembly import assemble_output


# ---------------------------------------------------------------------------
# TEST SCAFFOLDING CONFIG — see module docstring. NOT a production default.
# ---------------------------------------------------------------------------

def _stub_direction_adjustment(base_score: float, trend_quality: float | None) -> float:
    return base_score


def _causal_midrank_credit_transform(oas_series: RawSeries, as_of: str) -> tuple[float, float] | None:
    """Real (if simple) reference implementation, replacing the earlier
    fixed-constant stub, per the human's explicit direction (Message[189]):
    reuse the engine's own `causal_midrank()` primitive on the real OAS
    series — the same pattern already used for growth/small-cap rotation
    in `risk_appetite.py`, not a novel formula.

    `credit_level_pct` is manifest-declared `supportive_positive`
    (`{'polarity': 'supportive_positive', 'monotonicity_assertion': 'a
    higher oriented credit-support percentile cannot reduce Risk Appetite
    support'}`), while `oas_change`/OAS itself is `adverse_positive` (a
    HIGHER spread is worse) — so this transform must INVERT OAS's raw
    midrank: a LOW OAS level (tight, calm credit) sits at a low raw
    percentile of the OAS window but must map to a HIGH credit_level_pct.
    `credit_level_pct = 1.0 - causal_midrank(oas_window, oas_now) / 100.0`.

    `credit_change_score` (also `supportive_positive`: 'an improvement
    cannot reduce support') uses the exact same inversion applied to the
    1-session OAS CHANGE series (not the level series) — a large positive
    change (spread widening, adverse) sits at a high raw percentile of the
    change-window and must map to a LOW credit_change_score; a spread
    tightening (negative change) must map to a HIGH credit_change_score.

    Returns None if OAS itself is unavailable on `as_of`, or if there is
    insufficient history (fewer than REQUIRED_WINDOW_SIZE+1 valid sessions)
    for either the level or change midrank window — fail-closed, per the
    `CreditTransform` Protocol's own documented contract.
    """
    current_level = oas_series.value_on(as_of)
    if current_level is None:
        return None

    level_window_obs = oas_series.window_ending(as_of, REQUIRED_WINDOW_SIZE)
    if level_window_obs is None:
        return None
    level_window = [o.value for o in level_window_obs]
    try:
        credit_level_pct = 1.0 - causal_midrank(level_window, current_level) / 100.0
    except InsufficientHistoryError:
        return None

    # 1-session change series: need REQUIRED_WINDOW_SIZE+1 raw observations
    # to derive REQUIRED_WINDOW_SIZE consecutive-pair changes.
    change_domain_obs = oas_series.window_ending(as_of, REQUIRED_WINDOW_SIZE + 1)
    if change_domain_obs is None:
        return None
    change_window = [change_domain_obs[i].value - change_domain_obs[i - 1].value for i in range(1, len(change_domain_obs))]
    current_change = change_window[-1]
    try:
        credit_change_score = 1.0 - causal_midrank(change_window, current_change) / 100.0
    except InsufficientHistoryError:
        return None

    return (credit_level_pct, credit_change_score)


# VIX caps below are historical-extreme references (2020 COVID peak ~82.7,
# 2008 GFC peak ~80), not calibrated production thresholds — chosen only
# so the transforms below produce a real, varying [0,1] output across the
# genuine historical range rather than saturating at 0 or 1 for realistic
# data. Recalibration (or replacement with an EMPIRICAL-injected cap) is
# exactly the kind of follow-on work Message[188]'s checklist describes;
# this is a real-but-simple reference value, not a claimed-optimal one.
_IMPLIED_VOL_CAP = 80.0
_REALIZED_VOL_CAP = 0.80  # annualized realized volatility cap


def _implied_vol_stability_transform(raw_level: float) -> float:
    """VIX level -> [0,1] supportive-positive. Monotone-decreasing by
    construction (higher VIX -> lower or equal output); operates on the
    LEVEL only, never a signed change (keeps the VIX-decline-never-lowers-
    Stability invariant structurally satisfied, per stability.py's own
    docstring)."""
    return max(0.0, min(1.0, 1.0 - raw_level / _IMPLIED_VOL_CAP))


# VIX9D/VIX ratio real range observed in the pinned data is roughly
# [0.66, 1.59] (see Message[189]'s implementation notes) — below 1.0 is
# backwardation (near-term fear exceeds medium-term, a stress signal),
# above 1.0 is contango (calm term structure). This floor/ceiling spans
# comfortably past the observed extremes on both sides.
_VOL_CURVE_FLOOR = 0.60
_VOL_CURVE_CEILING = 1.60


def _vol_curve_stability_transform(raw_level: float) -> float:
    """VIX9D/VIX ratio -> [0,1] supportive-positive. A higher ratio
    (contango, calm) maps to a higher output; a lower ratio (backwardation,
    stress) maps to a lower output — monotone-increasing IN THE RATIO,
    which is the correct "monotone-decreasing in stress" polarity the
    Protocol requires (backwardation is the stressed direction here, not a
    literal higher-raw-number-is-worse convention like VIX itself)."""
    span = _VOL_CURVE_CEILING - _VOL_CURVE_FLOOR
    return max(0.0, min(1.0, (raw_level - _VOL_CURVE_FLOOR) / span))


def _realized_vol_stability_transform(raw_level: float) -> float:
    """Annualized realized volatility -> [0,1] supportive-positive. Same
    monotone-decreasing-in-stress shape as implied vol, with its own
    scale-appropriate cap (realized vol is naturally on a ~0.03-0.9 scale
    in the pinned data, NOT VIX's ~9-83 point scale — reusing the VIX cap
    here was the real scale-mismatch bug this replacement fixes, per
    Message[189]/[190]: the old single shared stub saturated near 1.0 for
    every real realized-vol value, since real realized vol values like
    0.13 are nowhere near a VIX-shaped 80-point cap)."""
    return max(0.0, min(1.0, 1.0 - raw_level / _REALIZED_VOL_CAP))


def _price_stability_transform(raw_price_damage: float) -> float:
    """price_damage (adverse-positive, already on [0,1] per
    _drawdown_price_damage_estimator below) -> price_stability
    (supportive-positive [0,1]). The simplest correct polarity flip: more
    damage -> less stability."""
    return max(0.0, min(1.0, 1.0 - raw_price_damage))


def _realized_vol_estimator(benchmark_series: RawSeries, as_of: str) -> float | None:
    """Real (if simple) reference implementation, replacing the earlier
    fixed-constant stub (Message[189]): standard trailing-20-session
    annualized historical volatility of daily benchmark returns —
    `stdev(daily_returns) * sqrt(252)`, a textbook realized-vol estimator,
    not a novel one. Returns None (fail-closed) if fewer than 21
    observations (20 return periods) exist ending at `as_of`."""
    window = benchmark_series.window_ending(as_of, 21)
    if window is None:
        return None
    closes = [o.value for o in window]
    daily_returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] != 0]
    if len(daily_returns) < 20:
        return None
    mean = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean) ** 2 for r in daily_returns) / len(daily_returns)
    stdev = variance ** 0.5
    return stdev * (252.0 ** 0.5)


def _drawdown_price_damage_estimator(benchmark_series: RawSeries, as_of: str) -> float | None:
    """Real (if simple) reference implementation, replacing the earlier
    fixed-constant stub (Message[189]): drawdown-from-peak magnitude over
    a trailing 252-session (~1 year) lookback — `(peak - current) / peak`,
    clipped to [0,1]. Adverse-positive per PriceDamageEstimator's own
    contract (higher = more damage). Standard, textbook drawdown, not a
    novel construction. Returns None (fail-closed) if fewer than 252
    observations exist ending at `as_of`."""
    window = benchmark_series.window_ending(as_of, 252)
    if window is None:
        return None
    closes = [o.value for o in window]
    current = closes[-1]
    peak = max(closes)
    if peak <= 0:
        return None
    drawdown = (peak - current) / peak
    return max(0.0, min(1.0, drawdown))


def _stub_scale_estimator(raw_change: float) -> float:
    return raw_change


def _stub_odd_squashing_transform(scaled_change: float) -> float:
    return max(-1.0, min(1.0, scaled_change))


def _stub_pillar_agreement(as_of: str) -> float | None:
    return None


def _stub_data_completeness(as_of: str) -> float | None:
    return None


def _stub_decision_margin(as_of: str) -> float | None:
    return None


def _stub_temporal_stability(as_of: str) -> float | None:
    return None


def _stub_crisis_domain_never_active(presence_series: RawSeries):
    """Scaffolding-only CRISIS domain stub: valid whenever the underlying
    series has an observation on `as_of` (so 'domain unavailable' still
    behaves realistically for dates outside a series' real history), but
    NEVER active — this orchestrator's whole purpose is exercising the
    pipeline's WIRING for Slice 11's diff tool, not producing a
    meaningful CRISIS determination, so "always calm" is a deliberately
    simple, unambiguous choice (no threshold/comparator/sign convention
    to get wrong, unlike an earlier version of this stub that used a
    `>=`/huge-magnitude-threshold construction and had a real sign bug:
    a threshold of -999999.0 with `>=` is ALWAYS true for any real
    positive price series, which silently made two of the four domains
    permanently 'active' and put every smoke-tested date into CRISIS —
    found via a real-data smoke test, not a unit test, since the
    synthetic fixtures elsewhere in this engine don't exercise this
    specific orchestrator wiring)."""
    def _ev(as_of: str) -> CrisisDomainReading:
        v = presence_series.value_on(as_of)
        return CrisisDomainReading(valid=v is not None, active=False)
    return _ev


@dataclass(frozen=True)
class TestScaffoldingConfig:
    """Bundles every arbitrary placeholder EMPIRICAL value the orchestrator
    needs to execute end-to-end. NOT a production default — see module
    docstring. `direction_horizons`/`direction_confirmation_bars` use small
    windows so synthetic fixtures with limited history can still exercise
    the full pipeline in tests without needing hundreds of days of data."""

    direction_horizons: DirectionHorizons = DirectionHorizons(ema_fast=5, sma_mid=10, sma_long=20)
    direction_base_scores: DirectionBaseScores = DirectionBaseScores(
        strong_bull=0.90, bull=0.80, bull_pullback=0.80, damaged_bull=0.55, bear=0.15
    )
    direction_confirmation_bars: int = 2
    trend_quality_regression_window: int = 21
    trend_quality_path_efficiency_window: int = 21
    trend_quality_weights: TrendQualityWeights = TrendQualityWeights(weight_linearity=0.5, weight_path_efficiency=0.5)
    breadth_sma50_window: int = 5
    breadth_sma200_window: int = 10
    breadth_blend: BreadthBlendConfig = BreadthBlendConfig(weight_sma50=0.5, weight_sma200=0.5)
    risk_appetite_weights: RiskAppetiteWeights = RiskAppetiteWeights(
        weight_credit=0.4, weight_growth_rotation=0.3, weight_small_cap_rotation=0.3
    )
    stability_weights: StabilityWeights = StabilityWeights(
        weight_implied_vol=0.25, weight_vol_curve=0.25, weight_realized_vol=0.25, weight_price=0.25
    )
    pillar_weights: PillarWeights = PillarWeights(
        weight_direction=0.25, weight_breadth=0.25, weight_risk_appetite=0.25, weight_stability=0.25
    )
    hard_veto_rules: tuple[HardVetoRule, ...] = ()
    soft_cap_rules: tuple[SoftCapRule, ...] = ()
    ordinary_boundaries: StateBoundaries = StateBoundaries(
        risk_off_neutral_boundary=0.35, neutral_risk_on_boundary=0.65,
        risk_off_neutral_buffer=0.0, neutral_risk_on_buffer=0.0,
    )
    ordinary_confirmation_bars: ConfirmationBars = ConfirmationBars(upgrade_bars=2, downgrade_bars=1)
    trending_config: TrendingConfig = TrendingConfig(
        trend_quality_floor=0.7, price_damage_ceiling=0.3, risk_appetite_floor=0.4, stability_floor=0.4,
        entry_bars=2, exit_bars=2,
    )
    impulse_fast_horizon_sessions: int = 5
    impulse_slow_horizon_sessions: int = 10
    impulse_weights: ImpulseWeights = ImpulseWeights(weight_fast=0.6, weight_slow=0.4)


TEST_SCAFFOLDING_CONFIG = TestScaffoldingConfig()


# ---------------------------------------------------------------------------
# REASONABLENESS_CHECK_CONFIG — a SECOND, separate scaffolding instance for
# real-history investigation (Message[191]/[194]), NOT a replacement for
# TEST_SCAFFOLDING_CONFIG. Still NOT a production default — every value
# below is exactly as arbitrary/uncalibrated as TEST_SCAFFOLDING_CONFIG's;
# the only thing that changed is the Direction MA window lengths, moved
# from the short 5/10/20-day windows (chosen so synthetic short-history
# test fixtures could still exercise the pipeline) to the 21/65/200-session
# EMA/SMA windows the design doc's own §6.1 structure table and plan §17.1
# ("v4.4 default 21/65/200 as a labeled benchmark preset") both reference
# by name — a real, cited reference configuration, not an invented number.
#
# WHY A SEPARATE CONFIG, NOT A CHANGE TO TEST_SCAFFOLDING_CONFIG (human
# decision, Message[195]): test_engine.py's own unit tests rely on
# TEST_SCAFFOLDING_CONFIG's SHORT windows to exercise fail-closed/boundary
# behavior against short synthetic fixtures; widening those windows would
# break that existing, still-needed test coverage. Real-history
# investigation (this config) and short-fixture unit testing
# (TEST_SCAFFOLDING_CONFIG) are two genuinely different purposes that
# happened to share one config object before this — now they don't.
#
# Found during the Message[191]/[194] reasonableness checks: the SHORT
# window config produced real false-signal whipsaws on at least 3
# independent historical instances (a March 2026 pullback, a July 2020
# wiggle, an August 2022 bear-market-rally overshoot) — this config exists
# specifically to re-run those same checks with a real, cited reference
# window length and see whether the false signals persist or resolve.
REASONABLENESS_CHECK_CONFIG = replace(
    TEST_SCAFFOLDING_CONFIG,
    direction_horizons=DirectionHorizons(ema_fast=21, sma_mid=65, sma_long=200),
)


# REASONABLENESS_CHECK_CONFIG_MID — a THIRD scaffolding instance, added per
# the human's direct question (Message[196]): does a mid-length window
# (8/21/65 — roughly half of 21/65/200) recover some of the short window's
# fast-reversal responsiveness while still avoiding the false signals? NOT
# a production default, same discipline as the other two configs.
#
# Answer, found by directly re-running the same 3 historical episodes
# (Message[195]'s dates) with this config, not assumed from the window
# length alone:
# - 2020-07-01 false BEAR signal: RESOLVED (matches 21/65/200's fix).
# - 2019-01-31 fast V-shaped reversal: PARTIALLY caught (NEUTRAL/BULL —
#   better than 21/65/200's NEUTRAL/BEAR, but not as fast as 5/10/20's
#   immediate RISK_ON/STRONG_BULL) — a real, genuine middle ground here.
# - 2022-08-15 bear-market-rally overshoot: NOT RESOLVED — this config
#   still gives RISK_ON/STRONG_BULL, the SAME wrong call as
#   TEST_SCAFFOLDING_CONFIG's 5/10/20. 8/21/65 is not long enough to
#   filter out a rally of this magnitude within an ongoing downtrend.
#
# Conclusion: 8/21/65 is NOT a strict improvement over 21/65/200 — it is a
# different, genuine trade-off point on the same responsiveness-vs-noise
# curve, one that happens to fail differently (still whipsaws on
# large-magnitude bear-market rallies) rather than uniformly better. Kept
# here as reusable infrastructure for continuing this comparison, not as
# a recommendation.
REASONABLENESS_CHECK_CONFIG_MID = replace(
    TEST_SCAFFOLDING_CONFIG,
    direction_horizons=DirectionHorizons(ema_fast=8, sma_mid=21, sma_long=65),
)


# REASONABLENESS_CHECK_CONFIG_REAL_BREADTH — a FOURTH scaffolding instance,
# per continued empirical study (Message[197]): `TestScaffoldingConfig`'s
# `breadth_sma50_window=5, breadth_sma200_window=10` are the SAME kind of
# test-fixture-convenience shortcut as Direction's original 5/10/20 MA
# windows (per that field's own name, "SMA50"/"SMA200" implies 50/200
# SESSIONS, not 5/10) — never chosen for real-history investigation. This
# config swaps in the field's own literally-named real window lengths
# (50/200 sessions), keeping every other value (including the still-short
# Direction horizons) unchanged, to isolate Breadth's own sensitivity
# specifically. NOT a production default, same discipline as the other
# three configs.
REASONABLENESS_CHECK_CONFIG_REAL_BREADTH = replace(
    TEST_SCAFFOLDING_CONFIG,
    breadth_sma50_window=50,
    breadth_sma200_window=200,
)


@dataclass(frozen=True)
class RawSeriesBundle:
    """Every raw series the orchestrator needs for one run, loaded once
    and reused across every as_of date in a replay — avoids re-reading
    pinned CSVs per bar. Callers building an INJECTED scenario construct
    a second bundle with modified series (see `replay.py`), never mutate
    a clean bundle's series in place (RawSeries is itself frozen/
    immutable, so in-place mutation is not even possible)."""

    benchmark: RawSeries
    breadth: RawSeriesCollection
    oas: RawSeries
    qqq: RawSeries
    iwm: RawSeries
    vix: RawSeries
    vix9d: RawSeries


def load_raw_series_bundle(manifest: Manifest) -> RawSeriesBundle:
    return RawSeriesBundle(
        benchmark=load_raw_series("benchmark_total_return_close", manifest),
        breadth=load_raw_collection("breadth_member_observations", manifest),
        oas=load_raw_series("oas_level", manifest),
        qqq=load_raw_series("qqq_total_return_close", manifest),
        iwm=load_raw_series("iwm_total_return_close", manifest),
        vix=load_raw_series("vix_level", manifest),
        vix9d=load_raw_series("vix9d_level", manifest),
    )


@dataclass
class RunningEngineState:
    """The full set of mutable, cross-bar persisted state a multi-day
    engine run needs — bundles DirectionConfirmationState (Slice 3) and
    EngineState (Slice 8's CRISIS/ordinary/TRENDING). Constructed once per
    independent run (a clean run and an injected run each get their OWN
    RunningEngineState — never shared, since sharing would let one run's
    history leak into the other's persisted counters)."""

    direction: DirectionConfirmationState
    state_machine: EngineState


def new_running_engine_state(config: TestScaffoldingConfig = TEST_SCAFFOLDING_CONFIG) -> RunningEngineState:
    return RunningEngineState(
        direction=DirectionConfirmationState(confirmation_bars=config.direction_confirmation_bars),
        state_machine=EngineState(),
    )


def run_engine_for_date(
    as_of: str,
    raw: RawSeriesBundle,
    running_state: RunningEngineState,
    manifest: Manifest,
    config: TestScaffoldingConfig = TEST_SCAFFOLDING_CONFIG,
) -> dict:
    """Run modules 4.1-4.12 for exactly one as_of date, advancing
    `running_state` in place (so a caller running a full date sequence
    just calls this once per date, in ascending order, reusing the same
    `running_state` object across calls). Returns the assembled+validated
    86-field output record (module 4.12) for this date.

    Every module's own fail-closed behavior is preserved unmodified — this
    function does not add a second layer of availability logic beyond
    catching each module's own `*UnavailableError` and converting it to
    `None`, exactly the same pattern `output_assembly.py` already
    documents ("a None Condition does not force Direction's fields to
    None" — each module decides its own availability, this orchestrator
    just wires the None-or-Result values through).
    """
    # --- Direction (4.3) ---
    direction_inputs = DirectionInputs(
        close=raw.benchmark.value_on(as_of),
        ema_fast=_sma_or_none(raw.benchmark, as_of, config.direction_horizons.ema_fast),
        sma_mid=_sma_or_none(raw.benchmark, as_of, config.direction_horizons.sma_mid),
        sma_long=_sma_or_none(raw.benchmark, as_of, config.direction_horizons.sma_long),
    )
    raw_structure = classify_structure(direction_inputs)
    confirmed_structure = running_state.direction.advance(raw_structure)

    # --- TrendQuality (4.4) ---
    trend_quality_result: TrendQualityResult | None
    try:
        trend_quality_result = compute_trend_quality(
            as_of, raw.benchmark, config.trend_quality_regression_window,
            config.trend_quality_path_efficiency_window, config.trend_quality_weights,
        )
    except TrendQualityUnavailableError:
        trend_quality_result = None

    direction_result: DirectionResult | None
    if confirmed_structure is None:
        direction_result = None
    else:
        direction_result = compute_direction_result(
            confirmed_structure, raw_structure, running_state.direction, config.direction_base_scores,
            trend_quality_result.trend_quality if trend_quality_result is not None else None,
            _stub_direction_adjustment,
        )

    # --- Breadth (4.5) ---
    breadth_result: BreadthResult | None
    try:
        breadth_result = compute_breadth(
            raw.breadth, as_of, config.breadth_sma50_window, config.breadth_sma200_window, config.breadth_blend,
        )
    except BreadthUnavailableError:
        breadth_result = None

    # --- Risk Appetite (4.6) ---
    risk_appetite_result: RiskAppetiteResult | None
    try:
        risk_appetite_result = compute_risk_appetite(
            as_of, raw.oas, raw.qqq, raw.iwm, raw.benchmark, _causal_midrank_credit_transform, config.risk_appetite_weights,
        )
    except RiskAppetiteUnavailableError:
        risk_appetite_result = None

    # --- Stability (4.7) ---
    stability_result: StabilityResult | None
    try:
        stability_result = compute_stability(
            as_of, raw.vix, raw.vix9d, raw.benchmark,
            _implied_vol_stability_transform, _vol_curve_stability_transform, _realized_vol_stability_transform,
            _realized_vol_estimator, _drawdown_price_damage_estimator, _price_stability_transform,
            config.stability_weights,
        )
    except StabilityUnavailableError:
        stability_result = None

    # --- Condition (4.8) ---
    condition_result: ConditionResult | None
    try:
        condition_result = compute_condition(
            as_of,
            direction_result.direction_score if direction_result is not None else None,
            breadth_result.breadth_score if breadth_result is not None else None,
            risk_appetite_result.risk_appetite_score if risk_appetite_result is not None else None,
            stability_result.stability_score if stability_result is not None else None,
            config.pillar_weights, config.hard_veto_rules, {}, config.soft_cap_rules, {},
        )
    except ConditionUnavailableError:
        condition_result = None

    any_hard_veto_active = bool(condition_result and condition_result.active_veto_ids)

    # --- State Machine (4.10) ---
    crisis_bar = evaluate_crisis_bar(as_of, CrisisDomainConfig(
        volatility_term_structure=_stub_crisis_domain_never_active(raw.vix),
        credit_stress=_stub_crisis_domain_never_active(raw.oas),
        price_damage=_stub_crisis_domain_never_active(raw.benchmark),
        participation_collapse=_stub_crisis_domain_never_active(raw.benchmark),
    ))
    exit_ctx = ConditionForExit(
        condition_score=condition_result.condition_score if condition_result is not None else None,
        any_hard_veto_active=any_hard_veto_active,
        neutral_entry_boundary_plus_buffer=config.ordinary_boundaries.risk_off_neutral_boundary,
    )
    trending_inputs = TrendingQualificationInputs(
        direction_structure=confirmed_structure,
        trend_quality=trend_quality_result.trend_quality if trend_quality_result is not None else None,
        price_damage=stability_result.price_damage if stability_result is not None else None,
        risk_appetite_score=risk_appetite_result.risk_appetite_score if risk_appetite_result is not None else None,
        stability_score=stability_result.stability_score if stability_result is not None else None,
    )
    state_result: StateResult = advance_state(
        as_of, running_state.state_machine, crisis_bar, exit_ctx,
        condition_result.condition_score if condition_result is not None else None,
        config.ordinary_boundaries, config.ordinary_confirmation_bars, any_hard_veto_active,
        trending_inputs, config.trending_config,
    )

    # --- Impulse (4.9) ---
    impulse_result: ImpulseResult | None = None
    if condition_result is not None:
        fast_h = _impulse_horizon(raw.benchmark, condition_result.condition_score, as_of, config.impulse_fast_horizon_sessions)
        slow_h = _impulse_horizon(raw.benchmark, condition_result.condition_score, as_of, config.impulse_slow_horizon_sessions)
        try:
            impulse_result = compute_impulse(as_of, fast_h, slow_h, _stub_scale_estimator, _stub_odd_squashing_transform, config.impulse_weights)
        except ImpulseUnavailableError:
            impulse_result = None

    # --- Confidence (4.11) ---
    confidence_result: ConfidenceResult = compute_confidence(
        as_of, _stub_pillar_agreement, _stub_data_completeness, _stub_decision_margin, _stub_temporal_stability,
    )

    # --- Output Assembly (4.12) ---
    return assemble_output(
        as_of, manifest.raw["schema_version"], manifest.raw["feature_contract_version"],
        "OK" if condition_result is not None else "DEGRADED",
        direction=direction_result, trend_quality=trend_quality_result, breadth=breadth_result,
        risk_appetite=risk_appetite_result, stability=stability_result, condition=condition_result,
        impulse=impulse_result, confidence=confidence_result, state=state_result,
    )


def _sma_or_none(series: RawSeries, as_of: str, window: int) -> float | None:
    w = series.window_ending(as_of, window)
    if w is None:
        return None
    return sum(o.value for o in w) / len(w)


def _impulse_horizon(benchmark: RawSeries, current_condition_score: float, as_of: str, horizon_sessions: int) -> ImpulseHorizonInputs:
    """Placeholder-scaffolding-only horizon construction: since this
    orchestrator doesn't persist a real historical condition_score series
    (that would require re-running the whole pipeline for every prior
    date, which the deliberately-scoped Slice 10 assembler does not do
    either), the t-h endpoint here is approximated using the SAME
    condition_score as t whenever a real prior value isn't tracked — this
    makes Impulse's OWN computation degenerate (near-zero change) in this
    scaffolding, but the point of this orchestrator is exercising the
    pipeline's WIRING for Slice 11's diff tool, not producing a
    meaningful Impulse value. A caller needing a real Impulse horizon
    would need to track a real condition_score history, which is future
    work explicitly out of this scaffolding's scope."""
    window = benchmark.window_ending(as_of, horizon_sessions)
    if window is None:
        endpoint_t_minus_h = ImpulseEndpoint(value=None, usable=False)
        interior_valid = False
    else:
        endpoint_t_minus_h = ImpulseEndpoint(value=current_condition_score, usable=True)
        interior_valid = True
    return ImpulseHorizonInputs(
        endpoint_t=ImpulseEndpoint(value=current_condition_score, usable=True),
        endpoint_t_minus_h=endpoint_t_minus_h,
        interior_all_valid=interior_valid,
    )
