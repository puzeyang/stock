"""Market Regime v5.1 — Slice 7 (Condition/Vetoes/Caps) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_slice7.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.condition import (  # noqa: E402
    PillarWeights,
    HardVetoRule,
    SoftCapRule,
    ConditionResult,
    ConditionUnavailableError,
    compute_condition,
)


def _equal_weights():
    return PillarWeights(weight_direction=0.25, weight_breadth=0.25, weight_risk_appetite=0.25, weight_stability=0.25)


# ---------------------------------------------------------------------------
# PillarWeights validation
# ---------------------------------------------------------------------------

class TestPillarWeights:
    def test_valid_weights_construct(self):
        PillarWeights(weight_direction=0.4, weight_breadth=0.2, weight_risk_appetite=0.2, weight_stability=0.2)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="sum to exactly 1.0"):
            PillarWeights(weight_direction=0.5, weight_breadth=0.2, weight_risk_appetite=0.2, weight_stability=0.2)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="nonnegative"):
            PillarWeights(weight_direction=-0.1, weight_breadth=0.4, weight_risk_appetite=0.4, weight_stability=0.3)


# ---------------------------------------------------------------------------
# HardVetoRule
# ---------------------------------------------------------------------------

class TestHardVetoRule:
    def test_invalid_comparator_rejected(self):
        with pytest.raises(ValueError, match="comparator"):
            HardVetoRule(veto_id="x", comparator="==", threshold=30.0)

    def test_gte_fires_at_and_above_threshold(self):
        rule = HardVetoRule(veto_id="vix_spike", comparator=">=", threshold=40.0)
        assert rule.fires(40.0) is True
        assert rule.fires(40.1) is True
        assert rule.fires(39.9) is False

    def test_lte_fires_at_and_below_threshold(self):
        rule = HardVetoRule(veto_id="breadth_collapse", comparator="<=", threshold=0.1)
        assert rule.fires(0.1) is True
        assert rule.fires(0.05) is True
        assert rule.fires(0.11) is False


# ---------------------------------------------------------------------------
# condition_pre_cap — weighted sum
# ---------------------------------------------------------------------------

class TestConditionPreCap:
    def test_weighted_sum_matches_manual_computation(self):
        weights = PillarWeights(weight_direction=0.4, weight_breadth=0.2, weight_risk_appetite=0.2, weight_stability=0.2)
        r = compute_condition(
            "2020-04-15", 0.8, 0.6, 0.5, 0.9, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(), soft_cap_domain_values={},
        )
        expected = 0.4 * 0.8 + 0.2 * 0.6 + 0.2 * 0.5 + 0.2 * 0.9
        assert r.condition_pre_cap == pytest.approx(expected)
        assert r.direction_contribution == pytest.approx(0.4 * 0.8)
        assert r.breadth_contribution == pytest.approx(0.2 * 0.6)
        assert r.risk_appetite_contribution == pytest.approx(0.2 * 0.5)
        assert r.stability_contribution == pytest.approx(0.2 * 0.9)

    def test_any_missing_pillar_raises_unavailable(self):
        weights = _equal_weights()
        for kwargs in [
            dict(direction_score=None, breadth_score=0.5, risk_appetite_score=0.5, stability_score=0.5),
            dict(direction_score=0.5, breadth_score=None, risk_appetite_score=0.5, stability_score=0.5),
            dict(direction_score=0.5, breadth_score=0.5, risk_appetite_score=None, stability_score=0.5),
            dict(direction_score=0.5, breadth_score=0.5, risk_appetite_score=0.5, stability_score=None),
        ]:
            with pytest.raises(ConditionUnavailableError, match="pillar scores are None"):
                compute_condition(
                    "2020-04-15", **kwargs, pillar_weights=weights,
                    hard_veto_rules=(), hard_veto_domain_values={},
                    soft_cap_rules=(), soft_cap_domain_values={},
                )


# ---------------------------------------------------------------------------
# Conformance requirement (plan §7 / design §7.3): no caps ⇒
# condition_score == condition_pre_cap after veto application.
# ---------------------------------------------------------------------------

class TestNoCapsConformance:
    def test_condition_score_equals_pre_cap_when_no_vetoes_fire_and_no_caps_configured(self):
        weights = PillarWeights(weight_direction=0.3, weight_breadth=0.3, weight_risk_appetite=0.2, weight_stability=0.2)
        r = compute_condition(
            "2020-04-15", 0.7, 0.6, 0.4, 0.8, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(), soft_cap_domain_values={},
        )
        assert r.condition_score == r.condition_pre_cap
        assert r.active_veto_ids == ()
        assert r.active_cap_ids == ()
        assert r.binding_cap_ids == ()

    def test_holds_across_a_range_of_real_valued_pillar_combinations(self):
        """Not just one hand-picked case: sweep several pillar-score
        combinations and confirm the identity holds every time with no
        caps configured, regardless of how extreme the pillar values are."""
        weights = PillarWeights(weight_direction=0.25, weight_breadth=0.25, weight_risk_appetite=0.25, weight_stability=0.25)
        combos = [
            (0.0, 0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0, 1.0),
            (0.1, 0.9, 0.3, 0.7),
            (0.5, 0.5, 0.5, 0.5),
            (0.99, 0.01, 0.5, 0.25),
        ]
        for d, b, ra, s in combos:
            r = compute_condition(
                "2020-04-15", d, b, ra, s, weights,
                hard_veto_rules=(), hard_veto_domain_values={},
                soft_cap_rules=(), soft_cap_domain_values={},
            )
            assert r.condition_score == r.condition_pre_cap, f"failed for pillars={d,b,ra,s}"


# ---------------------------------------------------------------------------
# Hard vetoes
# ---------------------------------------------------------------------------

class TestHardVetoes:
    def test_firing_veto_forces_condition_score_to_zero(self):
        weights = _equal_weights()
        veto = HardVetoRule(veto_id="vix_spike", comparator=">=", threshold=40.0)
        r = compute_condition(
            "2020-03-20", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(veto,), hard_veto_domain_values={"vix_spike": 55.0},
            soft_cap_rules=(), soft_cap_domain_values={},
        )
        assert r.condition_score == 0.0
        assert r.active_veto_ids == ("vix_spike",)
        # condition_pre_cap is still published as the pre-veto weighted sum,
        # not itself zeroed — the veto acts on condition_score, not
        # condition_pre_cap, per §7.2's own field distinction.
        assert r.condition_pre_cap == pytest.approx(0.9)

    def test_non_firing_veto_does_not_affect_condition_score(self):
        weights = _equal_weights()
        veto = HardVetoRule(veto_id="vix_spike", comparator=">=", threshold=40.0)
        r = compute_condition(
            "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(veto,), hard_veto_domain_values={"vix_spike": 15.0},
            soft_cap_rules=(), soft_cap_domain_values={},
        )
        assert r.condition_score == r.condition_pre_cap
        assert r.active_veto_ids == ()

    def test_missing_veto_domain_value_raises_unavailable_not_fires_or_clears(self):
        """§7.2: 'missing data never fires or clears a veto; it makes
        Condition unavailable.' A missing domain value must be neither
        silently treated as non-firing NOR as firing — it must make the
        whole computation unavailable."""
        weights = _equal_weights()
        veto = HardVetoRule(veto_id="vix_spike", comparator=">=", threshold=40.0)
        with pytest.raises(ConditionUnavailableError, match="vix_spike"):
            compute_condition(
                "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
                hard_veto_rules=(veto,), hard_veto_domain_values={},
                soft_cap_rules=(), soft_cap_domain_values={},
            )

    def test_multiple_vetoes_all_publish_when_multiple_fire(self):
        weights = _equal_weights()
        veto_a = HardVetoRule(veto_id="vix_spike", comparator=">=", threshold=40.0)
        veto_b = HardVetoRule(veto_id="credit_stress", comparator=">=", threshold=5.0)
        r = compute_condition(
            "2020-03-20", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(veto_a, veto_b),
            hard_veto_domain_values={"vix_spike": 55.0, "credit_stress": 6.0},
            soft_cap_rules=(), soft_cap_domain_values={},
        )
        assert set(r.active_veto_ids) == {"vix_spike", "credit_stress"}
        assert r.condition_score == 0.0

    def test_duplicate_veto_id_rejected(self):
        """A real bug found during self-review: veto_id doubles as a dict
        key in veto_cap_details and as the sole identity published in
        active_veto_ids, so a config with two rules sharing one veto_id
        could silently produce an internally contradictory result (e.g.
        active_veto_ids reports it fired via one rule's evaluation while
        veto_cap_details, keyed by the same id, shows a DIFFERENT rule's
        fired=False, whichever rule was evaluated last). Rejected
        explicitly at the config-validity boundary instead."""
        weights = _equal_weights()
        v1 = HardVetoRule(veto_id="dup", comparator=">=", threshold=10.0)
        v2 = HardVetoRule(veto_id="dup", comparator="<=", threshold=5.0)
        with pytest.raises(ValueError, match="duplicate veto_id"):
            compute_condition(
                "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
                hard_veto_rules=(v1, v2), hard_veto_domain_values={"dup": 20.0},
                soft_cap_rules=(), soft_cap_domain_values={},
            )

    def test_veto_takes_precedence_over_caps_no_caps_evaluated_for_binding(self):
        weights = _equal_weights()
        veto = HardVetoRule(veto_id="vix_spike", comparator=">=", threshold=40.0)
        cap = SoftCapRule(cap_id="participation_cap", transform=lambda v: 0.3)  # would otherwise bind hard
        r = compute_condition(
            "2020-03-20", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(veto,), hard_veto_domain_values={"vix_spike": 55.0},
            soft_cap_rules=(cap,), soft_cap_domain_values={"participation_cap": 0.05},
        )
        assert r.condition_score == 0.0
        assert r.active_cap_ids == ()
        assert r.binding_cap_ids == ()


# ---------------------------------------------------------------------------
# Soft caps
# ---------------------------------------------------------------------------

class TestSoftCaps:
    def test_inactive_cap_mapped_bound_of_one_does_not_affect_score(self):
        weights = _equal_weights()
        cap = SoftCapRule(cap_id="never_binds", transform=lambda v: 1.0)
        r = compute_condition(
            "2020-04-15", 0.8, 0.8, 0.8, 0.8, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap,), soft_cap_domain_values={"never_binds": 10.0},
        )
        assert r.condition_score == r.condition_pre_cap
        assert r.active_cap_ids == ()
        assert r.binding_cap_ids == ()

    def test_binding_cap_lowers_condition_score_via_min(self):
        weights = _equal_weights()
        cap = SoftCapRule(cap_id="tight_cap", transform=lambda v: 0.3)
        r = compute_condition(
            "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap,), soft_cap_domain_values={"tight_cap": 5.0},
        )
        assert r.condition_pre_cap == pytest.approx(0.9)
        assert r.condition_score == pytest.approx(0.3)
        assert r.active_cap_ids == ("tight_cap",)
        assert r.binding_cap_ids == ("tight_cap",)

    def test_min_composition_across_multiple_caps_takes_the_tightest(self):
        weights = _equal_weights()
        cap_a = SoftCapRule(cap_id="cap_a", transform=lambda v: 0.6)
        cap_b = SoftCapRule(cap_id="cap_b", transform=lambda v: 0.4)  # tightest
        cap_c = SoftCapRule(cap_id="cap_c", transform=lambda v: 0.9)
        r = compute_condition(
            "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap_a, cap_b, cap_c),
            soft_cap_domain_values={"cap_a": 1.0, "cap_b": 1.0, "cap_c": 1.0},
        )
        assert r.condition_score == pytest.approx(0.4)
        assert set(r.active_cap_ids) == {"cap_a", "cap_b", "cap_c"}
        assert r.binding_cap_ids == ("cap_b",)

    def test_ties_publish_all_binders(self):
        """§7.3: 'Ties publish all binders.' Two caps mapping to the exact
        same tightest bound must BOTH appear in binding_cap_ids, not just
        the first one encountered."""
        weights = _equal_weights()
        cap_a = SoftCapRule(cap_id="cap_a", transform=lambda v: 0.5)
        cap_b = SoftCapRule(cap_id="cap_b", transform=lambda v: 0.5)  # exact tie with cap_a
        cap_c = SoftCapRule(cap_id="cap_c", transform=lambda v: 0.8)
        r = compute_condition(
            "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap_a, cap_b, cap_c),
            soft_cap_domain_values={"cap_a": 1.0, "cap_b": 1.0, "cap_c": 1.0},
        )
        assert r.condition_score == pytest.approx(0.5)
        assert set(r.binding_cap_ids) == {"cap_a", "cap_b"}

    def test_missing_cap_domain_value_excludes_that_cap_without_affecting_others(self):
        weights = _equal_weights()
        cap_present = SoftCapRule(cap_id="present", transform=lambda v: 0.4)
        cap_missing = SoftCapRule(cap_id="missing", transform=lambda v: 0.1)  # would bind tighter if evaluated
        r = compute_condition(
            "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap_present, cap_missing),
            soft_cap_domain_values={"present": 1.0},  # "missing" has no entry at all
        )
        # Only "present" was evaluated; "missing" must not silently act as
        # active (would wrongly bind to 0.1) or inactive (would silently
        # vanish from active_cap_ids bookkeeping in a way indistinguishable
        # from a cap that genuinely mapped to 1.0) — it's simply absent.
        assert r.condition_score == pytest.approx(0.4)
        assert r.active_cap_ids == ("present",)
        assert "missing" not in r.veto_cap_details

    def test_cap_tying_condition_pre_cap_exactly_is_still_a_binder(self):
        """A real bug found during self-review: a cap whose mapped bound
        equals condition_pre_cap exactly (not below it) does not LOWER the
        score, but it IS mathematically part of the min-set that produces
        condition_score (min(condition_pre_cap, cap) with cap ==
        condition_pre_cap) — an earlier version of this module gated the
        binder-detection loop behind `condition_score < condition_pre_cap`,
        which wrongly produced an empty binding_cap_ids here."""
        weights = _equal_weights()
        cap = SoftCapRule(cap_id="tie_with_precap", transform=lambda v: 0.5)
        r = compute_condition(
            "2020-04-15", 0.5, 0.5, 0.5, 0.5, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap,), soft_cap_domain_values={"tie_with_precap": 1.0},
        )
        assert r.condition_pre_cap == pytest.approx(0.5)
        assert r.condition_score == pytest.approx(0.5)
        assert r.active_cap_ids == ("tie_with_precap",)
        assert r.binding_cap_ids == ("tie_with_precap",)

    def test_duplicate_cap_id_rejected(self):
        weights = _equal_weights()
        c1 = SoftCapRule(cap_id="dup", transform=lambda v: 0.5)
        c2 = SoftCapRule(cap_id="dup", transform=lambda v: 0.3)
        with pytest.raises(ValueError, match="duplicate cap_id"):
            compute_condition(
                "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
                hard_veto_rules=(), hard_veto_domain_values={},
                soft_cap_rules=(c1, c2), soft_cap_domain_values={"dup": 1.0},
            )

    def test_inactive_cap_tying_condition_score_is_never_a_binder(self):
        """A second real bug found during self-review: after fixing the
        first bug (caps that tie condition_pre_cap must still be
        publishable as binders), a naive unconditional 'mapped ==
        condition_score' check introduced a NEW bug — an explicitly
        INACTIVE cap (mapped bound == 1.0, §7.3's own definition of
        inactive) could still be reported as a binder whenever
        condition_score itself happened to be 1.0 (e.g. all four pillars
        at 1.0, no other active cap), producing the self-contradictory
        active_cap_ids=() with binding_cap_ids=(this cap,). A cap that is
        inactive by definition cannot simultaneously be a binder."""
        weights = _equal_weights()
        cap = SoftCapRule(cap_id="inactive_cap", transform=lambda v: 1.0)
        r = compute_condition(
            "2020-04-15", 1.0, 1.0, 1.0, 1.0, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap,), soft_cap_domain_values={"inactive_cap": 1.0},
        )
        assert r.condition_pre_cap == pytest.approx(1.0)
        assert r.condition_score == pytest.approx(1.0)
        assert r.active_cap_ids == ()
        assert r.binding_cap_ids == ()

    def test_order_independence_of_min_composition(self):
        """§7.3: 'Minimum composition is deterministic, order-independent.'
        Reordering the same cap rules must not change condition_score or
        which caps bind."""
        weights = _equal_weights()
        cap_a = SoftCapRule(cap_id="cap_a", transform=lambda v: 0.7)
        cap_b = SoftCapRule(cap_id="cap_b", transform=lambda v: 0.2)
        domain_values = {"cap_a": 1.0, "cap_b": 1.0}

        r1 = compute_condition(
            "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap_a, cap_b), soft_cap_domain_values=domain_values,
        )
        r2 = compute_condition(
            "2020-04-15", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(cap_b, cap_a), soft_cap_domain_values=domain_values,
        )
        assert r1.condition_score == r2.condition_score
        assert r1.binding_cap_ids == r2.binding_cap_ids


# ---------------------------------------------------------------------------
# condition_pct
# ---------------------------------------------------------------------------

class TestConditionPct:
    def test_condition_pct_is_condition_score_times_100(self):
        weights = _equal_weights()
        r = compute_condition(
            "2020-04-15", 0.5, 0.5, 0.5, 0.5, weights,
            hard_veto_rules=(), hard_veto_domain_values={},
            soft_cap_rules=(), soft_cap_domain_values={},
        )
        assert r.condition_pct == pytest.approx(r.condition_score * 100.0)
        assert r.condition_pct == pytest.approx(50.0)

    def test_condition_pct_is_zero_when_a_veto_fires(self):
        weights = _equal_weights()
        veto = HardVetoRule(veto_id="vix_spike", comparator=">=", threshold=40.0)
        r = compute_condition(
            "2020-03-20", 0.9, 0.9, 0.9, 0.9, weights,
            hard_veto_rules=(veto,), hard_veto_domain_values={"vix_spike": 55.0},
            soft_cap_rules=(), soft_cap_domain_values={},
        )
        assert r.condition_pct == 0.0


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_computation_is_repeatable(self):
        weights = PillarWeights(weight_direction=0.3, weight_breadth=0.3, weight_risk_appetite=0.2, weight_stability=0.2)
        cap = SoftCapRule(cap_id="cap_a", transform=lambda v: 0.6)
        veto = HardVetoRule(veto_id="vix_spike", comparator=">=", threshold=40.0)
        kwargs = dict(
            hard_veto_rules=(veto,), hard_veto_domain_values={"vix_spike": 15.0},
            soft_cap_rules=(cap,), soft_cap_domain_values={"cap_a": 1.0},
        )
        r1 = compute_condition("2020-04-15", 0.7, 0.6, 0.4, 0.8, weights, **kwargs)
        r2 = compute_condition("2020-04-15", 0.7, 0.6, 0.4, 0.8, weights, **kwargs)
        assert r1 == r2
