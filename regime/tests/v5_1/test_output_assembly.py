"""Market Regime v5.1 — Output Assembly & Manifest Validation (module 4.12) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Scope note (per explicit human direction via AskUserQuestion): assembly +
validation only, no end-to-end orchestrator, no invented EMPIRICAL config
values. Tests build synthetic Result objects directly (as if some future
caller already ran each module) rather than running the full engine.

Run with: python3 -m pytest regime/tests/v5_1/test_output_assembly.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.direction import DirectionStructure, DirectionResult  # noqa: E402
from v5_1.trend_quality import TrendQualityResult  # noqa: E402
from v5_1.breadth import BreadthResult  # noqa: E402
from v5_1.risk_appetite import RiskAppetiteResult  # noqa: E402
from v5_1.stability import StabilityResult  # noqa: E402
from v5_1.condition import ConditionResult  # noqa: E402
from v5_1.impulse import ImpulseResult  # noqa: E402
from v5_1.confidence import ConfidenceResult  # noqa: E402
from v5_1.state_machine import StateResult, OrdinaryState  # noqa: E402
from v5_1.output_assembly import assemble_output, validate_output  # noqa: E402


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


def _full_direction_result():
    return DirectionResult(
        confirmed_structure=DirectionStructure.BULL,
        raw_structure=DirectionStructure.STRONG_BULL,
        direction_sign=1,
        pending_state=DirectionStructure.STRONG_BULL,
        pending_count=1,
        direction_score=0.8,
    )


def _full_trend_quality_result():
    return TrendQualityResult(as_of="2020-04-15", linearity_raw=0.9, linearity_pct=0.7, path_efficiency_raw=0.6, path_efficiency_pct=0.5, trend_quality=0.6)


def _full_breadth_result():
    return BreadthResult(as_of="2020-04-15", source_tier="tier_2_fixed_nine_production", eligible_count=9, total_members=9, pct_above_sma50=0.6, pct_above_sma200=0.7, breadth_score=0.65)


def _full_risk_appetite_result():
    return RiskAppetiteResult(
        as_of="2020-04-15", credit_level_pct=0.5, credit_change_score=0.4,
        growth_rotation_raw=1.2, growth_rotation_pct=0.8, small_cap_rotation_raw=0.9, small_cap_rotation_pct=0.3,
        risk_appetite_score=0.55,
    )


def _full_stability_result():
    return StabilityResult(
        as_of="2020-04-15", implied_vol_stability=0.7, vol_curve_raw=0.95, vol_curve_stability=0.8,
        realized_volatility=0.2, realized_vol_stability=0.6, price_damage=0.1, price_stability=0.9,
        stability_score=0.75,
    )


def _full_condition_result():
    return ConditionResult(
        as_of="2020-04-15", direction_contribution=0.2, breadth_contribution=0.16,
        risk_appetite_contribution=0.11, stability_contribution=0.15,
        condition_pre_cap=0.62, condition_score=0.62, condition_pct=62.0,
        active_veto_ids=(), active_cap_ids=(), binding_cap_ids=(), veto_cap_details={},
    )


def _full_impulse_result():
    return ImpulseResult(as_of="2020-04-15", impulse_fast=0.1, impulse_slow=-0.05, impulse_score=0.04)


def _full_confidence_result():
    return ConfidenceResult(as_of="2020-04-15", pillar_agreement=0.8, data_completeness=0.9, decision_margin=0.3, temporal_stability=0.6)


def _full_state_result():
    return StateResult(
        as_of="2020-04-15", state="NEUTRAL", pending_state=None, pending_state_count=None,
        state_is_current=True, crisis_active=False, trending_active=False, ordinary_state=OrdinaryState.NEUTRAL,
    )


def _full_record_kwargs():
    return dict(
        direction=_full_direction_result(), trend_quality=_full_trend_quality_result(),
        breadth=_full_breadth_result(), risk_appetite=_full_risk_appetite_result(),
        stability=_full_stability_result(), condition=_full_condition_result(),
        impulse=_full_impulse_result(), confidence=_full_confidence_result(), state=_full_state_result(),
        raw_features={
            "benchmark_total_return_close": 300.0, "oas_level": 4.0, "qqq_total_return_close": 400.0,
            "iwm_total_return_close": 200.0, "vix_level": 15.0, "vix9d_level": 14.0, "vix3m_level": 16.0,
            "breadth_member_observations": [1.0, 2.0, 3.0],
        },
        unavailable_reason_codes=[], field_quality={}, source_tier="tier_2_fixed_nine_production",
        coverage_ratio=1.0, freshness_age_sessions=0, warmup_complete=True,
        reason_codes=[], crisis_domain_status={}, crisis_valid_domain_count=4, crisis_active_domain_count=0,
        crisis_watch=False, uncorroborated_veto=False, crisis_exit_count=0,
        trending_entry_count=0, trending_exit_count=0,
        oas_change=0.1, risk_appetite_contributions={}, stability_contributions={},
        benchmark_drawdown=0.05, benchmark_return_shock=0.02, pre_cap_and_pillar_impulses={},
        binding_event_changes=[],
    )


# ---------------------------------------------------------------------------
# Full-availability assembly + real manifest validation
# ---------------------------------------------------------------------------

class TestFullAvailabilityAssembly:
    def test_assembled_record_validates_cleanly_against_real_manifest(self, manifest):
        record = assemble_output(
            "2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"],
            "OK", **_full_record_kwargs(),
        )
        errors = validate_output(manifest, record)
        assert errors == [], f"unexpected validation errors: {errors}"

    def test_every_manifest_field_is_a_key_in_the_assembled_record(self, manifest):
        """Full 86-field coverage: every field the manifest declares MUST
        appear as a key in the assembled record (even if its value is
        None for a known gap) — a silently OMITTED key is a different,
        worse failure mode than an explicit null, and this is the
        conformance gate the plan names for this slice."""
        record = assemble_output(
            "2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"],
            "OK", **_full_record_kwargs(),
        )
        manifest_field_ids = {row["field_id"] for row in manifest.raw["fields"]}
        record_keys = set(record.keys())
        missing = manifest_field_ids - record_keys
        assert missing == set(), f"manifest fields missing from assembled record: {sorted(missing)}"

    def test_no_undeclared_keys_in_assembled_record(self, manifest):
        record = assemble_output(
            "2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"],
            "OK", **_full_record_kwargs(),
        )
        manifest_field_ids = {row["field_id"] for row in manifest.raw["fields"]}
        record_keys = set(record.keys())
        undeclared = record_keys - manifest_field_ids
        assert undeclared == set(), f"assembled record has undeclared keys: {sorted(undeclared)}"

    def test_direction_structure_fields_map_to_string_names_not_enum_objects(self):
        record = assemble_output(
            "2020-04-15", "5.1", "5.1", "OK", direction=_full_direction_result(),
        )
        assert record["direction_structure"] == "BULL"
        assert record["direction_structure_raw"] == "STRONG_BULL"
        assert record["direction_pending_state"] == "STRONG_BULL"
        assert isinstance(record["direction_structure"], str)


# ---------------------------------------------------------------------------
# All-unavailable assembly — every Result is None
# ---------------------------------------------------------------------------

class TestAllUnavailableAssembly:
    def test_all_none_modules_produces_a_schema_valid_all_null_record(self, manifest):
        record = assemble_output("2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"], "DEGRADED")
        errors = validate_output(manifest, record)
        assert errors == [], f"unexpected validation errors on the fully-unavailable record: {errors}"

    def test_state_is_current_is_false_not_none_when_state_is_none(self):
        """state_is_current is CLOSED non-nullable (manifest: 'Never null
        in an emitted record') — even with no StateResult at all, this
        field must still be a real boolean, not None."""
        record = assemble_output("2020-04-15", "5.1", "5.1", "DEGRADED")
        assert record["state_is_current"] is False

    def test_condition_score_and_state_are_none_when_their_results_are_none(self):
        record = assemble_output("2020-04-15", "5.1", "5.1", "DEGRADED")
        assert record["condition_score"] is None
        assert record["state"] is None


# ---------------------------------------------------------------------------
# Partial availability — some modules present, others None
# ---------------------------------------------------------------------------

class TestPartialAvailability:
    def test_condition_none_does_not_force_direction_fields_to_none(self):
        """This assembler's own documented boundary: a None Condition does
        NOT special-case Direction's own already-computed fields — that
        cross-module availability decision belongs to each module itself,
        not to this assembler."""
        record = assemble_output("2020-04-15", "5.1", "5.1", "DEGRADED", direction=_full_direction_result(), condition=None)
        assert record["direction_score"] == 0.8
        assert record["condition_score"] is None

    def test_state_none_does_not_force_condition_fields_to_none(self):
        record = assemble_output("2020-04-15", "5.1", "5.1", "DEGRADED", condition=_full_condition_result(), state=None)
        assert record["condition_score"] == pytest.approx(0.62)
        assert record["state"] is None


# ---------------------------------------------------------------------------
# validate_output correctly REJECTS a genuinely malformed record — proves
# the validation path is live, not a no-op that always passes.
# ---------------------------------------------------------------------------

class TestValidationActuallyCatchesErrors:
    def test_out_of_range_condition_score_is_rejected(self, manifest):
        record = assemble_output(
            "2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"],
            "OK", **_full_record_kwargs(),
        )
        record["condition_score"] = 1.5  # violates [0,1]
        errors = validate_output(manifest, record)
        assert any("condition_score" in e for e in errors)

    def test_wrong_type_is_rejected(self, manifest):
        record = assemble_output(
            "2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"],
            "OK", **_full_record_kwargs(),
        )
        record["direction_sign"] = "not_an_integer"
        errors = validate_output(manifest, record)
        assert any("direction_sign" in e for e in errors)

    def test_null_on_a_non_nullable_field_is_rejected(self, manifest):
        record = assemble_output(
            "2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"],
            "OK", **_full_record_kwargs(),
        )
        record["schema_version"] = None  # schema_version is non-nullable
        errors = validate_output(manifest, record)
        assert any("schema_version" in e for e in errors)


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_assembly_is_repeatable(self, manifest):
        r1 = assemble_output("2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"], "OK", **_full_record_kwargs())
        r2 = assemble_output("2020-04-15", manifest.raw["schema_version"], manifest.raw["feature_contract_version"], "OK", **_full_record_kwargs())
        assert r1 == r2
