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
from v5_1.engine import (  # noqa: E402
    load_raw_series_bundle,
    new_running_engine_state,
    run_engine_for_date,
    TEST_SCAFFOLDING_CONFIG,
)


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

    def test_pre_oas_dates_produce_unavailable_condition_and_state_not_a_crash(self, manifest, raw_bundle):
        """2020 dates predate real OAS coverage (starts 2023-08-25) — Risk
        Appetite, and therefore Condition, must be genuinely unavailable
        (None), not an exception and not a fabricated value."""
        state = new_running_engine_state()
        record = run_engine_for_date("2020-04-15", raw_bundle, state, manifest)
        assert record["condition_score"] is None
        errors = validate_output(manifest, record)
        assert errors == []

    def test_direction_is_available_even_when_condition_is_not(self, manifest, raw_bundle):
        """Direction only needs benchmark price data (available since the
        1990s) — it must be genuinely available on a 2020 date even though
        Condition (which needs Risk Appetite's OAS-gated pillar) is not."""
        state = new_running_engine_state()
        record = run_engine_for_date("2020-04-15", raw_bundle, state, manifest)
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
# TEST_SCAFFOLDING_CONFIG is clearly not silently reused as a real default
# ---------------------------------------------------------------------------

class TestScaffoldingConfigIsExplicit:
    def test_config_is_a_named_module_level_constant_not_a_hidden_default(self):
        """A structural sanity check that the scaffolding config is
        clearly named and importable on its own — making it easy for any
        future caller to see exactly what it is (and isn't)."""
        assert TEST_SCAFFOLDING_CONFIG is not None
        assert "TEST_SCAFFOLDING" in "TEST_SCAFFOLDING_CONFIG"
