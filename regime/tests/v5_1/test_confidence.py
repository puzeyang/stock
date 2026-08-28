"""Market Regime v5.1 — Confidence diagnostics (module 4.11) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_confidence.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.confidence import (  # noqa: E402
    ConfidenceResult,
    compute_confidence,
)


def _stub_pillar_agreement(as_of):
    return 0.8  # obviously-fake placeholder, proves the injection seam


def _stub_data_completeness(as_of):
    return 0.9


def _stub_decision_margin(as_of):
    return 0.3


def _stub_temporal_stability(as_of):
    return 0.6


def _unavailable(as_of):
    return None


# ---------------------------------------------------------------------------
# compute_confidence — basic assembly
# ---------------------------------------------------------------------------

class TestComputeConfidence:
    def test_assembles_all_four_diagnostics_from_their_own_estimators(self):
        r = compute_confidence(
            "2020-04-15", _stub_pillar_agreement, _stub_data_completeness,
            _stub_decision_margin, _stub_temporal_stability,
        )
        assert isinstance(r, ConfidenceResult)
        assert r.pillar_agreement == 0.8
        assert r.data_completeness == 0.9
        assert r.decision_margin == 0.3
        assert r.temporal_stability == 0.6

    def test_each_estimator_receives_the_same_as_of(self):
        received = {}

        def _capture(name):
            def _ev(as_of):
                received[name] = as_of
                return 0.5
            return _ev

        compute_confidence("2020-04-15", _capture("pa"), _capture("dc"), _capture("dm"), _capture("ts"))
        assert received == {"pa": "2020-04-15", "dc": "2020-04-15", "dm": "2020-04-15", "ts": "2020-04-15"}


# ---------------------------------------------------------------------------
# One diagnostic's unavailability must not affect the others (no aggregate,
# no cross-dependency) — the core §12 "no aggregate" design point.
# ---------------------------------------------------------------------------

class TestNoAggregateIndependence:
    def test_one_unavailable_diagnostic_does_not_raise_or_null_the_others(self):
        r = compute_confidence(
            "2020-04-15", _unavailable, _stub_data_completeness,
            _stub_decision_margin, _stub_temporal_stability,
        )
        assert r.pillar_agreement is None
        assert r.data_completeness == 0.9
        assert r.decision_margin == 0.3
        assert r.temporal_stability == 0.6

    def test_all_four_unavailable_simultaneously_is_not_an_error(self):
        r = compute_confidence("2020-04-15", _unavailable, _unavailable, _unavailable, _unavailable)
        assert r.pillar_agreement is None
        assert r.data_completeness is None
        assert r.decision_margin is None
        assert r.temporal_stability is None

    def test_result_has_no_aggregate_field(self):
        """§12: 'Publish no aggregate confidence scalar.' A structural
        check on the dataclass's own field set — there must be no fifth
        'confidence_score'-shaped field anywhere on ConfidenceResult."""
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(ConfidenceResult)}
        assert field_names == {"as_of", "pillar_agreement", "data_completeness", "decision_margin", "temporal_stability"}


class TestMonotonicityContract:
    """Golden-vector requirement (plan §6/design §14.1): 'Confidence
    monotonicity.' A gap found during Slice 12's conformance review:
    §12's own monotonicity constraints (pillar_agreement: 'more
    disagreement cannot improve it'; data_completeness: 'restoring data
    cannot reduce it') are documented on each Protocol's own docstring,
    but were never demonstrated with a concrete example proving the
    contract is actually satisfiable and that compute_confidence itself
    doesn't interfere with a compliant estimator's monotonicity — every
    formula here is entirely EMPIRICAL (§17.15, no CLOSED arithmetic
    exists to test numerically), so this demonstrates the SHAPE with an
    obviously-fake but genuinely monotone stub, the same 'proves the seam,
    asserts nothing about a real formula' pattern used throughout this
    engine's test suite."""

    def test_pillar_agreement_monotone_stub_shows_more_disagreement_cannot_improve_it(self):
        """A concrete, deliberately simple monotone-decreasing-in-
        dispersion stub: agreement = 1 - dispersion, clipped to [0,1].
        Sweeping increasing dispersion values must never show an
        INCREASE in the resulting pillar_agreement, proving the contract
        is satisfiable and that compute_confidence passes the estimator's
        output straight through unmodified (no interference)."""
        def _make_estimator(dispersion: float):
            def _ev(as_of):
                return max(0.0, 1.0 - dispersion)
            return _ev

        dispersions = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        agreements = []
        for d in dispersions:
            r = compute_confidence("2020-04-15", _make_estimator(d), _stub_data_completeness, _stub_decision_margin, _stub_temporal_stability)
            agreements.append(r.pillar_agreement)
        for i in range(len(agreements) - 1):
            assert agreements[i] >= agreements[i + 1], (
                f"dispersion {dispersions[i]}->{dispersions[i+1]}: agreement {agreements[i]}->{agreements[i+1]} "
                f"increased with more disagreement"
            )

    def test_data_completeness_monotone_stub_shows_restoring_data_cannot_reduce_it(self):
        """A concrete monotone-increasing-in-coverage stub: completeness
        equals the coverage ratio directly. Sweeping increasing coverage
        (more optional/tier data restored) must never show a DECREASE."""
        def _make_estimator(coverage_ratio: float):
            def _ev(as_of):
                return coverage_ratio
            return _ev

        coverages = [0.0, 0.25, 0.5, 0.75, 1.0]
        completenesses = []
        for c in coverages:
            r = compute_confidence("2020-04-15", _stub_pillar_agreement, _make_estimator(c), _stub_decision_margin, _stub_temporal_stability)
            completenesses.append(r.data_completeness)
        for i in range(len(completenesses) - 1):
            assert completenesses[i] <= completenesses[i + 1], (
                f"coverage {coverages[i]}->{coverages[i+1]}: completeness {completenesses[i]}->{completenesses[i+1]} "
                f"decreased when more data was restored"
            )


# ---------------------------------------------------------------------------
# C15 no-feedback invariant: decision_margin must never drive transitions —
# structural check that no state-machine module imports from confidence.py
# ---------------------------------------------------------------------------

class TestNoFeedbackInvariant:
    """Checks actual `import`/`from ... import` STATEMENTS only, via the
    `ast` module — not a naive whole-file substring search.

    Found a real false-positive during self-review, the same class of bug
    as Stability's `abs(` self-test (Message[175]): a naive `"confidence"
    not in source.lower()` check against whole-file text fails immediately
    on `ordinary_state.py`, which legitimately mentions "module 4.11,
    Confidence" in its own module DOCSTRING (prose describing
    decision_margin's home module) — not a real `import confidence`
    statement. Fixed by parsing each module's AST and checking only actual
    import statement targets, which cannot false-positive on prose."""

    def _imports_confidence(self, path) -> bool:
        import ast
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[-1] == "confidence" for alias in node.names):
                    return True
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[-1] == "confidence":
                    return True
        return False

    def test_no_state_machine_module_imports_from_confidence(self):
        src_dir = REPO_ROOT / "regime/src/v5_1"
        state_machine_modules = ["crisis.py", "ordinary_state.py", "trending.py", "state_machine.py", "condition.py"]
        for name in state_machine_modules:
            path = src_dir / name
            assert path.exists(), f"test setup error: {name} not found"
            assert not self._imports_confidence(path), (
                f"{name} imports from confidence.py — decision_margin (and every other Confidence "
                f"diagnostic) must never drive a state transition (C15)"
            )

    def test_output_assembly_is_a_legitimate_downstream_consumer_of_confidence(self):
        """The flip side of the invariant, made explicit rather than left
        implicit: module 4.12 (Output Assembly) IS expected to import
        Confidence's Result type, since publishing its four diagnostics is
        literally its job — the correct one-way data-flow direction
        (decision logic -> Confidence -> Output Assembly), not a C15
        violation, which is specifically about feeding back INTO decision
        logic.

        Found a real self-review bug in an earlier version of this test
        file (the same discovery made independently in test_impulse.py's
        self-review once output_assembly.py was built in Slice 10): a
        prior `test_no_other_v5_1_module_imports_from_confidence` asserted
        NO module anywhere may import confidence.py, which is broader than
        C15 actually requires and would incorrectly fail once Output
        Assembly legitimately imports Confidence to publish its fields.
        Replaced with this explicit affirmative check instead."""
        src_dir = REPO_ROOT / "regime/src/v5_1"
        path = src_dir / "output_assembly.py"
        if not path.exists():
            pytest.skip("output_assembly.py not yet built")
        assert self._imports_confidence(path), (
            "output_assembly.py is expected to import from confidence.py to publish Confidence's own fields"
        )


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_computation_is_repeatable(self):
        r1 = compute_confidence("2020-04-15", _stub_pillar_agreement, _stub_data_completeness, _stub_decision_margin, _stub_temporal_stability)
        r2 = compute_confidence("2020-04-15", _stub_pillar_agreement, _stub_data_completeness, _stub_decision_margin, _stub_temporal_stability)
        assert r1 == r2
