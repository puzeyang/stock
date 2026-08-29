"""Market Regime v5.1 — CRISIS (part of module 4.10) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_crisis.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.crisis import (  # noqa: E402
    CrisisDomainReading,
    CrisisDomainConfig,
    CrisisBarEvaluation,
    CrisisEvaluationContext,
    CrisisState,
    ConditionForExit,
    evaluate_crisis_bar,
    compute_uncorroborated_veto_diagnostics,
    EXIT_CONFIRMATION_BARS,
    ENTRY_DOMAIN_THRESHOLD,
    EXIT_BAR_REQUIRED_VALID_DOMAINS,
    ANCHOR_DOMAIN_KEYS,
)
from v5_1.stability import PriceDamageComponents  # noqa: E402


def _const_domain(valid: bool, active: bool, reason_codes: tuple[str, ...] = ()):
    def _ev(context: CrisisEvaluationContext):
        return CrisisDomainReading(valid=valid, active=active, reason_codes=reason_codes)
    return _ev


def _config(vol=(True, False), credit=(True, False), price=(True, False), participation=(True, False)):
    return CrisisDomainConfig(
        volatility_term_structure=_const_domain(*vol),
        credit_stress=_const_domain(*credit),
        price_damage=_const_domain(*price),
        participation_collapse=_const_domain(*participation),
    )


def _clear_exit_ctx(condition_score=0.9, boundary=0.4, veto=False):
    return ConditionForExit(condition_score=condition_score, any_hard_veto_active=veto, neutral_entry_boundary_plus_buffer=boundary)


# ---------------------------------------------------------------------------
# evaluate_crisis_bar — per-bar domain tallying
# ---------------------------------------------------------------------------

class TestEvaluateCrisisBar:
    def test_all_domains_valid_and_calm(self):
        config = _config()
        bar = evaluate_crisis_bar("2020-04-15", config)
        assert bar.valid_domain_count == 4
        assert bar.active_domain_count == 0

    def test_two_active_domains_counted_correctly(self):
        config = _config(vol=(True, True), credit=(True, True))
        bar = evaluate_crisis_bar("2020-03-20", config)
        assert bar.valid_domain_count == 4
        assert bar.active_domain_count == 2

    def test_invalid_domain_excluded_from_both_tallies(self):
        """A domain that is invalid (missing/stale) must not contribute to
        EITHER valid_domain_count or active_domain_count, even if its
        `active` field happens to be True — invalid means unavailable, and
        `active` is meaningless in that state per the module's own
        contract."""
        config = _config(vol=(False, True), credit=(True, True), price=(True, False), participation=(True, False))
        bar = evaluate_crisis_bar("2020-03-20", config)
        assert bar.valid_domain_count == 3  # vol excluded
        assert bar.active_domain_count == 1  # only credit_stress counts; vol's active=True is ignored

    def test_domain_status_dict_has_all_four_named_domains(self):
        config = _config()
        bar = evaluate_crisis_bar("2020-04-15", config)
        assert set(bar.domain_status.keys()) == {
            "volatility_term_structure", "credit_stress", "price_damage", "participation_collapse",
        }

    def test_independence_no_domain_receives_another_domains_reading(self):
        """Structural check (C13's 'independence' requirement): each
        evaluator is called with ONLY `as_of`, never with another domain's
        CrisisDomainReading — proven by inspecting each evaluator's actual
        call signature is satisfied with exactly one positional arg."""
        import inspect
        config = _config()
        for name, evaluator in config.domains().items():
            sig = inspect.signature(evaluator)
            assert len(sig.parameters) == 1, f"{name} evaluator must take exactly one argument (as_of)"


# ---------------------------------------------------------------------------
# CrisisState.advance — entry
# ---------------------------------------------------------------------------

class TestCrisisEntry:
    def test_starts_not_in_crisis_never_seeded(self):
        """Cold-start discipline consistent with Direction's fixed legacy
        bug (Message[172]): CrisisState must never start pre-seeded into
        CRISIS."""
        state = CrisisState()
        assert state.in_crisis is False
        assert state.crisis_exit_count == 0

    def test_two_active_domains_enters_crisis_immediately(self):
        state = CrisisState()
        bar = evaluate_crisis_bar("2020-03-20", _config(vol=(True, True), credit=(True, True)))
        state.advance(bar, _clear_exit_ctx())
        assert state.in_crisis is True

    def test_one_active_domain_does_not_enter_crisis(self):
        state = CrisisState()
        bar = evaluate_crisis_bar("2020-03-20", _config(vol=(True, True)))
        state.advance(bar, _clear_exit_ctx())
        assert state.in_crisis is False

    def test_three_or_four_active_domains_also_enters_crisis(self):
        state = CrisisState()
        bar = evaluate_crisis_bar("2020-03-20", _config(vol=(True, True), credit=(True, True), price=(True, True)))
        state.advance(bar, _clear_exit_ctx())
        assert state.in_crisis is True

    def test_every_single_domain_alone_fails_to_enter_crisis(self):
        """Golden-vector requirement (plan §6/design §14.1): 'Every CRISIS
        domain alone.' A gap found during Slice 12's conformance review:
        the existing test_one_active_domain_does_not_enter_crisis only
        exercises ONE arbitrary domain (vol) alone — this exhaustively
        checks all 4."""
        domain_kwargs_options = [
            dict(vol=(True, True)),
            dict(credit=(True, True)),
            dict(price=(True, True)),
            dict(participation=(True, True)),
        ]
        for kwargs in domain_kwargs_options:
            state = CrisisState()
            bar = evaluate_crisis_bar("2020-03-20", _config(**kwargs))
            state.advance(bar, _clear_exit_ctx())
            assert state.in_crisis is False, f"single active domain {kwargs} incorrectly entered CRISIS alone"

    def test_every_pair_of_domains_enters_crisis_except_the_unanchored_one(self):
        """Golden-vector requirement updated per the anchored-entry
        extension (Messages[232]/[233]/[234]/[236]/[238], human's exact
        instruction: "必须含D2或D3"/"no change"): of all C(4,2)=6
        domain-pair combinations, the 5 pairs that include D2
        (credit_stress) or D3 (price_damage) still enter CRISIS exactly as
        before — only vol+participation (D1+D4, the one pair with NEITHER
        a credit nor a price-damage confirmation) no longer enters. This
        is NOT a change to the CLOSED §9.2/C13 "2-of-4" topology or count
        — it is an additional confirmation requirement on top of it, per
        the human's explicit decision. See ANCHOR_DOMAIN_KEYS."""
        import itertools
        domain_names = ["vol", "credit", "price", "participation"]
        for a, b in itertools.combinations(domain_names, 2):
            kwargs = {a: (True, True), b: (True, True)}
            state = CrisisState()
            bar = evaluate_crisis_bar("2020-03-20", _config(**kwargs))
            state.advance(bar, _clear_exit_ctx())
            if {a, b} == {"vol", "participation"}:
                assert state.in_crisis is False, (
                    "domain pair vol+participation (D1+D4) has neither a credit nor a "
                    "price-damage confirmation and must NOT enter CRISIS under the "
                    "anchored-entry rule"
                )
            else:
                assert state.in_crisis is True, f"domain pair {a}+{b} did not enter CRISIS"

    def test_d1_d4_only_does_not_enter_crisis_from_non_crisis(self):
        """Direct, narrowly-scoped regression test for the anchored-entry
        rule's core case: D1(volatility)+D4(participation_collapse) active
        with D2/D3 both calm — active_domain_count==2 satisfies the CLOSED
        ENTRY_DOMAIN_THRESHOLD count alone, but must NOT enter CRISIS
        without an anchor confirmation."""
        state = CrisisState()
        bar = evaluate_crisis_bar(
            "2020-03-20",
            _config(vol=(True, True), participation=(True, True)),
        )
        assert bar.active_domain_count == 2  # count-only condition is satisfied
        state.advance(bar, _clear_exit_ctx())
        assert state.in_crisis is False
        assert state.crisis_exit_count == 0

    def test_each_anchored_pair_variant_enters_crisis(self):
        """All 5 domain-pair combinations that DO include D2 or D3 (i.e.
        every pair except D1+D4) enter CRISIS — explicit, non-exhaustive-
        loop version of the pair test above for direct readability."""
        anchored_pairs = [
            dict(vol=(True, True), credit=(True, True)),
            dict(vol=(True, True), price=(True, True)),
            dict(credit=(True, True), price=(True, True)),
            dict(credit=(True, True), participation=(True, True)),
            dict(price=(True, True), participation=(True, True)),
        ]
        for kwargs in anchored_pairs:
            state = CrisisState()
            bar = evaluate_crisis_bar("2020-03-20", _config(**kwargs))
            state.advance(bar, _clear_exit_ctx())
            assert state.in_crisis is True, f"anchored pair {kwargs} did not enter CRISIS"

    def test_d1_d4_only_does_not_change_diagnostic_fields(self):
        """Per the human's explicit "no change" answer to Message[236]'s
        closing question: a D1+D4-only bar must not trigger any NEW
        diagnostic/fallback state. `compute_uncorroborated_veto_diagnostics`
        is driven purely by active_domain_count and veto state, entirely
        independent of the anchored-entry rule — confirm it is unaffected."""
        bar = evaluate_crisis_bar(
            "2020-03-20",
            _config(vol=(True, True), participation=(True, True)),
        )
        diag_no_veto = compute_uncorroborated_veto_diagnostics(bar.active_domain_count, any_hard_veto_active=False)
        assert diag_no_veto.uncorroborated_veto is False
        diag_with_veto = compute_uncorroborated_veto_diagnostics(bar.active_domain_count, any_hard_veto_active=True)
        # active_domain_count == 2 is "corroborated" for veto-diagnostic purposes
        # regardless of the anchored-entry rule — this diagnostic is unchanged.
        assert diag_with_veto.uncorroborated_veto is False

    def test_d1_d4_only_while_already_in_crisis_does_not_force_exit_or_advance_countdown(self):
        """The 'already-in-CRISIS, drops to D1+D4-only' case Message[238]
        required coverage for: once in CRISIS via a genuine anchored entry,
        a later bar with only D1+D4 active (no D2/D3, but still
        active_domain_count==2 >= ENTRY_DOMAIN_THRESHOLD) must NOT force an
        exit or advance crisis_exit_count — the existing exit predicate's
        own `active_domain_count < ENTRY_DOMAIN_THRESHOLD` requirement
        already handles this with no additional code needed (verified here
        directly, not just by inspection)."""
        state = CrisisState()
        entry_bar = evaluate_crisis_bar(
            "2020-03-20",
            _config(vol=(True, True), credit=(True, True)),
        )
        state.advance(entry_bar, _clear_exit_ctx())
        assert state.in_crisis is True

        d1_d4_only_bar = evaluate_crisis_bar(
            "2020-03-21",
            _config(vol=(True, True), participation=(True, True)),
        )
        state.advance(d1_d4_only_bar, _clear_exit_ctx())
        assert state.in_crisis is True  # remains in CRISIS, no forced exit
        assert state.crisis_exit_count == 0  # does not advance the exit countdown

    def test_entry_is_immediate_no_ordinary_downgrade_delay(self):
        """A single bar with 2+ active domains enters CRISIS on that exact
        bar — no multi-bar confirmation required for entry (unlike exit's
        5-bar requirement)."""
        state = CrisisState()
        calm_bar = evaluate_crisis_bar("2020-03-19", _config())
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.in_crisis is False

        crisis_bar = evaluate_crisis_bar("2020-03-20", _config(vol=(True, True), credit=(True, True)))
        state.advance(crisis_bar, _clear_exit_ctx())
        assert state.in_crisis is True  # entered on the very next bar, immediately


# ---------------------------------------------------------------------------
# CrisisState.advance — exit
# ---------------------------------------------------------------------------

class TestCrisisExit:
    def _entered_state(self) -> CrisisState:
        state = CrisisState()
        bar = evaluate_crisis_bar("2020-03-20", _config(vol=(True, True), credit=(True, True)))
        state.advance(bar, _clear_exit_ctx())
        assert state.in_crisis is True
        return state

    def test_exit_requires_five_consecutive_clear_bars(self):
        state = self._entered_state()
        calm_bar = evaluate_crisis_bar("d", _config())
        for i in range(EXIT_CONFIRMATION_BARS - 1):
            state.advance(calm_bar, _clear_exit_ctx())
            assert state.in_crisis is True, f"exited too early at bar {i+1}"
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.in_crisis is False

    def test_exit_count_resets_on_any_single_failing_bar(self):
        """§9.3: 'five CONSECUTIVE valid bars' — a single bar that fails
        any exit sub-condition must reset the count to zero, not merely
        pause it."""
        state = self._entered_state()
        calm_bar = evaluate_crisis_bar("d", _config())
        veto_bar_ctx = _clear_exit_ctx(veto=True)  # fails sub-condition (a)

        state.advance(calm_bar, _clear_exit_ctx())
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.crisis_exit_count == 2

        state.advance(calm_bar, veto_bar_ctx)  # veto active this bar: resets
        assert state.crisis_exit_count == 0
        assert state.in_crisis is True

        # Now needs a full fresh 5-bar run.
        for _ in range(EXIT_CONFIRMATION_BARS - 1):
            state.advance(calm_bar, _clear_exit_ctx())
            assert state.in_crisis is True
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.in_crisis is False

    def test_renewed_two_domain_confirmation_resets_exit_count(self):
        """§9.3: 'Renewed two-domain confirmation resets the count.'"""
        state = self._entered_state()
        calm_bar = evaluate_crisis_bar("d", _config())
        crisis_bar = evaluate_crisis_bar("d2", _config(vol=(True, True), credit=(True, True)))

        state.advance(calm_bar, _clear_exit_ctx())
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.crisis_exit_count == 2

        state.advance(crisis_bar, _clear_exit_ctx())  # renewed 2-domain confirmation
        assert state.crisis_exit_count == 0
        assert state.in_crisis is True

    def test_full_recovery_then_relapse_then_recovery_cycle(self):
        """Golden-vector requirement (plan §6/design §14.1): 'recovery,
        relapse.' A gap found during Slice 12's conformance review: the
        existing exit-count-reset tests interrupt a countdown mid-way but
        never actually complete a FULL exit, verify the state is genuinely
        OUT of CRISIS, then re-enter (relapse) via a fresh 2-domain
        confirmation, then complete a SECOND full recovery — proving the
        state machine handles more than one full cycle correctly, not
        just a single entry/exit pair."""
        state = self._entered_state()
        calm_bar = evaluate_crisis_bar("d", _config())
        relapse_bar = evaluate_crisis_bar("d_relapse", _config(price=(True, True), participation=(True, True)))

        # First full recovery: 5 consecutive clear bars.
        for _ in range(EXIT_CONFIRMATION_BARS):
            state.advance(calm_bar, _clear_exit_ctx())
        assert state.in_crisis is False
        assert state.crisis_exit_count == 0

        # Relapse via a DIFFERENT domain pair than the original entry.
        state.advance(relapse_bar, _clear_exit_ctx())
        assert state.in_crisis is True
        assert state.crisis_exit_count == 0

        # Second full recovery must independently require its own full
        # 5-bar countdown — not shortcut by the first recovery having
        # already happened once.
        for _ in range(EXIT_CONFIRMATION_BARS - 1):
            state.advance(calm_bar, _clear_exit_ctx())
            assert state.in_crisis is True
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.in_crisis is False

    def test_condition_score_none_fails_exit_condition(self):
        state = self._entered_state()
        calm_bar = evaluate_crisis_bar("d", _config())
        unavailable_ctx = ConditionForExit(condition_score=None, any_hard_veto_active=False, neutral_entry_boundary_plus_buffer=0.4)
        state.advance(calm_bar, unavailable_ctx)
        assert state.crisis_exit_count == 0
        assert state.in_crisis is True

    def test_condition_exactly_at_boundary_does_not_satisfy_exit_strict_inequality(self):
        state = self._entered_state()
        calm_bar = evaluate_crisis_bar("d", _config())
        boundary_ctx = _clear_exit_ctx(condition_score=0.4, boundary=0.4)  # exactly equal, not above
        state.advance(calm_bar, boundary_ctx)
        assert state.crisis_exit_count == 0

    def test_one_active_domain_during_countdown_does_not_block_exit(self):
        """Exit requires FEWER THAN TWO active domains, not zero — one
        active domain during the countdown must still count toward exit
        (it's the 2-domain re-entry that resets, not any nonzero count)."""
        state = self._entered_state()
        one_domain_bar = evaluate_crisis_bar("d", _config(vol=(True, True)))
        for _ in range(EXIT_CONFIRMATION_BARS):
            state.advance(one_domain_bar, _clear_exit_ctx())
        assert state.in_crisis is False

    def test_not_in_crisis_advance_is_a_no_op_for_exit_bookkeeping(self):
        state = CrisisState()
        calm_bar = evaluate_crisis_bar("d", _config())
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.in_crisis is False
        assert state.crisis_exit_count == 0


# ---------------------------------------------------------------------------
# CrisisEvaluationContext + price_damage plumbing (Message[218]/[219]/[221])
# ---------------------------------------------------------------------------

class TestCrisisEvaluationContext:
    def test_evaluators_receive_a_context_not_a_bare_string(self):
        """Direct check that the Protocol shape really changed — an
        evaluator that inspects its argument's .as_of/.price_damage_
        components attributes (rather than treating it as a bare str)
        must work."""
        received = []

        def _capturing_evaluator(context: CrisisEvaluationContext):
            received.append(context)
            return CrisisDomainReading(valid=True, active=False)

        config = CrisisDomainConfig(
            volatility_term_structure=_capturing_evaluator,
            credit_stress=_const_domain(True, False),
            price_damage=_const_domain(True, False),
            participation_collapse=_const_domain(True, False),
        )
        components = PriceDamageComponents(benchmark_drawdown=0.42, return_shock_5d=0.1, return_shock_20d=0.2)
        evaluate_crisis_bar("2020-03-20", config, price_damage_components=components)
        assert len(received) == 1
        assert received[0].as_of == "2020-03-20"
        assert received[0].price_damage_components == components

    def test_price_damage_components_is_passed_identically_to_all_four_evaluators(self):
        """Every domain gets the SAME context object's
        price_damage_components, even domains that don't use it — the
        shared-context design's whole point (Message[218]) is uniform
        delivery, not per-domain routing."""
        seen_values = []

        def _make_capturing(name):
            def _ev(context: CrisisEvaluationContext):
                seen_values.append((name, context.price_damage_components))
                return CrisisDomainReading(valid=True, active=False)
            return _ev

        config = CrisisDomainConfig(
            volatility_term_structure=_make_capturing("vol"),
            credit_stress=_make_capturing("credit"),
            price_damage=_make_capturing("price"),
            participation_collapse=_make_capturing("participation"),
        )
        components = PriceDamageComponents(benchmark_drawdown=0.75, return_shock_5d=0.3, return_shock_20d=0.4)
        evaluate_crisis_bar("2020-03-20", config, price_damage_components=components)
        assert seen_values == [
            ("vol", components), ("credit", components), ("price", components), ("participation", components),
        ]

    def test_price_damage_components_defaults_to_none_for_backward_compatible_callers(self):
        """A caller not yet passing price_damage_components (e.g.
        synthetic-fixture tests exercising only D1/D2/D4) must not be
        forced to supply one — defaults to None, exactly the same
        "unavailable" signal a real missing Stability value would
        produce."""
        captured = {}

        def _capture(context: CrisisEvaluationContext):
            captured["price_damage_components"] = context.price_damage_components
            return CrisisDomainReading(valid=True, active=False)

        config = CrisisDomainConfig(
            volatility_term_structure=_capture,
            credit_stress=_const_domain(True, False),
            price_damage=_const_domain(True, False),
            participation_collapse=_const_domain(True, False),
        )
        evaluate_crisis_bar("2020-03-20", config)  # no price_damage_components kwarg
        assert captured["price_damage_components"] is None


# ---------------------------------------------------------------------------
# CrisisDomainReading.reason_codes (Message[220]/[221])
# ---------------------------------------------------------------------------

class TestReasonCodes:
    def test_defaults_to_empty_tuple_for_backward_compatibility(self):
        reading = CrisisDomainReading(valid=True, active=False)
        assert reading.reason_codes == ()

    def test_reason_codes_propagate_through_evaluate_crisis_bar(self):
        config = _config(
            price=(False, False),
        )
        # Override price_damage evaluator to attach a real reason code,
        # simulating the canonical_price_damage_unavailable case.
        config = CrisisDomainConfig(
            volatility_term_structure=_const_domain(True, False),
            credit_stress=_const_domain(True, False),
            price_damage=_const_domain(False, False, reason_codes=("canonical_price_damage_unavailable",)),
            participation_collapse=_const_domain(True, False),
        )
        bar = evaluate_crisis_bar("2020-03-20", config)
        assert bar.domain_status["price_damage"].reason_codes == ("canonical_price_damage_unavailable",)
        # Domains without an explicit reason keep the empty-tuple default.
        assert bar.domain_status["volatility_term_structure"].reason_codes == ()


# ---------------------------------------------------------------------------
# EXIT_BAR_REQUIRED_VALID_DOMAINS — the human-decided 4/4-valid exit gate
# (Message[220]/[221]/[223])
# ---------------------------------------------------------------------------

class TestExitBarValidityGate:
    def test_constant_is_four(self):
        """Direct regression check on the human's decided value — this
        constant must never silently drift."""
        assert EXIT_BAR_REQUIRED_VALID_DOMAINS == 4

    def _entered_state(self) -> CrisisState:
        state = CrisisState()
        bar = evaluate_crisis_bar("2020-03-20", _config(vol=(True, True), credit=(True, True)))
        state.advance(bar, _clear_exit_ctx())
        assert state.in_crisis is True
        return state

    def test_one_domain_unavailable_blocks_exit_confirmation(self):
        """The core regression test for the fix: a bar with
        active_domain_count < 2 (would have satisfied the OLD exit
        condition) but only 3 of 4 domains valid must NOT count toward
        exit — this is exactly the gap Message[220] identified (an
        unavailable domain is indistinguishable from an observed-calm
        one under the active-count check alone)."""
        state = self._entered_state()
        three_valid_bar = evaluate_crisis_bar(
            "d",
            CrisisDomainConfig(
                volatility_term_structure=_const_domain(True, False),
                credit_stress=_const_domain(True, False),
                price_damage=_const_domain(False, False, reason_codes=("canonical_price_damage_unavailable",)),
                participation_collapse=_const_domain(True, False),
            ),
        )
        assert three_valid_bar.active_domain_count == 0  # would have satisfied the OLD condition
        assert three_valid_bar.valid_domain_count == 3   # but fails the NEW 4/4 gate

        for _ in range(EXIT_CONFIRMATION_BARS + 2):  # well past 5, to prove it never accumulates
            state.advance(three_valid_bar, _clear_exit_ctx())
        assert state.crisis_exit_count == 0
        assert state.in_crisis is True  # never exits — evidence was unknown, not calm

    def test_four_valid_domains_required_exactly_not_fewer(self):
        """Explicit boundary check: 3/4 valid must fail, 4/4 valid must
        pass, on otherwise-identical bars."""
        state = self._entered_state()
        three_valid = CrisisDomainConfig(
            volatility_term_structure=_const_domain(True, False),
            credit_stress=_const_domain(True, False),
            price_damage=_const_domain(False, False),
            participation_collapse=_const_domain(True, False),
        )
        bar_3of4 = evaluate_crisis_bar("d", three_valid)
        state.advance(bar_3of4, _clear_exit_ctx())
        assert state.crisis_exit_count == 0

        four_valid_calm_bar = evaluate_crisis_bar("d2", _config())  # all 4 valid, all calm
        for _ in range(EXIT_CONFIRMATION_BARS):
            state.advance(four_valid_calm_bar, _clear_exit_ctx())
        assert state.in_crisis is False

    def test_unavailable_domain_resets_an_in_progress_countdown(self):
        """A domain going unavailable partway through an otherwise-valid
        5-bar countdown must reset the count to zero (same "any failing
        bar resets, does not merely pause" rule as every other exit
        sub-condition), not merely fail to advance it."""
        state = self._entered_state()
        calm_bar = evaluate_crisis_bar("d", _config())
        gap_bar = evaluate_crisis_bar(
            "d_gap",
            CrisisDomainConfig(
                volatility_term_structure=_const_domain(True, False),
                credit_stress=_const_domain(True, False),
                price_damage=_const_domain(False, False),
                participation_collapse=_const_domain(True, False),
            ),
        )

        state.advance(calm_bar, _clear_exit_ctx())
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.crisis_exit_count == 2

        state.advance(gap_bar, _clear_exit_ctx())  # one domain unavailable this bar
        assert state.crisis_exit_count == 0
        assert state.in_crisis is True

        # Must need a full fresh 5-bar run afterward.
        for _ in range(EXIT_CONFIRMATION_BARS - 1):
            state.advance(calm_bar, _clear_exit_ctx())
            assert state.in_crisis is True
        state.advance(calm_bar, _clear_exit_ctx())
        assert state.in_crisis is False


# ---------------------------------------------------------------------------
# Uncorroborated veto diagnostics (§9.2)
# ---------------------------------------------------------------------------

class TestUncorroboratedVetoDiagnostics:
    def test_zero_active_domains_with_veto(self):
        d = compute_uncorroborated_veto_diagnostics(active_domain_count=0, any_hard_veto_active=True)
        assert d.uncorroborated_veto is True
        assert d.crisis_watch is False

    def test_one_active_domain_with_veto(self):
        d = compute_uncorroborated_veto_diagnostics(active_domain_count=1, any_hard_veto_active=True)
        assert d.uncorroborated_veto is True
        assert d.crisis_watch is True

    def test_two_active_domains_with_veto_is_corroborated_not_uncorroborated(self):
        d = compute_uncorroborated_veto_diagnostics(active_domain_count=2, any_hard_veto_active=True)
        assert d.uncorroborated_veto is False
        assert d.crisis_watch is False

    def test_no_veto_active_gives_both_false_regardless_of_domain_count(self):
        for count in (0, 1, 2, 3, 4):
            d = compute_uncorroborated_veto_diagnostics(active_domain_count=count, any_hard_veto_active=False)
            assert d.uncorroborated_veto is False
            assert d.crisis_watch is False


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_identical_bar_sequence_produces_identical_final_state(self):
        bars_config = [
            _config(),
            _config(vol=(True, True), credit=(True, True)),
            _config(),
            _config(),
        ]
        state1 = CrisisState()
        state2 = CrisisState()
        for i, cfg in enumerate(bars_config):
            bar = evaluate_crisis_bar(f"d{i}", cfg)
            state1.advance(bar, _clear_exit_ctx())
            state2.advance(bar, _clear_exit_ctx())
        assert state1.in_crisis == state2.in_crisis
        assert state1.crisis_exit_count == state2.crisis_exit_count
