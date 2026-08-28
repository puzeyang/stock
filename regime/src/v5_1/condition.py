"""Market Regime v5.1 — Slice 7: Condition / Vetoes / Caps (module 4.8).

Design §7 (C1, C3, C11, C12, E8, E9, E10): the four pillars (Direction,
Breadth, Risk Appetite, Stability) combine into `condition_pre_cap` via a
nonnegative, sum-to-one weighted sum, clipped to [0,1] only for
floating-point safety (§7.1). Hard vetoes (§7.2) are memoryless,
current-bar-only safety circuits keyed to declared raw domains — a valid
veto forces `condition_score = 0` and at least RISK_OFF; missing data never
fires or clears a veto (fail-closed, C16 — it makes Condition unavailable
instead). Soft caps (§7.3) default to an empty list in production; any
adopted cap is a continuous monotone-decreasing-safety upper bound in [0,1]
(1 = inactive), has no memory, and is min-composed across all active caps.
Hard vetoes take precedence over caps. Minimum composition is deterministic,
order-independent, and avoids multiplicative compounding.

**Conformance requirement this module must satisfy (§7.3, plan §7)**: with
`soft_cap_config == []` (the production default), `condition_score ==
condition_pre_cap` after veto application — proven directly by a dedicated
test, not just implied by the min-composition logic.

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`):
`pillar_weights`, `condition_pre_cap`, `condition_score`, `condition_pct`,
`active_veto_ids`, `active_cap_ids`, `binding_cap_ids`, `veto_cap_details`.
`direction_contribution`/`breadth_contribution` (module 4.3/4.5's owned
scalar per-pillar weighted terms feeding `condition_pre_cap`, per their own
manifest consumer lists) are also computed here, since they are simply
`weight_i * pillar_i` and this module is where that weighted sum happens —
`risk_appetite_contributions`/`stability_contributions` are each pillar's
OWN internal per-component breakdown (already published by Slices 5/6's own
Result dataclasses) and are not re-derived here.

**EMPIRICAL scope:** pillar weights (E8), hard-veto domains/thresholds (E9),
and whether/how any soft cap is adopted (E10) are all EMPIRICAL — no
specific weight, veto domain, veto threshold, or cap curve is CLOSED
anywhere in the design. This module defines the shape (weighted sum, veto
application, min-composed caps) but never embeds a concrete configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class ConditionUnavailableError(Exception):
    """Signals Condition is genuinely unavailable for this as_of date per
    design §4.1's fail-closed rule — never neutralized to a default. Raised
    when a required pillar input itself is unavailable (None); NEVER raised
    by a missing hard-veto domain value, which per §7.2 must make Condition
    unavailable through this same path (missing data never fires OR clears
    a veto — it removes the ability to evaluate Condition at all)."""


@dataclass(frozen=True)
class PillarWeights:
    """EMPIRICAL (§17.8/§7.1) — injected. Nonnegative weights summing to
    one, combining the four pillar scores into condition_pre_cap."""

    weight_direction: float
    weight_breadth: float
    weight_risk_appetite: float
    weight_stability: float

    def __post_init__(self) -> None:
        weights = (self.weight_direction, self.weight_breadth, self.weight_risk_appetite, self.weight_stability)
        if any(w < 0 for w in weights):
            raise ValueError("PillarWeights: all weights must be nonnegative")
        total = sum(weights)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"PillarWeights: weights must sum to exactly 1.0, got {total}")


@dataclass(frozen=True)
class HardVetoRule:
    """EMPIRICAL (§17.9/§7.2) — one hard-veto rule keyed to a declared raw
    domain value the caller supplies (this module does not compute raw
    domain values itself, per §7.2's "keyed to declared raw domains" — the
    domain value is whatever real raw/canonical feature the EMPIRICAL
    config names, e.g. a VIX level or credit spread, supplied by the
    caller). `comparator` decides whether the veto fires when the domain
    value is >= or <= `threshold` — both directions are legitimate
    depending on the domain's own polarity (e.g. "VIX >= X" vs. "breadth
    <= Y"), so this is not hardcoded to one direction.

    `veto_id` is a stable identifier published in `active_veto_ids` and
    `veto_cap_details` — never a positional index, so identity survives
    config reordering.
    """

    veto_id: str
    comparator: str  # ">=" or "<="
    threshold: float

    def __post_init__(self) -> None:
        if self.comparator not in (">=", "<="):
            raise ValueError(f"HardVetoRule.comparator must be '>=' or '<=', got {self.comparator!r}")

    def fires(self, domain_value: float) -> bool:
        if self.comparator == ">=":
            return domain_value >= self.threshold
        return domain_value <= self.threshold


@dataclass(frozen=True)
class SoftCapRule:
    """EMPIRICAL (§17.10/§7.3) — one soft-cap rule. `transform` MUST be a
    continuous monotone function of a raw domain value into [0,1], where 1
    means inactive (no capping effect) — implementers own this contract;
    this module does not choose or embed any specific curve. Per §7.3, an
    adopted cap must use a raw domain or canonical raw feature, never
    aggregate Condition or a pillar itself — enforced by convention here
    (the caller supplies `domain_value`, never a pillar score), not by a
    runtime type check, since this module cannot distinguish a raw feature
    value from a pillar score once both are plain floats.

    `cap_id` is a stable identifier published in `active_cap_ids`/
    `binding_cap_ids`/`veto_cap_details`."""

    cap_id: str
    transform: Callable[[float], float]

    def mapped_bound(self, domain_value: float) -> float:
        return self.transform(domain_value)


@dataclass(frozen=True)
class ConditionResult:
    as_of: str
    direction_contribution: float
    breadth_contribution: float
    risk_appetite_contribution: float
    stability_contribution: float
    condition_pre_cap: float
    condition_score: float
    condition_pct: float
    active_veto_ids: tuple[str, ...]
    active_cap_ids: tuple[str, ...]
    binding_cap_ids: tuple[str, ...]
    veto_cap_details: dict = field(default_factory=dict)


def compute_condition(
    as_of: str,
    direction_score: float | None,
    breadth_score: float | None,
    risk_appetite_score: float | None,
    stability_score: float | None,
    pillar_weights: PillarWeights,
    hard_veto_rules: tuple[HardVetoRule, ...],
    hard_veto_domain_values: dict[str, float | None],
    soft_cap_rules: tuple[SoftCapRule, ...],
    soft_cap_domain_values: dict[str, float | None],
) -> ConditionResult:
    """Full Condition computation for one as_of date.

    Raises ConditionUnavailableError if:
    - any of the four pillar scores is None (a pillar itself unavailable
      makes condition_pre_cap unavailable, per C16 fail-closed — Condition
      cannot be a weighted sum of a missing term); or
    - any hard-veto rule's declared domain value is missing (None) from
      `hard_veto_domain_values` — per §7.2 "missing data never fires or
      clears a veto; it makes Condition unavailable." A missing veto
      domain is NOT silently treated as "veto does not fire" (that would be
      firing-by-omission's opposite failure — quietly clearing a safety
      circuit because its input went missing) and NOT silently treated as
      "veto fires" either (that would be inventing a positive signal from
      an absence) — it is a genuine unavailability of Condition itself.

    A missing soft-cap domain value is different: soft caps are OPTIONAL
    (production default is none), so a missing cap domain value simply
    means that specific cap cannot be evaluated and is excluded from the
    min-composition (never treated as "inactive" (1.0) OR "fully capping"
    (0.0) by substitution — it is dropped from consideration entirely,
    same as any other optional diagnostic with no current input).
    """
    if direction_score is None or breadth_score is None or risk_appetite_score is None or stability_score is None:
        raise ConditionUnavailableError(
            f"Condition unavailable as of {as_of}: one or more pillar scores are None "
            f"(direction={direction_score}, breadth={breadth_score}, "
            f"risk_appetite={risk_appetite_score}, stability={stability_score})"
        )

    # FOUND DURING SELF-REVIEW: veto_id/cap_id are used as dict keys in
    # veto_cap_details below (and as the sole identity in active_veto_ids/
    # active_cap_ids/binding_cap_ids), so a config with a duplicated id
    # would silently collapse to whichever rule happens to be evaluated
    # last for veto_cap_details, while active_veto_ids could still report
    # the id as fired based on a DIFFERENT rule's evaluation — an
    # internally self-contradictory result (e.g. active_veto_ids says a
    # veto fired while veto_cap_details for that same id shows
    # fired=False). This is a config-validity problem, not a per-bar
    # condition, so it is rejected explicitly and immediately rather than
    # left to silently corrupt output.
    veto_ids_seen = [rule.veto_id for rule in hard_veto_rules]
    if len(veto_ids_seen) != len(set(veto_ids_seen)):
        raise ValueError(f"hard_veto_rules contains duplicate veto_id values: {veto_ids_seen}")
    cap_ids_seen = [rule.cap_id for rule in soft_cap_rules]
    if len(cap_ids_seen) != len(set(cap_ids_seen)):
        raise ValueError(f"soft_cap_rules contains duplicate cap_id values: {cap_ids_seen}")

    direction_contribution = pillar_weights.weight_direction * direction_score
    breadth_contribution = pillar_weights.weight_breadth * breadth_score
    risk_appetite_contribution = pillar_weights.weight_risk_appetite * risk_appetite_score
    stability_contribution = pillar_weights.weight_stability * stability_score

    condition_pre_cap = direction_contribution + breadth_contribution + risk_appetite_contribution + stability_contribution
    # Clipped only for floating-point safety, per §7.1 — the weighted sum of
    # four already-[0,1] pillars with nonnegative weights summing to one is
    # mathematically already in [0,1]; this clip exists solely to absorb
    # float roundoff at the exact 0/1 boundary, never to correct a real
    # out-of-range input.
    condition_pre_cap = min(1.0, max(0.0, condition_pre_cap))

    active_veto_ids: list[str] = []
    veto_cap_details: dict = {}
    for rule in hard_veto_rules:
        domain_value = hard_veto_domain_values.get(rule.veto_id)
        if domain_value is None:
            raise ConditionUnavailableError(
                f"Condition unavailable as of {as_of}: hard-veto rule {rule.veto_id!r} has no "
                f"domain value supplied — missing data never fires or clears a veto (§7.2)"
            )
        fired = rule.fires(domain_value)
        veto_cap_details[rule.veto_id] = {
            "kind": "veto",
            "domain_value": domain_value,
            "threshold": rule.threshold,
            "comparator": rule.comparator,
            "fired": fired,
        }
        if fired:
            active_veto_ids.append(rule.veto_id)

    if active_veto_ids:
        # A valid veto sets condition_score = 0 immediately (§7.2) — hard
        # vetoes take precedence over soft caps entirely; caps are not even
        # evaluated for their binding effect once a veto has fired, since
        # min(0.0, anything <= 1.0) == 0.0 regardless, but more importantly
        # per §7.3 "hard vetoes take precedence" is a precedence rule, not
        # merely an arithmetic coincidence — active_cap_ids/binding_cap_ids
        # stay empty in this branch, not populated with irrelevant caps.
        condition_score = 0.0
        active_cap_ids: tuple[str, ...] = ()
        binding_cap_ids: tuple[str, ...] = ()
    else:
        active_cap_id_list: list[str] = []
        binding_cap_id_list: list[str] = []
        bound_values: list[float] = [condition_pre_cap]  # min-composed against condition_pre_cap itself
        for cap_rule in soft_cap_rules:
            domain_value = soft_cap_domain_values.get(cap_rule.cap_id)
            if domain_value is None:
                # Optional diagnostic input missing: this cap is simply not
                # evaluated this bar, not forced active or inactive.
                continue
            mapped = cap_rule.mapped_bound(domain_value)
            is_active = mapped < 1.0
            veto_cap_details[cap_rule.cap_id] = {
                "kind": "cap",
                "domain_value": domain_value,
                "mapped_bound": mapped,
                "active": is_active,
            }
            if is_active:
                active_cap_id_list.append(cap_rule.cap_id)
            bound_values.append(mapped)

        condition_score = min(bound_values)
        # Deterministic, order-independent min-composition (§7.3): every
        # ACTIVE cap (mapped bound < 1.0 — §7.3 "1 is inactive") whose
        # mapped bound equals the final minimum is a binder — ties publish
        # ALL binders, not just the first one found, per §7.3's explicit
        # "ties publish all binders." condition_pre_cap itself is never a
        # binder (it is not a cap).
        #
        # FOUND DURING SELF-REVIEW (round 1): an earlier version gated this
        # entire loop behind `condition_score < condition_pre_cap`, which
        # silently produced an empty binding_cap_ids for a cap whose mapped
        # bound happened to equal condition_pre_cap exactly (a real,
        # constructed case: condition_pre_cap=0.5, one cap mapping to
        # exactly 0.5) — that cap IS mathematically part of the min-set
        # that determines condition_score, so it must be published as a
        # binder even though it didn't LOWER the score below pre_cap.
        #
        # FOUND DURING SELF-REVIEW (round 2): the round-1 fix then checked
        # EVERY cap's mapped bound against condition_score unconditionally,
        # which introduced a different real bug — an explicitly INACTIVE
        # cap (mapped bound == 1.0, by §7.3's own definition of inactive)
        # could still get published as a "binder" whenever condition_score
        # itself happened to equal 1.0 (all four pillars at 1.0, no other
        # cap active), producing the self-contradictory state
        # `active_cap_ids == ()` but `binding_cap_ids == ("that_cap",)` — a
        # cap cannot bind anything while being simultaneously inactive.
        # Fixed by restricting binder detection to ACTIVE caps only.
        for cap_rule in soft_cap_rules:
            domain_value = soft_cap_domain_values.get(cap_rule.cap_id)
            if domain_value is None:
                continue
            mapped = cap_rule.mapped_bound(domain_value)
            if mapped < 1.0 and mapped == condition_score:
                binding_cap_id_list.append(cap_rule.cap_id)

        active_cap_ids = tuple(active_cap_id_list)
        binding_cap_ids = tuple(binding_cap_id_list)

    return ConditionResult(
        as_of=as_of,
        direction_contribution=direction_contribution,
        breadth_contribution=breadth_contribution,
        risk_appetite_contribution=risk_appetite_contribution,
        stability_contribution=stability_contribution,
        condition_pre_cap=condition_pre_cap,
        condition_score=condition_score,
        condition_pct=condition_score * 100.0,
        active_veto_ids=tuple(active_veto_ids),
        active_cap_ids=active_cap_ids,
        binding_cap_ids=binding_cap_ids,
        veto_cap_details=veto_cap_details,
    )
