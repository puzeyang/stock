"""Market Regime v5.1 — Impulse (module 4.9) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_impulse.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.impulse import (  # noqa: E402
    ImpulseEndpoint,
    ImpulseHorizonInputs,
    ImpulseWeights,
    ImpulseResult,
    ImpulseUnavailableError,
    compute_horizon_impulse,
    compute_impulse,
)


def _usable(value: float) -> ImpulseEndpoint:
    return ImpulseEndpoint(value=value, usable=True)


def _unusable() -> ImpulseEndpoint:
    return ImpulseEndpoint(value=None, usable=False)


def _identity_scale(raw_change: float) -> float:
    """Obviously-fake stub proving the injection seam: no scaling at all."""
    return raw_change


def _clip_transform(scaled_change: float) -> float:
    """An obviously-fake but genuinely odd/monotone/zero-preserving/bounded
    stub: clip to [-1, 1]. Proves the seam without asserting a real
    formula (tanh etc. are explicitly benchmark-only per §11)."""
    return max(-1.0, min(1.0, scaled_change))


def _weights(fast=0.6, slow=0.4):
    return ImpulseWeights(weight_fast=fast, weight_slow=slow)


# ---------------------------------------------------------------------------
# ImpulseWeights validation
# ---------------------------------------------------------------------------

class TestImpulseWeights:
    def test_valid_weights_construct(self):
        ImpulseWeights(weight_fast=0.5, weight_slow=0.5)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="sum to exactly 1.0"):
            ImpulseWeights(weight_fast=0.5, weight_slow=0.4)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="nonnegative"):
            ImpulseWeights(weight_fast=-0.1, weight_slow=1.1)


# ---------------------------------------------------------------------------
# compute_horizon_impulse — per-horizon computation and fail-closed behavior
# ---------------------------------------------------------------------------

class TestComputeHorizonImpulse:
    def test_positive_change_gives_positive_impulse(self):
        horizon = ImpulseHorizonInputs(endpoint_t=_usable(0.7), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        result = compute_horizon_impulse(horizon, _identity_scale, _clip_transform)
        assert result > 0

    def test_negative_change_gives_negative_impulse(self):
        horizon = ImpulseHorizonInputs(endpoint_t=_usable(0.3), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        result = compute_horizon_impulse(horizon, _identity_scale, _clip_transform)
        assert result < 0

    def test_unchanged_maps_exactly_to_zero(self):
        """§11: 'unchanged maps exactly to zero.'"""
        horizon = ImpulseHorizonInputs(endpoint_t=_usable(0.5), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        result = compute_horizon_impulse(horizon, _identity_scale, _clip_transform)
        assert result == 0.0

    def test_endpoint_t_unusable_raises(self):
        horizon = ImpulseHorizonInputs(endpoint_t=_unusable(), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        with pytest.raises(ImpulseUnavailableError, match="endpoint_t is not usable"):
            compute_horizon_impulse(horizon, _identity_scale, _clip_transform)

    def test_endpoint_t_minus_h_unusable_raises(self):
        horizon = ImpulseHorizonInputs(endpoint_t=_usable(0.5), endpoint_t_minus_h=_unusable(), interior_all_valid=True)
        with pytest.raises(ImpulseUnavailableError, match="endpoint_t_minus_h is not usable"):
            compute_horizon_impulse(horizon, _identity_scale, _clip_transform)

    def test_stale_but_present_value_is_still_unavailable(self):
        """A key case per the module's own docstring: usable=False must be
        authoritative REGARDLESS of whether `value` looks numerically
        fine — a stale-but-numerically-present endpoint must still raise,
        not silently compute from the stale value."""
        stale_but_present = ImpulseEndpoint(value=0.5, usable=False)
        horizon = ImpulseHorizonInputs(endpoint_t=_usable(0.7), endpoint_t_minus_h=stale_but_present, interior_all_valid=True)
        with pytest.raises(ImpulseUnavailableError):
            compute_horizon_impulse(horizon, _identity_scale, _clip_transform)

    def test_invalid_interior_session_raises_even_with_both_endpoints_usable(self):
        """The Message[162] correction's core case: BOTH endpoints usable,
        but an interior session invalid — must still be unavailable, not
        silently computed as if only endpoints mattered."""
        horizon = ImpulseHorizonInputs(endpoint_t=_usable(0.7), endpoint_t_minus_h=_usable(0.5), interior_all_valid=False)
        with pytest.raises(ImpulseUnavailableError, match="interior sessions"):
            compute_horizon_impulse(horizon, _identity_scale, _clip_transform)

    def test_sign_consistency_across_many_synthetic_pairs(self):
        """§11: 'sign(impulse_h) = sign(condition_t - condition_t-h) when
        nonzero' — swept across several (t, t-h) pairs, not just one."""
        pairs = [(0.9, 0.1), (0.1, 0.9), (0.5, 0.5), (1.0, 0.0), (0.0, 1.0), (0.3, 0.30000001)]
        for t, t_minus_h in pairs:
            horizon = ImpulseHorizonInputs(endpoint_t=_usable(t), endpoint_t_minus_h=_usable(t_minus_h), interior_all_valid=True)
            result = compute_horizon_impulse(horizon, _identity_scale, _clip_transform)
            raw_change = t - t_minus_h
            if raw_change > 0:
                assert result > 0, f"t={t}, t-h={t_minus_h}: expected positive impulse"
            elif raw_change < 0:
                assert result < 0, f"t={t}, t-h={t_minus_h}: expected negative impulse"
            else:
                assert result == 0.0

    def test_equal_and_opposite_paths_give_equal_and_opposite_impulse(self):
        """Golden-vector requirement (plan §6/design §14.1): 'equal/
        opposite paths.' A gap found during Slice 12's conformance
        review: a rise of magnitude X and a fall of the SAME magnitude X
        must produce impulse values that are exact negatives of each
        other — not merely 'both nonzero with the correct sign'
        (test_sign_consistency above), but a proven magnitude symmetry."""
        rising = ImpulseHorizonInputs(endpoint_t=_usable(0.7), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        falling = ImpulseHorizonInputs(endpoint_t=_usable(0.5), endpoint_t_minus_h=_usable(0.7), interior_all_valid=True)
        rising_impulse = compute_horizon_impulse(rising, _identity_scale, _clip_transform)
        falling_impulse = compute_horizon_impulse(falling, _identity_scale, _clip_transform)
        assert rising_impulse == pytest.approx(-falling_impulse)

    def test_monotone_rising_path_across_multiple_horizons_gives_consistent_positive_impulse(self):
        """Golden-vector requirement: 'monotone paths.' A genuinely
        monotone increasing condition_score sequence (0.1, 0.3, 0.5, 0.7,
        0.9) checked across two different horizon lengths from the same
        endpoint — both must show positive impulse, matching the
        monotone direction, and the LONGER horizon (larger net move) must
        show a impulse based on a larger raw change than the shorter one."""
        path = [0.1, 0.3, 0.5, 0.7, 0.9]
        short_horizon = ImpulseHorizonInputs(endpoint_t=_usable(path[-1]), endpoint_t_minus_h=_usable(path[-2]), interior_all_valid=True)
        long_horizon = ImpulseHorizonInputs(endpoint_t=_usable(path[-1]), endpoint_t_minus_h=_usable(path[0]), interior_all_valid=True)
        short_impulse = compute_horizon_impulse(short_horizon, _identity_scale, _clip_transform)
        long_impulse = compute_horizon_impulse(long_horizon, _identity_scale, _clip_transform)
        assert short_impulse > 0
        assert long_impulse > 0
        assert long_impulse > short_impulse  # larger net move over the longer horizon

    def test_saturation_extreme_change_clips_to_the_transform_bound(self):
        """Golden-vector requirement: 'saturation.' An extreme raw change
        (far beyond the transform's own bound) must clip to exactly the
        transform's boundary value, not overflow or produce an
        out-of-range result — proving the 'symmetrically bounded' (§11)
        contract actually holds at the extreme, not just for
        moderate values."""
        extreme_rise = ImpulseHorizonInputs(endpoint_t=_usable(1000.0), endpoint_t_minus_h=_usable(-1000.0), interior_all_valid=True)
        extreme_fall = ImpulseHorizonInputs(endpoint_t=_usable(-1000.0), endpoint_t_minus_h=_usable(1000.0), interior_all_valid=True)
        assert compute_horizon_impulse(extreme_rise, _identity_scale, _clip_transform) == 1.0
        assert compute_horizon_impulse(extreme_fall, _identity_scale, _clip_transform) == -1.0


# ---------------------------------------------------------------------------
# compute_impulse — full aggregate
# ---------------------------------------------------------------------------

class TestComputeImpulse:
    def test_aggregate_is_weighted_sum_of_horizon_impulses(self):
        fast = ImpulseHorizonInputs(endpoint_t=_usable(0.8), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        slow = ImpulseHorizonInputs(endpoint_t=_usable(0.8), endpoint_t_minus_h=_usable(0.3), interior_all_valid=True)
        weights = _weights(fast=0.6, slow=0.4)
        r = compute_impulse("2020-04-15", fast, slow, _identity_scale, _clip_transform, weights)
        assert isinstance(r, ImpulseResult)
        expected = 0.6 * r.impulse_fast + 0.4 * r.impulse_slow
        assert r.impulse_score == pytest.approx(expected)

    def test_aggregate_stays_within_bounded_range_when_horizons_are_bounded(self):
        """A convex combination (nonnegative weights summing to one) of two
        values each in [-1,1] must itself stay in [-1,1] — verified
        directly, not just assumed from the arithmetic."""
        fast = ImpulseHorizonInputs(endpoint_t=_usable(100.0), endpoint_t_minus_h=_usable(-100.0), interior_all_valid=True)
        slow = ImpulseHorizonInputs(endpoint_t=_usable(-100.0), endpoint_t_minus_h=_usable(100.0), interior_all_valid=True)
        weights = _weights(fast=0.3, slow=0.7)
        r = compute_impulse("2020-04-15", fast, slow, _identity_scale, _clip_transform, weights)
        assert -1.0 <= r.impulse_score <= 1.0
        assert r.impulse_fast == 1.0  # clipped
        assert r.impulse_slow == -1.0  # clipped

    def test_fast_horizon_unavailable_raises(self):
        fast = ImpulseHorizonInputs(endpoint_t=_unusable(), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        slow = ImpulseHorizonInputs(endpoint_t=_usable(0.8), endpoint_t_minus_h=_usable(0.3), interior_all_valid=True)
        with pytest.raises(ImpulseUnavailableError):
            compute_impulse("2020-04-15", fast, slow, _identity_scale, _clip_transform, _weights())

    def test_slow_horizon_unavailable_raises(self):
        fast = ImpulseHorizonInputs(endpoint_t=_usable(0.8), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        slow = ImpulseHorizonInputs(endpoint_t=_usable(0.8), endpoint_t_minus_h=_unusable(), interior_all_valid=True)
        with pytest.raises(ImpulseUnavailableError):
            compute_impulse("2020-04-15", fast, slow, _identity_scale, _clip_transform, _weights())


# ---------------------------------------------------------------------------
# C14 no-feedback invariant: structural check that no other module reads
# from impulse.py
# ---------------------------------------------------------------------------

class TestNoFeedbackInvariant:
    """Checks actual `import`/`from ... import` STATEMENTS only, via the
    `ast` module — not a naive whole-file substring search.

    Found a real false-positive during self-review (once confidence.py was
    added in the same slice, its own module docstring mentions "Impulse"
    in prose describing C14/C15's shared no-feedback pattern): a naive
    `"impulse" not in source.lower()` check against whole-file text fails
    on any module whose comments/docstrings merely MENTION Impulse by
    name, not just one that actually imports it. Fixed by parsing each
    module's AST and checking only actual import statement targets.

    **Found a SECOND, more substantive self-review bug once Slice 10 added
    `output_assembly.py`**: the AST-based check (correct in itself) was
    still applied too broadly — it asserted NO module anywhere may import
    Impulse, but C14's actual invariant is narrower: "Impulse never feeds
    CONDITION, CAPS, VETOES, COUNTERS, OR STATE" — a one-way constraint on
    the UPSTREAM decision-logic modules (condition.py/crisis.py/
    ordinary_state.py/trending.py/state_machine.py), not a blanket ban on
    every module in the codebase ever importing impulse.py. Module 4.12
    (Output Assembly) is explicitly DOWNSTREAM of everything per the
    plan's own dependency order, and its entire job is to read already-
    finalized Impulse/Confidence results for publication — that is the
    expected, correct data-flow direction, not a violation. Fixed by
    scoping the check to the actual decision-logic module list instead of
    every module in the directory."""

    DECISION_LOGIC_MODULES = ["crisis.py", "ordinary_state.py", "trending.py", "state_machine.py", "condition.py"]

    def _imports_impulse(self, path) -> bool:
        import ast
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[-1] == "impulse" for alias in node.names):
                    return True
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[-1] == "impulse":
                    return True
        return False

    def test_no_decision_logic_module_imports_from_impulse(self):
        """§11/C14: 'Impulse never feeds Condition, caps, vetoes, counters,
        or state.' Enforced by omission on the specific set of modules
        that make those decisions — verified against each one's actual
        import statements."""
        src_dir = REPO_ROOT / "regime/src/v5_1"
        for name in self.DECISION_LOGIC_MODULES:
            path = src_dir / name
            assert path.exists(), f"test setup error: {name} not found"
            assert not self._imports_impulse(path), (
                f"{name} imports from impulse.py — Impulse must never feed back into "
                f"Condition, caps, vetoes, counters, or state (C14)"
            )

    def test_output_assembly_is_a_legitimate_downstream_consumer_of_impulse(self):
        """The flip side of the invariant, made explicit rather than left
        implicit: module 4.12 (Output Assembly) IS expected to import
        Impulse's Result type, since publishing Impulse's own fields is
        literally its job — this is the correct one-way data-flow
        direction (decision logic -> Impulse -> Output Assembly), not a
        violation of C14, which is specifically about feeding back INTO
        decision logic."""
        src_dir = REPO_ROOT / "regime/src/v5_1"
        path = src_dir / "output_assembly.py"
        if not path.exists():
            pytest.skip("output_assembly.py not yet built")
        assert self._imports_impulse(path), (
            "output_assembly.py is expected to import from impulse.py to publish Impulse's own fields"
        )


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_computation_is_repeatable(self):
        fast = ImpulseHorizonInputs(endpoint_t=_usable(0.8), endpoint_t_minus_h=_usable(0.5), interior_all_valid=True)
        slow = ImpulseHorizonInputs(endpoint_t=_usable(0.8), endpoint_t_minus_h=_usable(0.3), interior_all_valid=True)
        weights = _weights()
        r1 = compute_impulse("2020-04-15", fast, slow, _identity_scale, _clip_transform, weights)
        r2 = compute_impulse("2020-04-15", fast, slow, _identity_scale, _clip_transform, weights)
        assert r1 == r2
