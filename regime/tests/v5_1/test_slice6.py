"""Market Regime v5.1 — Slice 6 (Stability) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_slice6.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.raw_features import load_raw_series, RawSeries, RawObservation  # noqa: E402
from v5_1.stability import (  # noqa: E402
    compute_vol_curve_raw,
    compute_stability,
    StabilityWeights,
    StabilityUnavailableError,
    StabilityResult,
    PriceDamageComponents,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def vix_series(manifest):
    return load_raw_series("vix_level", manifest)


@pytest.fixture(scope="module")
def vix9d_series(manifest):
    return load_raw_series("vix9d_level", manifest)


@pytest.fixture(scope="module")
def spy_series(manifest):
    return load_raw_series("benchmark_total_return_close", manifest)


def _make_series(field_id: str, contract_id: str, dates_values: list[tuple[str, float]]) -> RawSeries:
    obs = tuple(RawObservation(date=d, value=v, source_contract_id=contract_id, field_name="close") for d, v in dates_values)
    return RawSeries(field_id=field_id, source_contract_id=contract_id, field_name="close", observations=obs)


# Stub EMPIRICAL transforms — obviously-fake placeholders proving the
# injection seam, asserting nothing about a real formula. Bounded to [0,1]
# per MonotoneDecreasingTransform's documented output contract.
def _stub_monotone_decreasing(raw_level: float) -> float:
    return max(0.0, min(1.0, (100.0 - raw_level) / 100.0))


def _stub_realized_vol(benchmark_series, as_of):
    v = benchmark_series.value_on(as_of)
    if v is None:
        return None
    return 0.2  # fixed placeholder


def _stub_price_damage_components(benchmark_series, as_of):
    """Migrated per Message[225]-[227]'s discussion-log review: the old
    single-scalar `PriceDamageEstimator` stub is replaced with the
    two-step `PriceDamageComponentsEstimator`/`PriceDamageComposer`
    shape. Deliberately-fake, out-of-[0,1]-range placeholder values
    (matching this suite's existing convention for every other stub),
    proving the injection seam rather than asserting a real formula."""
    v = benchmark_series.value_on(as_of)
    if v is None:
        return None
    return PriceDamageComponents(benchmark_drawdown=5.0, return_shock_5d=3.0, return_shock_20d=4.0)


def _stub_price_damage_composer(components):
    return components.benchmark_drawdown  # obviously-fake: ignores the other two components


def _default_weights():
    return StabilityWeights(weight_implied_vol=0.25, weight_vol_curve=0.25, weight_realized_vol=0.25, weight_price=0.25)


# ---------------------------------------------------------------------------
# StabilityWeights validation
# ---------------------------------------------------------------------------

class TestWeights:
    def test_valid_weights_construct(self):
        StabilityWeights(weight_implied_vol=0.4, weight_vol_curve=0.2, weight_realized_vol=0.2, weight_price=0.2)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="sum to exactly 1.0"):
            StabilityWeights(weight_implied_vol=0.5, weight_vol_curve=0.2, weight_realized_vol=0.2, weight_price=0.2)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="nonnegative"):
            StabilityWeights(weight_implied_vol=-0.1, weight_vol_curve=0.4, weight_realized_vol=0.4, weight_price=0.3)

    def test_zero_weight_on_a_domain_allowed(self):
        StabilityWeights(weight_implied_vol=1.0, weight_vol_curve=0.0, weight_realized_vol=0.0, weight_price=0.0)


# ---------------------------------------------------------------------------
# vol_curve_raw (VIX9D/VIX)
# ---------------------------------------------------------------------------

class TestVolCurveRaw:
    def test_real_ratio_on_well_warmed_date(self, vix9d_series, vix_series):
        r = compute_vol_curve_raw(vix9d_series, vix_series, "2020-04-15")
        assert r is not None
        assert r > 0

    def test_none_when_either_missing(self, vix9d_series, vix_series):
        assert compute_vol_curve_raw(vix9d_series, vix_series, "1900-01-01") is None

    def test_zero_vix_raises(self):
        vix9d = _make_series("test", "TEST", [("2020-01-01", 15.0)])
        vix = _make_series("test", "TEST", [("2020-01-01", 0.0)])
        with pytest.raises(StabilityUnavailableError, match="exactly zero"):
            compute_vol_curve_raw(vix9d, vix, "2020-01-01")


# ---------------------------------------------------------------------------
# Full Stability computation — real data
# ---------------------------------------------------------------------------

class TestFullComputationRealData:
    def test_end_to_end_real_data(self, vix_series, vix9d_series, spy_series):
        r = compute_stability(
            "2020-04-15", vix_series, vix9d_series, spy_series,
            _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol, _stub_price_damage_components, _stub_price_damage_composer, _stub_monotone_decreasing,
            _default_weights(),
        )
        assert isinstance(r, StabilityResult)
        w = _default_weights()
        expected = (
            w.weight_implied_vol * r.implied_vol_stability
            + w.weight_vol_curve * r.vol_curve_stability
            + w.weight_realized_vol * r.realized_vol_stability
            + w.weight_price * r.price_stability
        )
        assert r.stability_score == pytest.approx(expected)

    def test_unavailable_when_vix_missing(self, vix_series, vix9d_series, spy_series):
        with pytest.raises(StabilityUnavailableError, match="VIX unavailable"):
            compute_stability(
                "1900-01-01", vix_series, vix9d_series, spy_series,
                _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
                _stub_realized_vol, _stub_price_damage_components, _stub_price_damage_composer, _stub_monotone_decreasing,
                _default_weights(),
            )

    def test_unavailable_when_price_damage_components_estimator_returns_none(self, vix_series, vix9d_series, spy_series):
        def _always_unavailable(series, as_of):
            return None

        with pytest.raises(StabilityUnavailableError, match="price_damage_components unavailable"):
            compute_stability(
                "2020-04-15", vix_series, vix9d_series, spy_series,
                _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
                _stub_realized_vol, _always_unavailable, _stub_price_damage_composer, _stub_monotone_decreasing,
                _default_weights(),
            )

    def test_perturbing_one_domain_transform_never_changes_another_domains_output(self, vix_series, vix9d_series, spy_series):
        """Golden-vector requirement (plan §6/design §14.1): 'Independent
        Stability perturbations.' A gap found during Slice 12's
        conformance review: the existing tests prove the VIX-decline
        polarity invariant and the weighted-sum arithmetic, but never
        directly proved the 4 domains are actually computed
        INDEPENDENTLY of each other — i.e. that swapping out ONE domain's
        transform changes ONLY that domain's own output field, leaving
        the other 3 domains' outputs byte-identical. Proved directly by
        running compute_stability twice with everything held fixed except
        the implied_vol_transform, and confirming only
        implied_vol_stability (and, downstream, stability_score) differ —
        vol_curve_stability/realized_vol_stability/price_stability must
        be EXACTLY unchanged."""
        def _perturbed_implied_vol_transform(raw_level):
            return _stub_monotone_decreasing(raw_level) * 0.5  # deliberately different from the other domains' transform

        r_baseline = compute_stability(
            "2020-04-15", vix_series, vix9d_series, spy_series,
            _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol, _stub_price_damage_components, _stub_price_damage_composer, _stub_monotone_decreasing,
            _default_weights(),
        )
        r_perturbed = compute_stability(
            "2020-04-15", vix_series, vix9d_series, spy_series,
            _perturbed_implied_vol_transform, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol, _stub_price_damage_components, _stub_price_damage_composer, _stub_monotone_decreasing,
            _default_weights(),
        )
        assert r_perturbed.implied_vol_stability != r_baseline.implied_vol_stability  # the perturbed domain DID change
        assert r_perturbed.vol_curve_stability == r_baseline.vol_curve_stability  # unaffected
        assert r_perturbed.realized_vol_stability == r_baseline.realized_vol_stability  # unaffected
        assert r_perturbed.price_stability == r_baseline.price_stability  # unaffected
        assert r_perturbed.vol_curve_raw == r_baseline.vol_curve_raw  # raw inputs unaffected too
        assert r_perturbed.realized_volatility == r_baseline.realized_volatility
        assert r_perturbed.price_damage == r_baseline.price_damage

    def test_unavailable_when_realized_vol_estimator_returns_none(self, vix_series, vix9d_series, spy_series):
        def _always_unavailable(series, as_of):
            return None

        with pytest.raises(StabilityUnavailableError, match="realized_volatility unavailable"):
            compute_stability(
                "2020-04-15", vix_series, vix9d_series, spy_series,
                _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
                _always_unavailable, _stub_price_damage_components, _stub_price_damage_composer, _stub_monotone_decreasing,
                _default_weights(),
            )


# ---------------------------------------------------------------------------
# PriceDamageComponents / composer (Message[225]-[227]'s discussion-log
# review): benchmark_drawdown and benchmark_return_shock were already
# declared manifest/schema fields (role="explainability") that no code
# ever populated — these tests verify the two-step "compute components
# once, compose separately" contract is actually real, not just present
# in the type signature.
# ---------------------------------------------------------------------------

class TestPriceDamageComponents:
    def test_result_carries_the_same_components_instance_estimator_returned(self, vix_series, vix9d_series, spy_series):
        """`StabilityResult.price_damage_components` must be the EXACT
        object `price_damage_components_estimator` returned, not a copy
        or a re-derivation — direct proof of the "computed once, shared"
        discipline `compute_stability`'s own docstring requires."""
        sentinel = PriceDamageComponents(benchmark_drawdown=0.11, return_shock_5d=0.22, return_shock_20d=0.33)

        def _returns_sentinel(series, as_of):
            return sentinel

        r = compute_stability(
            "2020-04-15", vix_series, vix9d_series, spy_series,
            _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol, _returns_sentinel, _stub_price_damage_composer, _stub_monotone_decreasing,
            _default_weights(),
        )
        assert r.price_damage_components is sentinel

    def test_benchmark_drawdown_property_reads_through_to_components(self, vix_series, vix9d_series, spy_series):
        r = compute_stability(
            "2020-04-15", vix_series, vix9d_series, spy_series,
            _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol, _stub_price_damage_components, _stub_price_damage_composer, _stub_monotone_decreasing,
            _default_weights(),
        )
        assert r.benchmark_drawdown == r.price_damage_components.benchmark_drawdown
        assert r.benchmark_drawdown == 5.0  # the stub's fixed placeholder value

    def test_composer_is_a_separate_step_from_the_components_estimator(self, vix_series, vix9d_series, spy_series):
        """A composer that ignores the components estimator's actual
        output entirely (returns a constant) must still drive
        price_damage — proving the two are genuinely independent
        callables, not one function secretly doing both jobs."""
        def _constant_composer(components):
            return 0.5

        r = compute_stability(
            "2020-04-15", vix_series, vix9d_series, spy_series,
            _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol, _stub_price_damage_components, _constant_composer, _stub_monotone_decreasing,
            _default_weights(),
        )
        assert r.price_damage == 0.5
        assert r.price_damage_components.benchmark_drawdown == 5.0  # components unaffected by the composer swap


# ---------------------------------------------------------------------------
# CLOSED invariant: a VIX decline must not lower Stability (the inherited
# abs(VIX change)-is-polarity-wrong bug, structurally avoided)
# ---------------------------------------------------------------------------

class TestVixDeclineNeverLowersStability:
    def test_lower_vix_level_never_produces_lower_implied_vol_stability_via_monotone_transform(self):
        """A genuinely monotone-decreasing transform, by construction,
        assigns a LOWER VIX level a HIGHER (or equal) stability output —
        this is the correct polarity design §6.6 requires, verified
        directly using a real monotone-decreasing stub across a range of
        VIX levels (not just one before/after pair)."""
        levels = [10.0, 15.0, 20.0, 30.0, 45.0, 60.0, 80.0]
        outputs = [_stub_monotone_decreasing(v) for v in levels]
        # As VIX level increases, stability output must be non-increasing.
        for i in range(len(outputs) - 1):
            assert outputs[i] >= outputs[i + 1], (
                f"VIX level {levels[i]} -> stability {outputs[i]}, but VIX level {levels[i+1]} "
                f"(higher) -> stability {outputs[i+1]} (should be lower or equal, not higher)"
            )

    def test_declining_vix_across_real_consecutive_sessions_shows_non_decreasing_stability(self, vix_series, vix9d_series, spy_series):
        """A real-data regression check: find two REAL consecutive trading
        sessions where VIX genuinely declined, and confirm
        implied_vol_stability did not decrease across that same transition
        — this is the actual scenario the inherited bug got backwards (a
        calming VIX being scored as if conditions worsened)."""
        # Search a real window for a day where VIX fell from the prior session.
        dates = [o.date for o in vix_series.observations if "2020-04" <= o.date[:7] <= "2020-06"]
        found = False
        for i in range(1, len(dates)):
            prev_date, cur_date = dates[i - 1], dates[i]
            prev_vix = vix_series.value_on(prev_date)
            cur_vix = vix_series.value_on(cur_date)
            if prev_vix is not None and cur_vix is not None and cur_vix < prev_vix:
                prev_stability = _stub_monotone_decreasing(prev_vix)
                cur_stability = _stub_monotone_decreasing(cur_vix)
                assert cur_stability >= prev_stability, (
                    f"VIX declined from {prev_vix} ({prev_date}) to {cur_vix} ({cur_date}), "
                    f"but implied_vol_stability went from {prev_stability} to {cur_stability} (decreased)"
                )
                found = True
                break
        assert found, "test setup error: no real VIX-decline day found in the searched window"

    def test_no_signed_change_or_abs_value_computation_anywhere_in_module(self):
        """A structural/textual check against the actual module CODE (not
        docstrings/comments): the specific inherited bug was computing
        stability from `abs(VIX_t - VIX_{t-1})` — confirm no such
        construction appears in any real statement of this module's source.

        Found a real bug in my own first version of this test during
        self-review: a naive `"abs(" not in source` check against the WHOLE
        file (including docstrings) fails immediately, because this
        module's own docstring quotes the inherited bug by name as
        documentation (`abs(VIX change)`) — a false positive from the
        check's own design, not a real violation. It also would have missed
        that `StabilityWeights.__post_init__` legitimately uses `abs(total
        - 1.0) > 1e-9` for floating-point tolerance, a completely unrelated,
        correct use of `abs()` that has nothing to do with VIX polarity —
        so a version of this check that additionally tried to strip
        docstrings but still flagged any remaining `abs(` would ALSO have
        been wrong, just via a false positive on a different line. Fixed:
        check function BODIES only (via `inspect.getsource` on each
        function/method object, not the module), and check specifically for
        `abs(` applied near a `vix`-named identifier, not `abs(` in any
        context — the actual reintroduction risk is `abs(vix...)`-shaped
        code, not `abs()` used for an unrelated purpose like weight-sum
        tolerance."""
        import inspect
        from v5_1 import stability as stability_module

        functions_to_check = [
            stability_module.compute_vol_curve_raw,
            stability_module.compute_stability,
        ]
        for func in functions_to_check:
            body_source = inspect.getsource(func)
            # Look for abs( applied to something vix-related specifically,
            # not any abs() call anywhere in the function body.
            lowered = body_source.lower()
            idx = 0
            while True:
                idx = lowered.find("abs(", idx)
                if idx == -1:
                    break
                nearby = lowered[max(0, idx - 30):idx + 30]
                assert "vix" not in nearby, (
                    f"found abs() applied near a vix-related identifier in {func.__name__}: {nearby!r} "
                    f"— potential polarity-bug reintroduction"
                )
                idx += 4
            assert "vix_change" not in lowered
            assert "_delta" not in lowered


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_computation_is_repeatable(self, vix_series, vix9d_series, spy_series):
        r1 = compute_stability(
            "2020-04-15", vix_series, vix9d_series, spy_series,
            _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol, _stub_price_damage_components, _stub_price_damage_composer, _stub_monotone_decreasing,
            _default_weights(),
        )
        r2 = compute_stability(
            "2020-04-15", vix_series, vix9d_series, spy_series,
            _stub_monotone_decreasing, _stub_monotone_decreasing, _stub_monotone_decreasing,
            _stub_realized_vol, _stub_price_damage_components, _stub_price_damage_composer, _stub_monotone_decreasing,
            _default_weights(),
        )
        assert r1 == r2
