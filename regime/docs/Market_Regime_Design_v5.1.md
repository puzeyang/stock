# Market Regime System — Design Specification v5.1

**Status:** Architecture baseline; implementation and calibration pending  
**Schema version:** `5.1`  
**Feature-contract version:** `5.1`  
**Decision record:** `research/market/discussion/market-regime-discussion.md`, Messages 1–67  
**Supersedes:** `Market_Regime_Design_v5.0.md`  
**Historical predecessor:** `market_regime_claude.md` v4.4 (frozen)

## 0. Authority and status language

This is the sole design specification for Market Regime v5.1. It incorporates the complete review of all ten `INHERITED_PENDING_REVIEW` items in v5.0 §19. It is a breaking measurement contract, not an implementation claim and not an addendum to v4.4 or v5.0.

Status labels are normative:

- **CLOSED:** the architecture or invariant is decided.
- **EMPIRICAL:** the role and test boundary are decided, but a formula, source, coefficient, horizon, threshold, or adoption choice requires evidence.
- **OUT_OF_SCOPE:** intentionally excluded from the measurement engine.

Normative requirements use **MUST**, **MUST NOT**, **SHOULD**, and **MAY**. EMPIRICAL values MUST NOT be presented as final constants. V4.4 values are comparison baselines only unless this document says otherwise.

## 1. Product boundary

### 1.1 Measurement outputs

The engine measures current market conditions and emits:

- four supportive-positive pillars: Direction, Breadth, Risk Appetite, and Stability;
- `condition_score` in `[0,1]`;
- orthogonal `direction_sign` in `{-1,0,+1}`;
- one mutually exclusive state: `CRISIS`, `RISK_OFF`, `NEUTRAL`, `RISK_ON`, or `TRENDING`;
- signed `impulse_score` in `[-1,1]`;
- four separate Confidence diagnostics;
- raw-feature, source-quality, gate, cap, crisis, and state-machine diagnostics.

Higher pillar and Condition values always mean more supportive conditions. `direction_sign` is signed, not supportive-positive.

### 1.2 Policy and routing boundary

Measurement outputs are descriptive facts, never actions. The measurement schema MUST NOT emit or alias:

- `position_size_multiplier`, `portfolio_risk_budget`, or `target_exposure`;
- `strategy_fit`, `tf_fit`, `vs_fit`, or `mr_fit`;
- `tradable_signal`, recommended strategy, order side, or buy/add/exit markers;
- `recovery_throttle`, `risk_budget`, `exposure_permission`, or `leverage_factor`.

`direction_sign` is not a long/short router. `BULL_PULLBACK` is not a buy signal. `RISK_ON` and `RISK_OFF` are not sufficient sizing instructions. `TRENDING` is not leverage authorization. Condition is not a position-size multiplier.

A separately versioned policy/routing product MAY consume immutable v5.1 outputs plus strategy, instrument, portfolio, cost, liquidity, financing, and mandate inputs. It MUST NOT write back into measurement history or state.

A temporary downstream `legacy_v4_policy_adapter` MAY preserve existing consumer behavior during migration. It is not a v5.1 measurement output or endorsement and requires its own version and parity tests.

### 1.3 Path dependence

Condition contains no allocation policy and no latent episode memory. Identical valid inputs over every declared lookback MUST produce identical pillars and Condition.

Finite, explicitly declared confirmation logic is allowed for `direction_structure` and the categorical regime state. Replay MUST reconstruct it from sufficient history or restore versioned state. Path-dependent exposure scaling belongs downstream.

## 2. Processing topology

```text
Versioned raw series + metadata
              │
              ▼
 Alignment / freshness / warm-up
              │
              ▼
 Canonical raw features (computed once)
              │
              ▼
 Causal transforms where required
              │
              ▼
 Direction ─ Breadth ─ Risk Appetite ─ Stability
              │
              ▼
      condition_pre_cap [0,1]
              │
       hard vetoes / optional caps
              │
              ▼
        condition_score [0,1]
       ┌──────┼─────────┐
       ▼      ▼         ▼
   Impulse Confidence  State machine
                         │
                         ▼
 CRISIS / RISK_OFF / NEUTRAL / RISK_ON / TRENDING
```

One canonical feature may have multiple declared consumers. This is not double counting. Double counting occurs when the same economic feature is independently recomputed or added to multiple pillars with inconsistent sources, windows, signs, or scales.

## 3. Data contract

### 3.1 Required metadata

Every raw and derived field MUST declare:

- provider, symbol, field, and dataset version;
- source tier and fallback reason, if any;
- observation and publication timestamps, timezone, calendar, and frequency;
- units, currency, and adjustment/total-return policy;
- revision/vintage policy where applicable;
- freshness and staleness limits;
- missing-data and fallback rules;
- coverage denominator and warm-up requirement;
- duplicate and alignment policy;
- polarity: supportive-positive, adverse-positive, signed-directional, or non-directional;
- a testable monotonicity assertion;
- all consumers.

### 3.2 Benchmark

Use one pinned S&P 500 benchmark contract, either SPX or one declared SPY total-return proxy. Never switch within a published history. The same series/version supplies Direction, realized volatility, benchmark returns, and canonical price damage.

RSP is not a v5.1 Direction input. It was removed with TrendQuality concentration de-duplication.

### 3.3 Breadth tiers

**Tier 1 — preferred:** point-in-time constituent membership, contemporaneous sector classification, and adjusted closes for every eligible constituent, or authoritative point-in-time historical sector-index series.

**Tier 2 — reproducible long history:** fixed nine-sector ETF universe used unchanged for the entire history:

`XLK, XLF, XLV, XLY, XLP, XLE, XLI, XLB, XLU`

**Tier 3 — diagnostic only:** the fixed-eleven universe adds `XLRE` and `XLC` over its common fully warmed sample. It MUST NOT auto-replace or splice Tier 2.

### 3.4 Risk Appetite

Required conceptual inputs are:

- point-in-time high-yield OAS level and change, with publication/vintage metadata;
- QQQ, IWM, and the pinned SPY total-return series.

A validated ETF credit proxy MAY be used only under a separately versioned source tier. HYG with IEF and/or LQD, including duration-neutral variants, remains an EMPIRICAL comparison against OAS and MUST be labeled non-equivalent.

### 3.5 Stability

Canonical production inputs are:

- VIX spot;
- VIX9D;
- the pinned benchmark total-return series.

VIX3M is diagnostic/challenger-only under a separate source contract. It is not required for canonical production. Other cross-asset stress series are not required.

### 3.6 No additional feeds

CRISIS reuses volatility/curve stress, credit stress, canonical price damage, and pinned Breadth. TRENDING reuses Direction/TrendQuality, price damage, Risk Appetite, and Stability. Confidence consumes existing outputs, decision surfaces, metadata, and engine state.

### 3.7 Explicit exclusions

Fed Funds, US2Y, US10Y, the yield curve, DXY, real yields, breakevens, macro releases, portfolio holdings, orders, leverage, RecoveryThrottle, target exposure, and strategy configuration do not determine v5.1 regime.

Their absence MUST NOT reduce `data_completeness` or make Condition unavailable.

## 4. Alignment, availability, and state persistence

### 4.1 Fail closed

Missing, stale, misaligned, or insufficiently warmed required data makes the affected pillar and Condition unavailable. It is never filled neutral or converted to numeric zero. The last categorical state may be retained only with `state_is_current = false` and explicit reason codes.

A data outage is unknown, not CRISIS.

### 4.2 Expected sessions

All horizons use expected trading sessions, not arbitrary row counts. A causal 504-session transform requires 504 valid aligned expected-session observations after the raw feature’s own lookback. Nested features require additional prehistory.

### 4.3 Persisted state

Persist, with schema version and as-of timestamp:

- regime displayed state, pending state, and count;
- CRISIS exit count;
- TRENDING active flag and counters;
- `confirmed_structure`, `pending_upgrade`, and `pending_count`;
- stale/current status and reason codes.

Replay MUST reconstruct the same state from sufficient history or restore this exact versioned state.

## 5. Canonical normalization

### 5.1 Causal empirical midrank

Where a relative transform is required, use a causal 504-session empirical midrank including the current valid observation:

```text
less  = count(window_value < current_value)
equal = count(window_value == current_value)
percentile = 100 * (less + 0.5 * equal) / 504
```

Requirements:

- exactly 504 valid expected-session observations;
- ties use the formula above;
- no expanding-window shortcut;
- no hidden winsorization, forward fill, neutral fill, or interpolation;
- normalize each canonical raw feature once and reuse it; never rerank a combined score.

### 5.2 Raw thresholds

Economically meaningful raw thresholds—VIX level, OAS, drawdown, return shock, participation, and curve ratios—remain in raw units when used by vetoes, caps, CRISIS, or TRENDING. Do not percentile-transform them merely for uniformity.

### 5.3 Challenger

A longer-window robust-z method is EMPIRICAL and may replace midrank only under a new feature-contract version, full recalibration, regenerated history, and parity tests. Histories MUST NOT be spliced.

## 6. Pillars

### 6.1 Direction structure

Direction uses a deterministic, exhaustive, first-match structure over the pinned benchmark. The internal/output field is `direction_structure`, not `trend_state`.

V4.4 benchmark definitions are:

| Structure | Benchmark rule | `direction_sign` |
|---|---|---:|
| `STRONG_BULL` | `close > EMA21 > SMA65 > SMA200` | +1 |
| `BULL` | `close > EMA21` and `EMA21 > SMA200`, excluding prior match | +1 |
| `BULL_PULLBACK` | `close <= EMA21`, `SMA65 > SMA200`, `close > SMA200` | +1 |
| `DAMAGED_BULL` | `close > SMA200`, excluding prior matches | 0 |
| `BEAR` | `close <= SMA200` | -1 |

The partition, first-match rule, and sign mapping are CLOSED. Exact 21/65/200 horizons are EMPIRICAL.

Base scores obey:

```text
STRONG_BULL > BULL >= BULL_PULLBACK > DAMAGED_BULL > BEAR
```

Equality between BULL and BULL_PULLBACK is allowed because structure retains diagnostic value independent of score contribution. Other inequalities are strict. Exact v4.4 base values `0.90/0.80/0.78/0.55/0.15` are EMPIRICAL benchmark values only.

Direction contains no drawdown, breadth, volatility, credit, or rotation term.

### 6.2 Direction confirmation

Publish `direction_structure_raw` every fully valid bar. Order structures from most to least supportive.

- a less-supportive raw structure becomes confirmed immediately;
- a more-supportive raw structure requires consecutive confirmation;
- a candidate resets if raw returns to confirmed, deteriorates, or changes to another upgrade target;
- the exact upgrade count or state-specific counts are EMPIRICAL;
- v4.4 symmetric 3/3 is benchmark-only.

Before the first fully valid raw classification, Direction is unavailable. Initialize confirmed structure from the first observed valid classification; never seed a semantic constant. The known `STRONG_BULL` cold-start defect requires a dedicated regression vector.

Canonical `direction_score` is unsmoothed. A chart-only smoothed series must have a distinct name and cannot feed any output or logic.

### 6.3 TrendQuality

TrendQuality is direction-neutral benchmark-price path quality with two separately published components:

- `linearity_pct`: causal midrank of rolling regression R²;
- `path_efficiency_pct`: causal midrank of absolute net movement divided by cumulative absolute movement.

Combine them with nonnegative weights summing to one. Do not rerank or smooth the combination.

`concentration_pct` is removed; participation belongs exclusively to Breadth. EMA-crossing count is a distinct challenger hypothesis, not another implementation of path efficiency. Regression domain, horizons, zero-movement handling, weights, Direction adjustment coefficient, and all TRENDING thresholds are EMPIRICAL. V4.4’s three-term blend and `74.3` threshold are benchmark artifacts only.

### 6.4 Breadth

Breadth measures participation independently of cap-weighted Direction. The production source tier is explicit in every output. Tier histories are never automatically spliced.

The SMA50/SMA200 participation blend and pillar weight are EMPIRICAL. Missing required coverage makes Breadth unavailable; it is not neutralized.

### 6.5 Risk Appetite

Risk Appetite measures credit plus revealed rotation only. It contains no price damage, rates, curve, macro, or absolute benchmark momentum.

Publish:

- canonical credit level and change components;
- `growth_rotation_pct` from QQQ/SPY total-return relative performance;
- `small_cap_rotation_pct` from IWM/SPY total-return relative performance.

Relative rotation remains valid in falling markets because it measures revealed preference independent of absolute direction. Each rotation raw feature receives one causal 504-session midrank. No gating or sign flip by benchmark return is permitted.

Combine credit and rotation through a bounded convex formula with nonnegative weights summing to one. Zero production weights are allowed by empirical disposition while diagnostics remain published. No additive clipped adjustment architecture, smoothing, winsorization, neutral fill, or absolute QQQ/IWM momentum is canonical.

Horizons, transforms, credit source/construction, weights, and component retention are EMPIRICAL.

### 6.6 Stability

Stability is a supportive-positive bounded convex combination of four separately published domains:

1. `implied_vol_stability`: monotone-decreasing transform of raw VIX level;
2. `vol_curve_stability`: monotone-decreasing transform of VIX9D/VIX;
3. `realized_vol_stability`: monotone-decreasing transform of realized benchmark volatility;
4. `price_stability`: supportive transform of adverse-positive canonical `price_damage`.

Nonnegative weights sum to one. The canonical `price_damage` feature is computed once and may be consumed by Stability, CRISIS, TRENDING, and diagnostics. Stability MUST NOT create a private copy.

VIX relative-to-average, signed VIX ROC, VIX9D absolute level, and VIX3M/VIX are challengers/diagnostics only. A VIX decline MUST NOT lower Stability; the inherited `abs(VIX change)` implementation is polarity-wrong. No smoothing, neutral fallback, stale forward fill, or second inversion is allowed.

Transforms, horizons, realized-vol estimator, price-damage construction, weights, and challenger retention are EMPIRICAL.

## 7. Condition, vetoes, and caps

### 7.1 Weighted measurement

```text
condition_pre_cap = Σ(weight_i * pillar_i)
```

Pillar weights are nonnegative, sum to one, and are EMPIRICAL. The result is clipped only for floating-point safety to `[0,1]`. Publish each contribution.

### 7.2 Hard vetoes

Hard vetoes are memoryless current-condition safety circuits keyed to declared raw domains. A valid veto sets `condition_score = 0` immediately and forces at least `RISK_OFF`. Exact domains and thresholds are EMPIRICAL. Missing data never fires or clears a veto; it makes Condition unavailable.

### 7.3 Conditional soft caps

Production defaults to no soft caps. Adoption is EMPIRICAL.

Any adopted cap MUST:

- use a declared raw domain or canonical raw feature, never aggregate Condition or a pillar;
- be a continuous monotone upper bound in `[0,1]`, with `1` inactive;
- contain no memory or hysteresis;
- publish source value, threshold, mapped bound, active flag, and binding identifier.

```text
condition_score = min(condition_pre_cap, all_active_caps)
```

Hard vetoes take precedence. Minimum composition is deterministic, order-independent, and avoids multiplicative compounding. Ties publish all binders. If empirical tests show no stable incremental safety benefit beyond weights, vetoes, and CRISIS logic, caps remain absent.

## 8. State taxonomy and ordinary hysteresis

| State | Meaning |
|---|---|
| `CRISIS` | Corroborated multi-domain acute stress |
| `RISK_OFF` | Adverse or vetoed without CRISIS corroboration |
| `NEUTRAL` | Mixed/intermediate conditions |
| `RISK_ON` | Broadly supportive conditions |
| `TRENDING` | Persistent unusually clean bull trend |

Exactly one state is emitted. Direction remains orthogonal.

Ordinary state transitions use asymmetric hysteresis: downgrades are faster than upgrades. Exact boundaries, buffers, and counts are EMPIRICAL. `decision_margin` is diagnostic only and never changes counters or labels. A hard veto bypasses ordinary downgrade delay.

## 9. CRISIS

### 9.1 Independent domains

CRISIS confirmation uses four non-nested raw domains:

1. volatility/term-structure stress;
2. canonical credit stress;
3. canonical price damage;
4. participation collapse.

Independent means no confirmation is an algebraic input to another. Economic correlation is expected. Direction, Condition, and aggregate pillars do not count.

### 9.2 Entry and diagnostics

Two valid domains active on the same bar enter CRISIS immediately, without ordinary downgrade delay. At least two domains must be valid.

A hard veto with fewer than two confirmations forces RISK_OFF, not CRISIS:

- zero domains: `uncorroborated_veto = true`, `crisis_watch = false`;
- one domain: `uncorroborated_veto = true`, `crisis_watch = true`.

Publish per-domain valid/active flags, coverage, count, reason codes, and entry/exit counters. Missing/stale is unavailable, never calm or stressed.

### 9.3 Exit

Exit requires all of the following for five consecutive valid bars:

- all hard vetoes clear;
- fewer than two crisis domains active;
- Condition above the NEUTRAL-entry boundary plus buffer.

Renewed two-domain confirmation resets the count.

### 9.4 No exchange-halt override

Exchange halts are OUT_OF_SCOPE operational events. Missing data yields unavailable Condition and stale state, never CRISIS. A future execution-control schema may block orders from an authoritative halt feed; measurement outputs and history are not overwritten.

## 10. TRENDING

TRENDING is the fifth exclusive state, not a badge, entry signal, or leverage mechanism. Qualification requires a bullish `direction_structure`, sufficiently high TrendQuality, shallow canonical price damage, Risk Appetite and Stability veto floors, and persistent state rules.

Exact qualification, veto, entry, and exit thresholds/counters are EMPIRICAL. The inherited `74.3` threshold is not retained by rescaling.

When active:

- `state = TRENDING`;
- `condition_score <= 1.0`;
- no leverage bonus is added.

## 11. Impulse

Impulse describes motion in final post-veto/post-cap `condition_score`, before categorical state hysteresis.

Publish fast and slow endpoint changes plus one aggregate `impulse_score` in `[-1,1]`.

Requirements:

- positive means Condition improved; negative means deteriorated; unchanged maps exactly to zero;
- for each valid horizon, `sign(impulse_h) = sign(condition_t - condition_t-h)` when nonzero;
- scaling is causal and anchored at zero, never recentered on a rolling mean;
- the aggregate transform is continuous, odd, monotone, zero-preserving, and symmetrically bounded;
- fast/slow weights are nonnegative and sum to one;
- at most one declared odd squashing transform is applied;
- missing/stale endpoints or invalid required interior sessions make the horizon and aggregate unavailable;
- Impulse never feeds Condition, caps, vetoes, counters, or state.

Publish pre-cap changes, pillar impulses, and binding-cap/veto changes separately for attribution. They do not replace headline Condition Impulse.

Horizons, scale estimator/window/floor, weights, and transform are EMPIRICAL. V4.4’s 5/20, 0.6/0.4, rolling z-score, and tanh are benchmark-only.

## 12. Confidence diagnostics

Publish no aggregate confidence scalar.

- `pillar_agreement`: common-polarity pillar dispersion; more disagreement cannot improve it.
- `data_completeness`: optional/tier coverage and freshness; restoring data cannot reduce it. Required failure makes Condition unavailable instead.
- `decision_margin`: distance from the applicable decision surface, including TRENDING; it never drives transitions.
- `temporal_stability`: recent Condition noise and label fragility.

Formulas are EMPIRICAL. Confidence never rescales Condition or state.

## 13. Output schema

### 13.1 Core fields

- `schema_version`, `feature_contract_version`, `as_of`;
- `condition_pre_cap`, `condition_score`, derived `condition_pct`;
- `state`, `state_is_current`, `direction_sign`;
- `direction_score`, `breadth_score`, `risk_appetite_score`, `stability_score`;
- `direction_structure_raw`, `direction_structure`;
- `linearity_pct`, `path_efficiency_pct`, `trend_quality`;
- `growth_rotation_pct`, `small_cap_rotation_pct` and credit components;
- four Stability domain scores and canonical `price_damage`;
- `impulse_fast`, `impulse_slow`, `impulse_score`;
- four Confidence diagnostics.

### 13.2 Explainability and state fields

Publish all canonical raw/normalized features, contributions, active vetoes/caps, binding identifiers, source tier, coverage, freshness, warm-up, polarity, reason codes, Direction pending state, ordinary regime pending state, CRISIS counters, and TRENDING counters.

### 13.3 Nullability

The machine-readable manifest defines type, unit, range, polarity, nullability, status, source contract, and consumers for every field. Unavailable Condition is null/NA with reasons, never numeric zero.

### 13.4 Removed fields

V5.1 emits no `trend_state` alias; use `direction_structure`. It emits no macro panel, exchange-halt override, policy/routing/sizing field, or trading-action marker.

## 14. Validation

### 14.1 Golden vectors

Immutable vectors MUST cover:

- normalization ties, exact warm-up, missing sessions, and stale data;
- every Direction structure and boundary;
- Direction cold start in every raw structure, especially first valid non-STRONG_BULL after insufficient history;
- immediate downgrades, candidate upgrades, oscillation, target changes, nonadjacent jumps, and restart parity;
- TrendQuality component polarity and de-duplication;
- Breadth source tiers and no-splice behavior;
- Risk Appetite relative rotation in rising and falling markets;
- independent Stability perturbations, including that a VIX fall never lowers Stability;
- hard vetoes, optional caps, ties, and no-cap baseline;
- every CRISIS domain alone and pair, missing-domain cases, recovery, and relapse;
- TRENDING entry, persistence, veto, and exit;
- Impulse zero, equal/opposite paths, monotone paths, veto/cap changes, saturation, gaps, and sign consistency;
- Confidence monotonicity;
- measurement/policy boundary invariants.

### 14.2 Empirical method

Use preregistered compact challenger sets, anchored walk-forward evaluation, untouched holdout periods, crisis/trend subperiods, bootstrap uncertainty, sensitivity surfaces, and ablations. Report tail loss, false restriction, turnover, dwell/transition behavior, calibration stability, redundancy, and opportunity cost as applicable. Do not select a broad-grid in-sample optimum.

### 14.3 Python/Pine parity

Python is the reference implementation. Pine must reproduce every feasible field within declared tolerances or be labeled proxy-only. Exact matching is required for booleans, labels, counters, source tiers, and reason codes. Float tolerances are EMPIRICAL and field-specific.

### 14.4 Layer-boundary tests

The measurement engine MUST run without strategy or portfolio configuration. Changing routing rules MUST leave every measurement output byte-identical. Missing policy inputs cannot affect Condition availability. Measurement visualizations contain no trading verbs. Downstream policy state cannot affect replayed measurement outputs.

## 15. Migration

1. Freeze v4.4 and v5.0 artifacts and retain their histories.
2. Publish v5.1 schema and feature-contract namespaces side by side.
3. Rename `trend_state` to `direction_structure` with no silent alias.
4. Remove RSP from Direction, rebuild TrendQuality, and recalibrate dependent Direction/TRENDING values.
5. Rebuild Risk Appetite and Stability under their convex topologies.
6. Re-derive pillar weights, vetoes, state boundaries, CRISIS, and TRENDING in dependency order.
7. Validate no-caps baseline before activating any cap.
8. Calibrate Impulse and Confidence diagnostics.
9. Build golden vectors and Python reference; parity-test Pine.
10. Shadow-run v4.4/v5.0/v5.1 and reconcile every difference.
11. Migrate continuous sizing consumers through a separately versioned policy adapter; never alias Condition inside measurement.
12. Cut over only after acceptance criteria pass.

Historical fields are never rewritten. No old `market_permission` is aliased to new Condition.

## 16. CLOSED register

1. Four supportive-positive pillars; direction orthogonal.
2. Five mutually exclusive states; TRENDING exclusive, stateful, bull-only, and non-levered.
3. Condition contains no MemoryDiscount, sizing policy, or latent episode memory.
4. Direction structure partition, sign mapping, partial-order constraint, and breaking rename.
5. Direction upgrades confirm; downgrades are immediate; valid-data initialization only.
6. TrendQuality is price-only linearity plus path efficiency; concentration/RSP removed.
7. Breadth source tiers are pinned, diagnostic eleven-sector history is never auto-spliced.
8. Risk Appetite is credit plus independently valid SPY-relative rotation, combined convexly.
9. Stability is a four-domain convex topology; VIX3M is challenger-only; price damage computed once.
10. Canonical relative normalization is causal 504-session midrank.
11. Hard vetoes are immediate current-feature constraints.
12. Soft-cap interface is raw-domain, continuous, memoryless, observable, and min-composed; default is no caps.
13. CRISIS uses 2-of-4 non-nested raw domains with immediate entry and five-bar corroborated-clear exit.
14. Impulse tracks final Condition with sign consistency, zero anchor, and no feedback.
15. Confidence is four diagnostics with no aggregate scalar.
16. Missing required data fails closed; unknown is not CRISIS.
17. Exchange-halt override removed from measurement.
18. Macro panel removed from the regime schema and lifecycle.
19. Measurement-to-routing/action aliases prohibited; interface is one-way and immutable.
20. V5.1 is a breaking schema/feature-contract version with side-by-side migration.

## 17. EMPIRICAL register

1. Direction MA horizons and base scores.
2. Direction upgrade confirmation count(s).
3. TrendQuality regression domain, horizons, zero handling, weights, Direction adjustment, and challenger selection.
4. Breadth SMA50/SMA200 blend and pillar weight.
5. Canonical credit source/construction, ETF proxy selection, and duration-neutralization.
6. Risk Appetite horizons, transforms, weights, and component retention.
7. Stability transforms, horizons, realized-vol estimator, price damage, weights, and challenger retention.
8. Four pillar weights and contribution transforms.
9. Hard-veto domains and thresholds.
10. Whether any soft cap is adopted; every cap domain, threshold, and curve.
11. State boundaries, buffers, and ordinary hysteresis counts.
12. Four CRISIS formulas and thresholds.
13. TRENDING qualification, veto, entry, and exit thresholds/counters.
14. Impulse horizons, scale estimator, weights, and transform.
15. Confidence formulas and calibration; any future aggregate requires a new decision/version.
16. RecoveryThrottle versus no throttle and legacy MemoryDiscount downstream.
17. No leverage versus legacy `+0.05` versus volatility-targeted leverage downstream.
18. 504-midrank versus longer robust-z challenger.
19. Per-source freshness/as-of tolerances.
20. Python/Pine numerical and data-parity tolerances.

## 18. OUT_OF_SCOPE register

- strategy selection, routing, fit, and action labels;
- position sizing and portfolio construction;
- leverage authorization and RecoveryThrottle adoption;
- execution, transaction costs, financing, and broker integration;
- exchange-halt order controls;
- macro-context product fields and macro forecasting;
- intraday regime calculation unless separately versioned;
- compatibility-policy design beyond the permitted separate adapter boundary.

## 19. Resolved inherited-item audit

V5.0 §19 contained ten inherited items. All are now dispositioned:

| Item | V5.1 disposition |
|---|---|
| Direction MA state/base-score table | Structure CLOSED; horizons/scores EMPIRICAL |
| TrendQuality construction | Two-component topology CLOSED; formulas/weights EMPIRICAL |
| Direction confirmation bars | Asymmetric implementation CLOSED; counts EMPIRICAL |
| Risk Appetite relative strength | Relative/convex topology CLOSED; formulas/weights EMPIRICAL |
| Stability and VIX3M | Four-domain topology CLOSED; formulas/weights EMPIRICAL; VIX3M challenger-only |
| Soft caps | Conditional interface CLOSED; adoption and parameters EMPIRICAL; default none |
| Impulse 5/20 tanh | Invariants/topology CLOSED; all constants/transform EMPIRICAL |
| Exchange-halt override | Removed; OUT_OF_SCOPE |
| Macro-context panel | Removed; OUT_OF_SCOPE |
| Measurement-to-routing coupling | Prohibited; routing/policy OUT_OF_SCOPE |

There are no remaining `INHERITED_PENDING_REVIEW` items in v5.1.

## 20. Acceptance criteria

V5.1 is implementation-ready only when:

- a machine-readable manifest exists and matches this document;
- every required source contract is pinned;
- release-blocking EMPIRICAL tasks are complete;
- all golden-vector and boundary invariants pass;
- Python reference outputs are reproducible;
- Pine is parity-tested or explicitly proxy-only;
- v4.4/v5.0/v5.1 shadow differences are reconciled;
- no policy, routing, macro, or operational field leaks into measurement;
- no unresolved constant is presented as normative.

Until then, v5.1 is the authoritative architecture baseline, not a production trading signal.
