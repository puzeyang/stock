"""Market Regime v5.1 — Slice 8a: CRISIS (part of module 4.10).

Design §9 (C13): CRISIS confirmation uses four independent, non-nested raw
domains — (1) volatility/term-structure stress, (2) canonical credit
stress, (3) canonical price damage, (4) participation collapse.
"Independent" means no domain's confirmation is an algebraic input to
another (economic correlation between them is expected and fine; Direction,
Condition, and the aggregate pillars themselves do not count as domains).

Entry (§9.2, EXTENDED per the human's explicit decision — discussion log
Messages[232]/[233]/[236]/[238], "anchored entry"): two or more VALID
domains ACTIVE on the same bar, WHERE AT LEAST ONE of the two-or-more
active domains is credit_stress (D2) or price_damage (D3), enters CRISIS
immediately — no ordinary downgrade delay. A bar where only volatility_
term_structure (D1) and participation_collapse (D4) are active does NOT
enter CRISIS, even with active_domain_count>=2 — found, via exploratory
analysis (Messages[229]/[232]), to empirically co-occur far more often
than D2/D3 do, and to be the actual mechanism behind every apparent false
positive found in that exploratory challenge set. At least two domains
must be VALID (not just active) for CRISIS entry to even be considered; a
hard veto with fewer than two confirmed domains forces RISK_OFF instead,
with two distinguishable diagnostic states — UNCHANGED by the anchored-
entry extension above, per the human's explicit "no change" answer
(Message[238]) to whether a D1+D4-only bar should publish any new
diagnostic or alter these fields:
  - 0 domains active: `uncorroborated_veto=true`, `crisis_watch=false`;
  - 1 domain active:  `uncorroborated_veto=true`, `crisis_watch=true`.

Exit (§9.3, EXTENDED per Message[220]/[221]/[223]'s human-decided
fail-closed fix — see `EXIT_BAR_REQUIRED_VALID_DOMAINS`): requires ALL of
(a) all hard vetoes clear, (b) fewer than two domains active, (c) Condition
above the NEUTRAL-entry boundary plus buffer, AND (d, added) all FOUR
domains valid this bar — for five CONSECUTIVE bars all meeting every one of
(a)-(d). A renewed two-domain confirmation at any point resets the exit
count to zero. (d) exists because, without it, a domain going UNAVAILABLE
is indistinguishable from that domain being observed CALM under (b) alone —
both simply fail to add to `active_domain_count` — which would let an exit
be confirmed on bars where CRISIS-relevant evidence was genuinely unknown,
not genuinely absent. The human chose the most conservative option (ALL
FOUR, not some lower minimum) when this gap was raised.

Fail-closed (§4.1/§9.2's own "missing/stale is unavailable, never calm or
stressed"): a domain with insufficient/stale/missing input is UNAVAILABLE
(neither active nor inactive) — never silently counted as "0" (calm) in the
valid-domain tally, on EITHER the entry OR (per the extension above) the
exit side. §9.4: exchange halts are explicitly OUT_OF_SCOPE here — this
module has no halt-detection logic and none should be added.

Owned manifest fields (per `market_regime_v5.1_field_ownership.v1.0.json`,
module 4.10 subset relevant to CRISIS): `crisis_domain_status`,
`crisis_valid_domain_count`, `crisis_active_domain_count`, `crisis_watch`,
`uncorroborated_veto`, `crisis_exit_count`.

**EMPIRICAL scope (§17.12):** the four CRISIS formulas and thresholds
themselves are entirely EMPIRICAL — no domain's concrete valid/active
formula is CLOSED anywhere in the design. Each domain is injected as a
`CrisisDomainEvaluator` Protocol; this module owns the CLOSED topology
(independence, 2-of-4 entry, 5-bar corroborated-clear exit,
uncorroborated-veto diagnostics) plus the human-decided (not originally
v5.1-CLOSED) `EXIT_BAR_REQUIRED_VALID_DOMAINS=4` exit-validity gate — never
a concrete domain formula, which remains genuinely EMPIRICAL and injected
by the caller (see `engine.py`'s real-but-simple D1-D4 reference
implementations, explicitly NOT production defaults, per the same
discipline as every other EMPIRICAL formula in this investigation).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .stability import PriceDamageComponents

EXIT_CONFIRMATION_BARS = 5  # CLOSED (§9.3): "five consecutive valid bars", not EMPIRICAL.
ENTRY_DOMAIN_THRESHOLD = 2  # CLOSED (§9.2/C13): "2-of-4", not EMPIRICAL.
EXIT_BAR_REQUIRED_VALID_DOMAINS = 4  # human-decided (Message[220]/[221]/[223], not an original v5.1 design-doc CLOSED value): each exit-confirmation bar must have ALL FOUR domains valid, not merely "fewer than two active" — closes the gap where an unavailable domain (e.g. D3's price_damage=None) is indistinguishable from an observed-calm domain under the entry-side ENTRY_DOMAIN_THRESHOLD check alone (design §9.2's "Missing/stale is unavailable, never calm or stressed" applied to exit, not just entry). Most conservative option of the ones discussed; the human explicitly chose it over a lower/data-driven threshold.
ANCHOR_DOMAIN_KEYS = ("credit_stress", "price_damage")  # human-decided (Messages[232]/[233]/[234]/[236]/[238], human's exact instruction: "必须含D2或D3"/"no change"): entry additionally requires at least one of D2 (credit_stress) or D3 (price_damage) to be VALID and ACTIVE, on top of the CLOSED ENTRY_DOMAIN_THRESHOLD=2 count. Empirical motivation, not a reinterpretation of §9.2/C13's CLOSED "2-of-4" topology: across the 8-episode exploratory challenge set (`crisis_validation.py`), every apparent false positive was a D1(volatility)+D4(participation_collapse)-only pair with neither a credit nor a price-damage confirmation, while every one of the 6 positive-labeled crisis episodes had a real D2 or D3 confirmation at first entry. Diagnostic fields (`uncorroborated_veto`, `crisis_watch`) are explicitly UNCHANGED by this — the human's answer to Message[236]'s closing question was "no change", i.e. no new fallback/watch state is published when entry is blocked this way.


@dataclass(frozen=True)
class CrisisDomainReading:
    """One domain's evaluation for one bar. `valid=False` means the domain
    is genuinely unavailable this bar (missing/stale/insufficiently warmed
    input) — `active` is meaningless and MUST be ignored by callers when
    `valid` is False (never treated as calm-by-omission).

    `reason_codes` (added per Message[220]/[221]'s discussion-log review,
    closing a real gap against design §9.2's "Publish per-domain
    valid/active flags, coverage, count, reason codes, and entry/exit
    counters" — the field did not exist before): a tuple of stable string
    identifiers explaining WHY a domain is unavailable or WHICH raw
    sub-condition made it active, e.g. `("canonical_price_damage_
    unavailable",)` for D3 when Stability's `price_damage` is None, or
    `("extreme",)` / `("level_stress", "curve_stress")` for a real active
    domain — never free text, always a stable machine-checkable code.
    Defaults to `()` (empty) for backward compatibility with every
    existing caller that predates this field; an empty tuple is valid
    (e.g. a domain that is simply calm/inactive has nothing to explain)."""

    valid: bool
    active: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CrisisEvaluationContext:
    """Shared, immutable per-bar context passed UNIFORMLY to all four
    domain evaluators (added per Message[218]/[219]'s discussion-log
    review). Replaces the bare `as_of: str` `CrisisDomainEvaluator`
    previously received — needed because `evaluate_crisis_bar` calls
    every domain identically in one loop (`evaluator(context)`), so no
    single domain can receive a parameter the others don't; domains that
    don't need `price_damage` (D1/D2/D4) simply ignore it.

    `price_damage_components` carries the SAME canonical
    `PriceDamageComponents` instance `compute_stability` already computed
    this invocation (`StabilityResult.price_damage_components`) — per
    `compute_stability`'s own explicit MUST ("callers needing any
    price-damage component elsewhere (CRISIS, diagnostics) MUST reuse
    this same returned `PriceDamageComponents` instance, never call the
    estimator again independently"), the price-damage domain evaluator
    (D3) MUST read this field, never recompute its own drawdown/
    return-shock measures. Per the human's explicit decision
    (Message[227]), D3 reads the raw `benchmark_drawdown`/
    `return_shock_5d`/`return_shock_20d` components directly (needed
    since Message[211]'s D3 design uses independent 5-day/20-day
    thresholds a single composed scalar cannot represent) — NOT only the
    composed `price_damage` scalar every other consumer uses. `None` if
    Stability (and therefore the canonical components) was itself
    unavailable this bar — D3 must then return `valid=False` with a
    `canonical_price_damage_unavailable` reason code, per Message[221]."""

    as_of: str
    price_damage_components: "PriceDamageComponents | None"


class CrisisDomainEvaluator(Protocol):
    """EMPIRICAL (§17.12/§9.1) — the shape one CRISIS domain's evaluator
    MUST have. Implementers decide the concrete raw-domain formula and
    threshold; this module never embeds one. Each of the four domains
    (volatility/term-structure stress, credit stress, price damage,
    participation collapse) gets its own separately injected evaluator
    instance — independence (C13) is enforced by construction here: no
    evaluator receives another domain's reading as an input."""

    def __call__(self, context: CrisisEvaluationContext) -> CrisisDomainReading:
        ...


@dataclass(frozen=True)
class CrisisDomainConfig:
    """The four independently-injected domain evaluators, keyed by their
    CLOSED domain names (§9.1's own four-item list — the SET of domains is
    CLOSED, only each domain's internal formula is EMPIRICAL)."""

    volatility_term_structure: CrisisDomainEvaluator
    credit_stress: CrisisDomainEvaluator
    price_damage: CrisisDomainEvaluator
    participation_collapse: CrisisDomainEvaluator

    def domains(self) -> dict[str, CrisisDomainEvaluator]:
        return {
            "volatility_term_structure": self.volatility_term_structure,
            "credit_stress": self.credit_stress,
            "price_damage": self.price_damage,
            "participation_collapse": self.participation_collapse,
        }


@dataclass(frozen=True)
class CrisisBarEvaluation:
    """One bar's raw domain readings, independent of any persisted
    entry/exit state — this is the pure per-bar computation; entry/exit
    hysteresis is applied separately by `CrisisState.advance()`."""

    as_of: str
    domain_status: dict[str, CrisisDomainReading]
    valid_domain_count: int
    active_domain_count: int


def evaluate_crisis_bar(
    as_of: str, config: CrisisDomainConfig, price_damage_components: "PriceDamageComponents | None" = None,
) -> CrisisBarEvaluation:
    """Evaluate all four CRISIS domains for one bar. `valid_domain_count`
    counts domains where `valid=True` (regardless of active/inactive);
    `active_domain_count` counts domains where BOTH `valid=True` AND
    `active=True` — an invalid domain never contributes to either an
    active or an inactive tally, per §9.2's "missing/stale is unavailable,
    never calm or stressed."

    `price_damage_components` (added per Message[218]/[219]/[221], shape
    updated per Message[225]/[226]/[227]) is the SAME canonical
    `PriceDamageComponents` instance the caller's own `compute_stability`
    invocation already computed this bar (`StabilityResult.
    price_damage_components`, or `None` if Stability was itself
    unavailable) — passed through unchanged into a shared
    `CrisisEvaluationContext` given identically to all four domain
    evaluators, per `CrisisEvaluationContext`'s own docstring. D1/D2/D4
    are free to ignore it; only D3 (price damage) is expected to read it,
    and reads the raw components directly per the human's decision
    (Message[227]), not a composed scalar. Defaults to `None` for
    backward compatibility with any caller not yet passing a real value
    (e.g. synthetic-fixture tests exercising D1/D2/D4 only) — a `None`
    here simply means D3 (if present in `config`) will see
    `context.price_damage_components is None` and must handle that as
    its own unavailability case, exactly as it would for a real missing
    value.
    """
    context = CrisisEvaluationContext(as_of=as_of, price_damage_components=price_damage_components)
    status: dict[str, CrisisDomainReading] = {}
    valid_count = 0
    active_count = 0
    for name, evaluator in config.domains().items():
        reading = evaluator(context)
        status[name] = reading
        if reading.valid:
            valid_count += 1
            if reading.active:
                active_count += 1

    return CrisisBarEvaluation(
        as_of=as_of,
        domain_status=status,
        valid_domain_count=valid_count,
        active_domain_count=active_count,
    )


@dataclass(frozen=True)
class ConditionForExit:
    """The two Condition-side facts CRISIS exit needs, per §9.3(c)
    ("Condition above the NEUTRAL-entry boundary plus buffer") and
    §9.3(a) ("all hard vetoes clear") — supplied by the caller each bar,
    since Condition (module 4.8) and its NEUTRAL-entry boundary (module
    4.10's own ordinary-hysteresis EMPIRICAL config) are computed
    elsewhere. `condition_score` may be None if Condition itself is
    unavailable this bar (fail-closed: an unavailable Condition can never
    satisfy the exit condition)."""

    condition_score: float | None
    any_hard_veto_active: bool
    neutral_entry_boundary_plus_buffer: float


@dataclass
class CrisisState:
    """Mutable persisted CRISIS entry/exit state (design §4.3's "CRISIS
    exit count" persisted field). `in_crisis` starts False (never seeded
    into CRISIS at cold start — consistent with this engine's established
    "never seed a semantic constant" discipline from Direction's cold-start
    fix, Message[172])."""

    in_crisis: bool = False
    crisis_exit_count: int = 0

    def advance(self, bar: CrisisBarEvaluation, exit_ctx: ConditionForExit) -> "CrisisState":
        """Advance CRISIS entry/exit state by one bar. Returns self
        (mutated in place) for convenient chaining; also returned
        explicitly so callers can treat this as either a mutation or a
        pure-ish step depending on style.

        Entry (§9.2, EXTENDED per the human's explicit decision, discussion
        log Messages[232]/[233]/[236]/[238] — "anchored entry"): fires
        immediately (no downgrade delay to wait through — CRISIS entry
        from any prior state is itself the fastest possible transition)
        whenever `valid_domain_count >= 2` AND `active_domain_count >= 2`
        AND at least one of the two active domains is `credit_stress` (D2)
        or `price_damage` (D3) — i.e. a bar where ONLY `volatility_term_
        structure` (D1) and `participation_collapse` (D4) are active does
        NOT enter CRISIS. This is a real, human-decided change to §9.2's
        entry corroboration rule, not a tuning of an EMPIRICAL threshold
        within it — found via exploratory analysis (discussion log
        Messages[229]/[232]) that D1+D4 empirically co-occur far more
        than D2/D3 do, and that all 3 apparent false positives in that
        exploratory challenge set were D1+D4-only bars, while D2/D3
        stayed quiet specifically on those same bars. Per the human's
        explicit "no change" answer (Message[238]) to the one remaining
        open question: a D1+D4-only bar that fails this anchored-entry
        check does NOT publish any new diagnostic field, does NOT cap the
        ordinary categorical state, and does NOT alter `crisis_watch`/
        `uncorroborated_veto` (those remain exactly what
        `compute_uncorroborated_veto_diagnostics` already defines,
        unchanged) — the ordinary state machine runs exactly as it did
        before this change on such a bar. `valid_domain_count >= 2` is
        kept as a separate, explicit check for the same invariant-
        verification reason as before (an active domain is always also
        valid, so `active_domain_count >= 2` already implies it
        structurally).

        Exit (§9.3, extended per Message[220]/[221]/[223]'s human-decided
        fail-closed fix): while in CRISIS, exits only after
        EXIT_CONFIRMATION_BARS (5) CONSECUTIVE bars all simultaneously
        satisfying (a) no hard veto active, (b) `active_domain_count < 2`,
        (c) `condition_score` is not None and exceeds
        `neutral_entry_boundary_plus_buffer`, AND (d, added) ALL FOUR
        domains are `valid` this bar (`valid_domain_count ==
        EXIT_BAR_REQUIRED_VALID_DOMAINS`). (d) closes a real gap §9.3's
        original text left open: without it, a domain going unavailable
        (e.g. D3's canonical price_damage becoming None) is
        indistinguishable from that same domain being observed calm —
        both simply fail to increment `active_domain_count` — so an
        exit could be confirmed on bars where the CRISIS-relevant
        evidence was genuinely unknown, not genuinely absent. This is
        the SAME §9.2 principle ("Missing/stale is unavailable, never
        calm or stressed") already enforced on the entry side, extended
        to the exit side, per the human's explicit conservative choice
        (require ALL four domains valid, not merely some minimum count)
        rather than an unvalidated lower threshold. A renewed 2-domain
        confirmation at ANY point while counting resets crisis_exit_count
        to 0 (§9.3's own "renewed two-domain confirmation resets the
        count") — checked before the ordinary per-bar exit-condition
        check, since renewed entry is a stronger, overriding signal.
        """
        anchored_confirmation = any(
            (reading := bar.domain_status.get(key)) is not None and reading.valid and reading.active
            for key in ANCHOR_DOMAIN_KEYS
        )

        if bar.active_domain_count >= ENTRY_DOMAIN_THRESHOLD and anchored_confirmation:
            assert bar.valid_domain_count >= ENTRY_DOMAIN_THRESHOLD, (
                "invariant violated: active_domain_count >= 2 must imply valid_domain_count >= 2 "
                "(an active domain is, by CrisisDomainReading's own contract, always also valid)"
            )
            self.in_crisis = True
            self.crisis_exit_count = 0
            return self

        if not self.in_crisis:
            return self

        exit_condition_met = (
            not exit_ctx.any_hard_veto_active
            and bar.active_domain_count < ENTRY_DOMAIN_THRESHOLD
            and exit_ctx.condition_score is not None
            and exit_ctx.condition_score > exit_ctx.neutral_entry_boundary_plus_buffer
            and bar.valid_domain_count == EXIT_BAR_REQUIRED_VALID_DOMAINS
        )

        if exit_condition_met:
            self.crisis_exit_count += 1
            if self.crisis_exit_count >= EXIT_CONFIRMATION_BARS:
                self.in_crisis = False
                self.crisis_exit_count = 0
        else:
            # Any bar that fails the exit condition (short of a full
            # 2-domain re-entry, already handled above) resets the count —
            # §9.3 requires FIVE CONSECUTIVE valid bars, not five bars
            # total, so a single failing bar restarts the count from zero.
            # This includes a bar where fewer than all four domains are
            # valid (the new (d) condition above) — an "unknown" bar
            # can never count toward exit confirmation, it can only ever
            # reset the counter, same as any other failing bar.
            self.crisis_exit_count = 0

        return self


@dataclass(frozen=True)
class UncorroboratedVetoDiagnostics:
    """§9.2's two distinguishable "hard veto with fewer than two
    confirmations" diagnostic states. This is a pure function of the
    CURRENT bar's active_domain_count alone — it does not depend on
    persisted CrisisState, since it's a diagnostic about the current bar's
    corroboration level, not a hysteresis-gated transition."""

    uncorroborated_veto: bool
    crisis_watch: bool


def compute_uncorroborated_veto_diagnostics(active_domain_count: int, any_hard_veto_active: bool) -> UncorroboratedVetoDiagnostics:
    """§9.2: 'A hard veto with fewer than two confirmations forces
    RISK_OFF, not CRISIS' — zero active domains gives
    uncorroborated_veto=true/crisis_watch=false; one active domain gives
    uncorroborated_veto=true/crisis_watch=true. With two or more active
    domains, CRISIS itself is entered (handled by CrisisState.advance),
    and this diagnostic pair is both False — there is no "uncorroborated"
    veto once corroboration is actually met. Both flags are also False
    whenever no hard veto is active at all, regardless of domain count —
    this diagnostic is specifically about a VETO lacking corroboration,
    not about domain count in isolation.
    """
    if not any_hard_veto_active or active_domain_count >= ENTRY_DOMAIN_THRESHOLD:
        return UncorroboratedVetoDiagnostics(uncorroborated_veto=False, crisis_watch=False)
    if active_domain_count == 0:
        return UncorroboratedVetoDiagnostics(uncorroborated_veto=True, crisis_watch=False)
    return UncorroboratedVetoDiagnostics(uncorroborated_veto=True, crisis_watch=True)
