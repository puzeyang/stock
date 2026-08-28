# Market Regime v5.1 — Reference Implementation Plan

**Status:** DRAFT — planning artifact, not yet independently reviewed. No implementation code exists yet under this plan.
**Purpose:** the missing prerequisite identified in `market-regime-discussion.md` Message[157]/[158]/[159]/[160] — the frozen Freshness/Staleness Threshold Experiment (`Freshness_Threshold_Experiment_v1.0.md`) cannot compute three of its six Stage-1 §5 metrics without a working Python reference implementation of the v5.1 measurement engine, and none exists. Building it is authorized by the human's "agree" to Message[158]'s four-point plan; it does not authorize Stage-1 outcome computation, threshold calibration, portfolio policy, or holdout access, per Message[160]'s explicit boundary.
**Decision record:** `market-regime-discussion.md`, Messages 157–160 (this plan's own authorization) and Messages 1–67 (the design's own decision record, per the design doc header). Filed at `research/market/discussion/market-regime-discussion.md` when Messages 1–160 were written; moved to `regime/discussion/market-regime-discussion.md` as of Message[184] (2026-08-27) — the log itself is append-only and unedited by the move, so message numbers are stable regardless of which path a given message was written under.
**Design under implementation:** `Market_Regime_Design_v5.1.md`
**Manifest under implementation:** `market_regime_fields.v5.1.json`, `market_regime_field_manifest.schema.v1.0.0.json`
**Consumer graph:** `market_regime_consumer_graph.v5.1.json`

## 0. Pinned identities at plan-authoring time

**Post-move note (added 2026-08-27, found during an independent senior-dev
review):** the `research/regime/...` paths in the table below are exactly
as they were at plan-authoring time (2026-08-26) — this table is a
point-in-time historical record, deliberately not rewritten here, the same
treatment as the frozen freshness registry's own `traceability` block (see
`regime/README.md`'s "Known, deliberate inconsistency" section). Every
file this table names except `research/regime/src/state_layer.py` (line 27
— that file legitimately never moved; it belongs to the older v1.0/v7.2
engine that stayed in `research/regime/`) has since moved to `regime/...`
(no `research/` prefix) as part of the 2026-08-27 reorganization — see
Message[184] in `regime/discussion/market-regime-discussion.md`. Use
`regime/README.md`'s own layout table for current paths; the hashes below
remain historically accurate for the design doc, frozen spec, and frozen
registry (their content never changed), but are STALE for the field
manifest, manifest schema, consumer graph, calendar artifact, and field
ownership map/verifier, all four of which were legitimately re-pointed at
their new paths during the move and therefore now hash differently (see
`regime/README.md` for current hashes).

Every artifact this plan is written against, content-addressed. Any change to these files after this plan is written invalidates the plan's own claims about them and requires re-verification before implementation proceeds on the affected slice.

| Artifact | Path | SHA-256 |
|---|---|---|
| Design doc | `research/regime/docs/Market_Regime_Design_v5.1.md` | `ee9414342b07b2033f77a8a2365406b809eed97bfa778eb260e2f5130288af87` |
| Field manifest | `research/regime/schema/market_regime_fields.v5.1.json` | `761b07e8f8471444664da4a48147003308c096bfb83fa5758b480bda469d4c7b` |
| Manifest schema | `research/regime/schema/market_regime_field_manifest.schema.v1.0.0.json` | `9be0655ba33b4379ba3bedafa64037206e012702f1bc829e67560c9700a5109d` |
| Consumer graph | `research/regime/schema/market_regime_consumer_graph.v5.1.json` | `8b5871b08a1560b0aeccbb6f1b609c8500719ac6fd0c75149603a59ba9787cce` |
| Frozen freshness spec | `research/regime/docs/Freshness_Threshold_Experiment_v1.0.md` | `c5899dfc7359eab220e1aeba070474800f6bf19b49c10e9615597cf3adde9a0a` (post-freeze hash, per Message[155]/[156]) |
| Frozen freshness registry | `research/regime/schema/freshness_injection_registry.v1.0.json` | `7b4e9697607bc62147b7074949a24d9ad3b1b51f73b91ea37d730d90947047fe` (post-freeze, per Message[155]/[156]) |
| Expected-session calendar artifact | `research/regime/schema/expected_session_calendar.v1.0.json` | `e51f745f9efff78516f0f2f3770f62699356c1fb639e0f0c10050cf75d199188` — **load-bearing for module 4.1's session-count arithmetic** (added per Message[162] item 4, omitted from the original plan) |
| Field ownership map | `research/regime/schema/market_regime_v5.1_field_ownership.v1.0.json` | `466e839f2bb2a81878228477a93b0e13eb617aa74c85c618b6eecc02cf165341` — **authoritative 86-field→module assignment, added per Message[164] item 1**; every field in the pinned manifest maps to exactly one owner from the closed 4.1–4.12 vocabulary, role-checked; this is what §7.1's manifest-conformance gate and Slice 10 integration actually check against, not an informal "respective module" claim |
| Field ownership verifier | `research/regime/tools/verify_field_ownership.py` | `9779bd9732f4441c9a0e0c5d6fdcca8b2b3ffcbb40363ee8eaa13ff0f3fdd09c` — standalone checker, independent of the script that built the ownership map, re-verifiable via `python3 research/regime/tools/verify_field_ownership.py` |
| Repo commit at plan-authoring | — | `4dab6d1103660775a2252a093afb18a95fc5ae99` (dirty tree; unrelated files only — `lib/data/fear_greed/*.parquet`, untracked `.claude/`, `stock.code-workspace`) |

Confirmed via direct grep this session: **no existing code implements v5.1.** `research/regime/src/state_layer.py` uses the six-state vocabulary `CONSTRUCTIVE, NEUTRAL, CAUTION, ELEVATED_RISK, CORRECTIVE, CRISIS` (the older v1.0/v7.2 engine), not v5.1's five mutually-exclusive states `CRISIS, RISK_OFF, NEUTRAL, RISK_ON, TRENDING`. ChatGPT independently confirmed the same via a full-repo search (Message[158]). This plan starts from zero.

**Identity inheritance rule (added per Message[162] item 4):** every source-data snapshot identity used by any slice is inherited from, and MUST be re-verified against, the pinned field manifest (`market_regime_fields.v5.1.json`'s own `snapshot_sha256` entries) at the time that slice runs — never assumed stable from this plan's own authoring time. This table's hashes establish this plan's own identity; they are not a substitute for each slice re-checking the manifest's live pins before it runs, exactly as `verify_freshness_registry.py` already does for the freshness experiment.

## 1. CLOSED requirement inventory (from design §16, cross-checked against §§1–15)

Every CLOSED item is a hard invariant the implementation MUST satisfy exactly; none of these are tunable.

| # | CLOSED item | Design ref | Module owner (§4 below) |
|---|---|---|---|
| C1 | Four supportive-positive pillars (Direction, Breadth, Risk Appetite, Stability), each converging independently on `condition_pre_cap`. `direction_sign` (in `{-1,0,+1}`) is orthogonal to Condition and never enters the pillar-weighted sum; `direction_score` (the Direction pillar's own supportive-positive contribution, informed internally by TrendQuality) is what feeds `condition_pre_cap` (corrected per Message[162] item 1 — the original inventory conflated "Direction orthogonal" with "not a pillar contributor," when only the *sign* is orthogonal, not the pillar's score) | §16.1, §1.1 | Pillars |
| C2 | Five mutually exclusive states; TRENDING exclusive, stateful, bull-only, non-levered | §16.2, §8, §10 | State machine |
| C3 | Condition contains no MemoryDiscount, sizing policy, or latent episode memory | §16.3, §1.3 | Condition/Vetoes/Caps |
| C4 | Direction structure partition is deterministic, exhaustive, first-match; partial order `STRONG_BULL > BULL >= BULL_PULLBACK > DAMAGED_BULL > BEAR`; `direction_structure` not `trend_state` | §16.4, §6.1 | Direction |
| C5 | Direction upgrades confirm (consecutive-bar requirement); downgrades are immediate; valid-data-only initialization (no semantic-constant seed) | §16.5, §6.2 | Direction |
| C6 | TrendQuality = price-only `linearity_pct` + `path_efficiency_pct`; concentration/RSP removed | §16.6, §6.3 | TrendQuality |
| C7 | Breadth source tiers pinned (Tier 1/2/3); Tier 3 (diagnostic eleven-sector) never auto-spliced into Tier 2 | §16.7, §3.3, §6.4 | Breadth |
| C8 | Risk Appetite = credit + independently-valid SPY-relative rotation, combined convexly; no absolute momentum, no gating/sign-flip by benchmark return | §16.8, §6.5 | Risk Appetite |
| C9 | Stability = four-domain convex topology; VIX3M challenger-only; canonical `price_damage` computed once, shared not copied | §16.9, §6.6 | Stability |
| C10 | Canonical relative normalization is causal 504-session empirical midrank (tie formula fixed) | §16.10, §5.1 | Normalization primitive |
| C11 | Hard vetoes are immediate current-feature constraints (memoryless); missing data never fires/clears a veto | §16.11, §7.2 | Condition/Vetoes/Caps |
| C12 | Soft-cap interface is raw-domain, continuous, memoryless, observable, min-composed; default is no caps | §16.12, §7.3 | Condition/Vetoes/Caps |
| C13 | CRISIS uses 2-of-4 non-nested raw domains, immediate entry, five-consecutive-bar corroborated-clear exit | §16.13, §9 | CRISIS state machine |
| C14 | Impulse tracks final `condition_score` with sign consistency, zero anchor, no feedback into Condition/caps/vetoes/counters/state | §16.14, §11 | Impulse |
| C15 | Confidence is four diagnostics, no aggregate scalar | §16.15, §12 | Confidence |
| C16 | Missing required data fails closed; unknown ≠ CRISIS | §16.16, §4.1, §9.4 | Alignment/Availability |
| C17 | Exchange-halt override removed from measurement (OUT_OF_SCOPE) | §16.17, §9.4 | N/A (explicitly excluded) |
| C18 | Macro panel removed from schema/lifecycle (OUT_OF_SCOPE) | §16.18 | N/A (explicitly excluded) |
| C19 | Measurement→routing/action aliases prohibited; interface is one-way, immutable | §16.19, §1.2, §14.4 | Layer-boundary conformance |
| C20 | V5.1 is a breaking schema/feature-contract version, side-by-side migration | §16.20, §15 | N/A (versioning discipline, not a runtime invariant) |

Additional CLOSED invariants not separately numbered in §16 but stated elsewhere and equally binding:
- **Path dependence** (§1.3): identical valid inputs over every declared lookback MUST produce identical pillars/Condition; only `direction_structure` confirmation and categorical state carry finite, explicit confirmation logic; replay MUST reconstruct or restore exact state.
- **Fail-closed philosophy** (§4.1): missing/stale/misaligned/insufficiently-warmed data → pillar and Condition unavailable, never neutral-filled or zeroed; last categorical state retained only with `state_is_current = false` plus reason codes.
- **Expected-session horizons** (§4.2): all horizons count expected trading sessions, never raw row counts.
- **No additional feeds** (§3.6): CRISIS/TRENDING/Confidence reuse existing outputs only — no new source contracts beyond the ten already pinned in the manifest.
- **Nullability discipline** (§13.3): unavailable Condition is null/NA with reasons, never numeric zero.
- **Layer-boundary tests** (§14.4): engine MUST run with zero strategy/portfolio configuration; routing changes MUST leave every measurement output byte-identical.

## 2. EMPIRICAL interface inventory (from design §17)

Every EMPIRICAL item MUST be implemented as a **named, versioned, injectable parameter** — never a hardcoded production constant — per the design's own instruction that "EMPIRICAL values MUST NOT be presented as final constants" (§0). V4.4 values, where cited in the design, are permitted ONLY as a labeled comparison/regression-test baseline, never as the shipped default.

| # | EMPIRICAL item | Design ref | Parameterization requirement |
|---|---|---|---|
| E1 | Direction MA horizons and base scores | §17.1, §6.1 | `direction_horizons: {ema, sma_mid, sma_long}` (v4.4 default 21/65/200 as a *labeled benchmark preset*, not the only preset); `direction_base_scores: {STRONG_BULL, BULL, BULL_PULLBACK, DAMAGED_BULL, BEAR}` respecting the C4 partial order at construction time (a config validator, not a runtime check) |
| E2 | Direction upgrade confirmation count(s) | §17.2, §6.2 | `direction_confirmation_bars` (v4.4 symmetric 3/3 benchmark-only; per-state count MAY differ) |
| E3 | TrendQuality regression domain/horizons/zero-handling/weights/Direction adjustment/challenger selection | §17.3, §6.3 | `trendquality_config` object; EMA-crossing-count challenger implemented as a separate diagnostic function, never merged into path efficiency |
| E4 | Breadth SMA50/SMA200 blend and pillar weight | §17.4, §6.4 | `breadth_blend_weights`, `pillar_weight_breadth` |
| E5 | Canonical credit source/construction, ETF proxy selection, duration-neutralization | §17.5, §3.4, §6.5 | `credit_source_config` (OAS canonical; HYG/IEF/LQD proxy variants labeled non-equivalent per §3.4, never silently substituted) |
| E6 | Risk Appetite horizons/transforms/weights/component retention | §17.6, §6.5 | `risk_appetite_config` |
| E7 | Stability transforms/horizons/realized-vol estimator/price-damage construction/weights/challenger retention | §17.7, §6.6 | `stability_config` |
| E8 | Four pillar weights and contribution transforms | §17.8, §7.1 | `pillar_weights: {direction, breadth, risk_appetite, stability}` — nonnegative, sum-to-one enforced at load time |
| E9 | Hard-veto domains and thresholds | §17.9, §7.2 | `hard_veto_config` (list of `{domain, threshold, comparator}`) |
| E10 | Whether any soft cap is adopted; every cap domain/threshold/curve | §17.10, §7.3 | `soft_cap_config` — empty list is the production default; must be provably empty-safe (no caps ⇒ `condition_score == condition_pre_cap` after veto) |
| E11 | State boundaries, buffers, ordinary hysteresis counts | §17.11, §8 | `state_transition_config` |
| E12 | Four CRISIS formulas and thresholds | §17.12, §9.1–§9.3 | `crisis_domain_config` (one entry per domain, independent of the other three) |
| E13 | TRENDING qualification/veto/entry/exit thresholds/counters | §17.13, §10 | `trending_config` |
| E14 | Impulse horizons/scale estimator/weights/transform | §17.14, §11 | `impulse_config` |
| E15 | Confidence formulas and calibration | §17.15, §12 | `confidence_config`; any future aggregate scalar is explicitly OUT_OF_SCOPE without a new design decision |
| E16 | RecoveryThrottle vs. no throttle; legacy MemoryDiscount downstream | §17.16 | OUT_OF_SCOPE for this engine (downstream policy layer only, per §1.2) — plan does not implement, only ensures no accidental coupling |
| E17 | No leverage vs. legacy `+0.05` vs. volatility-targeted leverage downstream | §17.17 | Same as E16 — OUT_OF_SCOPE for the measurement engine |
| E18 | 504-midrank vs. longer robust-z challenger | §17.18, §5.3 | Midrank is canonical/default; robust-z challenger implemented as a separately-versioned, clearly labeled alternative, never silently substituted (§5.3 requires a new feature-contract version to adopt) |
| E19 | Per-source freshness/as-of tolerances | §17.19 | This is the exact interface the frozen Freshness Threshold Experiment tests — see §5 below |
| E20 | Python/Pine numerical and data-parity tolerances | §17.20, §14.3 | Deferred — Pine parity is a later acceptance-gate item (§8), not required for the Python reference engine itself |

E16/E17 are explicitly OUT_OF_SCOPE for this plan (design §1.2, §18) and are listed only so no future slice accidentally reintroduces them.

## 3. OUT_OF_SCOPE register (from design §18) — hard exclusions for every module

- Strategy selection, routing, fit, and action labels.
- Position sizing and portfolio construction.
- Leverage authorization and RecoveryThrottle adoption.
- Execution, transaction costs, financing, broker integration.
- Exchange-halt order controls.
- Macro-context product fields and macro forecasting.
- Intraday regime calculation (unless separately versioned — not this plan).
- Compatibility-policy design beyond the permitted separate adapter boundary.

No module in §4 may emit, consume, or reference any of the above. This is enforced mechanically by the layer-boundary conformance suite (§7.4).

## 4. Module / API boundaries and dependency order

Modules are listed in required build order (each depends only on modules above it). This is also the implementation-slice order for §8's independently-reviewable slices.

Corrected per Message[162] item 1: the original diagram wrongly routed Direction/TrendQuality/Breadth/Risk Appetite into Stability, then Stability alone into Condition. Design §2's actual topology has TrendQuality as an internal input to Direction (not a peer pillar — TrendQuality has no separate pillar weight in E8's `pillar_weights`, it only feeds `direction_score` per §6.3), and all FOUR pillars (Direction, Breadth, Risk Appetite, Stability) converge INDEPENDENTLY on `condition_pre_cap`. Stability depends only on canonical features from 4.2 (VIX/VIX9D/VIX3M/benchmark realized-vol/`price_damage`), never on the other three pillars' outputs.

**Further corrected per Message[164] item 2**: the round-1 fix still drew a direct arrow from 4.2's canonical features into the `condition_pre_cap` node (labeled "price_damage shared"), which is itself a bypass of the four-pillar convergence — `price_damage` is computed once inside Stability (4.7, design §6.6), not fed to `condition_pre_cap` directly. The diagram below removes that arrow entirely; `condition_pre_cap` now has exactly four inputs (the four pillar contributions), and `price_damage`'s downstream sharing with 4.10's CRISIS price-damage domain is shown as a normal 4.7→4.10 read, not a line touching the weighted-sum node.

```
                    ┌─────────────────────────┐
                    │ 4.1 Contracts & Primitives│   (manifest loader, freshness/as-of
                    └────────────┬─────────────┘    evaluator, causal midrank, expected-
                                 │                    session calendar reader)
                    ┌────────────▼─────────────┐
                    │ 4.2 Canonical Raw Features │   (per-field canonical computations;
                    └────────────┬─────────────┘    shared, never re-derived — see §4.2
                                 │                    for the exact scope, corrected below)
        ┌────────────┬──────────┼──────────┬────────────┐
        ▼            ▼          ▼          ▼            ▼
  ┌───────────┐ ┌─────────┐┌─────────┐┌─────────┐
  │4.4 Trend   │ │4.5      ││4.6      ││4.7      │
  │Quality     │ │Breadth  ││Risk     ││Stability │
  └─────┬──────┘ └────┬────┘│Appetite │└────┬────┘
        │              │    └────┬────┘     │  computes canonical `price_damage`
        ▼              │         │          │  ONCE (design §6.6) — shared downstream
  ┌───────────┐        │         │          │  by 4.10's CRISIS price-damage domain,
  │4.3         │        │         │          │  never re-derived there (see note below
  │Direction   │        │         │          │  the diagram)
  │(consumes   │        │         │          │
  │TrendQuality│        │         │          │
  │internally) │        │         │          │
  └─────┬──────┘        │         │          │
        │               │         │          │
        ▼               ▼         ▼          ▼
  ┌──────────────────────────────────────────────────┐
  │  condition_pre_cap = Σ(weight_i · pillar_i)        │
  │  — exactly FOUR pillar-contribution inputs          │
  │    (Direction, Breadth, Risk Appetite, Stability);   │
  │    NO other module feeds this node directly          │
  └────────────────────────┬───────────────────────────┘
                            │
        ┌────────────────────▼─────────────────────┐
        │  4.8 Condition / Vetoes / Caps      │
        └────────┬───────────────┬───────────┘
                  │               │
        ┌─────────▼────┐   ┌──────▼──────────────┐
        │ 4.9 Impulse   │   │ 4.10 State Machine   │◄── consumes 4.7's shared
        └───────────────┘   │  (ordinary/CRISIS/    │    `price_damage` output for its
                             │   TRENDING)           │    CRISIS price-damage domain —
                             └──────────┬────────────┘    a normal downstream read, not
                                        │                  a `condition_pre_cap` bypass
                             ┌──────────▼────────────┐
                             │ 4.11 Confidence         │◄─── (consumes state + pillars)
                             └──────────┬────────────┘
                                        │
                             ┌──────────▼────────────┐
                             │ 4.12 Output Assembly &  │
                             │   Manifest Validation   │
                             └──────────┬────────────┘
                                        │
                             ┌──────────▼────────────┐
                             │ 4.13 Replay Interface   │
                             │  (clean vs. injected)   │
                             └───────────────────────┘
```

### 4.1 Contracts & Primitives
- **Manifest loader**: parses `market_regime_fields.v5.1.json` against `market_regime_field_manifest.schema.v1.0.0.json` (jsonschema Draft 2020-12, matching the discipline already used in `verify_freshness_registry.py`), exposing typed `SourceContract` objects.
- **Freshness/as-of evaluator**: implements design §2's "Alignment / freshness / warm-up" stage and §4.1's fail-closed rule using the boundary-semantics vocabulary already CLOSED in the frozen Freshness spec §2 (CURRENT/STALE/MISSING/MISALIGNED states, reason codes) — **this is the exact interface the freshness experiment's candidate `N` values plug into**, so it MUST accept `N` as an injected parameter per source family, not a constant.
- **Expected-session calendar reader**: reads `research/regime/schema/expected_session_calendar.v1.0.json` (already built and frozen in the freshness-experiment work) for XNYS/Cboe/FRED session calendars — reused, not reimplemented.
- **Causal 504-session empirical midrank** (design §5.1): the tie-formula-exact primitive, computed once, shared by every pillar that needs it (C10). Unit-testable in total isolation from any pillar logic.

*Output contract:* `RawObservation` records with full §3.1 metadata (provider, symbol, field, dataset version, source tier, timestamps, timezone, calendar, frequency, units, adjustment policy, vintage policy, freshness/staleness limits, missing-data rule, coverage denominator, warm-up requirement, duplicate/alignment policy, polarity, monotonicity assertion, consumers) — this is a direct mapping from each manifest `source_contract`, not a new schema.

### 4.2 Canonical Raw Features
**Corrected per Message[162] item 2** — the original text claimed "one function per manifest field," which is wrong: the manifest has 86 fields by role (8 raw, 34 core, 31 explainability, 13 state, directly confirmed by role-count query against the pinned manifest), and this module owns only the raw-input layer, not core/explainability/state outputs (those belong to their respective pillar/Condition/state-machine/output-assembly modules, §4.3–§4.12).

This module's actual scope is exactly the manifest's 8 `role: raw` fields, one canonical computation per field, plus the small set of derived-raw intermediates each raw field's own `consumers` list implies but which are not separately published manifest rows (e.g. `realized_volatility`, `benchmark_drawdown`, `benchmark_return_shock` derived from `benchmark_total_return_close`; `growth_rotation_raw`/`small_cap_rotation_raw` derived from the QQQ/IWM/benchmark raw triple) — these derived-raw intermediates are still "canonical raw features" in design §2's sense (computed once, before any pillar-specific logic), not core/explainability outputs, because no pillar publishes them directly as its own headline score.

| Manifest raw field | Source contract | Canonical raw features derived from it |
|---|---|---|
| `benchmark_total_return_close` | `BENCHMARK_V5_1` | benchmark price series; realized volatility; `benchmark_drawdown`; `benchmark_return_shock`; canonical `price_damage` (design §6.6, shared not re-derived) |
| `breadth_member_observations` | `BREADTH_V5_1` | breadth participation series, per active tier (§3.3) |
| `oas_level` | `OAS_V5_1` | credit level/change components (§6.5) |
| `qqq_total_return_close` | `QQQ_V5_1` | `growth_rotation_raw` (QQQ/SPY relative) |
| `iwm_total_return_close` | `IWM_V5_1` | `small_cap_rotation_raw` (IWM/SPY relative) |
| `vix_level` | `VIX_V5_1` | `implied_vol_stability` raw input |
| `vix9d_level` | `VIX9D_V5_1` | `vol_curve_stability` raw input (VIX9D/VIX ratio) |
| `vix3m_level` | `VIX3M_DIAGNOSTIC_V5_1` | diagnostic/challenger-only input (§3.5) |

Each canonical feature is computed exactly once and referenced (not recomputed) by every downstream pillar/domain that consumes it — the consumer graph (`market_regime_consumer_graph.v5.1.json`) is the authoritative multi-consumer map. The conformance gate (§7.2) verifies the *declared direct edges* in that graph against real code references — it does not require every one of the manifest's 86 fields to be produced by this module; core/explainability/state fields are produced by their true owning modules (§4.3–§4.12) and validated by those modules' own manifest-conformance gate (§7.1) instead.

*Output contract:* `CanonicalFeature` records: value, polarity, coverage/warm-up status, freshness state (from 4.1's evaluator), source contract ID.

### 4.3 Direction (C4, C5, E1, E2)
Implements the five-structure partition, first-match rule, partial order, sign mapping (C4); asymmetric confirmation — immediate downgrade, consecutive-bar upgrade (C5); valid-data-only cold-start initialization with the documented `STRONG_BULL` cold-start defect covered by a dedicated regression vector (§6.2, also required in golden vectors §14.1). Publishes `direction_structure_raw`, `direction_structure`, `direction_sign`, `direction_score` (unsmoothed — any smoothed variant is a separately-named, non-feeding diagnostic only).

### 4.4 TrendQuality (C6, E3)
`linearity_pct` (causal midrank of rolling regression R²) and `path_efficiency_pct` (causal midrank of net/cumulative absolute movement), combined with nonnegative sum-to-one weights, no reranking of the combination. EMA-crossing-count challenger is a separate diagnostic function.

### 4.5 Breadth (C7, E4)
Tier-aware (Tier 1/2/3 per §3.3), pinned source tier explicit in every output, no auto-splice. Missing required coverage → unavailable (fail-closed per C16), never neutralized.

### 4.6 Risk Appetite (C8, E5, E6)
Credit level/change (canonical OAS; ETF-proxy variant explicitly labeled non-equivalent) + `growth_rotation_pct` (QQQ/SPY) + `small_cap_rotation_pct` (IWM/SPY), each one causal-504-midrank, combined via a bounded convex formula. No gating/sign-flip by benchmark return; no absolute momentum term.

### 4.7 Stability (C9, E7)
Four domains (`implied_vol_stability`, `vol_curve_stability`, `realized_vol_stability`, `price_stability`), each a monotone transform of its raw input, combined convexly. Consumes the shared canonical `price_damage` from 4.2 (never a private copy — a conformance check, §7). VIX3M challenger-only. Polarity conformance test: a VIX *decline* must never *lower* Stability (explicitly named as a historical defect to regression-test against, §6.6).

### 4.8 Condition / Vetoes / Caps (C1, C3, C11, C12, E8, E9, E10)
`condition_pre_cap = Σ(weight_i · pillar_i)` (E8, validated nonnegative/sum-to-one at config load). Hard vetoes (E9): memoryless, current-bar-only, force `condition_score = 0` and at least RISK_OFF; missing data never fires/clears a veto (fail-closed, C16). Soft caps (E10): empty by default; if adopted, continuous monotone `[0,1]` upper bound with no memory, min-composed, all binders published on ties. Production-default no-caps case is a conformance requirement (§7): `condition_score == condition_pre_cap` after veto application whenever `soft_cap_config == []`.

### 4.9 Impulse (C14, E14)
Motion in final post-veto/post-cap `condition_score`, before state hysteresis. Fast/slow endpoint changes, one aggregate `impulse_score`; causal, zero-anchored, odd/monotone/bounded transform; sign-consistency with `condition_t - condition_t-h`.

**Corrected per Message[162] item 3**: Impulse is NOT a pure function of the numeric `condition_score` series alone — design §11 explicitly requires "missing/stale endpoints or invalid required interior sessions make the horizon and aggregate unavailable," meaning module 4.9's real input contract is the aligned `condition_score` series **plus** its per-observation freshness/validity metadata (from 4.1's evaluator) and expected-session coverage over the horizon's full interior window, not just the bare numeric values. A horizon is unavailable if EITHER endpoint is missing/stale OR any required interior expected session is invalid — this must be checked explicitly, not inferred from gaps in the numeric series (a numeric gap and an "invalid but present" observation are different failure modes and must both be caught).

The no-feedback invariant (C14: Impulse never feeds Condition, caps, vetoes, counters, or state) is preserved and remains conformance-checked (§7) — but as a **one-way data-flow constraint** (nothing computed by 4.9 may be read by 4.1–4.8/4.10), not as a claim that 4.9's own inputs are limited to bare numeric values. 4.9 legitimately reads freshness/validity/session metadata that flows forward from 4.1, it just never writes anything back upstream.

### 4.10 State Machine (C2, C13, E11, E12, E13)
Three sub-components sharing one exclusive-state output:
- **Ordinary hysteresis** (§8): asymmetric — downgrades faster than upgrades; hard veto bypasses ordinary downgrade delay.
- **CRISIS** (§9, C13): four independent non-nested raw domains (volatility/term-structure stress, credit stress, canonical price damage, participation collapse); 2-of-4 immediate entry; five-consecutive-valid-bar corroborated-clear exit; `uncorroborated_veto`/`crisis_watch` diagnostics for the 0-domain/1-domain hard-veto cases (§9.2); missing/stale is unavailable, never calm or stressed (never silently counted as "0 domains active").
- **TRENDING** (§10): fifth exclusive state; qualification requires bullish `direction_structure` + sufficient TrendQuality + shallow `price_damage` + Risk Appetite/Stability veto floors + persistence rules; `condition_score <= 1.0` always, no leverage bonus.

*Persisted state* (design §4.3, exact required fields): `regime displayed state, pending state, count`; `CRISIS exit count`; `TRENDING active flag and counters`; `confirmed_structure, pending_upgrade, pending_count`; `stale/current status and reason codes`. This is a versioned, serializable `EngineState` record — the `ENGINE_STATE_V5_1` manifest contract already anticipates this.

### 4.11 Confidence (C15, E15)
Four diagnostics only, no aggregate: `pillar_agreement` (disagreement can't improve it), `data_completeness` (restoring data can't reduce it; required failure makes Condition unavailable instead of degrading completeness), `decision_margin` (never drives transitions), `temporal_stability`.

### 4.12 Output Assembly & Manifest Validation
Assembles the full §13 output schema (core fields §13.1, explainability/state fields §13.2). Every field validated against the manifest's declared type/unit/range/polarity/nullability/status/source-contract/consumers (§13.3) — reusing the same jsonschema-based validation discipline as `verify_freshness_registry.py` and `validate_output_contract.py` (already built for the manifest itself). Unavailable Condition is null/NA with reasons, never zero (a hard conformance check).

### 4.13 Replay Interface (clean vs. injected)
**This is the module the frozen Freshness Threshold Experiment actually needs.** Given (a) a clean/ideal input dataset and (b) the same dataset with a registered freshness injection applied (per `freshness_injection_registry.v1.0.json`'s schema — reused directly, not reinvented), replay both through the full engine (4.1–4.12) and diff every output field. This is what makes §5's three engine-dependent metrics computable: "Affected Condition/regime bars" = fields that differ between clean and injected runs; "Delayed crisis detection" = lag between clean-run CRISIS entry and injected-run CRISIS entry (or non-entry); "Spurious state transitions" = state changes in the injected run absent from the clean run, attributed to the specific injected source per §3's three-way FRED split or the equivalent XNYS/Cboe boundary-state logic.

*Non-goal, explicitly:* this replay interface does NOT decide thresholds, does NOT touch the sealed holdout injections, and does NOT compute portfolio outcomes — it is purely a deterministic dual-run diff tool, reusable by the freshness experiment's eventual Stage-1 runner but built and testable independently of it (per Message[158] item 1: "It is fine to build and test tooling with synthetic fixtures, but do not apply it to the frozen development injections").

## 5. Freshness/as-of evaluation — the exact bridge to the frozen experiment

The Freshness Threshold Experiment's `N` (missed expected sessions/business days per family) is not a new concept this plan invents — it is design §17.19's already-named EMPIRICAL item ("Per-source freshness/as-of tolerances"), and the CURRENT/STALE/MISSING/MISALIGNED state vocabulary with its exact reason-code mapping is already CLOSED in `Freshness_Threshold_Experiment_v1.0.md` §2. Module 4.1's freshness evaluator MUST:

1. Accept `N` as an injectable per-family parameter (not read it from any config baked into this plan — the frozen experiment supplies candidate values from its own grid, §1 of that spec).
2. Reuse the exact state/reason-code vocabulary and boundary arithmetic already specified in `Freshness_Threshold_Experiment_v1.0.md` §2, not a reinvented one — this is the single most important cross-artifact consistency requirement in this plan, since a divergent definition here would silently invalidate the frozen experiment's own preregistration.
3. Reuse the pinned `expected_session_calendar.v1.0.json` artifact for session-count arithmetic — never recompute a calendar inline.

## 6. Golden vectors (design §14.1) — mapped to modules

Every listed requirement below is mandatory before its owning module's slice can be marked complete (§8). This is a checklist, not exhaustive prose — each row becomes one or more concrete test cases.

| Golden-vector requirement (§14.1) | Owning module |
|---|---|
| Normalization ties, exact warm-up, missing sessions, stale data | 4.1, 4.2 |
| Every Direction structure and boundary | 4.3 |
| Direction cold start in every raw structure, especially first valid non-STRONG_BULL after insufficient history | 4.3 |
| Immediate downgrades, candidate upgrades, oscillation, target changes, nonadjacent jumps, restart parity | 4.3 |
| TrendQuality component polarity and de-duplication | 4.4 |
| Breadth source tiers and no-splice behavior | 4.5 |
| Risk Appetite relative rotation in rising and falling markets | 4.6 |
| Independent Stability perturbations, including that a VIX fall never lowers Stability | 4.7 |
| Hard vetoes, optional caps, ties, no-cap baseline | 4.8 |
| Every CRISIS domain alone and pair, missing-domain cases, recovery, relapse | 4.10 |
| TRENDING entry, persistence, veto, exit | 4.10 |
| Impulse zero, equal/opposite paths, monotone paths, veto/cap changes, saturation, gaps, sign consistency | 4.9 |
| Confidence monotonicity | 4.11 |
| Measurement/policy boundary invariants | 4.12, §7.4 below |

## 7. Conformance suite (acceptance gates before any slice is "done")

Distinct from golden vectors (which test correctness of one module's logic); these are cross-cutting structural gates every slice must pass:

1. **Manifest conformance**: every field this module emits exists in the manifest with matching type/unit/range/polarity/nullability/status; every field `market_regime_v5.1_field_ownership.v1.0.json` assigns to this module is actually emitted, and this module emits no field assigned to a different owner (checked mechanically via `verify_field_ownership.py` — added per Message[164] item 1, replacing the earlier informal "the manifest declares this module MUST emit" language, which had no machine-checkable ownership source).
2. **Consumer-graph conformance**: every consumer edge this module's inputs declare in `market_regime_consumer_graph.v5.1.json` is a real code reference; no undeclared consumer edge exists in code.
3. **Fail-closed conformance**: for every required input, a synthetic missing/stale/misaligned/under-warmed fixture produces `unavailable` (null/NA + reason codes), never a neutral-filled or zeroed value.
4. **Layer-boundary conformance** (C19, §14.4): the engine runs with zero strategy/portfolio configuration present; a routing-config diff (feeding two different hypothetical downstream policy configs, neither of which this engine reads) leaves every measurement output byte-identical; no OUT_OF_SCOPE (§3) field appears anywhere in output.
5. **Path-dependence conformance** (§1.3): identical valid inputs replayed twice produce byte-identical pillars/Condition; state-machine replay from history matches restored versioned state exactly.
6. **No-cap baseline conformance** (E10): with `soft_cap_config == []`, `condition_score == condition_pre_cap` after veto, for every fixture.
7. **EMPIRICAL-not-hardcoded conformance**: grep-based check that no EMPIRICAL constant (§2's table) appears as a bare literal inside module logic — every one must be sourced from an injected config object, mirroring the discipline already used for `REQUIRED_LENGTHS`/`FAMILY_CONTRACT_IDS`-style constants in `verify_freshness_registry.py`, but for *config*, not code-level enums (the CLOSED enums themselves, e.g. the five state names, are legitimately hardcoded — only EMPIRICAL numeric/formula choices are gated).

## 8. Implementation slices (build order = review order)

Per the discussion's established "first turn holder builds, other reviews" rule, each slice below is proposed as one independently reviewable unit — built, self-tested, then handed to the other party for independent review before the next slice starts, mirroring the discipline already used throughout the freshness-registry verification work (build → self-test → independent retest → fix → repeat).

1. **Slice 1 — Contracts & Primitives** (§4.1): manifest loader, freshness/as-of evaluator (with the exact frozen vocabulary reuse from §5), causal midrank primitive, expected-session calendar reader. Deliverable: a standalone, fully unit-tested module with zero pillar logic.
2. **Slice 2 — Canonical Raw Features** (§4.2): one canonical computation per manifest `role: raw` field (8 total) plus their derived-raw intermediates per §4.2's table; declared-consumer-edge conformance check (§7.2) as this slice's primary acceptance gate, not full 86-field coverage.
3. **Slice 3 — Direction & TrendQuality** (§4.3–§4.4): the two modules with no cross-pillar dependency between them; buildable and reviewable together or separately.
4. **Slice 4 — Breadth**: (§4.5), depends only on Slice 2.
5. **Slice 5 — Risk Appetite**: (§4.6), depends only on Slice 2.
6. **Slice 6 — Stability**: (§4.7), depends on Slice 2's shared `price_damage`.
7. **Slice 7 — Condition / Vetoes / Caps**: (§4.8), depends on Slices 3–6 (all four pillars must exist).
8. **Slice 8 — Ordinary + CRISIS + TRENDING state machines**: (§4.10), depends on Slice 7; largest single slice given C13's four independent domains and C2/C10's exclusivity requirements — may be further split into ordinary-hysteresis / CRISIS / TRENDING sub-slices if review load warrants, decided at that time.
9. **Slice 9 — Impulse & Confidence**: (§4.9, §4.11), depend on Slice 7 (Impulse) and Slice 8 (Confidence, which reads state).
10. **Slice 10 — Output Assembly & Manifest Validation**: (§4.12), integrates all prior slices; full §13 schema conformance is this slice's acceptance gate, checked against `market_regime_v5.1_field_ownership.v1.0.json` for complete 86-field coverage (every field assigned an owner in §0's ownership map is actually present in the assembled output, with no owner emitting a field it wasn't assigned).
11. **Slice 11 — Replay Interface**: (§4.13), depends on Slice 10 being complete; this is the slice the frozen Freshness Experiment's eventual Stage-1 runner will call.
12. **Slice 12 — Full conformance suite + golden vectors**: (§6, §7), run end-to-end across all prior slices as the final acceptance gate before this plan is considered complete.

Per Message[160]/[158]: **no development injection from the frozen experiment is evaluated at any point in Slices 1–12.** Synthetic fixtures only. The freshness experiment's own specification revision/refreeze (Message[158] item 3 — defining each §5 metric mathematically: denominator, units, aggregation, baseline, attribution, crisis-lag start/end, transition matching, recovery criterion, and resolving "turnover") is a separate, subsequent piece of work, gated on this plan's Slice 12 passing, not concurrent with it.

## 9. What this plan does NOT authorize

Per Message[160]'s explicit boundary and design §1.2/§18:
- Portfolio policy, sizing, or routing of any kind.
- Threshold calibration or candidate selection for the freshness experiment.
- Any access to the freshness experiment's sealed holdout injections.
- Running Stage 1 of the freshness experiment (even partially) — that remains blocked until (a) this plan's Slice 12 passes independent review, AND (b) the freshness experiment's own §5 metrics are revised and refrozen per Message[158] item 3.
- Silent adoption of any EMPIRICAL value as if it were CLOSED — every EMPIRICAL parameter must remain visibly, individually overridable per §2's table.

## 10. Version history

- **v1.0 (2026-08-26):** Initial plan, authored by CLAUDE per Message[160]'s specification and the "first turn holder builds" rule, in response to Messages 157–160's identification of the missing v5.1 reference engine as a blocker for the frozen Freshness Threshold Experiment's Stage 1. Not yet independently reviewed by CHATGPT.
- **v1.0 corrections, round 1 (2026-08-26, following Message[162]'s review):** four material corrections, all independently verified before fixing (role-count query against the pinned manifest confirmed 8 raw/34 core/31 explainability/13 state = 86; direct read of design §2's topology diagram confirmed four peer pillars, not a chain through Stability; direct read of design §11 confirmed the missing/stale/invalid-interior-session requirement; direct grep confirmed the calendar artifact's hash was absent from §0). (1) Redrew §4's topology diagram: TrendQuality now feeds Direction internally (not a peer pillar — it has no separate entry in E8's `pillar_weights`), and all four pillars (Direction, Breadth, Risk Appetite, Stability) converge independently on `condition_pre_cap`; Stability now shown depending only on 4.2's canonical features, never on the other three pillars. Sharpened C1 to distinguish `direction_sign` (orthogonal, excluded from the pillar sum) from `direction_score` (the Direction pillar's own contribution, which does feed the sum). (2) Rewrote §4.2 and Slice 2 to scope "Canonical Raw Features" to the manifest's 8 `role: raw` fields plus their derived-raw intermediates (with an explicit per-raw-field table), not "one function per manifest field" — the remaining 78 core/explainability/state fields belong to their true owning modules (§4.3–§4.12), each validated by that module's own manifest-conformance gate (§7.1), not by Slice 2's consumer-graph gate. (3) Corrected §4.9's Impulse description: it is not a pure function of the bare numeric `condition_score` series — design §11 requires missing/stale-endpoint AND invalid-required-interior-session unavailability, so 4.9's real input is the aligned Condition series plus freshness/validity/session metadata from 4.1; the no-feedback invariant (C14) is now stated as a one-way data-flow constraint, not an input-purity claim. (4) Added the `expected_session_calendar.v1.0.json` artifact's hash to §0 (previously omitted despite module 4.1 depending on it), plus an explicit identity-inheritance rule requiring every slice to re-verify source-snapshot hashes against the live manifest at run time, not trust this plan's own authoring-time pins as permanently valid. Plan hash recomputed after these edits; status remains DRAFT pending independent re-review.
- **v1.0 corrections, round 2 (2026-08-26, following Message[164]'s review):** two remaining contradictions, both confirmed directly before fixing (grep of the round-1 diagram confirmed the `◄──┘` bypass arrow into `condition_pre_cap` was still present; grep of §7.1 confirmed "the manifest declares this module MUST emit" had no machine-checkable ownership source, since the manifest itself has no owner-module property). (1) Built `research/regime/schema/market_regime_v5.1_field_ownership.v1.0.json` — a versioned JSON artifact assigning all 86 manifest fields to exactly one owner from the closed 4.1–4.12 module vocabulary, with declared role-compatibility constraints (raw→4.2 only; state→4.3/4.10 only; core/explainability→any module but 4.1). Built `research/regime/tools/verify_field_ownership.py` as a standalone checker (independent of the script that generated the artifact) proving: manifest field IDs exactly equal ownership map keys (no missing, no extra), all 86 assignments unique, every owner in the closed vocabulary, every assignment role-compatible. Ran it: `PASS — manifest IDs == ownership keys, 86 unique field assignments, all owners in closed 4.1-4.12 vocabulary, all role-compatible`. Also ran three negative-mutation checks (a field with no owner; an owner outside the closed vocabulary; a role-incompatible owner) and confirmed the verifier rejects all three. Pinned both artifacts' hashes in §0; §7.1's manifest-conformance gate and Slice 10 now reference the ownership map as authoritative instead of an informal claim. (2) Removed the diagram's bypass arrow entirely — `condition_pre_cap` now shows exactly four inputs (the four pillar contributions) with no other module touching that node; `price_damage`'s sharing with 4.10's CRISIS domain is now drawn as a normal 4.7→4.10 downstream read. Plan hash recomputed after these edits; status remains DRAFT pending independent re-review.
