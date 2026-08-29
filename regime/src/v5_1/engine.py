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
sound, but specific downstream computations it feeds were (one still is)
STRUCTURALLY DEGENERATE, not merely "using placeholder numbers":

1. **CRISIS can never fire through this orchestrator BY DEFAULT.**
   **(Update, 2026-08-28 — Messages[211]-[223]/[232]-[244]: no longer
   true unconditionally.)** When `use_real_crisis_domains=False` (the
   default — see `TestScaffoldingConfig.use_real_crisis_domains`'s own
   docstring below), `_stub_crisis_domain_never_active()` still returns
   `active=False` unconditionally for all four domains, every bar, and
   `replay.py`'s `crisis_entry_lag()` — one of the freshness spec's
   THREE headline engine-dependent metrics (plan §4.13) — still can
   only ever return `None` through this default config. But setting
   `use_real_crisis_domains=True` now wires in real (if uncalibrated)
   D1-D4 evaluators (`_d1_volatility_term_structure_evaluator` etc.,
   plus the anchored-entry corroboration rule in `crisis.py`'s
   `CrisisState.advance()`) that genuinely fire on real stress data —
   verified directly against real pinned 2018/2020/2022/2023/2025 data
   in `test_engine.py::TestRealCrisisDomains` and the 8-episode
   exploratory study in `crisis_validation.py`. This item is CLOSED for
   the opt-in path; the underlying D1-D4 thresholds remain genuinely
   EMPIRICAL/uncalibrated (§17.12, item E12), and `use_real_crisis_domains`
   itself remains explicitly NOT a production default either way — see
   below.
2. **Impulse (FIXED per Message[207] — was previously always ~zero
   through this orchestrator, see history below).**
   `_impulse_horizon()`'s `t-h` endpoint used to be set to the SAME value
   as the `t` endpoint (`current_condition_score`) because no real
   historical `condition_score` series was tracked. Per the human's
   explicit direction (Message[207], reversing this file's own prior
   "explicitly out of this engine's own scope" framing below), this
   orchestrator now persists a real per-run `condition_score_history` on
   `RunningEngineState` (populated once per `run_engine_for_date` call, in
   the SAME ascending-date order every other piece of cross-bar state in
   this file already requires) and `_impulse_horizon()` looks up the REAL
   `t-h` date's recorded value from it — `raw_change` is now a genuine,
   nonzero (whenever the real history moved) computation, not a
   structural zero. See `_impulse_horizon()`'s own docstring for the
   exact lookup/fail-closed contract.

Item 1 (CRISIS) was previously disclosed only in
`_stub_crisis_domain_never_active`'s own docstring/comment — true, but
not given the same prominence as the smaller "known gaps" list in
Message[181]/[183] of the discussion log (`oas_change`,
`binding_event_changes`, etc.). **This paragraph is itself now
partially historical**: real (if uncalibrated) D1-D4 evaluators were
built per Message[211]'s baseline preset and extensively reviewed/
corrected through Messages[212]-[244] (unit-corrected in [212]/[213],
canonical price-damage components in [225]-[228], anchored-entry
corroboration in [232]-[239], per-domain mechanism traces in
[240]-[244]) — this was NOT "silently papered over with a more
realistic-looking but equally arbitrary placeholder"; each formula's
real thresholds and their real, documented behavior on real historical
data are on record in the discussion log, still explicitly labeled
uncalibrated. Anyone using `replay.py`'s `crisis_entry_lag()` through
the DEFAULT config (`use_real_crisis_domains=False`) still gets `None`
always, exactly as before; anyone opting into
`use_real_crisis_domains=True` now gets a real, if uncalibrated,
result — this distinction did not exist when this paragraph was
originally written and must not be collapsed back into "CRISIS cannot
produce a real result" without qualification.

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
from .breadth import BreadthBlendConfig, BreadthResult, BreadthUnavailableError, compute_breadth, compute_participation
from .risk_appetite import RiskAppetiteWeights, RiskAppetiteResult, RiskAppetiteUnavailableError, compute_risk_appetite
from .stability import StabilityWeights, StabilityResult, StabilityUnavailableError, compute_stability, PriceDamageComponents
from .condition import (
    PillarWeights, HardVetoRule, SoftCapRule, ConditionResult, ConditionUnavailableError, compute_condition,
)
from .impulse import (
    ImpulseEndpoint, ImpulseHorizonInputs, ImpulseWeights, ImpulseResult, ImpulseUnavailableError, compute_impulse,
)
from .confidence import ConfidenceResult, compute_confidence
from .crisis import (
    CrisisDomainReading, CrisisDomainConfig, CrisisBarEvaluation, CrisisEvaluationContext, CrisisState,
    ConditionForExit, evaluate_crisis_bar, compute_uncorroborated_veto_diagnostics,
)
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
    _price_damage_composer below) -> price_stability
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


_RETURN_SHOCK_5D_CAP = 0.20   # real-but-simple reference scale, not calibrated (see docstring below)
_RETURN_SHOCK_20D_CAP = 0.35  # real-but-simple reference scale, not calibrated (see docstring below)


def _price_damage_components_estimator(benchmark_series: RawSeries, as_of: str) -> PriceDamageComponents | None:
    """Real (if simple) reference implementation, replacing the earlier
    single-scalar `_drawdown_price_damage_estimator` (Message[189],
    itself replaced per Message[225]/[226]/[227]'s discussion-log review):
    computes THREE independent components in one pass, each `[0,1]`
    adverse-positive:

    - `benchmark_drawdown`: drawdown-from-peak magnitude over a trailing
      252-session (~1 year) lookback — `(peak - current) / peak`, clipped
      to [0,1]. Standard, textbook drawdown, not a novel construction
      (same formula the old single-scalar estimator used).
    - `return_shock_5d`/`return_shock_20d`: the magnitude of a NEGATIVE
      5-session/20-session return, clipped to [0,1] via a real-but-simple
      reference cap (`_RETURN_SHOCK_5D_CAP=0.20`, `_RETURN_SHOCK_20D_CAP=
      0.35` — chosen only so Message[211]'s cited D3 thresholds,
      `return_5d <= -0.07`/`return_20d <= -0.12`, land at a real,
      non-degenerate point within [0,1] rather than saturating; NOT a
      calibrated production value, same discipline as `_IMPLIED_VOL_CAP`/
      `_REALIZED_VOL_CAP` elsewhere in this file). A POSITIVE return
      contributes zero shock (this measures damage from a decline, not
      volatility in either direction).

    Returns None (fail-closed) if fewer than 252 observations exist
    ending at `as_of` (the binding constraint — the longest of the three
    lookbacks)."""
    window = benchmark_series.window_ending(as_of, 252)
    if window is None:
        return None
    closes = [o.value for o in window]
    current = closes[-1]
    peak = max(closes)
    if peak <= 0:
        return None
    drawdown = max(0.0, min(1.0, (peak - current) / peak))

    close_5d_ago = closes[-6] if len(closes) >= 6 else None
    close_20d_ago = closes[-21] if len(closes) >= 21 else None
    if close_5d_ago is None or close_20d_ago is None or close_5d_ago <= 0 or close_20d_ago <= 0:
        return None

    return_5d = current / close_5d_ago - 1.0
    return_20d = current / close_20d_ago - 1.0
    shock_5d = max(0.0, min(1.0, -return_5d / _RETURN_SHOCK_5D_CAP)) if return_5d < 0 else 0.0
    shock_20d = max(0.0, min(1.0, -return_20d / _RETURN_SHOCK_20D_CAP)) if return_20d < 0 else 0.0

    return PriceDamageComponents(
        benchmark_drawdown=drawdown, return_shock_5d=shock_5d, return_shock_20d=shock_20d,
    )


def _price_damage_composer(components: PriceDamageComponents) -> float:
    """Real (if simple) reference implementation: the canonical
    `price_damage` scalar is the MAXIMUM of the three components — a
    real, non-arbitrary choice (adverse-positive polarity means "the
    worst currently-observed signal wins," so a sharp 5-day shock that
    hasn't yet shown up in the slower 252-session drawdown still drives
    `price_damage` up immediately, and vice versa) rather than an
    unweighted average, which would let a severe short-term shock get
    diluted by two calmer, slower-moving components. NOT a calibrated
    production formula — a real-but-simple composition rule, same
    discipline as every other EMPIRICAL formula in this file. How this
    composer's output should feed the single manifest-declared
    `benchmark_return_shock` field (a composition of JUST the two shock
    components, distinct from this function's THREE-component
    price_damage composition) remains a separate, explicitly still-open
    choice per Message[227] — not resolved by this function."""
    return max(components.benchmark_drawdown, components.return_shock_5d, components.return_shock_20d)


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
    def _ev(context: CrisisEvaluationContext) -> CrisisDomainReading:
        v = presence_series.value_on(context.as_of)
        return CrisisDomainReading(valid=v is not None, active=False)
    return _ev


# ---------------------------------------------------------------------------
# REAL (if simple, uncalibrated) CRISIS domain evaluators (D1-D4), per the
# discussion log's extensively-reviewed proposal (Messages[211]-[223]):
# ChatGPT's original concrete formulas (Message[211]), Claude's independent
# review that found and fixed a real OAS unit bug (Message[212]/[213]), a
# real D3 canonical-price_damage-reuse fix (Message[213]/[215]/[216]), and
# the CrisisEvaluationContext/reason_codes/4-of-4-exit-gate topology
# extensions to crisis.py itself (Message[217]-[223]). Explicitly NOT
# production defaults — every threshold below is a human-decided baseline
# preset from that review thread, not a calibrated, backtested constant,
# same discipline as every other EMPIRICAL formula in this file. Unlike
# Direction/Breadth's window-length EMPIRICAL parameters (which had real
# historical price data to check against), these four formulas have NO
# cited design-doc reference value (confirmed in Message[212]) — the
# thresholds are a preregistered research baseline per Message[211] §九,
# not a claimed-correct production configuration.
# ---------------------------------------------------------------------------

# D1: volatility/term-structure stress — VIX level, VIX9D/VIX curve, and a
# 5-session VIX jump, each independently checked; "extreme" is a single-
# evidence shortcut so a genuinely extreme print doesn't wait on a second,
# slower-moving confirmation. Baseline preset per Message[211] §三.
_D1_VIX_LEVEL_THRESHOLD = 30.0
_D1_VIX_PCT504_THRESHOLD = 90.0
_D1_CURVE_RATIO_THRESHOLD = 1.05
_D1_JUMP_5D_THRESHOLD = 0.50
_D1_EXTREME_VIX = 40.0
_D1_EXTREME_RATIO = 1.15


def _d1_volatility_term_structure_evaluator(vix_series: RawSeries, vix9d_series: RawSeries):
    """D1 per Message[211] §三 (baseline preset), verified against real
    pinned VIX/VIX9D data at 4 known crisis dates in Message[212] (e.g.
    2020-03-16: VIX=82.69/VIX9D=109.46/ratio=1.324 — triggers extreme on
    both sub-conditions independently)."""
    def _ev(context: CrisisEvaluationContext) -> CrisisDomainReading:
        vix = vix_series.value_on(context.as_of)
        vix9d = vix9d_series.value_on(context.as_of)
        if vix is None or vix9d is None or vix == 0:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("vix_or_vix9d_unavailable",))

        vix_window_obs = vix_series.window_ending(context.as_of, REQUIRED_WINDOW_SIZE)
        vix_5d_obs = vix_series.window_ending(context.as_of, 6)
        if vix_window_obs is None or vix_5d_obs is None:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("insufficient_vix_history",))

        try:
            vix_pct504 = causal_midrank([o.value for o in vix_window_obs], vix)
        except InsufficientHistoryError:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("insufficient_vix_history",))

        ratio = vix9d / vix
        jump_5d = vix / vix_5d_obs[0].value - 1.0 if vix_5d_obs[0].value != 0 else 0.0

        reasons = []
        level_stress = vix >= _D1_VIX_LEVEL_THRESHOLD or vix_pct504 >= _D1_VIX_PCT504_THRESHOLD
        curve_stress = ratio >= _D1_CURVE_RATIO_THRESHOLD
        jump_stress = jump_5d >= _D1_JUMP_5D_THRESHOLD
        extreme = vix >= _D1_EXTREME_VIX or ratio >= _D1_EXTREME_RATIO

        if level_stress:
            reasons.append("level_stress")
        if curve_stress:
            reasons.append("curve_stress")
        if jump_stress:
            reasons.append("jump_stress")
        if extreme:
            reasons.append("extreme")

        active = extreme or sum([level_stress, curve_stress, jump_stress]) >= 2
        return CrisisDomainReading(valid=True, active=active, reason_codes=tuple(reasons))
    return _ev


# D2: credit stress — real pinned OAS data is in PERCENTAGE POINTS (FRED
# BAMLH0A0HYM2 standard unit, e.g. 10.87 at the 2020 COVID peak), NOT basis
# points. Message[211]'s original "600 bp" thresholds are here expressed
# directly in percentage points (600bp = 6.00pp) per Message[212]'s found
# unit bug and Message[213]'s adopted fix — comparisons are against the
# SAME unit the pinned series is actually in, no runtime unit conversion.
_D2_OAS_LEVEL_PP_THRESHOLD = 6.00
_D2_OAS_LEVEL_PCT504_THRESHOLD = 90.0
_D2_OAS_WIDEN_20D_PP_THRESHOLD = 1.00
_D2_OAS_WIDEN_PCT504_THRESHOLD = 90.0
_D2_EXTREME_OAS_LEVEL_PP = 8.00
_D2_EXTREME_OAS_WIDEN_20D_PP = 2.00
_D2_CHANGE_HORIZON_SESSIONS = 20


def _d2_credit_stress_evaluator(oas_series: RawSeries):
    """D2 per Message[211] §四, unit-corrected per Message[212]/[213]
    (percentage points, matching the real pinned BAMLH0A0HYM2 series —
    NOT basis points as originally drafted). Verified against real OAS
    data at 4 known crisis dates: 2020-03-23 OAS=10.87pp, comfortably
    above both the level and extreme thresholds. `oas_change_20d_pct504`
    needs REQUIRED_WINDOW_SIZE + 20 = 524 raw observations (not 504) to
    produce 504 valid 20-session-change values — the warm-up requirement
    identified in Message[220]/[213]'s review, not merely assumed."""
    def _ev(context: CrisisEvaluationContext) -> CrisisDomainReading:
        current_level = oas_series.value_on(context.as_of)
        if current_level is None:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("oas_unavailable",))

        level_window_obs = oas_series.window_ending(context.as_of, REQUIRED_WINDOW_SIZE)
        change_domain_obs = oas_series.window_ending(context.as_of, REQUIRED_WINDOW_SIZE + _D2_CHANGE_HORIZON_SESSIONS)
        if level_window_obs is None or change_domain_obs is None:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("insufficient_oas_history",))

        try:
            oas_level_pct504 = causal_midrank([o.value for o in level_window_obs], current_level)
        except InsufficientHistoryError:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("insufficient_oas_history",))

        change_values = [
            change_domain_obs[i].value - change_domain_obs[i - _D2_CHANGE_HORIZON_SESSIONS].value
            for i in range(_D2_CHANGE_HORIZON_SESSIONS, len(change_domain_obs))
        ]
        current_change_20d = change_values[-1]
        try:
            oas_change_pct504 = causal_midrank(change_values, current_change_20d)
        except InsufficientHistoryError:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("insufficient_oas_history",))

        reasons = []
        level_stress = current_level >= _D2_OAS_LEVEL_PP_THRESHOLD or oas_level_pct504 >= _D2_OAS_LEVEL_PCT504_THRESHOLD
        widen_stress = current_change_20d >= _D2_OAS_WIDEN_20D_PP_THRESHOLD and oas_change_pct504 >= _D2_OAS_WIDEN_PCT504_THRESHOLD
        extreme = current_level >= _D2_EXTREME_OAS_LEVEL_PP or current_change_20d >= _D2_EXTREME_OAS_WIDEN_20D_PP

        if level_stress:
            reasons.append("level_stress")
        if widen_stress:
            reasons.append("widen_stress")
        if extreme:
            reasons.append("extreme")

        active = extreme or (level_stress and widen_stress)
        return CrisisDomainReading(valid=True, active=active, reason_codes=tuple(reasons))
    return _ev


# D3: price damage — MUST reuse the SAME canonical `PriceDamageComponents`
# Stability already computed this invocation, per `compute_stability`'s
# own explicit MUST ("never call the estimator again independently") and
# `CrisisEvaluationContext`'s docstring. This evaluator does NOT recompute
# drawdown/return-shock itself — the corrected design after Message[213]'s
# retracted "call the estimator directly" error, Message[216]'s follow-up
# fix, and Message[225]/[226]/[227]'s canonical-components-contract
# extension (which finally makes the FULL Message[211] D3 design
# implementable, including the shock_stress/trend_damage sub-conditions
# that were previously omitted for lack of a return_5d/return_20d field
# on the canonical interface).
#
# Thresholds below are Message[211] §五's exact baseline preset
# (`dd_stress<=-12%`, `shock_stress(5d)<=-7%`, `trend_damage(20d)<=-12%`,
# `extreme=(drawdown<=-20%) OR (5d<=-12%)`), re-expressed in the
# normalized [0,1] scale `_price_damage_components_estimator` actually
# produces (drawdown is already a raw fraction, no rescaling; the two
# shock components are the raw percentage divided by their own cap —
# `_RETURN_SHOCK_5D_CAP=0.20`, `_RETURN_SHOCK_20D_CAP=0.35` — so e.g.
# Message[211]'s real "-7% on 5 days" becomes `0.07/0.20 = 0.35` on this
# evaluator's own normalized scale). Real preset value, still NOT a
# calibrated production threshold — same discipline as D1/D2/D4.
_D3_DRAWDOWN_STRESS_THRESHOLD = 0.12
_D3_SHOCK_5D_STRESS_THRESHOLD = 0.07 / _RETURN_SHOCK_5D_CAP
_D3_TREND_DAMAGE_20D_THRESHOLD = 0.12 / _RETURN_SHOCK_20D_CAP
_D3_EXTREME_DRAWDOWN = 0.20
_D3_EXTREME_SHOCK_5D = 0.12 / _RETURN_SHOCK_5D_CAP


def _d3_price_damage_evaluator():
    """D3: reads `context.price_damage_components` (the canonical
    components, already computed once by `compute_stability` this
    invocation) — never its own independent drawdown/return-shock
    calculation. Each component is already a [0,1] adverse-positive
    value per `PriceDamageComponents`' own contract, so no further
    transform is needed here, only threshold comparison, matching
    Message[211] §五's exact `dd_stress`/`shock_stress`/`trend_damage`/
    `extreme` structure."""
    def _ev(context: CrisisEvaluationContext) -> CrisisDomainReading:
        if context.price_damage_components is None:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("canonical_price_damage_unavailable",))

        components = context.price_damage_components
        dd_stress = components.benchmark_drawdown >= _D3_DRAWDOWN_STRESS_THRESHOLD
        shock_stress = components.return_shock_5d >= _D3_SHOCK_5D_STRESS_THRESHOLD
        trend_damage = components.return_shock_20d >= _D3_TREND_DAMAGE_20D_THRESHOLD
        extreme = (
            components.benchmark_drawdown >= _D3_EXTREME_DRAWDOWN
            or components.return_shock_5d >= _D3_EXTREME_SHOCK_5D
        )
        reasons = []
        if dd_stress:
            reasons.append("dd_stress")
        if shock_stress:
            reasons.append("shock_stress")
        if trend_damage:
            reasons.append("trend_damage")
        if extreme:
            reasons.append("extreme")

        active = extreme or sum([dd_stress, shock_stress, trend_damage]) >= 2
        return CrisisDomainReading(valid=True, active=active, reason_codes=tuple(reasons))
    return _ev


# D4: participation collapse — Tier 2 fixed 9-sector-ETF universe, reusing
# `breadth.py`'s own `compute_participation` (the same real accessor
# Breadth's own pillar uses) rather than a private re-derivation. Baseline
# preset per Message[211] §六, verified against real Breadth data at 4
# known crisis dates in Message[212] (e.g. 2020-03-23:
# pct_above_50=pct_above_200=0.0, far below both thresholds).
_D4_SHORT_COLLAPSE_THRESHOLD = 0.25
_D4_LONG_COLLAPSE_THRESHOLD = 0.35
_D4_EXTREME_SHORT = 0.10
_D4_EXTREME_LONG = 0.20
_D4_SMA50_WINDOW = 50
_D4_SMA200_WINDOW = 200
_D4_SPEED_LOOKBACK_SESSIONS = 5
_D4_SPEED_DROP_PP_THRESHOLD = 0.25
_D4_MIN_COVERAGE = 0.90


def _d4_participation_collapse_evaluator(breadth_collection: RawSeriesCollection):
    """D4 per Message[211] §六, real windows (50/200 sessions, matching
    the field names' own literal meaning, not the 5/10 fixture shortcut
    already established as test-convenience-only elsewhere in this
    investigation — Messages[191]/[197])."""
    def _ev(context: CrisisEvaluationContext) -> CrisisDomainReading:
        try:
            pct50_now, pct200_now, eligible_now, total_now = compute_participation(
                breadth_collection, context.as_of, _D4_SMA50_WINDOW, _D4_SMA200_WINDOW,
            )
        except BreadthUnavailableError:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("participation_unavailable",))

        if total_now == 0 or eligible_now / total_now < _D4_MIN_COVERAGE:
            return CrisisDomainReading(valid=False, active=False, reason_codes=("insufficient_coverage",))

        speed_collapse = False
        try:
            past_dates = _breadth_dates_ending(breadth_collection, context.as_of, _D4_SPEED_LOOKBACK_SESSIONS + 1)
            if past_dates is not None:
                past_as_of = past_dates[0]
                pct50_past, _pct200_past, eligible_past, total_past = compute_participation(
                    breadth_collection, past_as_of, _D4_SMA50_WINDOW, _D4_SMA200_WINDOW,
                )
                if total_past > 0 and eligible_past / total_past >= _D4_MIN_COVERAGE:
                    speed_collapse = (pct50_past - pct50_now) >= _D4_SPEED_DROP_PP_THRESHOLD
        except BreadthUnavailableError:
            speed_collapse = False

        short_collapse = pct50_now <= _D4_SHORT_COLLAPSE_THRESHOLD
        long_collapse = pct200_now <= _D4_LONG_COLLAPSE_THRESHOLD
        extreme = pct50_now <= _D4_EXTREME_SHORT and pct200_now <= _D4_EXTREME_LONG

        reasons = []
        if short_collapse:
            reasons.append("short_collapse")
        if long_collapse:
            reasons.append("long_collapse")
        if speed_collapse:
            reasons.append("speed_collapse")
        if extreme:
            reasons.append("extreme")

        active = extreme or sum([short_collapse, long_collapse, speed_collapse]) >= 2
        return CrisisDomainReading(valid=True, active=active, reason_codes=tuple(reasons))
    return _ev


def _breadth_dates_ending(collection: RawSeriesCollection, as_of: str, size: int) -> tuple[str, ...] | None:
    """Helper: the `size` most recent real trading dates on/before `as_of`
    shared by the Breadth collection's own member series, reusing whatever
    date set `compute_participation` itself would consider — implemented
    via the first member's own `window_ending`, matching the assumption
    every Tier 2 member shares the same real trading-day calendar (already
    an implicit assumption throughout `breadth.py`, not a new one)."""
    members = list(collection.members.values())
    if not members:
        return None
    window = members[0].window_ending(as_of, size)
    if window is None:
        return None
    return tuple(o.date for o in window)


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
    use_real_crisis_domains: bool = False
    """Per Message[211]-[223]'s extensively-reviewed CRISIS domain
    proposal: when False (the default, preserving every prior config's
    exact existing behavior), CRISIS uses the original
    `_stub_crisis_domain_never_active` stub — structurally always-calm,
    CRISIS can never fire, same as before this message. When True, uses
    the real (if uncalibrated, human-reviewed) D1-D4 evaluators
    (`_d1_volatility_term_structure_evaluator` etc.) instead. NOT a
    production default either way — this flag exists so the real
    evaluators are opt-in, isolating their effect for comparison against
    the stub, same `dataclasses.replace()`-based isolation discipline as
    every other EMPIRICAL parameter tested in this investigation."""


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


# REASONABLENESS_CHECK_CONFIG_BREADTH_MID — a mid-length Breadth window
# comparison point, per continued empirical study. Unlike Direction's
# 8/21/65 mid config (REASONABLENESS_CHECK_CONFIG_MID), which had a
# citeable reference (design §6.1's own EMA21/SMA65/SMA200 structure
# table), there is NO other window length cited anywhere in the design
# for Breadth besides the field names' own literal 50/200 — this is
# flagged honestly rather than dressed up as a reference value. 20/50
# sessions is used here as a common, independently-recognizable
# short/medium-trend pairing (distinct from both the 5/10 fixture
# shortcut and the 50/200 "real" window), chosen to probe whether
# Breadth's sensitivity is a smooth function of window length or has a
# sharper break point somewhere between the two extremes already tested.
# NOT a production default, NOT a cited benchmark — an invented probe
# point, same `dataclasses.replace()` discipline as every other config
# here.
REASONABLENESS_CHECK_CONFIG_BREADTH_MID = replace(
    TEST_SCAFFOLDING_CONFIG,
    breadth_sma50_window=20,
    breadth_sma200_window=50,
)


# REASONABLENESS_CHECK_CONFIG_ALL_REAL — a FIFTH scaffolding instance, per
# continued empirical study (Message[198]): combines the two independent
# fixes found so far (Direction's real 21/65/200 EMA/SMA windows from
# REASONABLENESS_CHECK_CONFIG, and Breadth's real 50/200 SMA windows from
# REASONABLENESS_CHECK_CONFIG_REAL_BREADTH) into ONE config — every prior
# comparison tested exactly one pillar's window fix in isolation, holding
# the other pillar's short/fixture window fixed; this tests whether fixing
# BOTH at once changes the picture (e.g. do the two pillars' now-both-real
# windows reinforce each other, or does one dominate/mask the other's
# effect on condition_score/state?). NOT a production default, same
# discipline as every other config here.
REASONABLENESS_CHECK_CONFIG_ALL_REAL = replace(
    TEST_SCAFFOLDING_CONFIG,
    direction_horizons=DirectionHorizons(ema_fast=21, sma_mid=65, sma_long=200),
    breadth_sma50_window=50,
    breadth_sma200_window=200,
)


# REASONABLENESS_CHECK_CONFIG_MID_ALL — a SIXTH scaffolding instance, per
# continued empirical study. Every prior combined config
# (REASONABLENESS_CHECK_CONFIG_ALL_REAL) paired Direction's longest
# window (21/65/200) with Breadth's longest window (50/200) — the two
# "most real" endpoints. This config instead pairs Direction's longest
# window with Breadth's MID window (20/50, REASONABLENESS_CHECK_CONFIG_
# BREADTH_MID) — a combination never previously built or tested,
# isolating whether Message[198]'s "combining both real-window fixes
# compounds their responsiveness cost" finding is specific to the
# 50/200 Breadth window, or holds just as strongly with a shorter,
# faster Breadth window paired against the same long Direction window.
# NOT a production default, NOT a cited benchmark (inherits the same
# caveat as REASONABLENESS_CHECK_CONFIG_BREADTH_MID: 20/50 is an
# invented probe point, not a design citation) — same
# `dataclasses.replace()` discipline as every other config here.
REASONABLENESS_CHECK_CONFIG_MID_ALL = replace(
    TEST_SCAFFOLDING_CONFIG,
    direction_horizons=DirectionHorizons(ema_fast=21, sma_mid=65, sma_long=200),
    breadth_sma50_window=20,
    breadth_sma200_window=50,
)


# REASONABLENESS_CHECK_CONFIG_REAL_IMPULSE — a SEVENTH scaffolding
# instance, extending this investigation to Impulse (module 4.11) for the
# first time — every prior config touched only Direction/Breadth.
# `TestScaffoldingConfig.impulse_fast_horizon_sessions=5,
# impulse_slow_horizon_sessions=10` is the SAME test-fixture-convenience
# shortcut pattern already found in Direction's original 5/10/20 and
# Breadth's original 5/10 (Messages[191]/[197]) — chosen so
# `test_engine.py`'s synthetic short-history fixtures could exercise the
# pipeline, never chosen for real-history investigation. Unlike Breadth's
# blend-weight-style fields (SMA50/SMA200 mix, out of scope per
# Message[199]'s deferral) and unlike Breadth's own invented 20/50 probe
# point (no design citation), Impulse's horizons DO have a real design
# citation: plan §17 item 14's own summary table labels this
# "Impulse 5/20 tanh" (design plan, "Invariants/topology CLOSED; all
# constants/transform EMPIRICAL") — 5/20 sessions, not 5/10. This config
# swaps in that cited real value for the slow horizon, holding
# Direction/Breadth at their original TEST_SCAFFOLDING_CONFIG values to
# isolate Impulse's own sensitivity, same isolation discipline as every
# prior single-pillar config. NOT a production default — same discipline
# as every other config here. `impulse_weights` (a blend-weight-style
# field) is deliberately left untouched, consistent with Message[199]'s
# standing deferral of all weight-shaped EMPIRICAL parameters.
#
# IMPORTANT HISTORY (Message[207]): this config was originally built
# BEFORE `_impulse_horizon()`'s structural degeneracy was discovered and
# fixed — at that time, comparing this config against TEST_SCAFFOLDING_
# CONFIG was IMPOSSIBLE to do meaningfully, since impulse_score was
# mechanically ~0 regardless of horizon length (see the module docstring's
# former "KNOWN LIMITATIONS" item 2). Per the human's explicit direction,
# `RunningEngineState`/`_impulse_horizon()` were fixed to track a real
# condition_score history — this config is NOW genuinely comparable
# against TEST_SCAFFOLDING_CONFIG's 5/10, unlike when it was first built.
REASONABLENESS_CHECK_CONFIG_REAL_IMPULSE = replace(
    TEST_SCAFFOLDING_CONFIG,
    impulse_fast_horizon_sessions=5,
    impulse_slow_horizon_sessions=20,
)


# REASONABLENESS_CHECK_ROUGH_BASELINE — an EIGHTH scaffolding instance,
# built per the human's explicit direction ("Option a": stand up an
# end-to-end run using every real-scale fix already found, rather than
# waiting for full calibration). Combines every real/cited window fix
# this investigation has independently found so far — Direction's
# 21/65/200 (REASONABLENESS_CHECK_CONFIG), Breadth's 50/200
# (REASONABLENESS_CHECK_CONFIG_REAL_BREADTH), Impulse's 5/20
# (REASONABLENESS_CHECK_CONFIG_REAL_IMPULSE) — plus, for the first time,
# `use_real_crisis_domains=True` (Messages[211]-[257]'s D1-D4 evaluators
# and the anchored-entry rule), which no prior REASONABLENESS_CHECK_*
# config has ever turned on.
#
# EXPLICITLY STILL UNCALIBRATED, NOT HIDDEN: `pillar_weights` (equal
# 25% each), `hard_veto_rules`/`soft_cap_rules` (both empty),
# `risk_appetite_weights`/`stability_weights`/`trend_quality_weights`
# (equal-split placeholders), `trend_quality_regression_window`/
# `trend_quality_path_efficiency_window` (still 21, a TEST_SCAFFOLDING_
# CONFIG value never itself reasonableness-checked against a real
# citation the way Direction/Breadth/Impulse's windows were), and every
# D1-D4 numeric threshold inside crisis.py/engine.py remain exactly
# their original Message[211] uncalibrated values. This config makes
# the pipeline's WIRING run on real-scale windows where such a
# real-scale reference already exists and has been checked; it does
# NOT constitute a calibrated production configuration in any sense —
# same "NOT a production default" discipline as every other config in
# this file. A caller MUST NOT treat this config's output as anything
# beyond a real-scale-windowed, still-uncalibrated rough baseline.
REASONABLENESS_CHECK_ROUGH_BASELINE = replace(
    TEST_SCAFFOLDING_CONFIG,
    direction_horizons=DirectionHorizons(ema_fast=21, sma_mid=65, sma_long=200),
    breadth_sma50_window=50,
    breadth_sma200_window=200,
    impulse_fast_horizon_sessions=5,
    impulse_slow_horizon_sessions=20,
    use_real_crisis_domains=True,
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
    engine run needs — bundles DirectionConfirmationState (Slice 3),
    EngineState (Slice 8's CRISIS/ordinary/TRENDING), and (per Message[207]
    — this used to be a structural gap, see the module docstring's former
    "KNOWN LIMITATIONS" item 2, now fixed) `condition_score_history`, a
    real per-date record of this SAME run's own finalized condition_score
    values, keyed by `as_of` date string. Constructed once per independent
    run (a clean run and an injected run each get their OWN
    RunningEngineState — never shared, since sharing would let one run's
    history leak into the other's persisted counters). `condition_score_
    history` is exactly this same "never share across independent runs"
    discipline extended to Impulse's own real input — a run's Impulse
    computation may only see ITS OWN prior condition_score values, never
    another run's."""

    direction: DirectionConfirmationState
    state_machine: EngineState
    condition_score_history: dict[str, float]


def new_running_engine_state(config: TestScaffoldingConfig = TEST_SCAFFOLDING_CONFIG) -> RunningEngineState:
    return RunningEngineState(
        direction=DirectionConfirmationState(confirmation_bars=config.direction_confirmation_bars),
        state_machine=EngineState(),
        condition_score_history={},
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

    # `unavailable_reason_codes` (Message[264] point 1 — a real,
    # previously-undocumented gap this fixes): every pillar's
    # *UnavailableError below carries a genuine, informative
    # human-readable message (verified directly against every raise
    # site in trend_quality.py/breadth.py/risk_appetite.py/stability.py/
    # condition.py), but it was previously discarded entirely — the
    # pillar result was set to None and the WHY was thrown away, so a
    # degraded/unavailable record's top-level `unavailable_reason_codes`
    # field was always empty (confirmed: engine.py never populated it
    # before this fix). Each pillar's real message is now collected
    # here, tagged with which pillar it came from, and threaded through
    # to the assembled output — closing the loop Message[262]/[264]
    # correctly identified the runner script alone could never close
    # (the data simply did not exist upstream to extract).
    pillar_unavailable_reasons: list[str] = []

    # --- TrendQuality (4.4) ---
    trend_quality_result: TrendQualityResult | None
    try:
        trend_quality_result = compute_trend_quality(
            as_of, raw.benchmark, config.trend_quality_regression_window,
            config.trend_quality_path_efficiency_window, config.trend_quality_weights,
        )
    except TrendQualityUnavailableError as e:
        trend_quality_result = None
        pillar_unavailable_reasons.append(f"trend_quality_unavailable:{e}")

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
    except BreadthUnavailableError as e:
        breadth_result = None
        pillar_unavailable_reasons.append(f"breadth_unavailable:{e}")

    # --- Risk Appetite (4.6) ---
    risk_appetite_result: RiskAppetiteResult | None
    try:
        risk_appetite_result = compute_risk_appetite(
            as_of, raw.oas, raw.qqq, raw.iwm, raw.benchmark, _causal_midrank_credit_transform, config.risk_appetite_weights,
        )
    except RiskAppetiteUnavailableError as e:
        risk_appetite_result = None
        pillar_unavailable_reasons.append(f"risk_appetite_unavailable:{e}")

    # --- Stability (4.7) ---
    stability_result: StabilityResult | None
    try:
        stability_result = compute_stability(
            as_of, raw.vix, raw.vix9d, raw.benchmark,
            _implied_vol_stability_transform, _vol_curve_stability_transform, _realized_vol_stability_transform,
            _realized_vol_estimator, _price_damage_components_estimator, _price_damage_composer, _price_stability_transform,
            config.stability_weights,
        )
    except StabilityUnavailableError as e:
        stability_result = None
        pillar_unavailable_reasons.append(f"stability_unavailable:{e}")

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
    except ConditionUnavailableError as e:
        condition_result = None
        pillar_unavailable_reasons.append(f"condition_unavailable:{e}")

    # Record this run's own real condition_score into the running history
    # BEFORE the Impulse block below reads it back for OTHER (earlier)
    # dates — per Message[207], this is what makes Impulse's horizons real
    # rather than structurally degenerate (see module docstring's
    # "KNOWN LIMITATIONS" item 2 / `_impulse_horizon()`'s own docstring).
    # A None condition_score (this date unavailable) is NOT recorded —
    # fail-closed, consistent with every other None-handling in this
    # engine: a missing/unavailable date must read back as missing to a
    # later Impulse lookup, never silently treated as "no change happened."
    if condition_result is not None:
        running_state.condition_score_history[as_of] = condition_result.condition_score

    any_hard_veto_active = bool(condition_result and condition_result.active_veto_ids)

    # --- State Machine (4.10) ---
    if config.use_real_crisis_domains:
        crisis_domain_config = CrisisDomainConfig(
            volatility_term_structure=_d1_volatility_term_structure_evaluator(raw.vix, raw.vix9d),
            credit_stress=_d2_credit_stress_evaluator(raw.oas),
            price_damage=_d3_price_damage_evaluator(),
            participation_collapse=_d4_participation_collapse_evaluator(raw.breadth),
        )
    else:
        crisis_domain_config = CrisisDomainConfig(
            volatility_term_structure=_stub_crisis_domain_never_active(raw.vix),
            credit_stress=_stub_crisis_domain_never_active(raw.oas),
            price_damage=_stub_crisis_domain_never_active(raw.benchmark),
            participation_collapse=_stub_crisis_domain_never_active(raw.benchmark),
        )
    crisis_bar = evaluate_crisis_bar(
        as_of, crisis_domain_config,
        price_damage_components=stability_result.price_damage_components if stability_result is not None else None,
    )
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
        fast_h = _impulse_horizon(raw.benchmark, running_state.condition_score_history, as_of, config.impulse_fast_horizon_sessions)
        slow_h = _impulse_horizon(raw.benchmark, running_state.condition_score_history, as_of, config.impulse_slow_horizon_sessions)
        try:
            impulse_result = compute_impulse(as_of, fast_h, slow_h, _stub_scale_estimator, _stub_odd_squashing_transform, config.impulse_weights)
        except ImpulseUnavailableError:
            impulse_result = None

    # --- Confidence (4.11) ---
    confidence_result: ConfidenceResult = compute_confidence(
        as_of, _stub_pillar_agreement, _stub_data_completeness, _stub_decision_margin, _stub_temporal_stability,
    )

    # CRISIS diagnostics per §9.2's own "Publish per-domain valid/active
    # flags, coverage, count, reason codes, and entry/exit counters" —
    # previously never wired to assemble_output at all (crisis_bar was
    # computed only to feed advance_state), a gap that didn't matter while
    # CRISIS was structurally always-calm but does now that it can fire
    # for real. `uncorroborated_veto`/`crisis_watch` are a pure function
    # of THIS bar's active_domain_count, not persisted state (see that
    # function's own docstring) — computed fresh each call, same as
    # crisis_bar itself.
    veto_diagnostics = compute_uncorroborated_veto_diagnostics(crisis_bar.active_domain_count, any_hard_veto_active)

    # --- Output Assembly (4.12) ---
    # benchmark_drawdown/benchmark_return_shock: manifest-declared
    # explainability fields (role="explainability", per Message[225]'s
    # finding) that no prior code populated. benchmark_drawdown reads
    # straight through StabilityResult's own property. benchmark_
    # return_shock's exact 5d/20d composition rule remains an explicitly
    # open EMPIRICAL choice (Message[227]) — reusing the same real-but-
    # simple "maximum of the components" rule _price_damage_composer
    # already uses for price_damage itself (not a new, separately
    # invented formula), clearly non-final, rather than leaving a real,
    # now-computable value silently None.
    benchmark_return_shock = None
    if stability_result is not None:
        components = stability_result.price_damage_components
        benchmark_return_shock = max(components.return_shock_5d, components.return_shock_20d)

    return assemble_output(
        as_of, manifest.raw["schema_version"], manifest.raw["feature_contract_version"],
        "OK" if condition_result is not None else "DEGRADED",
        direction=direction_result, trend_quality=trend_quality_result, breadth=breadth_result,
        risk_appetite=risk_appetite_result, stability=stability_result, condition=condition_result,
        impulse=impulse_result, confidence=confidence_result, state=state_result,
        # Message[264] point 1: real pillar-unavailability reasons,
        # collected above at each *UnavailableError site — previously
        # this was always None/empty regardless of what actually
        # happened upstream. Only set when non-empty, matching every
        # other optional field's None-when-absent convention here.
        unavailable_reason_codes=pillar_unavailable_reasons if pillar_unavailable_reasons else None,
        crisis_domain_status=crisis_bar.domain_status,
        crisis_valid_domain_count=crisis_bar.valid_domain_count,
        crisis_active_domain_count=crisis_bar.active_domain_count,
        crisis_watch=veto_diagnostics.crisis_watch,
        uncorroborated_veto=veto_diagnostics.uncorroborated_veto,
        crisis_exit_count=running_state.state_machine.crisis.crisis_exit_count,
        benchmark_drawdown=stability_result.benchmark_drawdown if stability_result is not None else None,
        benchmark_return_shock=benchmark_return_shock,
    )


def _sma_or_none(series: RawSeries, as_of: str, window: int) -> float | None:
    w = series.window_ending(as_of, window)
    if w is None:
        return None
    return sum(o.value for o in w) / len(w)


def _impulse_horizon(
    benchmark: RawSeries, condition_score_history: dict[str, float], as_of: str, horizon_sessions: int,
) -> ImpulseHorizonInputs:
    """Real horizon construction (per Message[207], replacing the
    previously-structurally-degenerate version — see module docstring's
    "KNOWN LIMITATIONS" item 2's history). Looks up the ACTUAL `t-h`
    date's recorded `condition_score` from `condition_score_history`
    (populated once per `run_engine_for_date` call, in ascending-date
    order — see that function's own comment at the call site), rather
    than substituting the current value.

    `t-h` DATE identification reuses `benchmark.window_ending(as_of,
    horizon_sessions)` — the SAME real trading-day-counting convention
    every other EMPIRICAL window in this engine already uses (Direction's
    MA windows, Breadth's SMA windows, `scoring.py`'s `forward_return`) —
    rather than inventing a second date-counting scheme. The window's
    OLDEST entry (`window[0]`) is the real `t-h` date; that date's
    `condition_score_history` entry (if any) is `endpoint_t_minus_h`.

    Fail-closed per design §11 ("missing/stale endpoints or invalid
    required interior sessions make the horizon... unavailable") in THREE
    independent ways, matching every other None-handling convention in
    this engine:
    - `endpoint_t` (today) is unusable if `as_of` was never recorded
      (condition_result was None for this exact date — should not happen
      given the call site only invokes this when condition_result is
      NOT None, but checked directly rather than assumed);
    - `endpoint_t_minus_h` is unusable if `benchmark.window_ending` itself
      returns None (insufficient real trading-day history exists at all)
      OR the real `t-h` date exists in the benchmark calendar but was
      never recorded in `condition_score_history` (e.g. this run's own
      history simply doesn't reach that far back yet, or `condition_result`
      was genuinely unavailable that far back);
    - `interior_all_valid` requires EVERY real trading day strictly
      between `t-h` and `t` (the window's own interior entries) to also
      have a recorded, present `condition_score_history` entry — a single
      missing interior date poisons the whole horizon, per §11's own
      requirement, not silently skipped."""
    endpoint_t_value = condition_score_history.get(as_of)
    endpoint_t = ImpulseEndpoint(value=endpoint_t_value, usable=endpoint_t_value is not None)

    window = benchmark.window_ending(as_of, horizon_sessions)
    if window is None:
        return ImpulseHorizonInputs(
            endpoint_t=endpoint_t,
            endpoint_t_minus_h=ImpulseEndpoint(value=None, usable=False),
            interior_all_valid=False,
        )

    t_minus_h_date = window[0].date
    t_minus_h_value = condition_score_history.get(t_minus_h_date)
    endpoint_t_minus_h = ImpulseEndpoint(value=t_minus_h_value, usable=t_minus_h_value is not None)

    # Interior = every real trading day strictly between t-h and t, i.e.
    # every window entry except the oldest (t-h, checked above as
    # endpoint_t_minus_h) and the newest (window[-1] — the observation
    # on-or-before as_of per window_ending's own contract; NOT necessarily
    # exactly as_of if as_of itself isn't a trading day, but this
    # engine's benchmark series is a real trading-day series and every
    # caller of this function passes a real as_of, so window[-1] is as_of
    # whenever the window exists at all — t's own validity is checked
    # separately as endpoint_t above via the literal as_of key, not
    # re-derived from window[-1] here, so this holds regardless).
    interior_dates = [o.date for o in window[1:-1]]
    interior_all_valid = all(condition_score_history.get(d) is not None for d in interior_dates)

    return ImpulseHorizonInputs(
        endpoint_t=endpoint_t,
        endpoint_t_minus_h=endpoint_t_minus_h,
        interior_all_valid=interior_all_valid,
    )
