"""Market Regime v5.1 — Replay Interface (module 4.13) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

**Per plan §8 item 11 / Message[158] item 1: SYNTHETIC fixtures only.**
This suite never reads or applies `freshness_injection_registry.v1.0.json`
— every injection scenario here is constructed directly from
`RawSeriesBundle`/dates, never from the real frozen registry file.

Run with: python3 -m pytest regime/tests/v5_1/test_replay.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.calendar import load_calendar  # noqa: E402
from v5_1.engine import load_raw_series_bundle  # noqa: E402
from v5_1.replay import (  # noqa: E402
    injection_outage_dates,
    apply_injection,
    replay,
    diff_records,
    crisis_entry_lag,
    spurious_state_transitions,
    DateDiff,
    FieldDiff,
    ReplayResult,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def calendar():
    return load_calendar()


@pytest.fixture(scope="module")
def clean_raw(manifest):
    return load_raw_series_bundle(manifest)


# ---------------------------------------------------------------------------
# injection_outage_dates
# ---------------------------------------------------------------------------

class TestInjectionOutageDates:
    def test_returns_exact_count_of_consecutive_expected_sessions(self, calendar):
        dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 3)
        assert len(dates) == 3
        assert dates[0] == "2024-01-12"  # start_date itself, if it's an expected session
        assert dates == tuple(sorted(dates))

    def test_uses_expected_sessions_not_raw_calendar_days(self, calendar):
        """A weekend/holiday start_date should skip to the calendar's own
        next real expected session, not count raw calendar days."""
        dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-13", 1)  # a Saturday
        assert dates[0] > "2024-01-13"

    def test_non_positive_outage_length_rejected(self, calendar):
        with pytest.raises(ValueError, match="must be >= 1"):
            injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 0)

    def test_unknown_family_rejected(self, calendar):
        with pytest.raises(ValueError):
            injection_outage_dates(calendar, "NOT_A_REAL_FAMILY", "2024-01-12", 1)


# ---------------------------------------------------------------------------
# apply_injection
# ---------------------------------------------------------------------------

class TestApplyInjection:
    def test_removes_exact_observations_on_outage_dates_for_named_contracts(self, clean_raw, calendar):
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 2)
        injected = apply_injection(clean_raw, ("BENCHMARK_V5_1",), outage_dates)
        assert len(injected.benchmark.observations) == len(clean_raw.benchmark.observations) - 2
        for d in outage_dates:
            assert injected.benchmark.value_on(d) is None
            assert clean_raw.benchmark.value_on(d) is not None  # confirms these dates really had data to remove

    def test_unrelated_series_are_completely_unaffected(self, clean_raw, calendar):
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 1)
        injected = apply_injection(clean_raw, ("BENCHMARK_V5_1",), outage_dates)
        # Same object reference (frozen dataclasses, safe to share) — a
        # strong, mechanically-checkable guarantee nothing about oas/qqq/
        # iwm/vix/vix9d/breadth was touched at all.
        assert injected.oas is clean_raw.oas
        assert injected.qqq is clean_raw.qqq
        assert injected.iwm is clean_raw.iwm
        assert injected.vix is clean_raw.vix
        assert injected.vix9d is clean_raw.vix9d
        assert injected.breadth is clean_raw.breadth

    def test_multiple_contract_ids_all_affected(self, clean_raw, calendar):
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 1)
        injected = apply_injection(clean_raw, ("BENCHMARK_V5_1", "QQQ_V5_1"), outage_dates)
        for d in outage_dates:
            assert injected.benchmark.value_on(d) is None
            assert injected.qqq.value_on(d) is None
        assert injected.iwm is clean_raw.iwm  # not named, untouched

    def test_collection_contract_removes_from_every_member(self, clean_raw, calendar):
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 1)
        injected = apply_injection(clean_raw, ("BREADTH_V5_1",), outage_dates)
        for path, member in injected.breadth.members.items():
            assert member.value_on(outage_dates[0]) is None, f"member {path} still has an observation on {outage_dates[0]}"

    def test_unrecognized_contract_id_raises(self, clean_raw):
        with pytest.raises(ValueError, match="unrecognized"):
            apply_injection(clean_raw, ("NOT_A_REAL_CONTRACT",), ("2024-01-12",))

    def test_injecting_a_date_with_no_existing_observation_is_a_safe_no_op_for_that_date(self, clean_raw, calendar):
        """A date that never had an observation in the clean series to
        begin with (e.g. a real pre-existing weekend gap that slipped
        into outage_dates somehow) must not raise or corrupt anything —
        removing a non-existent observation is simply a no-op for that
        date."""
        injected = apply_injection(clean_raw, ("BENCHMARK_V5_1",), ("1776-07-04",))
        assert len(injected.benchmark.observations) == len(clean_raw.benchmark.observations)


# ---------------------------------------------------------------------------
# diff_records
# ---------------------------------------------------------------------------

class TestDiffRecords:
    def test_identical_records_produce_no_diffs(self):
        r1 = {"a": 1, "b": 2.0, "c": None}
        r2 = {"a": 1, "b": 2.0, "c": None}
        assert diff_records(r1, r2) == ()

    def test_a_single_differing_field_is_reported(self):
        r1 = {"a": 1, "b": 2.0}
        r2 = {"a": 1, "b": 3.0}
        diffs = diff_records(r1, r2)
        assert len(diffs) == 1
        assert diffs[0] == FieldDiff(field_id="b", clean_value=2.0, injected_value=3.0)

    def test_key_present_in_only_one_record_is_a_diff(self):
        r1 = {"a": 1}
        r2 = {"a": 1, "b": 2}
        diffs = diff_records(r1, r2)
        assert len(diffs) == 1
        assert diffs[0].field_id == "b"
        assert diffs[0].clean_value is None
        assert diffs[0].injected_value == 2

    def test_none_versus_a_real_value_is_a_diff_not_treated_as_equal(self):
        r1 = {"a": None}
        r2 = {"a": 0.5}
        diffs = diff_records(r1, r2)
        assert len(diffs) == 1

    def test_no_floating_point_tolerance_exact_equality_required(self):
        """This engine's deterministic-replay discipline requires
        bit-identical output for identical inputs — diff_records must not
        silently treat a tiny float difference as 'no diff'."""
        r1 = {"a": 0.1 + 0.2}
        r2 = {"a": 0.3}
        diffs = diff_records(r1, r2)
        assert len(diffs) == 1  # 0.1+0.2 != 0.3 exactly in IEEE 754


# ---------------------------------------------------------------------------
# End-to-end replay against real pinned data with a synthetic injection
# ---------------------------------------------------------------------------

class TestEndToEndReplay:
    def test_replay_produces_valid_manifest_conformant_records_on_both_sides(self, manifest, clean_raw, calendar):
        from v5_1.output_assembly import validate_output
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 1)
        injected_raw = apply_injection(clean_raw, ("BENCHMARK_V5_1",), outage_dates)
        dates = ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-16"]
        result = replay(dates, clean_raw, injected_raw, manifest)
        for d in dates:
            assert validate_output(manifest, result.clean_records[d]) == []
            assert validate_output(manifest, result.injected_records[d]) == []

    def test_outage_date_itself_shows_up_as_affected(self, manifest, clean_raw, calendar):
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 1)
        injected_raw = apply_injection(clean_raw, ("BENCHMARK_V5_1",), outage_dates)
        dates = ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-16"]
        result = replay(dates, clean_raw, injected_raw, manifest)
        assert outage_dates[0] in result.affected_dates

    def test_dates_before_the_outage_are_unaffected(self, manifest, clean_raw, calendar):
        """No-lookahead sanity check: a date strictly before the injected
        outage must be byte-identical between clean and injected runs —
        the injection cannot possibly affect the past."""
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 1)
        injected_raw = apply_injection(clean_raw, ("BENCHMARK_V5_1",), outage_dates)
        dates = ["2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12"]
        result = replay(dates, clean_raw, injected_raw, manifest)
        pre_outage_dates = [d for d in dates if d < outage_dates[0]]
        assert len(pre_outage_dates) > 0, "test setup error: need at least one pre-outage date"
        for d in pre_outage_dates:
            assert d not in result.affected_dates, f"{d} (before the outage) was unexpectedly affected"

    def test_no_injection_at_all_produces_zero_affected_dates(self, manifest, clean_raw):
        """A degenerate but important case: replaying the SAME clean
        bundle against itself (no injection applied) must show zero
        diffs anywhere — proves the diff mechanism doesn't spuriously
        flag differences on its own."""
        dates = ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-16"]
        result = replay(dates, clean_raw, clean_raw, manifest)
        assert result.affected_dates == ()

    def test_result_publishes_full_records_not_just_diffs(self, manifest, clean_raw, calendar):
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 1)
        injected_raw = apply_injection(clean_raw, ("BENCHMARK_V5_1",), outage_dates)
        dates = ["2024-01-10", "2024-01-12"]
        result = replay(dates, clean_raw, injected_raw, manifest)
        assert isinstance(result, ReplayResult)
        assert set(result.clean_records.keys()) == set(dates)
        assert set(result.injected_records.keys()) == set(dates)


# ---------------------------------------------------------------------------
# crisis_entry_lag
# ---------------------------------------------------------------------------

class TestCrisisEntryLag:
    def test_none_when_neither_run_ever_enters_crisis(self, manifest, clean_raw):
        dates = ["2024-01-10", "2024-01-11", "2024-01-12"]
        result = replay(dates, clean_raw, clean_raw, manifest)
        assert crisis_entry_lag(result) is None

    def test_zero_when_synthetic_records_show_identical_entry_bar(self):
        """Constructs a synthetic ReplayResult directly (not via a real
        engine run) to isolate crisis_entry_lag's own arithmetic from the
        scaffolding's 'always calm' CRISIS stub, which makes a real
        engine-produced CRISIS entry impossible to construct in this
        slice's own test fixtures."""
        dates = ("d0", "d1", "d2")
        clean_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "CRISIS"}, "d2": {"state": "CRISIS"}}
        injected_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "CRISIS"}, "d2": {"state": "CRISIS"}}
        result = ReplayResult(dates=dates, clean_records=clean_records, injected_records=injected_records, date_diffs=())
        assert crisis_entry_lag(result) == 0

    def test_positive_lag_when_injected_run_enters_later(self):
        dates = ("d0", "d1", "d2", "d3")
        clean_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "CRISIS"}, "d2": {"state": "CRISIS"}, "d3": {"state": "CRISIS"}}
        injected_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "NEUTRAL"}, "d2": {"state": "NEUTRAL"}, "d3": {"state": "CRISIS"}}
        result = ReplayResult(dates=dates, clean_records=clean_records, injected_records=injected_records, date_diffs=())
        assert crisis_entry_lag(result) == 2  # entered on index 3 vs index 1

    def test_negative_lag_when_injected_run_enters_earlier(self):
        """A real, distinguishable case this function must NOT collapse
        into 'no delay' or treat as an error — an injection could
        plausibly cause an EARLY false CRISIS entry, not only a delayed
        one."""
        dates = ("d0", "d1", "d2")
        clean_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "NEUTRAL"}, "d2": {"state": "CRISIS"}}
        injected_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "CRISIS"}, "d2": {"state": "CRISIS"}}
        result = ReplayResult(dates=dates, clean_records=clean_records, injected_records=injected_records, date_diffs=())
        assert crisis_entry_lag(result) == -1

    def test_none_when_clean_enters_but_injected_never_does(self):
        """spec §5's own 'or non-entry' phrasing."""
        dates = ("d0", "d1")
        clean_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "CRISIS"}}
        injected_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "NEUTRAL"}}
        result = ReplayResult(dates=dates, clean_records=clean_records, injected_records=injected_records, date_diffs=())
        assert crisis_entry_lag(result) is None


# ---------------------------------------------------------------------------
# spurious_state_transitions
# ---------------------------------------------------------------------------

class TestSpuriousStateTransitions:
    def test_empty_when_no_engine_produced_crisis_scaffolding_scenario(self, manifest, clean_raw):
        dates = ["2024-01-10", "2024-01-11", "2024-01-12"]
        result = replay(dates, clean_raw, clean_raw, manifest)
        assert spurious_state_transitions(result) == ()

    def test_first_date_is_never_itself_included_even_if_its_own_state_differs(self):
        """The FIRST date in `dates` can never appear IN THE RETURNED
        TUPLE (there's no preceding bar for it to have 'transitioned'
        from) — but this does NOT mean the function reports nothing when
        d0 differs. Found a real bug in my own first version of this
        test: I asserted the overall result should be empty because 'd0
        itself differs, but can't be spurious' — but d0 differing
        (RISK_ON vs NEUTRAL) means the INJECTED run transitioned
        RISK_ON->NEUTRAL between d0 and d1, while the clean run stayed
        NEUTRAL->NEUTRAL — that IS a genuine spurious transition AT d1,
        correctly detected. My test's expectation was simply wrong, not
        the implementation. Fixed to assert what the function should
        actually do: d0 itself is never in the output tuple, and d1 (the
        real transition bar) correctly is."""
        dates = ("d0", "d1")
        clean_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "NEUTRAL"}}
        injected_records = {"d0": {"state": "RISK_ON"}, "d1": {"state": "NEUTRAL"}}
        result = ReplayResult(dates=dates, clean_records=clean_records, injected_records=injected_records, date_diffs=())
        spurious = spurious_state_transitions(result)
        assert "d0" not in spurious
        assert spurious == ("d1",)

    def test_transition_in_injected_absent_from_clean_is_spurious(self):
        dates = ("d0", "d1", "d2")
        clean_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "NEUTRAL"}, "d2": {"state": "NEUTRAL"}}
        injected_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "RISK_OFF"}, "d2": {"state": "RISK_OFF"}}
        result = ReplayResult(dates=dates, clean_records=clean_records, injected_records=injected_records, date_diffs=())
        assert spurious_state_transitions(result) == ("d1",)  # d1 is the transition bar; d2 is not (no NEW transition there)

    def test_transition_present_in_both_runs_is_not_spurious(self):
        """A REAL market-driven transition that happens in BOTH runs
        (clean and injected, even if on the exact same date) must NOT be
        flagged — spurious specifically means the injection CAUSED it."""
        dates = ("d0", "d1")
        clean_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "RISK_ON"}}
        injected_records = {"d0": {"state": "NEUTRAL"}, "d1": {"state": "RISK_ON"}}
        result = ReplayResult(dates=dates, clean_records=clean_records, injected_records=injected_records, date_diffs=())
        assert spurious_state_transitions(result) == ()


# ---------------------------------------------------------------------------
# No access to the real frozen registry — structural check
# ---------------------------------------------------------------------------

class TestNeverTouchesTheFrozenRegistry:
    """Checks for an actual FILE-ACCESS path to the registry (a literal
    path/filename appearing as a string LITERAL a file-open call could
    use), not a bare textual mention — the same false-positive class
    caught repeatedly elsewhere in this engine's self-review (Message[175]
    's `abs(`, Message[180]'s `impulse`/`confidence` checks): a naive
    whole-file substring search fails immediately here, since this
    module's OWN docstring explicitly names the registry file in prose,
    describing what it deliberately does NOT do — that's documentation,
    not a real access path. Checked via `ast`, looking for the registry's
    filename appearing as a string literal constant in the parsed tree
    OUTSIDE of the module's own top-level docstring specifically (a
    `Module.body[0]` `Expr(Constant(str))` node, per how Python's ast
    represents a leading docstring) — a real accidental `open(...)`,
    `Path(...)`, or similar call would put the filename in a DIFFERENT
    AST location than the docstring, so this distinguishes "mentioned in
    documentation" from "used as a real string literal anywhere else."""

    def _has_registry_filename_outside_docstring(self, path) -> bool:
        """Found a real bug in my own first version of this helper during
        self-review: it identified the module docstring's `ast.Expr`
        WRAPPER node (`tree.body[0]`) and tried to skip it via `node is
        docstring_node` inside `ast.walk` — but `ast.walk` also visits the
        wrapper's CHILD node (the inner `ast.Constant` holding the actual
        string) as a SEPARATE node, which `is docstring_node` never
        matches (it's comparing against the Expr, not the Constant), so
        the docstring's own Constant was never actually exempted and the
        check still false-positived on it. Fixed by exempting
        `tree.body[0].value` (the inner Constant itself), not
        `tree.body[0]` (the Expr wrapper)."""
        import ast
        tree = ast.parse(path.read_text())
        docstring_constant_node = None
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            docstring_constant_node = tree.body[0].value

        for node in ast.walk(tree):
            if node is docstring_constant_node:
                continue
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if "freshness_injection_registry" in node.value:
                    return True
        return False

    def test_replay_module_has_no_real_file_access_path_to_the_registry(self):
        """Per plan §8 item 11 / Message[158] item 1: this slice never
        applies the tool to the real frozen registry."""
        path = REPO_ROOT / "regime/src/v5_1/replay.py"
        assert not self._has_registry_filename_outside_docstring(path)

    def test_engine_module_has_no_real_file_access_path_to_the_registry(self):
        path = REPO_ROOT / "regime/src/v5_1/engine.py"
        assert not self._has_registry_filename_outside_docstring(path)


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplayOfReplay:
    def test_running_the_same_replay_twice_gives_identical_results(self, manifest, clean_raw, calendar):
        outage_dates = injection_outage_dates(calendar, "XNYS_ETF_BREADTH", "2024-01-12", 1)
        injected_raw = apply_injection(clean_raw, ("BENCHMARK_V5_1",), outage_dates)
        dates = ["2024-01-10", "2024-01-11", "2024-01-12"]
        r1 = replay(dates, clean_raw, injected_raw, manifest)
        r2 = replay(dates, clean_raw, injected_raw, manifest)
        assert r1.clean_records == r2.clean_records
        assert r1.injected_records == r2.injected_records
        assert r1.affected_dates == r2.affected_dates
