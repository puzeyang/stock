"""Market Regime v5.1 — Slice 10: Output Assembly & Manifest Validation
(module 4.12).

**Scope, per explicit human direction (AskUserQuestion, this slice)**:
assembly + validation ONLY. Every EMPIRICAL configuration value across all
11 prior modules (pillar weights, veto thresholds, TrendQuality floors,
Impulse scale estimator/transform, Confidence formulas, etc.) remains
entirely undecided anywhere in this project — this module does not invent
placeholder values for any of them, and it is NOT an end-to-end "run the
whole engine for one as_of" orchestrator. It takes each module's
ALREADY-COMPUTED `Result` object (or `None`, meaning that module was
unavailable this bar) — as if some future calibration/orchestration layer
already ran them — and assembles + validates the combined 86-field record
against the manifest. This mirrors the plan's own framing of Slice 10 as
"integrates all prior slices; full §13 schema conformance is this slice's
acceptance gate."

Reuses `regime/tools/validate_output_contract.py`'s existing
`validate_record()` function directly (per the plan's own instruction:
"reusing the same jsonschema-based validation discipline... already built
for the manifest itself") — this module does not reimplement type/range/
nullability checking.

**Known real gaps, found and flagged during this slice rather than
silently worked around** (all EMPIRICAL-status fields with no engine
output producing them yet, because the modules that would produce them
have EMPIRICAL-internal formulas that were never required to expose this
particular intermediate — see this module's own `assemble_output`
docstring for the authoritative, current list):

- `oas_change` (4.6): `RiskAppetiteResult`/`CreditTransform` never surface
  the raw OAS change alongside `credit_level_pct`/`credit_change_score` —
  `CreditTransform`'s Protocol only returns the two percentile/score
  outputs, not the raw input change itself.
- `risk_appetite_contributions` (4.6) / `stability_contributions` (4.7):
  each pillar's OWN internal per-component weighted breakdown (distinct
  from `condition.py`'s cross-pillar `direction_contribution`/
  `breadth_contribution` scalars) was never assembled into a map by
  either module.
- `benchmark_drawdown` / `benchmark_return_shock` (4.7): raw inputs to the
  canonical `price_damage` computation — `PriceDamageEstimator` is an
  opaque injected callable per Slice 6's EMPIRICAL-interface pattern, so
  its internal drawdown/shock components were never required to be
  surfaced separately.
- `pre_cap_and_pillar_impulses` (4.9): Impulse's own attribution
  breakdown (§11: "Publish pre-cap changes, pillar impulses... for
  attribution") was never built — `impulse.py` only computes headline
  Condition Impulse (`impulse_fast`/`impulse_slow`/`impulse_score`), not
  a parallel per-pillar/pre-cap impulse computation.
- `binding_event_changes` (4.9, CLOSED): a cross-bar DIFF of binding
  veto/cap identifiers between consecutive bars — no module threads
  prior-bar state into this computation yet (Condition's own
  `active_veto_ids`/`active_cap_ids`/`binding_cap_ids` are single-bar
  outputs; nothing currently diffs bar t against bar t-1).
- module 4.1's own six diagnostic fields (`unavailable_reason_codes`,
  `field_quality`, `source_tier`, `coverage_ratio`,
  `freshness_age_sessions`, `warmup_complete`): Slice 1 built the
  freshness EVALUATOR (`evaluate_freshness()`), not an aggregator that
  rolls per-field freshness/coverage up into these six output-record
  fields — this assembler accepts them as caller-supplied inputs (same as
  every other unproduced field) rather than computing them itself.

For every one of these, `assemble_output` accepts an explicit optional
parameter (default `None`) rather than silently omitting the field —
`None` is a legitimate value for every nullable EMPIRICAL field per §13.3
("Unavailable Condition is null/NA with reasons, never numeric zero," a
principle this module extends to every nullable field it cannot itself
compute), so a caller who has not yet built the missing computation gets a
schema-valid (if diagnostically incomplete) record, not a silently-missing
key or an invented value.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# validate_output_contract.py lives in tools/, not src/v5_1/ — imported by
# path since tools/ is a standalone script directory, not a package this
# module would otherwise import via a relative import.
_TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from validate_output_contract import validate_record  # noqa: E402

from .condition import ConditionResult
from .confidence import ConfidenceResult
from .contracts import Manifest
from .direction import DirectionResult
from .breadth import BreadthResult
from .risk_appetite import RiskAppetiteResult
from .stability import StabilityResult
from .trend_quality import TrendQualityResult
from .impulse import ImpulseResult
from .state_machine import StateResult


def _structure_name(structure) -> str | None:
    return structure.name if structure is not None else None


def assemble_output(
    as_of: str,
    schema_version: str,
    feature_contract_version: str,
    engine_status: str,
    *,
    direction: DirectionResult | None = None,
    trend_quality: TrendQualityResult | None = None,
    breadth: BreadthResult | None = None,
    risk_appetite: RiskAppetiteResult | None = None,
    stability: StabilityResult | None = None,
    condition: ConditionResult | None = None,
    impulse: ImpulseResult | None = None,
    confidence: ConfidenceResult | None = None,
    state: StateResult | None = None,
    # Raw features (module 4.1's shared collection, module 4.2's canonical
    # raw values) — caller-supplied, since this is an ASSEMBLY module, not
    # a raw-feature loader (that's Slice 2's own job).
    raw_features: dict[str, Any] | None = None,
    # Module 4.1's six per-field diagnostic outputs (see module docstring
    # — Slice 1 built the evaluator, not an aggregator producing these).
    unavailable_reason_codes: list | None = None,
    field_quality: dict | None = None,
    source_tier: str | None = None,
    coverage_ratio: float | None = None,
    freshness_age_sessions: int | None = None,
    warmup_complete: bool | None = None,
    # State-machine explainability fields not carried on StateResult itself.
    reason_codes: list | None = None,
    crisis_domain_status: dict | None = None,
    crisis_valid_domain_count: int | None = None,
    crisis_active_domain_count: int | None = None,
    crisis_watch: bool | None = None,
    uncorroborated_veto: bool | None = None,
    crisis_exit_count: int | None = None,
    trending_entry_count: int | None = None,
    trending_exit_count: int | None = None,
    # The known-gap fields (see module docstring) — explicit, not omitted.
    oas_change: float | None = None,
    risk_appetite_contributions: dict | None = None,
    stability_contributions: dict | None = None,
    benchmark_drawdown: float | None = None,
    benchmark_return_shock: float | None = None,
    pre_cap_and_pillar_impulses: dict | None = None,
    binding_event_changes: list | None = None,
) -> dict[str, Any]:
    """Assemble one as_of date's full 86-field output record from each
    module's already-computed Result object (or None). Performs NO
    computation of its own beyond field-name mapping/renaming/unwrapping —
    every value either comes directly from a Result object's own field, a
    caller-supplied raw/diagnostic input, or is `None` (nullable, per
    §13.3, whenever the source Result itself is None or the field is a
    known gap per this module's own docstring).

    A `None`-valued module Result (e.g. `condition=None`) does NOT special-
    case that module's dependents — this function does not, for example,
    force `state=None` just because `condition=None`; that CROSS-MODULE
    availability propagation is each module's OWN job (e.g. `crisis.py`'s
    `ConditionForExit.condition_score` already accepts `None`, and
    `state_machine.py`'s `advance_state` already handles that fail-closed
    at the point of computation) — by the time a `Result` object reaches
    this assembler, its own module has already made its own fail-closed
    decision. This function's only job is field mapping into the flat
    output shape, never a second layer of availability logic.
    """
    record: dict[str, Any] = {
        "schema_version": schema_version,
        "feature_contract_version": feature_contract_version,
        "as_of": as_of,
        "engine_status": engine_status,
    }

    if raw_features:
        record.update(raw_features)

    record.update({
        "unavailable_reason_codes": unavailable_reason_codes,
        "field_quality": field_quality,
        "source_tier": source_tier,
        "coverage_ratio": coverage_ratio,
        "freshness_age_sessions": freshness_age_sessions,
        "warmup_complete": warmup_complete,
    })

    if direction is not None:
        record.update({
            "direction_structure_raw": _structure_name(direction.raw_structure),
            "direction_structure": _structure_name(direction.confirmed_structure),
            "direction_sign": direction.direction_sign,
            "direction_pending_state": _structure_name(direction.pending_state),
            "direction_pending_count": direction.pending_count,
            "direction_score": direction.direction_score,
        })
    else:
        record.update({
            "direction_structure_raw": None, "direction_structure": None, "direction_sign": None,
            "direction_pending_state": None, "direction_pending_count": None, "direction_score": None,
        })

    if trend_quality is not None:
        record.update({
            "linearity_raw": trend_quality.linearity_raw,
            "linearity_pct": trend_quality.linearity_pct,
            "path_efficiency_raw": trend_quality.path_efficiency_raw,
            "path_efficiency_pct": trend_quality.path_efficiency_pct,
            "trend_quality": trend_quality.trend_quality,
        })
    else:
        record.update({
            "linearity_raw": None, "linearity_pct": None, "path_efficiency_raw": None,
            "path_efficiency_pct": None, "trend_quality": None,
        })

    if breadth is not None:
        record.update({
            "pct_above_sma50": breadth.pct_above_sma50,
            "pct_above_sma200": breadth.pct_above_sma200,
            "breadth_eligible_count": breadth.eligible_count,
            "breadth_score": breadth.breadth_score,
        })
    else:
        record.update({
            "pct_above_sma50": None, "pct_above_sma200": None,
            "breadth_eligible_count": None, "breadth_score": None,
        })

    if risk_appetite is not None:
        record.update({
            "oas_change": oas_change,
            "credit_level_pct": risk_appetite.credit_level_pct,
            "credit_change_score": risk_appetite.credit_change_score,
            "growth_rotation_raw": risk_appetite.growth_rotation_raw,
            "growth_rotation_pct": risk_appetite.growth_rotation_pct,
            "small_cap_rotation_raw": risk_appetite.small_cap_rotation_raw,
            "small_cap_rotation_pct": risk_appetite.small_cap_rotation_pct,
            "risk_appetite_contributions": risk_appetite_contributions,
            "risk_appetite_score": risk_appetite.risk_appetite_score,
        })
    else:
        record.update({
            "oas_change": oas_change, "credit_level_pct": None, "credit_change_score": None,
            "growth_rotation_raw": None, "growth_rotation_pct": None, "small_cap_rotation_raw": None,
            "small_cap_rotation_pct": None, "risk_appetite_contributions": None, "risk_appetite_score": None,
        })

    if stability is not None:
        record.update({
            "implied_vol_stability": stability.implied_vol_stability,
            "vol_curve_raw": stability.vol_curve_raw,
            "vol_curve_stability": stability.vol_curve_stability,
            "realized_volatility": stability.realized_volatility,
            "realized_vol_stability": stability.realized_vol_stability,
            "benchmark_drawdown": benchmark_drawdown,
            "benchmark_return_shock": benchmark_return_shock,
            "price_damage": stability.price_damage,
            "price_stability": stability.price_stability,
            "stability_contributions": stability_contributions,
            "stability_score": stability.stability_score,
        })
    else:
        record.update({
            "implied_vol_stability": None, "vol_curve_raw": None, "vol_curve_stability": None,
            "realized_volatility": None, "realized_vol_stability": None,
            "benchmark_drawdown": benchmark_drawdown, "benchmark_return_shock": benchmark_return_shock,
            "price_damage": None, "price_stability": None,
            "stability_contributions": stability_contributions, "stability_score": None,
        })

    if condition is not None:
        record.update({
            "pillar_weights": None,  # the injected PillarWeights config itself, not a Result field
            "condition_pre_cap": condition.condition_pre_cap,
            "condition_score": condition.condition_score,
            "condition_pct": condition.condition_pct,
            "active_veto_ids": list(condition.active_veto_ids),
            "active_cap_ids": list(condition.active_cap_ids),
            "binding_cap_ids": list(condition.binding_cap_ids),
            "veto_cap_details": condition.veto_cap_details,
            "direction_contribution": condition.direction_contribution,
            "breadth_contribution": condition.breadth_contribution,
        })
    else:
        record.update({
            "pillar_weights": None, "condition_pre_cap": None, "condition_score": None, "condition_pct": None,
            "active_veto_ids": None, "active_cap_ids": None, "binding_cap_ids": None, "veto_cap_details": None,
            "direction_contribution": None, "breadth_contribution": None,
        })

    if impulse is not None:
        record.update({
            "impulse_fast": impulse.impulse_fast,
            "impulse_slow": impulse.impulse_slow,
            "impulse_score": impulse.impulse_score,
            "pre_cap_and_pillar_impulses": pre_cap_and_pillar_impulses,
            "binding_event_changes": binding_event_changes,
        })
    else:
        record.update({
            "impulse_fast": None, "impulse_slow": None, "impulse_score": None,
            "pre_cap_and_pillar_impulses": pre_cap_and_pillar_impulses,
            "binding_event_changes": binding_event_changes,
        })

    if confidence is not None:
        record.update({
            "pillar_agreement": confidence.pillar_agreement,
            "data_completeness": confidence.data_completeness,
            "decision_margin": confidence.decision_margin,
            "temporal_stability": confidence.temporal_stability,
        })
    else:
        record.update({
            "pillar_agreement": None, "data_completeness": None,
            "decision_margin": None, "temporal_stability": None,
        })

    if state is not None:
        record.update({
            "state_is_current": state.state_is_current,
            "state": state.state,
            "pending_state": state.pending_state,
            "pending_state_count": state.pending_state_count,
            "reason_codes": reason_codes,
            "crisis_domain_status": crisis_domain_status,
            "crisis_valid_domain_count": crisis_valid_domain_count,
            "crisis_active_domain_count": crisis_active_domain_count,
            "crisis_watch": crisis_watch,
            "uncorroborated_veto": uncorroborated_veto,
            "crisis_exit_count": crisis_exit_count,
            "trending_active": state.trending_active,
            "trending_entry_count": trending_entry_count,
            "trending_exit_count": trending_exit_count,
        })
    else:
        # state_is_current is CLOSED non-nullable (§4.3/manifest: "Never
        # null in an emitted record") — even with no StateResult at all,
        # this field must still be populated, and False is the only
        # honest value when there is no current state resolution.
        record.update({
            "state_is_current": False,
            "state": None, "pending_state": None, "pending_state_count": None,
            "reason_codes": reason_codes, "crisis_domain_status": crisis_domain_status,
            "crisis_valid_domain_count": crisis_valid_domain_count,
            "crisis_active_domain_count": crisis_active_domain_count,
            "crisis_watch": crisis_watch, "uncorroborated_veto": uncorroborated_veto,
            "crisis_exit_count": crisis_exit_count, "trending_active": None,
            "trending_entry_count": trending_entry_count, "trending_exit_count": trending_exit_count,
        })

    return record


def validate_output(manifest: Manifest, record: dict[str, Any]) -> list[str]:
    """Validate an assembled record against the manifest, reusing
    `validate_output_contract.py`'s own `validate_record()` — the exact
    same jsonschema-based check the standalone tool applies, not a
    reimplementation. `manifest.raw` is the manifest's own already-loaded
    dict form (from `contracts.py`'s `load_manifest()`), matching the
    shape `validate_record()` expects (a dict with a `"fields"` list)."""
    return validate_record(manifest.raw, record)
