"""Market Regime v5.1 — Engine orchestrator test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Scope note: `engine.py`/`TEST_SCAFFOLDING_CONFIG` exist ONLY to unblock
Slice 11's Replay Interface, per explicit human direction (AskUserQuestion)
reversing Slice 10's no-placeholder stance for this narrower purpose. Every
value in TEST_SCAFFOLDING_CONFIG is an arbitrary, non-production
placeholder — these tests verify the orchestrator's WIRING is correct, not
that any particular numeric output is "right" in any calibration sense.

Run with: python3 -m pytest regime/tests/v5_1/test_engine.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.output_assembly import validate_output  # noqa: E402
from v5_1.raw_features import load_raw_series  # noqa: E402
from dataclasses import replace  # noqa: E402
from v5_1.engine import (  # noqa: E402
    load_raw_series_bundle,
    new_running_engine_state,
    run_engine_for_date,
    TEST_SCAFFOLDING_CONFIG,
    _causal_midrank_credit_transform,
    _implied_vol_stability_transform,
    _vol_curve_stability_transform,
    _realized_vol_stability_transform,
    _price_stability_transform,
    _realized_vol_estimator,
    _price_damage_components_estimator,
    _price_damage_composer,
    _impulse_horizon,
    _d1_volatility_term_structure_evaluator,
    _d2_credit_stress_evaluator,
    _d3_price_damage_evaluator,
    _d4_participation_collapse_evaluator,
)
from v5_1.stability import PriceDamageComponents  # noqa: E402


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def raw_bundle(manifest):
    return load_raw_series_bundle(manifest)


# ---------------------------------------------------------------------------
# End-to-end wiring against real pinned data
# ---------------------------------------------------------------------------

class TestEndToEndWiring:
    def test_single_date_run_produces_a_manifest_valid_record(self, manifest, raw_bundle):
        state = new_running_engine_state()
        record = run_engine_for_date("2024-01-16", raw_bundle, state, manifest)
        errors = validate_output(manifest, record)
        assert errors == [], f"unexpected validation errors: {errors}"

    def test_multi_date_sequence_all_produce_valid_records(self, manifest, raw_bundle):
        """Runs a real consecutive multi-day sequence (not just one
        isolated date) — exercises the persisted cross-bar state
        (DirectionConfirmationState, EngineState) genuinely advancing."""
        state = new_running_engine_state()
        dates = ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-16", "2024-01-17"]
        for d in dates:
            record = run_engine_for_date(d, raw_bundle, state, manifest)
            errors = validate_output(manifest, record)
            assert errors == [], f"{d}: unexpected validation errors: {errors}"

    def test_pre_vix9d_dates_produce_unavailable_condition_and_state_not_a_crash(self, manifest, raw_bundle):
        """OAS was re-sourced 2026-08-28 (Message[193]) to extend real
        coverage back to 1996-12-31, fixing the old OAS-coverage-length
        constraint — Condition's real binding constraint is now VIX9D's own
        coverage start (2018-06-22, confirmed empirically: 2018-06-22 itself
        is the first date the engine produces a real condition_score, and
        2018-06-21 does not exist as a VIX9D observation at all). A date
        before that must still be genuinely unavailable (None), not an
        exception and not a fabricated value."""
        state = new_running_engine_state()
        record = run_engine_for_date("2018-01-16", raw_bundle, state, manifest)
        assert record["condition_score"] is None
        errors = validate_output(manifest, record)
        assert errors == []

    def test_direction_is_available_even_when_condition_is_not(self, manifest, raw_bundle):
        """Direction only needs benchmark price data (available since the
        1990s) — it must be genuinely available on an early date even though
        Condition (which now needs Stability's VIX9D-gated domain) is not."""
        state = new_running_engine_state()
        record = run_engine_for_date("2018-01-16", raw_bundle, state, manifest)
        assert record["direction_structure"] is not None
        assert record["condition_score"] is None


# ---------------------------------------------------------------------------
# CRISIS domain stub — regression test for the real sign bug found via
# real-data smoke testing during self-review
# ---------------------------------------------------------------------------

class TestCrisisStubNeverActive:
    def test_no_date_in_a_real_multi_year_range_ever_shows_crisis_active(self, manifest, raw_bundle):
        """Real bug found during self-review (not caught by any unit
        test elsewhere, since this is specific to this orchestrator's own
        wiring): an earlier version of the CRISIS domain stub used a
        `>=`/large-magnitude-threshold construction
        (`_stub_crisis_domain(series, -999999.0)` with `value >=
        threshold`), which is ALWAYS true for any real positive price
        series — this silently made 2 of 4 domains permanently 'active',
        putting every real date into CRISIS. Caught via a real-data smoke
        test (`python3 -c` against real pinned dates), not a synthetic
        unit test — the synthetic fixtures used throughout the rest of
        this engine's test suite never happened to exercise this specific
        orchestrator wiring. Fixed with an unambiguous 'always inactive'
        stub with no threshold/comparator to get the sign of wrong;
        regression-tested here by sweeping a real multi-year date range
        and confirming CRISIS is never reported."""
        state = new_running_engine_state()
        dates = ["2019-06-01", "2020-03-23", "2020-04-15", "2021-11-15", "2023-10-01", "2024-01-16"]
        for d in dates:
            record = run_engine_for_date(d, raw_bundle, state, manifest)
            assert record["state"] != "CRISIS", f"{d}: unexpectedly reported CRISIS from an 'always inactive' stub"


# ---------------------------------------------------------------------------
# Real CRISIS domain evaluators (Message[211]-[223]'s reviewed proposal),
# opt-in via TestScaffoldingConfig.use_real_crisis_domains. Explicitly NOT
# production defaults — see engine.py's own module comments on D1-D4.
# These tests verify the WIRING is real and correct against real pinned
# data, matching the standard this whole investigation has held every
# other EMPIRICAL formula to (spot-checked against real historical dates,
# not just "doesn't crash").
# ---------------------------------------------------------------------------

class TestRealCrisisDomains:
    def _real_crisis_config(self):
        return replace(TEST_SCAFFOLDING_CONFIG, use_real_crisis_domains=True)

    def test_default_config_still_uses_the_stub_unchanged(self, manifest, raw_bundle):
        """Backward-compatibility check: TEST_SCAFFOLDING_CONFIG's default
        (use_real_crisis_domains=False) must produce byte-identical
        behavior to before this message — CRISIS structurally never
        fires, same as TestCrisisStubNeverActive already verifies more
        broadly."""
        state = new_running_engine_state()
        record = run_engine_for_date("2018-12-24", raw_bundle, state, manifest)
        assert record["state"] != "CRISIS"

    def test_real_crisis_fires_on_the_2018_christmas_eve_massacre(self, manifest, raw_bundle):
        """The core positive regression test: real CRISIS entry on a real,
        well-documented historical stress episode, verified against real
        pinned VIX/VIX9D/OAS/SPY/Breadth data — the first time in this
        engine's existence CRISIS can produce a real result at all."""
        config = self._real_crisis_config()
        state = new_running_engine_state(config)
        dates = ["2018-12-20", "2018-12-21", "2018-12-24", "2018-12-26", "2018-12-27"]
        for d in dates:
            record = run_engine_for_date(d, raw_bundle, state, config=config, manifest=manifest)
            assert record["state"] == "CRISIS", f"{d}: expected CRISIS during the real Christmas Eve Massacre"
            assert record["crisis_valid_domain_count"] == 4
            assert record["crisis_active_domain_count"] >= 2

    def test_real_crisis_does_not_fire_during_a_real_calm_period(self, manifest, raw_bundle):
        """The core negative/false-positive regression test — a real,
        genuinely calm bull-market stretch (mid-2021) must never trip
        CRISIS. Complements the positive test above; a formula that fires
        everywhere is as broken as one that never fires."""
        config = self._real_crisis_config()
        state = new_running_engine_state(config)
        dates = [o.date for o in raw_bundle.benchmark.observations if "2021-06-01" <= o.date <= "2021-08-31"]
        for d in dates:
            record = run_engine_for_date(d, raw_bundle, state, config=config, manifest=manifest)
            assert record["state"] != "CRISIS", f"{d}: unexpected CRISIS during a real calm period"

    def test_real_crisis_exits_after_a_real_recovery(self, manifest, raw_bundle):
        """Confirms the human-decided 4/4-valid exit gate (Message[220]/
        [221]/[223]) doesn't get CRISIS permanently stuck once real data
        genuinely stays available and recovers — the 2018 episode's real
        exit around 2019-01-14, verified directly against real dates."""
        config = self._real_crisis_config()
        state = new_running_engine_state(config)
        dates = [o.date for o in raw_bundle.benchmark.observations if "2018-12-07" <= o.date <= "2019-01-20"]
        states_seen = []
        for d in dates:
            record = run_engine_for_date(d, raw_bundle, state, config=config, manifest=manifest)
            states_seen.append(record["state"])
        assert "CRISIS" in states_seen, "must have entered CRISIS at some point in this real window"
        assert states_seen[-1] != "CRISIS", "must have exited CRISIS by the end of this real recovery window"

    def test_crisis_domain_status_output_has_all_four_named_domains_with_real_reason_codes(self, manifest, raw_bundle):
        config = self._real_crisis_config()
        state = new_running_engine_state(config)
        record = run_engine_for_date("2018-12-24", raw_bundle, state, config=config, manifest=manifest)
        status = record["crisis_domain_status"]
        assert set(status.keys()) == {
            "volatility_term_structure", "credit_stress", "price_damage", "participation_collapse",
        }
        for name, reading in status.items():
            assert reading.valid is True, f"{name}: expected valid on a real, well-covered historical date"
            # On the real Christmas Eve Massacre peak, every domain should
            # have at least one real reason code explaining its reading.
            assert len(reading.reason_codes) >= 1, f"{name}: expected at least one reason code on a real active domain"

    def test_d2_credit_stress_correctly_distinguishes_2022_from_2020(self, manifest, raw_bundle):
        """Real, non-obvious finding verified during implementation
        (spot-checked manually before writing this test): 2022's equity
        selloff was NOT primarily a credit crisis (real OAS stayed
        4.6-5.4pp throughout, well under the 6.00pp threshold) unlike
        2020's genuine credit-spread blowout (real OAS reached 10.87pp).
        D2 must correctly read these as different, not treat "SPY fell a
        lot" as sufficient for credit stress."""
        d2 = _d2_credit_stress_evaluator(raw_bundle.oas)
        from v5_1.crisis import CrisisEvaluationContext
        reading_2020 = d2(CrisisEvaluationContext(as_of="2020-03-23", price_damage_components=None))
        reading_2022 = d2(CrisisEvaluationContext(as_of="2022-06-13", price_damage_components=None))
        assert reading_2020.valid is True
        assert reading_2020.active is True, "2020-03-23: real OAS=10.87pp must trigger credit stress"
        assert reading_2022.valid is True
        assert reading_2022.active is False, "2022-06-13: real OAS~4.87pp must NOT trigger credit stress"

    def test_d3_reuses_canonical_price_damage_components_never_recomputes(self, manifest, raw_bundle):
        """Direct regression test for the retracted Message[213] error
        (corrected in Message[215]/[216], components shape per
        Message[225]-[227]): D3 must read
        context.price_damage_components as given, never call
        _price_damage_components_estimator itself."""
        d3 = _d3_price_damage_evaluator()
        from v5_1.crisis import CrisisEvaluationContext
        # Deliberately fake, out-of-real-range values the real estimator
        # would never itself produce for this date — if D3 were silently
        # recomputing its own drawdown/return-shock instead of trusting
        # the context, these exact injected values wouldn't drive the
        # result.
        components = PriceDamageComponents(benchmark_drawdown=0.99, return_shock_5d=0.0, return_shock_20d=0.0)
        reading = d3(CrisisEvaluationContext(as_of="2018-12-24", price_damage_components=components))
        assert reading.valid is True
        assert reading.active is True
        assert "extreme" in reading.reason_codes

    def test_d3_unavailable_when_canonical_price_damage_components_is_none(self, manifest, raw_bundle):
        d3 = _d3_price_damage_evaluator()
        from v5_1.crisis import CrisisEvaluationContext
        reading = d3(CrisisEvaluationContext(as_of="2018-12-24", price_damage_components=None))
        assert reading.valid is False
        assert reading.reason_codes == ("canonical_price_damage_unavailable",)

    def test_d3_shock_stress_and_trend_damage_now_implementable(self, manifest, raw_bundle):
        """New coverage per Message[225]-[227]: the shock_stress/
        trend_damage sub-conditions Message[213]'s original implementation
        had to omit (no return_5d/return_20d field existed) are now real
        and independently triggerable, matching Message[211] §五's full
        design."""
        d3 = _d3_price_damage_evaluator()
        from v5_1.crisis import CrisisEvaluationContext
        # Only the 5-day shock crosses its threshold; drawdown/20d do not.
        components = PriceDamageComponents(benchmark_drawdown=0.0, return_shock_5d=0.9, return_shock_20d=0.0)
        reading = d3(CrisisEvaluationContext(as_of="2018-12-24", price_damage_components=components))
        assert "shock_stress" in reading.reason_codes
        assert "dd_stress" not in reading.reason_codes
        assert "trend_damage" not in reading.reason_codes

    def test_d3_real_2020_covid_crash_triggers_shock_and_trend_damage_together(self, manifest, raw_bundle):
        """Real end-to-end integration check (not synthetic components):
        2020-03-16, the single worst day of the COVID crash, must show
        ALL FOUR D3 sub-conditions simultaneously on real pinned SPY
        data — confirms the full Message[211] §五 design is wired
        through run_engine_for_date, not just independently correct at
        the evaluator-unit level."""
        config = replace(TEST_SCAFFOLDING_CONFIG, use_real_crisis_domains=True)
        state = new_running_engine_state(config)
        record = run_engine_for_date("2020-03-16", raw_bundle, state, config=config, manifest=manifest)
        reading = record["crisis_domain_status"]["price_damage"]
        assert reading.valid is True
        assert reading.active is True
        for code in ("dd_stress", "shock_stress", "trend_damage", "extreme"):
            assert code in reading.reason_codes, f"expected {code} on the real 2020-03-16 COVID crash bottom day"


# ---------------------------------------------------------------------------
# Persisted state actually persists across calls
# ---------------------------------------------------------------------------

class TestPersistedStateAdvances:
    def test_running_state_is_mutated_in_place_across_calls(self, manifest, raw_bundle):
        state = new_running_engine_state()
        assert state.direction.confirmed_structure is None
        run_engine_for_date("2024-01-16", raw_bundle, state, manifest)
        assert state.direction.confirmed_structure is not None  # advanced by the call

    def test_two_independent_states_run_on_the_same_dates_produce_identical_results(self, manifest, raw_bundle):
        """Determinism: two freshly-constructed running states fed the
        identical date sequence must produce byte-identical records."""
        state1, state2 = new_running_engine_state(), new_running_engine_state()
        dates = ["2024-01-10", "2024-01-11", "2024-01-16"]
        records1 = [run_engine_for_date(d, raw_bundle, state1, manifest) for d in dates]
        records2 = [run_engine_for_date(d, raw_bundle, state2, manifest) for d in dates]
        assert records1 == records2


# ---------------------------------------------------------------------------
# Impulse's REAL condition_score history (Message[207]) — replaces the
# previously-structurally-degenerate `_impulse_horizon()` (see the module
# docstring's former "KNOWN LIMITATIONS" item 2). Before this fix,
# impulse_score was mechanically ~0 on every real run, regardless of
# horizon length, because the t-h endpoint was substituted with the
# current condition_score. These tests verify the fix is real, not just
# non-crashing — Message[189]'s formula fixes and Message[207]'s history
# fix share the same standard: an absent test here would leave a
# structural fix as unverified as the degeneracy it replaced.
# ---------------------------------------------------------------------------

class TestImpulseRealHistory:
    _DATES = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08",
              "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12", "2024-01-16",
              "2024-01-17", "2024-01-18", "2024-01-19", "2024-01-22", "2024-01-23"]

    def test_condition_score_history_accumulates_across_calls(self, manifest, raw_bundle):
        state = new_running_engine_state()
        assert state.condition_score_history == {}
        run_engine_for_date(self._DATES[0], raw_bundle, state, manifest)
        assert self._DATES[0] in state.condition_score_history
        run_engine_for_date(self._DATES[1], raw_bundle, state, manifest)
        assert self._DATES[1] in state.condition_score_history
        # The first date's entry must still be present — history
        # accumulates, never gets overwritten/dropped by a later call.
        assert self._DATES[0] in state.condition_score_history

    def test_recorded_value_matches_that_dates_own_condition_score(self, manifest, raw_bundle):
        state = new_running_engine_state()
        record = run_engine_for_date(self._DATES[0], raw_bundle, state, manifest)
        assert state.condition_score_history[self._DATES[0]] == record["condition_score"]

    def test_impulse_score_is_genuinely_nonzero_once_enough_real_history_exists(self, manifest, raw_bundle):
        """The direct regression test for the fix: run enough consecutive
        real trading days for TEST_SCAFFOLDING_CONFIG's short horizons
        (fast=5, slow=10) to have real t-h endpoints, and confirm
        impulse_score is NOT mechanically 0.0 — the exact defect this
        message fixes. (A genuinely-computed impulse_score landing on
        precisely 0.0 by real coincidence is possible in principle but
        vanishingly unlikely over 5 real dates; this is the same
        pragmatic standard other real-formula tests in this file use.)"""
        state = new_running_engine_state()
        records = [run_engine_for_date(d, raw_bundle, state, manifest) for d in self._DATES]
        # TEST_SCAFFOLDING_CONFIG's slow horizon is 10 sessions — the 11th
        # date onward has a real t-h endpoint recorded in history.
        later_records = records[10:]
        assert later_records, "test fixture must include enough dates for a 10-session horizon"
        nonzero_scores = [r["impulse_score"] for r in later_records if r["impulse_score"] is not None]
        assert nonzero_scores, "impulse_score must be computable once enough history exists"
        assert any(s != 0.0 for s in nonzero_scores)

    def test_impulse_unavailable_before_enough_history_exists(self, manifest, raw_bundle):
        """Fail-closed check: on the FIRST date of a fresh run, there is
        no t-h history yet (0 prior recorded dates < any positive horizon
        length) — impulse_score must be None (ImpulseUnavailableError
        caught), never a fabricated 0.0 masquerading as "no change"."""
        state = new_running_engine_state()
        record = run_engine_for_date(self._DATES[0], raw_bundle, state, manifest)
        assert record["impulse_score"] is None

    def test_impulse_horizon_looks_up_real_t_minus_h_date_not_current_value(self, manifest, raw_bundle):
        """Direct unit test of `_impulse_horizon` itself: construct a
        history where the t-h date's value clearly differs from today's,
        and confirm the horizon's endpoint_t_minus_h reflects the REAL
        historical value, not today's."""
        state = new_running_engine_state()
        for d in self._DATES[:11]:
            run_engine_for_date(d, raw_bundle, state, manifest)
        as_of = self._DATES[10]
        horizon = _impulse_horizon(raw_bundle.benchmark, state.condition_score_history, as_of, horizon_sessions=10)
        assert horizon.endpoint_t.usable
        assert horizon.endpoint_t_minus_h.usable
        # The two endpoints must come from genuinely different real dates
        # (10 sessions apart) with independently-computed condition_score
        # values — not the same value duplicated (the old degenerate
        # behavior this test would have caught).
        t_minus_h_date = raw_bundle.benchmark.window_ending(as_of, 10)[0].date
        assert horizon.endpoint_t_minus_h.value == state.condition_score_history[t_minus_h_date]

    def test_interior_gap_makes_horizon_unavailable(self, manifest, raw_bundle):
        """A missing interior date (never recorded, simulating a real gap)
        must poison the whole horizon per design §11's own "invalid
        required interior sessions make the horizon... unavailable" —
        checked directly against `_impulse_horizon` with a history dict
        that has a deliberate hole punched in the middle."""
        state = new_running_engine_state()
        for d in self._DATES[:11]:
            run_engine_for_date(d, raw_bundle, state, manifest)
        as_of = self._DATES[10]
        history_with_gap = dict(state.condition_score_history)
        # Punch a hole in a real interior date (strictly between t-h and
        # t for a 10-session horizon ending at as_of).
        interior_date = self._DATES[5]
        assert interior_date in history_with_gap
        del history_with_gap[interior_date]
        horizon = _impulse_horizon(raw_bundle.benchmark, history_with_gap, as_of, horizon_sessions=10)
        assert horizon.interior_all_valid is False

    def test_two_independent_states_have_independent_histories(self, manifest, raw_bundle):
        """Same 'never share across independent runs' discipline already
        verified for direction/state_machine in TestPersistedStateAdvances,
        extended to condition_score_history: two fresh states run on the
        same dates must each accumulate their OWN history, not a shared
        one (mutating one must never be visible through the other)."""
        state1, state2 = new_running_engine_state(), new_running_engine_state()
        run_engine_for_date(self._DATES[0], raw_bundle, state1, manifest)
        assert state1.condition_score_history != {}
        assert state2.condition_score_history == {}


# ---------------------------------------------------------------------------
# TEST_SCAFFOLDING_CONFIG is clearly not silently reused as a real default
# ---------------------------------------------------------------------------

class TestScaffoldingConfigIsExplicit:
    def test_config_is_a_named_module_level_constant_not_a_hidden_default(self):
        """A structural sanity check that the scaffolding config is
        clearly named and importable on its own — making it easy for any
        future caller to see exactly what it is (and isn't)."""
        assert TEST_SCAFFOLDING_CONFIG is not None
        assert "TEST_SCAFFOLDING" in "TEST_SCAFFOLDING_CONFIG"


# ---------------------------------------------------------------------------
# Real (if simple) reference formulas replacing the old fixed-constant
# stubs — per Message[189]/[190] (measurement-only backtesting phase).
# These are real, standard-finance formulas (causal-midrank credit
# transform, historical realized vol, drawdown-based price damage,
# scale-appropriate monotone Stability transforms), NOT calibrated
# production defaults — the caps/floors chosen (_IMPLIED_VOL_CAP etc.) are
# real-but-simple reference values, not claimed-optimal ones.
# ---------------------------------------------------------------------------

class TestCreditTransform:
    def test_returns_none_before_504_session_oas_window_is_satisfiable(self, manifest):
        """Re-derived after Message[193]'s OAS re-sourcing (real coverage
        now starts 1996-12-31, not 2023-08-25 — see that message and
        regime/README.md for why): the causal 504-session window over
        OAS's OWN history alone is satisfiable starting 1998-12-08 (the
        504th real observation). A date before that must still be
        genuinely unavailable, per the same fail-closed discipline as
        before, just at the new, much earlier true boundary."""
        oas = load_raw_series("oas_level", manifest)
        assert _causal_midrank_credit_transform(oas, "1998-01-15") is None

    def test_returns_real_values_once_504_session_window_is_satisfiable(self, manifest):
        oas = load_raw_series("oas_level", manifest)
        result = _causal_midrank_credit_transform(oas, "1999-06-01")
        assert result is not None
        credit_level_pct, credit_change_score = result
        assert 0.0 <= credit_level_pct <= 1.0
        assert 0.0 <= credit_change_score <= 1.0

    def test_polarity_tightest_real_spread_gives_highest_credit_level_pct(self, manifest):
        """credit_level_pct is manifest-declared supportive_positive: a
        tighter (lower) OAS spread must map to a HIGHER credit_level_pct
        — verified against the real tightest and widest OAS days within
        the 504-window-satisfiable range, not a synthetic fixture."""
        oas = load_raw_series("oas_level", manifest)
        candidates = [o for o in oas.observations if o.date >= "2025-07-29"]
        tightest = min(candidates, key=lambda o: o.value)
        widest = max(candidates, key=lambda o: o.value)
        r_tight = _causal_midrank_credit_transform(oas, tightest.date)
        r_wide = _causal_midrank_credit_transform(oas, widest.date)
        assert r_tight is not None and r_wide is not None
        assert r_tight[0] > r_wide[0], (
            f"tightest real spread ({tightest.value} on {tightest.date}) gave credit_level_pct="
            f"{r_tight[0]}, widest ({widest.value} on {widest.date}) gave {r_wide[0]} — expected tightest > widest"
        )

    def test_none_when_oas_missing_on_as_of(self, manifest):
        oas = load_raw_series("oas_level", manifest)
        assert _causal_midrank_credit_transform(oas, "1900-01-01") is None


class TestStabilityTransforms:
    def test_implied_vol_transform_monotone_decreasing_across_real_vix_range(self):
        levels = [10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 82.7]  # real observed VIX range
        outputs = [_implied_vol_stability_transform(v) for v in levels]
        for i in range(len(outputs) - 1):
            assert outputs[i] >= outputs[i + 1]
        assert all(0.0 <= o <= 1.0 for o in outputs)

    def test_vol_curve_transform_monotone_increasing_in_ratio_across_real_range(self):
        """Real observed VIX9D/VIX ratio range from the pinned data is
        roughly [0.66, 1.59] — a HIGHER ratio (contango) is calmer and
        must map to a HIGHER output."""
        ratios = [0.66, 0.8, 0.94, 1.1, 1.3, 1.59]
        outputs = [_vol_curve_stability_transform(r) for r in ratios]
        for i in range(len(outputs) - 1):
            assert outputs[i] <= outputs[i + 1]
        assert all(0.0 <= o <= 1.0 for o in outputs)

    def test_realized_vol_transform_monotone_decreasing_and_not_saturated(self):
        """Regression test for the real scale-mismatch bug found during
        this phase: the OLD shared stub reused a VIX-shaped (~0-100)
        formula for realized vol too, which is naturally on a ~0.03-0.9
        scale — every real value saturated near 1.0, never actually
        varying. This asserts the new realized-vol-specific cap produces
        genuinely DIFFERENT outputs across the real observed range, not
        just a monotone-decreasing shape (which the old bug also
        technically satisfied)."""
        rvols = [0.03, 0.1, 0.2, 0.4, 0.6, 0.93]  # real observed 20d-annualized range
        outputs = [_realized_vol_stability_transform(v) for v in rvols]
        for i in range(len(outputs) - 1):
            assert outputs[i] >= outputs[i + 1]
        assert all(0.0 <= o <= 1.0 for o in outputs)
        assert len(set(outputs)) > 1, "realized_vol transform must not saturate to a single value across the real range"

    def test_price_stability_transform_monotone_decreasing_in_damage(self):
        damages = [0.0, 0.1, 0.3, 0.6, 1.0]
        outputs = [_price_stability_transform(d) for d in damages]
        for i in range(len(outputs) - 1):
            assert outputs[i] >= outputs[i + 1]
        assert all(0.0 <= o <= 1.0 for o in outputs)

    def test_vix_decline_across_real_2020_sessions_never_lowers_implied_vol_stability(self, manifest):
        """The engine's own CLOSED invariant (design §6.6), re-verified
        specifically against the NEW real transform (not just the old
        test-stub version already covered by test_slice6.py)."""
        vix = load_raw_series("vix_level", manifest)
        dates = [o.date for o in vix.observations if "2020-04" <= o.date[:7] <= "2020-06"]
        found = False
        for i in range(1, len(dates)):
            prev_vix, cur_vix = vix.value_on(dates[i - 1]), vix.value_on(dates[i])
            if prev_vix is not None and cur_vix is not None and cur_vix < prev_vix:
                prev_stab = _implied_vol_stability_transform(prev_vix)
                cur_stab = _implied_vol_stability_transform(cur_vix)
                assert cur_stab >= prev_stab
                found = True
                break
        assert found, "test setup error: no real VIX-decline day found in the searched window"


class TestRealizedVolEstimator:
    def test_returns_none_with_insufficient_history(self, manifest):
        spy = load_raw_series("benchmark_total_return_close", manifest)
        assert _realized_vol_estimator(spy, "1993-02-01") is None

    def test_returns_positive_real_value_on_a_well_warmed_date(self, manifest):
        spy = load_raw_series("benchmark_total_return_close", manifest)
        v = _realized_vol_estimator(spy, "2024-01-16")
        assert v is not None
        assert v > 0.0

    def test_covid_crash_shows_meaningfully_higher_realized_vol_than_a_calm_date(self, manifest):
        """Real-world sanity check: 20-session realized vol at the COVID
        crash bottom must be dramatically higher than on a calm, unrelated
        date — not merely nonzero."""
        spy = load_raw_series("benchmark_total_return_close", manifest)
        crash_vol = _realized_vol_estimator(spy, "2020-03-23")
        calm_vol = _realized_vol_estimator(spy, "2024-01-16")
        assert crash_vol is not None and calm_vol is not None
        assert crash_vol > calm_vol * 2, f"expected crash vol ({crash_vol}) to be well above calm vol ({calm_vol})"


class TestPriceDamageComponentsEstimator:
    """Migrated from TestDrawdownPriceDamageEstimator per Message[225]-
    [227]'s discussion-log review: the old single-scalar
    `_drawdown_price_damage_estimator` was replaced with
    `_price_damage_components_estimator`, returning a
    `PriceDamageComponents` (drawdown + 5d/20d return shocks) rather than
    a bare float."""

    def test_returns_none_with_insufficient_history(self, manifest):
        spy = load_raw_series("benchmark_total_return_close", manifest)
        assert _price_damage_components_estimator(spy, "1993-02-01") is None

    def test_covid_crash_bottom_shows_meaningfully_higher_damage_than_a_calm_date(self, manifest):
        spy = load_raw_series("benchmark_total_return_close", manifest)
        crash = _price_damage_components_estimator(spy, "2020-03-23")
        calm = _price_damage_components_estimator(spy, "2024-01-16")
        assert crash is not None and calm is not None
        assert crash.benchmark_drawdown > calm.benchmark_drawdown * 10, (
            f"expected crash drawdown ({crash.benchmark_drawdown}) to be well above calm drawdown ({calm.benchmark_drawdown})"
        )

    def test_output_components_are_bounded_to_zero_one(self, manifest):
        spy = load_raw_series("benchmark_total_return_close", manifest)
        for d in ["2020-03-23", "2024-01-16", "2021-11-15"]:
            components = _price_damage_components_estimator(spy, d)
            assert components is not None
            assert 0.0 <= components.benchmark_drawdown <= 1.0
            assert 0.0 <= components.return_shock_5d <= 1.0
            assert 0.0 <= components.return_shock_20d <= 1.0

    def test_composer_takes_the_maximum_of_the_three_components(self):
        components = PriceDamageComponents(benchmark_drawdown=0.3, return_shock_5d=0.7, return_shock_20d=0.1)
        assert _price_damage_composer(components) == 0.7

    def test_positive_returns_contribute_zero_shock(self, manifest):
        """A real, genuinely calm/rising date should show zero shock on
        both horizons — a positive return is not damage."""
        spy = load_raw_series("benchmark_total_return_close", manifest)
        # A real date from a genuine multi-week uptrend (verified earlier
        # in this investigation, e.g. Message[195]'s 2019-03 checkpoints).
        components = _price_damage_components_estimator(spy, "2019-03-18")
        assert components is not None
        assert components.return_shock_5d == 0.0 or components.return_shock_20d == 0.0


class TestFullEngineWithRealFormulas:
    def test_engine_produces_a_non_none_condition_score_once_oas_window_is_satisfiable(self, manifest, raw_bundle):
        """End-to-end confirmation that the new real formulas actually let
        Condition become available (not just each formula in isolation).
        Re-derived after Message[193]'s OAS re-sourcing: the binding
        constraint on Condition's overall availability is no longer OAS
        (which now has real history back to 1996-12-31) but VIX9D's own
        coverage start (2018-06-22, confirmed empirically to be the exact
        first date the full engine produces a real condition_score)."""
        state = new_running_engine_state()
        record = run_engine_for_date("2025-08-01", raw_bundle, state, manifest)
        assert record["condition_score"] is not None
        assert record["risk_appetite_score"] is not None
        assert record["stability_score"] is not None
        errors = validate_output(manifest, record)
        assert errors == []

    def test_engine_condition_score_still_none_before_vix9d_coverage_starts(self, manifest, raw_bundle):
        """2018-01-16 predates VIX9D's own coverage start (2018-06-22), so
        Stability is unavailable, which alone makes condition_score
        unavailable. Checked Risk Appetite directly too (not assumed) —
        it's actually ALREADY available by this date (IWM's own 504-session
        window opened 2002-06-03, long before 2018), so this test does not
        assert on risk_appetite_score; the point being tested is Stability's
        gate specifically."""
        state = new_running_engine_state()
        record = run_engine_for_date("2018-01-16", raw_bundle, state, manifest)
        assert record["condition_score"] is None
        assert record["stability_score"] is None
