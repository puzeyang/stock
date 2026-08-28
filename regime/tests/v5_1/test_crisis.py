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
    CrisisState,
    ConditionForExit,
    evaluate_crisis_bar,
    compute_uncorroborated_veto_diagnostics,
    EXIT_CONFIRMATION_BARS,
    ENTRY_DOMAIN_THRESHOLD,
)


def _const_domain(valid: bool, active: bool):
    def _ev(as_of):
        return CrisisDomainReading(valid=valid, active=active)
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

    def test_every_pair_of_domains_enters_crisis(self):
        """Golden-vector requirement: 'Every CRISIS domain... pair.' All
        C(4,2)=6 domain-pair combinations, not just the one (vol+credit)
        pair the existing tests happen to use."""
        import itertools
        domain_names = ["vol", "credit", "price", "participation"]
        for a, b in itertools.combinations(domain_names, 2):
            kwargs = {a: (True, True), b: (True, True)}
            state = CrisisState()
            bar = evaluate_crisis_bar("2020-03-20", _config(**kwargs))
            state.advance(bar, _clear_exit_ctx())
            assert state.in_crisis is True, f"domain pair {a}+{b} did not enter CRISIS"

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
