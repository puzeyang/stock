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
credit transform, stability transforms, direction adjustment, etc.)
remains genuinely open, exactly as it was at the end of Slice 9.

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

from dataclasses import dataclass

from .contracts import Manifest, load_manifest
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


def _stub_credit_transform(oas_series: RawSeries, as_of: str) -> tuple[float, float] | None:
    v = oas_series.value_on(as_of)
    if v is None:
        return None
    return (0.5, 0.0)


def _stub_monotone_decreasing(raw_level: float) -> float:
    return max(0.0, min(1.0, (100.0 - raw_level) / 100.0))


def _stub_realized_vol_estimator(benchmark_series: RawSeries, as_of: str) -> float | None:
    v = benchmark_series.value_on(as_of)
    return None if v is None else 0.2


def _stub_price_damage_estimator(benchmark_series: RawSeries, as_of: str) -> float | None:
    """Note found during an independent senior-dev review (2026-08-27):
    this stub is injected directly into `stability.py`'s
    `PriceDamageEstimator` Protocol parameter, bypassing
    `raw_features.py`'s own `compute_derived_raw()`/
    `register_derived_raw_estimator()` registry (which is designed to
    `raise NotImplementedError` for an unregistered derived-raw estimator
    — a genuine fail-loud mechanism built in Slice 2). Both are legitimate
    injection points per their own module's interface (Stability's own
    Protocol parameter vs. Slice 2's registry), so this is not a bug, but
    it does mean Slice 2's fail-loud registry is never actually exercised
    by this orchestrator — flagged here rather than left implicit."""
    v = benchmark_series.value_on(as_of)
    return None if v is None else 0.1


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
            as_of, raw.oas, raw.qqq, raw.iwm, raw.benchmark, _stub_credit_transform, config.risk_appetite_weights,
        )
    except RiskAppetiteUnavailableError:
        risk_appetite_result = None

    # --- Stability (4.7) ---
    stability_result: StabilityResult | None
    try:
        stability_result = compute_stability(
            as_of, raw.vix, raw.vix9d, raw.benchmark,
            _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol_estimator, _stub_price_damage_estimator, _stub_monotone_decreasing,
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
