"""Market Regime v5.1 — Slice 5 (Risk Appetite) test suite.

Solo review context: ChatGPT is unavailable; this suite is the adversarial
self-review pass in its place, per the human's Message[170] direction.

Run with: python3 -m pytest regime/tests/v5_1/test_slice5.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.raw_features import load_raw_series, RawSeries, RawObservation  # noqa: E402
from v5_1.normalization import REQUIRED_WINDOW_SIZE  # noqa: E402
from v5_1.risk_appetite import (  # noqa: E402
    compute_rotation_raw,
    compute_rotation_pct,
    compute_risk_appetite,
    RiskAppetiteWeights,
    RiskAppetiteUnavailableError,
    RiskAppetiteResult,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


@pytest.fixture(scope="module")
def qqq_series(manifest):
    return load_raw_series("qqq_total_return_close", manifest)


@pytest.fixture(scope="module")
def iwm_series(manifest):
    return load_raw_series("iwm_total_return_close", manifest)


@pytest.fixture(scope="module")
def spy_series(manifest):
    return load_raw_series("benchmark_total_return_close", manifest)


@pytest.fixture(scope="module")
def oas_series(manifest):
    return load_raw_series("oas_level", manifest)


def _stub_credit_transform(oas_series, as_of):
    """An obviously-fake stub for the EMPIRICAL credit transform interface —
    proves the injection seam, asserts nothing about a real formula."""
    v = oas_series.value_on(as_of)
    if v is None:
        return None
    return (0.5, 0.0)  # fixed placeholder values ([0,1] scale), deliberately not meaningful


def _make_series(field_id: str, contract_id: str, dates_values: list[tuple[str, float]]) -> RawSeries:
    obs = tuple(RawObservation(date=d, value=v, source_contract_id=contract_id, field_name="close") for d, v in dates_values)
    return RawSeries(field_id=field_id, source_contract_id=contract_id, field_name="close", observations=obs)


# ---------------------------------------------------------------------------
# RiskAppetiteWeights validation
# ---------------------------------------------------------------------------

class TestWeights:
    def test_valid_weights_construct(self):
        RiskAppetiteWeights(weight_credit=0.4, weight_growth_rotation=0.3, weight_small_cap_rotation=0.3)

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="sum to exactly 1.0"):
            RiskAppetiteWeights(weight_credit=0.5, weight_growth_rotation=0.3, weight_small_cap_rotation=0.3)

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="nonnegative"):
            RiskAppetiteWeights(weight_credit=-0.1, weight_growth_rotation=0.6, weight_small_cap_rotation=0.5)

    def test_zero_weight_on_a_component_allowed(self):
        """Design §6.5: 'Zero production weights are allowed by empirical
        disposition while diagnostics remain published.'"""
        RiskAppetiteWeights(weight_credit=1.0, weight_growth_rotation=0.0, weight_small_cap_rotation=0.0)


# ---------------------------------------------------------------------------
# Rotation raw ratio — real data
# ---------------------------------------------------------------------------

class TestRotationRaw:
    def test_real_ratio_on_well_warmed_date(self, qqq_series, spy_series):
        r = compute_rotation_raw(qqq_series, spy_series, "2020-04-15")
        assert r is not None
        assert r > 0  # both series are positive-valued prices

    def test_none_when_numerator_missing(self, qqq_series, spy_series):
        assert compute_rotation_raw(qqq_series, spy_series, "1900-01-01") is None

    def test_zero_denominator_raises(self):
        num = _make_series("test", "TEST", [("2020-01-01", 5.0)])
        denom = _make_series("test", "TEST", [("2020-01-01", 0.0)])
        with pytest.raises(RiskAppetiteUnavailableError, match="exactly zero"):
            compute_rotation_raw(num, denom, "2020-01-01")


# ---------------------------------------------------------------------------
# Rotation percentile — the exact causal-504-midrank requirement
# ---------------------------------------------------------------------------

class TestRotationPercentile:
    def test_real_percentile_is_in_valid_range(self, qqq_series, spy_series):
        raw, pct = compute_rotation_pct(qqq_series, spy_series, "2020-04-15")
        assert raw is not None
        assert pct is not None
        assert 0.0 <= pct <= 1.0

    def test_covid_recovery_shows_high_growth_rotation_percentile(self, qqq_series, spy_series):
        """A real-world sanity check: QQQ dramatically outperformed SPY
        during the April 2020 tech-led recovery — the percentile should be
        high (top of its own 504-session distribution), not merely 'a
        number in range.'"""
        raw, pct = compute_rotation_pct(qqq_series, spy_series, "2020-04-15")
        assert pct > 0.9

    def test_insufficient_history_gives_raw_but_no_pct(self, qqq_series, spy_series):
        """A real, distinguishable partial-unavailability case: the current
        ratio exists, but there isn't yet a full 504-session window to rank
        it against."""
        raw, pct = compute_rotation_pct(qqq_series, spy_series, "1999-06-01")
        assert raw is not None
        assert pct is None

    def test_no_current_observation_gives_none_and_none(self, qqq_series, spy_series):
        raw, pct = compute_rotation_pct(qqq_series, spy_series, "1900-01-01")
        assert raw is None
        assert pct is None

    def test_mismatched_window_dates_fail_closed(self):
        """Two series whose 504-length windows don't align date-for-date
        (a gap in one but not the other) must fail closed (pct=None), never
        silently pair mismatched dates into a corrupted ratio series."""
        # numerator has a gap the denominator doesn't
        dates_num = [(f"2020-{(i//28)+1:02d}-{(i%28)+1:02d}", 10.0) for i in range(REQUIRED_WINDOW_SIZE)]
        dates_denom = [(f"2020-{(i//28)+1:02d}-{(i%28)+1:02d}", 5.0) for i in range(REQUIRED_WINDOW_SIZE)]
        # remove one date from the numerator only, breaking alignment
        dates_num_broken = dates_num[:-2] + dates_num[-1:]
        num = _make_series("test", "TEST", dates_num_broken)
        denom = _make_series("test", "TEST", dates_denom)
        as_of = dates_denom[-1][0]
        raw, pct = compute_rotation_pct(num, denom, as_of)
        # raw may or may not be None depending on whether as_of itself is
        # present in the broken numerator series; the key assertion is pct.
        assert pct is None


# ---------------------------------------------------------------------------
# CLOSED invariant: no gating or sign flip by benchmark return
# ---------------------------------------------------------------------------

class TestNoSignFlipInvariant:
    def test_rotation_percentile_identical_regardless_of_benchmark_direction(self):
        """The core CLOSED invariant from design §6.5: rotation validity
        does not depend on whether the benchmark itself rose or fell.
        Constructs two scenarios with IDENTICAL relative-performance shape
        (numerator consistently outperforming denominator by the same
        multiplicative factor throughout) but opposite absolute benchmark
        direction (rising vs. falling), and proves the rotation percentile
        is byte-identical in both — the ratio, and therefore the midrank
        percentile, only depends on relative performance, never on the
        benchmark's own sign."""
        n = REQUIRED_WINDOW_SIZE
        import datetime
        base = datetime.date(2015, 1, 1)
        real_dates = []
        d = base
        while len(real_dates) < n + 1:
            if d.weekday() < 5:
                real_dates.append(d.isoformat())
            d += datetime.timedelta(days=1)

        # Rising benchmark: denom goes from 100 up to 100+n (linear, stays
        # positive throughout). Falling benchmark: denom counts DOWN from a
        # high starting point by the same linear step, staying positive for
        # the whole window (n+1 steps down from 100000 never approaches 0).
        # Both use denom values that are exact powers-of-two-friendly
        # integers-as-floats and a numerator built as an EXACT integer
        # multiple (3x, not 1.5x) of the denominator, so `numerator/denom`
        # round-trips to precisely the same float for every observation —
        # avoiding floating-point noise entirely rather than fighting it.
        #
        # This replaced two earlier broken attempts, both found during
        # self-review: (1) `200.0 - i` goes NEGATIVE partway through a
        # 504-length window (a nonsensical price series), silently producing
        # a None midrank result via a zero/negative-denominator guard firing
        # mid-window; (2) `200.0 * (0.999**i)` stays positive but its
        # repeated-multiplication float noise meant `numerator/denom` did
        # NOT round-trip to a bit-identical ratio at every index (min/max
        # ratio measured at 1.4999999999999998 / 1.5000000000000002 across
        # the window), which broke the "all-ties" assumption the test relied
        # on and produced a genuinely different midrank (47.9 vs 50.0) that
        # looked like — but was not — evidence of a real asymmetry.
        rising_denom = [(real_dates[i], 100.0 + i) for i in range(n + 1)]
        rising_num = [(real_dates[i], 3.0 * (100.0 + i)) for i in range(n + 1)]

        falling_denom = [(real_dates[i], 100000.0 - i) for i in range(n + 1)]
        falling_num = [(real_dates[i], 3.0 * (100000.0 - i)) for i in range(n + 1)]

        rising_denom_series = _make_series("test", "TEST", rising_denom)
        rising_num_series = _make_series("test", "TEST", rising_num)
        falling_denom_series = _make_series("test", "TEST", falling_denom)
        falling_num_series = _make_series("test", "TEST", falling_num)

        as_of = real_dates[-1]
        raw_rise, pct_rise = compute_rotation_pct(rising_num_series, rising_denom_series, as_of)
        raw_fall, pct_fall = compute_rotation_pct(falling_num_series, falling_denom_series, as_of)

        # Both scenarios have a CONSTANT 1.5x ratio throughout (outperformance
        # is uniform), so the ratio itself is flat and the midrank should be
        # the same (50th percentile via the all-ties formula) in both — the
        # benchmark's absolute direction (rising vs falling) must not affect
        # this at all.
        assert raw_rise == pytest.approx(3.0)
        assert raw_fall == pytest.approx(3.0)
        assert pct_rise == pytest.approx(pct_fall)
        assert pct_rise == pytest.approx(0.5)  # constant ratio -> all-ties -> 50th percentile -> 0.5 on [0,1]

    def test_compute_rotation_raw_has_no_benchmark_sign_parameter(self):
        """A structural check: the function signature itself has no
        parameter through which a benchmark-direction sign could be passed
        in and branched on — this is a code-shape assertion, not a runtime
        behavior assertion, confirming the invariant is enforced by omission
        rather than by a conditional that could be bypassed."""
        import inspect
        sig = inspect.signature(compute_rotation_raw)
        param_names = set(sig.parameters.keys())
        assert "benchmark_sign" not in param_names
        assert "sign" not in param_names
        assert "direction" not in param_names


# ---------------------------------------------------------------------------
# Full Risk Appetite computation
# ---------------------------------------------------------------------------

class TestFullComputation:
    def test_end_to_end_real_data(self, oas_series, qqq_series, iwm_series, spy_series):
        weights = RiskAppetiteWeights(weight_credit=0.4, weight_growth_rotation=0.3, weight_small_cap_rotation=0.3)
        r = compute_risk_appetite(
            "2024-01-16", oas_series, qqq_series, iwm_series, spy_series, _stub_credit_transform, weights
        )
        assert isinstance(r, RiskAppetiteResult)
        expected_score = 0.4 * r.credit_level_pct + 0.3 * r.growth_rotation_pct + 0.3 * r.small_cap_rotation_pct
        assert r.risk_appetite_score == pytest.approx(expected_score)

    def test_unavailable_when_credit_transform_returns_none(self, oas_series, qqq_series, iwm_series, spy_series):
        weights = RiskAppetiteWeights(weight_credit=1.0, weight_growth_rotation=0.0, weight_small_cap_rotation=0.0)

        def _always_unavailable(oas_series, as_of):
            return None

        with pytest.raises(RiskAppetiteUnavailableError, match="credit transform unavailable"):
            compute_risk_appetite(
                "2024-01-16", oas_series, qqq_series, iwm_series, spy_series, _always_unavailable, weights
            )

    def test_unavailable_when_growth_rotation_has_insufficient_history(self, spy_series):
        """Real pinned data can't isolate this case: OAS's own history only
        starts 2023-08-25, by which point QQQ (available since 1999) always
        has 504+ sessions of history — there is no real as_of date where the
        stub credit transform succeeds but growth_rotation genuinely lacks
        history (a real bug in my own first draft of this test, found during
        self-review: it asserted this using '1999-06-01', a date where OAS
        itself has NO data at all yet, so the credit-transform-unavailable
        branch fires first — a different, already-covered case). Uses a
        synthetic short QQQ series instead to isolate exactly this path."""
        short_qqq = _make_series("test", "QQQ_V5_1", [("2020-01-01", 100.0), ("2020-01-02", 101.0)])
        short_iwm = _make_series("test", "IWM_V5_1", [("2020-01-01", 50.0), ("2020-01-02", 50.5)])
        short_spy = _make_series("test", "BENCHMARK_V5_1", [("2020-01-01", 300.0), ("2020-01-02", 302.0)])
        oas_with_data = _make_series("test", "OAS_V5_1", [("2020-01-02", 3.5)])
        weights = RiskAppetiteWeights(weight_credit=1.0, weight_growth_rotation=0.0, weight_small_cap_rotation=0.0)
        with pytest.raises(RiskAppetiteUnavailableError, match="growth_rotation unavailable"):
            compute_risk_appetite(
                "2020-01-02", oas_with_data, short_qqq, short_iwm, short_spy, _stub_credit_transform, weights
            )


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_computation_is_repeatable(self, oas_series, qqq_series, iwm_series, spy_series):
        weights = RiskAppetiteWeights(weight_credit=0.4, weight_growth_rotation=0.3, weight_small_cap_rotation=0.3)
        r1 = compute_risk_appetite("2024-01-16", oas_series, qqq_series, iwm_series, spy_series, _stub_credit_transform, weights)
        r2 = compute_risk_appetite("2024-01-16", oas_series, qqq_series, iwm_series, spy_series, _stub_credit_transform, weights)
        assert r1 == r2
