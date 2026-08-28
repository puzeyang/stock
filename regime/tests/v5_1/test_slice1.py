"""Market Regime v5.1 — Slice 1 test suite, per ChatGPT Message[168]'s
required requirement-to-test matrix:

1. Strict manifest/schema loading and pinned-identity checks.
2. CURRENT/STALE/MISSING/MISALIGNED semantics and reason codes.
3. Fail-closed handling of missing, stale, misaligned, duplicated, and
   under-warmed inputs.
4. Point-in-time/as-of enforcement with no future observations.
5. Expected-session arithmetic against the pinned calendar including
   closures and boundary cases.
6. The causal 504-session empirical midrank: exact tie formula,
   insufficient-history behavior, no-lookahead invariance.
7. Negative fixtures for malformed contracts and calendar mismatches.
8. Deterministic replay evidence.

Uses only synthetic fixtures and the already-frozen calendar/manifest
artifacts read-only — no development/holdout freshness-experiment injection
is touched anywhere in this suite, per the plan's explicit boundary.

Run with: python3 -m pytest regime/tests/v5_1/test_slice1.py -v
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import (  # noqa: E402
    ManifestLoadError,
    load_manifest,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SCHEMA_PATH,
)
from v5_1.calendar import (  # noqa: E402
    CalendarLoadError,
    ExpectedSessionCalendar,
    load_calendar,
    DEFAULT_CALENDAR_PATH,
)
from v5_1.freshness import (  # noqa: E402
    evaluate_freshness,
    FreshnessState,
    ReasonCode,
    FreshnessResult,
)
from v5_1.normalization import (  # noqa: E402
    causal_midrank,
    InsufficientHistoryError,
    REQUIRED_WINDOW_SIZE,
)


# ---------------------------------------------------------------------------
# 1. Manifest/schema loading and pinned-identity checks
# ---------------------------------------------------------------------------

class TestManifestLoading:
    def test_loads_real_manifest_cleanly(self):
        m = load_manifest()
        assert m.schema_version == "5.1"
        assert m.feature_contract_version == "5.1"
        assert len(m.fields) == 86
        assert len(m.source_contracts) == 10

    def test_manifest_hash_is_computed_from_real_bytes(self):
        m = load_manifest()
        import hashlib
        expected = hashlib.sha256(DEFAULT_MANIFEST_PATH.read_bytes()).hexdigest()
        assert m.manifest_sha256 == expected

    def test_design_doc_identity_verifies_against_real_bytes(self):
        m = load_manifest()
        error = m.verify_design_doc_identity()
        assert error is None, f"design doc identity check failed: {error}"

    def test_get_contract_returns_typed_source_contract(self):
        m = load_manifest()
        c = m.get_contract("BENCHMARK_V5_1")
        assert c.provider == "Yahoo Finance via yfinance 0.2.66"
        assert c.field_name == "adj_close"
        assert "research/data/raw/SPY.csv" in c.snapshot_paths

    def test_get_contract_raises_on_unknown_id(self):
        m = load_manifest()
        with pytest.raises(KeyError):
            m.get_contract("NOT_A_REAL_CONTRACT")

    def test_snapshot_hashes_verify_against_real_disk_bytes(self):
        m = load_manifest()
        c = m.get_contract("BENCHMARK_V5_1")
        errors = c.verify_snapshot_hashes()
        assert errors == [], f"snapshot hash verification failed: {errors}"

    # --- negative fixtures: malformed manifest ---

    def test_missing_manifest_file_raises(self, tmp_path):
        with pytest.raises(ManifestLoadError, match="not found"):
            load_manifest(manifest_path=tmp_path / "does_not_exist.json")

    def test_malformed_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        with pytest.raises(ManifestLoadError, match="not valid JSON"):
            load_manifest(manifest_path=bad)

    def test_schema_validation_failure_raises(self, tmp_path):
        with DEFAULT_MANIFEST_PATH.open() as f:
            data = json.load(f)
        del data["schema_version"]  # required field per schema
        bad = tmp_path / "missing_required.json"
        bad.write_text(json.dumps(data))
        with pytest.raises(ManifestLoadError, match="schema validation"):
            load_manifest(manifest_path=bad)

    def test_wrong_const_value_fails_schema(self, tmp_path):
        with DEFAULT_MANIFEST_PATH.open() as f:
            data = json.load(f)
        data["schema_version"] = "9.9"  # schema requires const "5.1"
        bad = tmp_path / "wrong_version.json"
        bad.write_text(json.dumps(data))
        with pytest.raises(ManifestLoadError, match="schema validation"):
            load_manifest(manifest_path=bad)

    def test_duplicate_source_contract_id_raises(self, tmp_path):
        with DEFAULT_MANIFEST_PATH.open() as f:
            data = json.load(f)
        data["source_contracts"].append(copy.deepcopy(data["source_contracts"][0]))
        bad = tmp_path / "dup_contract.json"
        bad.write_text(json.dumps(data))
        # Duplicate source_contract_id is a semantic error our loader catches
        # (the schema itself may or may not reject it via uniqueItems on the
        # whole object — the loader's own duplicate check is the authority).
        with pytest.raises(ManifestLoadError, match="duplicate source_contract_id|schema validation"):
            load_manifest(manifest_path=bad)

    def test_duplicate_field_id_raises(self, tmp_path):
        with DEFAULT_MANIFEST_PATH.open() as f:
            data = json.load(f)
        data["fields"].append(copy.deepcopy(data["fields"][0]))
        bad = tmp_path / "dup_field.json"
        bad.write_text(json.dumps(data))
        with pytest.raises(ManifestLoadError, match="duplicate field_id|schema validation"):
            load_manifest(manifest_path=bad)

    def test_tampered_manifest_identity_is_detectable(self, tmp_path):
        """Prove a tampered manifest produces a DIFFERENT hash than the real
        pinned one — the identity-inheritance mechanism actually works."""
        with DEFAULT_MANIFEST_PATH.open() as f:
            data = json.load(f)
        data["generated_at"] = "2099-01-01T00:00:00Z"  # innocuous-looking tamper
        tampered = tmp_path / "tampered.json"
        tampered.write_text(json.dumps(data))
        m_real = load_manifest()
        m_tampered = load_manifest(manifest_path=tampered)
        assert m_tampered.manifest_sha256 != m_real.manifest_sha256


# ---------------------------------------------------------------------------
# 2. CURRENT/STALE/MISSING/MISALIGNED semantics and reason codes
# ---------------------------------------------------------------------------

class TestFreshnessSemantics:
    def test_missing_when_no_prior_observation(self):
        r = evaluate_freshness(as_of="2020-01-01", last_observation_date=None, expected_sessions_since=[], n_allowance=1)
        assert r.state == FreshnessState.MISSING
        assert r.reason == ReasonCode.SOURCE_MISSING
        assert r.usable is False

    def test_current_on_time_has_null_reason(self):
        r = evaluate_freshness(as_of="2020-01-02", last_observation_date="2020-01-02", expected_sessions_since=[], n_allowance=2)
        assert r.state == FreshnessState.CURRENT
        assert r.reason is None
        assert r.usable is True

    def test_current_within_grace_has_explicit_reason(self):
        r = evaluate_freshness(
            as_of="2020-01-03", last_observation_date="2020-01-02",
            expected_sessions_since=["2020-01-03"], n_allowance=2,
        )
        assert r.state == FreshnessState.CURRENT
        assert r.reason == ReasonCode.SOURCE_LATE_WITHIN_GRACE
        assert r.usable is True, "SOURCE_LATE_WITHIN_GRACE must permit full computation, not just display retention (spec §2)"

    def test_stale_at_exactly_n_plus_1_missed(self):
        # N=1 allowance: missed=2 must be STALE (N+1 or more, never at exactly N)
        r = evaluate_freshness(
            as_of="2020-01-04", last_observation_date="2020-01-02",
            expected_sessions_since=["2020-01-03", "2020-01-04"], n_allowance=1,
        )
        assert r.state == FreshnessState.STALE
        assert r.reason == ReasonCode.SOURCE_STALE
        assert r.usable is False

    def test_current_at_exactly_n_missed_boundary(self):
        # N=2 allowance: missed=2 (exactly N) must still be CURRENT — inclusive of N itself
        r = evaluate_freshness(
            as_of="2020-01-04", last_observation_date="2020-01-02",
            expected_sessions_since=["2020-01-03", "2020-01-04"], n_allowance=2,
        )
        assert r.state == FreshnessState.CURRENT
        assert r.reason == ReasonCode.SOURCE_LATE_WITHIN_GRACE

    def test_misaligned_when_point_in_time_violation(self):
        r = evaluate_freshness(
            as_of="2020-01-02", last_observation_date="2020-01-02",
            expected_sessions_since=[], n_allowance=1, point_in_time_violation=True,
        )
        assert r.state == FreshnessState.MISALIGNED
        assert r.reason == ReasonCode.SOURCE_MISALIGNED
        assert r.usable is False

    def test_stale_takes_precedence_over_point_in_time_check(self):
        """A STALE observation is STALE regardless of point_in_time_violation
        — spec §2 checks point-in-time only for observations that would
        'otherwise be CURRENT by the count.'"""
        r = evaluate_freshness(
            as_of="2020-01-04", last_observation_date="2020-01-02",
            expected_sessions_since=["2020-01-03", "2020-01-04"], n_allowance=1,
            point_in_time_violation=True,
        )
        assert r.state == FreshnessState.STALE
        assert r.reason == ReasonCode.SOURCE_STALE

    def test_reason_code_construction_rejects_incompatible_pairing(self):
        with pytest.raises(ValueError):
            FreshnessResult(FreshnessState.STALE, ReasonCode.SOURCE_MISSING, 5)

    def test_reason_code_construction_rejects_current_with_stale_code(self):
        with pytest.raises(ValueError):
            FreshnessResult(FreshnessState.CURRENT, ReasonCode.SOURCE_STALE, 0)

    @pytest.mark.parametrize("state,reason", [
        (FreshnessState.CURRENT, None),
        (FreshnessState.CURRENT, ReasonCode.SOURCE_LATE_WITHIN_GRACE),
        (FreshnessState.STALE, ReasonCode.SOURCE_STALE),
        (FreshnessState.MISSING, ReasonCode.SOURCE_MISSING),
        (FreshnessState.MISALIGNED, ReasonCode.SOURCE_MISALIGNED),
    ])
    def test_all_five_valid_state_reason_pairs_construct(self, state, reason):
        FreshnessResult(state, reason, 0)


# ---------------------------------------------------------------------------
# 3. Fail-closed handling
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_missing_is_never_usable(self):
        r = evaluate_freshness(as_of="2020-01-01", last_observation_date=None, expected_sessions_since=[], n_allowance=99)
        assert r.usable is False

    def test_stale_is_never_usable(self):
        r = evaluate_freshness(
            as_of="2020-01-10", last_observation_date="2020-01-01",
            expected_sessions_since=[f"2020-01-{d:02d}" for d in range(2, 11)], n_allowance=1,
        )
        assert r.state == FreshnessState.STALE
        assert r.usable is False

    def test_misaligned_is_never_usable(self):
        r = evaluate_freshness(
            as_of="2020-01-01", last_observation_date="2020-01-01",
            expected_sessions_since=[], n_allowance=5, point_in_time_violation=True,
        )
        assert r.usable is False

    def test_negative_n_allowance_rejected(self):
        with pytest.raises(ValueError):
            evaluate_freshness(as_of="2020-01-01", last_observation_date="2020-01-01", expected_sessions_since=[], n_allowance=-1)

    def test_lookahead_last_observation_after_as_of_rejected(self):
        """A caller error where last_observation_date is AFTER as_of must be
        rejected loudly — this is a lookahead bug, not a valid freshness
        question, and must never silently produce a result."""
        with pytest.raises(ValueError, match="lookahead"):
            evaluate_freshness(as_of="2020-01-01", last_observation_date="2020-01-05", expected_sessions_since=[], n_allowance=1)

    def test_midrank_insufficient_history_raises_not_silently_approximates(self):
        with pytest.raises(InsufficientHistoryError):
            causal_midrank([1.0, 2.0, 3.0], 2.0)  # far fewer than 504

    # --- found during solo self-review (ChatGPT unavailable): the original
    # evaluate_freshness() trusted expected_sessions_since's LENGTH without
    # validating its contents, so a malformed/out-of-range/duplicated list
    # would silently corrupt the computed state with no error. Fixed, and
    # proven fixed with the four negative cases below. ---

    def test_expected_sessions_since_rejects_non_iso_date(self):
        with pytest.raises(ValueError, match="non-ISO date"):
            evaluate_freshness(
                as_of="2020-01-05", last_observation_date="2020-01-02",
                expected_sessions_since=["not-a-date"], n_allowance=5,
            )

    def test_expected_sessions_since_rejects_date_at_or_before_last_observation(self):
        """A date <= last_observation_date is not 'strictly after' — passing
        one must fail loudly, not silently inflate/miscount `missed`."""
        with pytest.raises(ValueError, match="outside the required range"):
            evaluate_freshness(
                as_of="2020-01-05", last_observation_date="2020-01-02",
                expected_sessions_since=["2020-01-02"], n_allowance=5,
            )

    def test_expected_sessions_since_rejects_date_after_as_of(self):
        """A date > as_of would itself be a lookahead smuggled in through
        this list, not caught by the top-level as_of/last_observation_date
        check alone."""
        with pytest.raises(ValueError, match="outside the required range"):
            evaluate_freshness(
                as_of="2020-01-05", last_observation_date="2020-01-02",
                expected_sessions_since=["2020-01-06"], n_allowance=5,
            )

    def test_expected_sessions_since_rejects_duplicates(self):
        with pytest.raises(ValueError, match="duplicate date"):
            evaluate_freshness(
                as_of="2020-01-05", last_observation_date="2020-01-02",
                expected_sessions_since=["2020-01-03", "2020-01-03"], n_allowance=5,
            )

    def test_midrank_does_not_use_expanding_window_shortcut(self):
        """503 observations must raise, not silently compute against a
        503-length window — no expanding-window shortcut is permitted."""
        window = [float(i) for i in range(REQUIRED_WINDOW_SIZE - 1)]
        with pytest.raises(InsufficientHistoryError):
            causal_midrank(window, float(REQUIRED_WINDOW_SIZE - 1))


# ---------------------------------------------------------------------------
# 4. Point-in-time / as-of enforcement — no future observations
# ---------------------------------------------------------------------------

class TestPointInTime:
    def test_as_of_equals_observation_date_is_valid(self):
        r = evaluate_freshness(as_of="2020-06-15", last_observation_date="2020-06-15", expected_sessions_since=[], n_allowance=0)
        assert r.state == FreshnessState.CURRENT

    def test_observation_strictly_before_as_of_is_valid(self):
        r = evaluate_freshness(
            as_of="2020-06-16", last_observation_date="2020-06-15",
            expected_sessions_since=["2020-06-16"], n_allowance=1,
        )
        assert r.state == FreshnessState.CURRENT

    def test_observation_after_as_of_raises(self):
        with pytest.raises(ValueError):
            evaluate_freshness(as_of="2020-06-14", last_observation_date="2020-06-15", expected_sessions_since=[], n_allowance=1)


# ---------------------------------------------------------------------------
# 5. Expected-session calendar arithmetic
# ---------------------------------------------------------------------------

class TestCalendar:
    def test_loads_real_pinned_calendar(self):
        # Hash updated after the 2026-08-27 move to top-level regime/ —
        # the calendar artifact's own "generated_by" field was rewritten
        # from "research/regime/tools/..." to "regime/tools/..." to keep
        # it accurate post-move, which necessarily changes its content
        # hash (this file is NOT one of the frozen freshness-experiment
        # artifacts, so updating it is expected and safe).
        cal = load_calendar()
        assert cal.sha256 == "06a0679dc909095a786851780d331081292e2d3dd6435c6b73672ef713354770"

    def test_known_ordinary_session_is_expected(self):
        cal = load_calendar()
        assert cal.is_expected_session("XNYS_ETF_BREADTH", "2019-08-15") is True

    def test_extraordinary_closure_is_not_expected(self):
        """9/11 closure — a real extraordinary closure, must not be an
        expected session, per the frozen calendar's own reconciliation."""
        cal = load_calendar()
        assert cal.is_expected_session("XNYS_ETF_BREADTH", "2001-09-11") is False

    def test_observed_holiday_exception_is_expected(self):
        """1999-12-31: XNYS trades the Friday before a Saturday New Year's —
        must be a real expected session (the frozen calendar's round-10 fix)."""
        cal = load_calendar()
        assert cal.is_expected_session("XNYS_ETF_BREADTH", "1999-12-31") is True

    def test_independence_day_observed_closure_is_excluded(self):
        """2020-07-03: Friday before a Saturday July 4th — must be excluded
        (nearest_workday rule, distinct from New Year's sunday_to_monday-only)."""
        cal = load_calendar()
        assert cal.is_expected_session("XNYS_ETF_BREADTH", "2020-07-03") is False

    def test_expected_sessions_between_boundary_cases(self):
        cal = load_calendar()
        # zero missed sessions: start == end (exclusive start, so returns [] when equal)
        result = cal.expected_sessions_between("XNYS_ETF_BREADTH", "2019-08-15", "2019-08-15")
        assert result == []

        # exactly one missed session
        result = cal.expected_sessions_between("XNYS_ETF_BREADTH", "2019-08-15", "2019-08-16")
        assert result == ["2019-08-16"]

    def test_weekend_is_not_counted_as_a_missed_session(self):
        cal = load_calendar()
        # Friday 2019-08-16 to Monday 2019-08-19: weekend in between, should be exactly 1 missed session
        result = cal.expected_sessions_between("XNYS_ETF_BREADTH", "2019-08-16", "2019-08-19")
        assert result == ["2019-08-19"]

    def test_unknown_family_raises(self):
        cal = load_calendar()
        with pytest.raises(ValueError, match="unknown family"):
            cal.is_expected_session("NOT_A_FAMILY", "2020-01-01")

    # --- negative fixtures: malformed/mismatched calendar ---

    def test_missing_calendar_file_raises(self, tmp_path):
        with pytest.raises(CalendarLoadError, match="not found"):
            ExpectedSessionCalendar(path=tmp_path / "does_not_exist.json")

    def test_malformed_calendar_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid")
        with pytest.raises(CalendarLoadError, match="not valid JSON"):
            ExpectedSessionCalendar(path=bad)

    def test_calendar_missing_families_key_raises(self, tmp_path):
        bad = tmp_path / "no_families.json"
        bad.write_text(json.dumps({"calendar_version": "1.0"}))
        with pytest.raises(CalendarLoadError, match="families"):
            ExpectedSessionCalendar(path=bad)

    def test_calendar_missing_one_required_family_raises(self, tmp_path):
        with DEFAULT_CALENDAR_PATH.open() as f:
            data = json.load(f)
        del data["families"]["FRED_OAS"]
        bad = tmp_path / "missing_family.json"
        bad.write_text(json.dumps(data))
        with pytest.raises(CalendarLoadError, match="missing families"):
            ExpectedSessionCalendar(path=bad)


# ---------------------------------------------------------------------------
# 6. Causal midrank: exact tie formula, insufficient history, no-lookahead
# ---------------------------------------------------------------------------

class TestCausalMidrank:
    def test_exact_size_required(self):
        window = [1.0] * REQUIRED_WINDOW_SIZE
        result = causal_midrank(window, 1.0)
        assert isinstance(result, float)

    def test_all_ties_gives_50th_percentile(self):
        """If every window value equals current_value: less=0, equal=504,
        percentile = 100*(0 + 0.5*504)/504 = 50.0 exactly."""
        window = [7.0] * REQUIRED_WINDOW_SIZE
        result = causal_midrank(window, 7.0)
        assert result == pytest.approx(50.0)

    def test_current_value_is_maximum_gives_near_100(self):
        window = [float(i) for i in range(REQUIRED_WINDOW_SIZE)]
        result = causal_midrank(window, float(REQUIRED_WINDOW_SIZE - 1))
        # less = 503, equal = 1 -> 100*(503+0.5)/504
        expected = 100.0 * (503 + 0.5) / REQUIRED_WINDOW_SIZE
        assert result == pytest.approx(expected)

    def test_current_value_is_minimum_gives_near_zero(self):
        window = [float(i) for i in range(REQUIRED_WINDOW_SIZE)]
        result = causal_midrank(window, 0.0)
        expected = 100.0 * (0 + 0.5) / REQUIRED_WINDOW_SIZE
        assert result == pytest.approx(expected)

    def test_exact_tie_formula_with_known_values(self):
        """Direct hand-computed check against the exact formula in design §5.1."""
        window = [1.0, 1.0, 2.0, 2.0, 2.0] + [0.0] * (REQUIRED_WINDOW_SIZE - 5)
        current = 2.0
        less = sum(1 for v in window if v < current)   # the (504-5)=499 zeros + 2 ones = 501
        equal = sum(1 for v in window if v == current)  # the 3 twos
        expected = 100.0 * (less + 0.5 * equal) / REQUIRED_WINDOW_SIZE
        result = causal_midrank(window, current)
        assert result == pytest.approx(expected)
        assert less == 501
        assert equal == 3

    def test_too_few_observations_raises(self):
        for n in (0, 1, 100, 503):
            with pytest.raises(InsufficientHistoryError):
                causal_midrank([1.0] * n, 1.0)

    def test_too_many_observations_raises(self):
        """Exactly 504 is required — 505 is also invalid, not silently
        truncated to the most recent 504 (that would hide a caller bug)."""
        with pytest.raises(InsufficientHistoryError):
            causal_midrank([1.0] * (REQUIRED_WINDOW_SIZE + 1), 1.0)

    def test_current_value_not_in_window_rejected(self):
        """Found during solo self-review (ChatGPT unavailable): design §5.1
        requires the midrank to include the current observation WITHIN the
        504-observation window — current_value must be a real member of
        window, not merely a same-length coincidence. A caller passing a
        current_value absent from window must be rejected loudly, not
        silently given a formula-shaped but meaningless result."""
        window = [float(i) for i in range(REQUIRED_WINDOW_SIZE)]  # values 0..503
        with pytest.raises(ValueError, match="not a member of window"):
            causal_midrank(window, 999.0)  # not in window at all

    def test_no_lookahead_invariance(self):
        """The function itself has no notion of 'future' — it is the
        caller's responsibility to construct a causal window. This test
        proves the function is a pure, order-sensitive-to-content-only
        computation: reordering the window (a stand-in for 'includes future
        data out of order') changes nothing about VALUE membership, only
        about whether the window was actually constructed causally upstream
        — which is exactly why this primitive alone cannot enforce
        causality, and why the conformance suite (plan §7.5) checks
        end-to-end path-dependence separately, not here."""
        window = [float(i) for i in range(REQUIRED_WINDOW_SIZE)]
        current = 250.0
        result_a = causal_midrank(window, current)
        result_b = causal_midrank(list(reversed(window)), current)
        assert result_a == result_b, "midrank must be order-independent within a fixed window (only membership counts)"


# ---------------------------------------------------------------------------
# 7. Deterministic replay evidence
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    """Design §1.3: identical valid inputs over every declared lookback MUST
    produce identical pillars and Condition. For Slice 1's primitives, this
    means: repeated calls with identical inputs must be byte-identical, and
    there is no hidden mutable global state anywhere in these modules."""

    def test_manifest_load_is_repeatable_and_identical(self):
        m1 = load_manifest()
        m2 = load_manifest()
        assert m1.manifest_sha256 == m2.manifest_sha256
        assert m1.fields == m2.fields
        assert set(m1.source_contracts.keys()) == set(m2.source_contracts.keys())

    def test_calendar_load_is_repeatable_and_identical(self):
        c1 = load_calendar()
        c2 = load_calendar()
        assert c1.sha256 == c2.sha256
        assert c1.expected_sessions("XNYS_ETF_BREADTH") == c2.expected_sessions("XNYS_ETF_BREADTH")

    def test_freshness_evaluation_is_pure_and_repeatable(self):
        kwargs = dict(
            as_of="2020-04-15", last_observation_date="2020-04-10",
            expected_sessions_since=["2020-04-13", "2020-04-14", "2020-04-15"], n_allowance=2,
        )
        r1 = evaluate_freshness(**kwargs)
        r2 = evaluate_freshness(**kwargs)
        assert r1 == r2

    def test_midrank_is_pure_and_repeatable(self):
        window = [float(i % 17) for i in range(REQUIRED_WINDOW_SIZE)]
        r1 = causal_midrank(window, 8.0)
        r2 = causal_midrank(window, 8.0)
        assert r1 == r2

    def test_full_slice1_pipeline_is_deterministic_across_two_fresh_loads(self):
        """A true end-to-end replay check: load manifest + calendar fresh
        twice, run a freshness evaluation using data derived from both,
        confirm byte-identical results — the closest Slice 1 alone can get
        to plan §1.3's 'replay MUST reconstruct...' requirement without a
        full engine (which doesn't exist until later slices)."""
        def run_once():
            m = load_manifest()
            cal = load_calendar()
            contract = m.get_contract("OAS_V5_1")
            missed = cal.expected_sessions_between("FRED_OAS", "2023-08-25", "2023-09-05")
            result = evaluate_freshness(
                as_of="2023-09-05", last_observation_date="2023-08-25",
                expected_sessions_since=missed, n_allowance=5,
            )
            return (m.manifest_sha256, cal.sha256, contract.provider, tuple(missed), result)

        run1 = run_once()
        run2 = run_once()
        assert run1 == run2
