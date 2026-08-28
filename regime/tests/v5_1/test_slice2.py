"""Market Regime v5.1 — Slice 2 (Canonical Raw Features) test suite.

Solo review context: ChatGPT is unavailable (out of credit, per the human's
Message[170] direction); this suite is the adversarial self-review pass in
its place. Uses the real pinned manifest/CSV snapshots read-only (loading
real data IS the point of this slice) plus synthetic fixtures for negative
cases. No development/holdout freshness-experiment injection is touched.

EMPIRICAL scope: derived-raw formulas (realized volatility, price_damage,
etc.) are deliberately NOT implemented here per the human's explicit
direction — this suite tests the loader and the injection interface only,
never asserts a specific formula's output.

Run with: python3 -m pytest regime/tests/v5_1/test_slice2.py -v
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.raw_features import (  # noqa: E402
    RawSeriesLoadError,
    RawSeries,
    RawSeriesCollection,
    RawObservation,
    load_raw_series,
    load_raw_collection,
    load_all_raw_series,
    register_derived_raw_estimator,
    compute_derived_raw,
    DERIVED_RAW_FEATURE_NAMES,
    SCALAR_RAW_FIELD_IDS,
    COLLECTION_RAW_FIELD_IDS,
    RAW_FIELD_IDS,
)


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


# ---------------------------------------------------------------------------
# Real-data loading — all 7 scalar fields + the 1 collection field
# ---------------------------------------------------------------------------

class TestScalarLoading:
    def test_all_7_scalar_fields_defined(self):
        assert len(SCALAR_RAW_FIELD_IDS) == 7
        assert "breadth_member_observations" not in SCALAR_RAW_FIELD_IDS

    def test_load_all_raw_series_loads_all_7(self, manifest):
        series = load_all_raw_series(manifest)
        assert set(series.keys()) == set(SCALAR_RAW_FIELD_IDS)
        for fid, s in series.items():
            assert isinstance(s, RawSeries)
            assert len(s.observations) > 0

    def test_benchmark_series_matches_known_row_count(self, manifest):
        s = load_raw_series("benchmark_total_return_close", manifest)
        assert s.source_contract_id == "BENCHMARK_V5_1"
        assert s.field_name == "adj_close"
        assert len(s.observations) == 8449  # SPY.csv's real row count, independently confirmed
        assert s.observations[0].date == "1993-01-29"

    def test_observations_are_sorted_and_unique(self, manifest):
        s = load_raw_series("vix_level", manifest)
        dates = [o.date for o in s.observations]
        assert dates == sorted(dates)
        assert len(dates) == len(set(dates))

    def test_value_on_exact_match(self, manifest):
        s = load_raw_series("benchmark_total_return_close", manifest)
        v = s.value_on("1993-01-29")
        assert v is not None
        assert v == pytest.approx(24.175382614135746)

    def test_value_on_missing_date_returns_none(self, manifest):
        s = load_raw_series("benchmark_total_return_close", manifest)
        assert s.value_on("1900-01-01") is None  # long before series start

    def test_load_raw_series_rejects_collection_field(self, manifest):
        with pytest.raises(ValueError, match="collection-shaped"):
            load_raw_series("breadth_member_observations", manifest)

    def test_load_raw_series_rejects_unknown_field(self, manifest):
        with pytest.raises(ValueError, match="not one of"):
            load_raw_series("not_a_real_field", manifest)


class TestCollectionLoading:
    def test_breadth_collection_has_9_members(self, manifest):
        coll = load_raw_collection("breadth_member_observations", manifest)
        assert coll.member_count() == 9
        assert isinstance(coll, RawSeriesCollection)

    def test_breadth_member_paths_match_manifest(self, manifest):
        coll = load_raw_collection("breadth_member_observations", manifest)
        contract = manifest.get_contract("BREADTH_V5_1")
        assert set(coll.members.keys()) == set(contract.snapshot_paths)

    def test_breadth_values_on_real_date_full_coverage(self, manifest):
        coll = load_raw_collection("breadth_member_observations", manifest)
        vals = coll.values_on("2020-04-15")
        assert len(vals) == 9  # all 9 sector ETFs have this well-warmed date

    def test_breadth_values_on_pre_inception_date_partial_coverage(self, manifest):
        """Sector ETFs inception in Dec 1998 — a date before that must show
        genuinely zero coverage, not an error and not a silent fabrication."""
        coll = load_raw_collection("breadth_member_observations", manifest)
        vals = coll.values_on("1993-06-01")
        assert len(vals) == 0

    def test_load_raw_collection_rejects_scalar_field(self, manifest):
        with pytest.raises(ValueError, match="not one of"):
            load_raw_collection("vix_level", manifest)


# ---------------------------------------------------------------------------
# Point-in-time / as-of / windowing correctness
# ---------------------------------------------------------------------------

class TestPointInTimeAccess:
    def test_as_of_on_exact_date_returns_that_observation(self, manifest):
        s = load_raw_series("vix_level", manifest)
        obs = s.as_of("2020-04-15")
        assert obs is not None
        assert obs.date == "2020-04-15"

    def test_as_of_on_gap_date_falls_back_to_prior_never_forward(self, manifest):
        """OAS has a real blank row on 2023-12-25 (Christmas) — as_of on
        that date must return the PRIOR real observation (2023-12-22), never
        interpolate and never look forward to 2023-12-26."""
        s = load_raw_series("oas_level", manifest)
        obs = s.as_of("2023-12-25")
        assert obs is not None
        assert obs.date == "2023-12-22"  # confirmed via direct grep of the CSV
        assert obs.value == pytest.approx(3.39)

    def test_as_of_before_series_start_returns_none(self, manifest):
        s = load_raw_series("vix_level", manifest)
        assert s.as_of("1990-01-01") is None

    def test_window_ending_correct_length_and_no_lookahead(self, manifest):
        s = load_raw_series("oas_level", manifest)
        w = s.window_ending("2023-12-27", 5)
        assert w is not None
        assert len(w) == 5
        assert w[-1].date == "2023-12-27"
        assert all(o.date <= "2023-12-27" for o in w)
        # The blank 2023-12-25 row must be skipped, not counted or filled —
        # confirmed the returned window spans 5 REAL trading days, which
        # naturally reaches back further than 5 calendar days because of it.
        assert w[0].date == "2023-12-20"

    def test_window_ending_insufficient_history_returns_none(self, manifest):
        s = load_raw_series("oas_level", manifest)
        w = s.window_ending("2023-08-25", 10)  # only 1 real observation exists this early
        assert w is None


# ---------------------------------------------------------------------------
# Fail-closed / negative fixtures
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_missing_source_file_raises(self, manifest, tmp_path):
        from v5_1.raw_features import _load_csv_column
        with pytest.raises(RawSeriesLoadError, match="does not exist"):
            _load_csv_column(tmp_path / "does_not_exist.csv", "adj_close")

    def test_missing_value_column_raises(self, tmp_path):
        from v5_1.raw_features import _load_csv_column
        bad = tmp_path / "bad.csv"
        bad.write_text("date,open,close\n2020-01-01,1.0,2.0\n")
        with pytest.raises(RawSeriesLoadError, match="no column"):
            _load_csv_column(bad, "adj_close")

    def test_no_date_column_raises(self, tmp_path):
        from v5_1.raw_features import _load_csv_column
        bad = tmp_path / "bad.csv"
        bad.write_text("timestamp,adj_close\n2020-01-01,1.0\n")
        with pytest.raises(RawSeriesLoadError, match="no recognized date column"):
            _load_csv_column(bad, "adj_close")

    def test_invalid_date_raises(self, tmp_path):
        from v5_1.raw_features import _load_csv_column
        bad = tmp_path / "bad.csv"
        bad.write_text("date,adj_close\nnot-a-date,1.0\n")
        with pytest.raises(RawSeriesLoadError, match="invalid ISO date"):
            _load_csv_column(bad, "adj_close")

    def test_non_numeric_value_raises(self, tmp_path):
        from v5_1.raw_features import _load_csv_column
        bad = tmp_path / "bad.csv"
        bad.write_text("date,adj_close\n2020-01-01,not-a-number\n")
        with pytest.raises(RawSeriesLoadError, match="non-numeric value"):
            _load_csv_column(bad, "adj_close")

    def test_blank_value_is_skipped_not_an_error(self, tmp_path):
        """Confirmed against real OAS data (2023-12-25): a blank value cell
        is a real missing observation, not a load error."""
        from v5_1.raw_features import _load_csv_column
        f = tmp_path / "blank.csv"
        f.write_text("date,adj_close\n2020-01-01,1.0\n2020-01-02,\n2020-01-03,3.0\n")
        pairs = _load_csv_column(f, "adj_close")
        assert pairs == [("2020-01-01", 1.0), ("2020-01-03", 3.0)]

    def test_duplicate_date_in_source_raises(self, manifest, tmp_path):
        from v5_1.raw_features import _build_series
        f = tmp_path / "dup.csv"
        f.write_text("date,adj_close\n2020-01-01,1.0\n2020-01-01,2.0\n")
        with pytest.raises(RawSeriesLoadError, match="duplicate date"):
            _build_series("test_field", "TEST_CONTRACT", "adj_close", str(f.relative_to(tmp_path)), tmp_path)

    def test_tampered_snapshot_hash_detected(self, manifest, tmp_path):
        """Prove the identity-inheritance check actually fires: point a real
        contract's manifest entry at a byte-different file and confirm
        load_raw_series refuses to load it."""
        import json
        from v5_1.contracts import load_manifest as _load_manifest

        real_manifest_path = REPO_ROOT / "regime/schema/market_regime_fields.v5.1.json"
        with real_manifest_path.open() as f:
            data = json.load(f)

        # Create a tampered copy of the real VIX.csv with one changed byte,
        # at a fake repo_root, while the manifest's pinned hash for VIX_V5_1
        # stays at its real, untouched value — the file has drifted from
        # what the manifest still claims it is.
        real_vix = REPO_ROOT / "research/technical-analysis/data/market/VIX.csv"
        tampered_content = real_vix.read_text().replace("2007-01-03", "2007-01-04", 1)
        fake_snapshot_dir = tmp_path / "research/technical-analysis/data/market"
        fake_snapshot_dir.mkdir(parents=True)
        (fake_snapshot_dir / "VIX.csv").write_text(tampered_content)

        tampered_manifest_path = tmp_path / "manifest.json"
        tampered_manifest_path.write_text(json.dumps(data))

        m = _load_manifest(manifest_path=tampered_manifest_path)
        with pytest.raises(RawSeriesLoadError, match="snapshot identity verification failed"):
            load_raw_series("vix_level", m, repo_root=tmp_path)

    def test_multi_path_scalar_contract_rejected(self, manifest, tmp_path):
        """A scalar field's contract declaring more than 1 snapshot path is
        a structural error this loader must catch, not silently use only
        the first path for (e.g. if BREADTH_V5_1 were accidentally wired
        to load_raw_series instead of load_raw_collection)."""
        import json
        from v5_1.contracts import load_manifest as _load_manifest

        real_manifest_path = REPO_ROOT / "regime/schema/market_regime_fields.v5.1.json"
        with real_manifest_path.open() as f:
            data = json.load(f)
        # Use VIX9D's own REAL pinned hash for the added path — the point of
        # this test is isolating the "too many paths" structural error, not
        # re-triggering the (separately tested) hash-mismatch error.
        vix9d_real_hash = "30d81f9cae2f9e38e59b9729a22e74a30393168d92f3f0ed939143b0e1cd8b54"
        for c in data["source_contracts"]:
            if c["source_contract_id"] == "VIX_V5_1":
                c["snapshot_paths"] = c["snapshot_paths"] + ["research/technical-analysis/data/market/VIX9D.csv"]
                c["snapshot_sha256"]["research/technical-analysis/data/market/VIX9D.csv"] = vix9d_real_hash
        bad_manifest_path = tmp_path / "manifest.json"
        bad_manifest_path.write_text(json.dumps(data))

        m = load_manifest(manifest_path=bad_manifest_path)
        with pytest.raises(RawSeriesLoadError, match="expected exactly 1"):
            load_raw_series("vix_level", m)


# ---------------------------------------------------------------------------
# Derived-raw feature interface — EMPIRICAL, deliberately unimplemented
# ---------------------------------------------------------------------------

class TestDerivedRawInterface:
    def test_all_6_derived_names_defined(self):
        assert len(DERIVED_RAW_FEATURE_NAMES) == 6
        assert "price_damage" in DERIVED_RAW_FEATURE_NAMES
        assert "realized_volatility" in DERIVED_RAW_FEATURE_NAMES

    def test_unregistered_derived_feature_raises_not_implemented(self, manifest):
        """The core EMPIRICAL-scope requirement: NO formula is embedded.
        Calling an unregistered derived feature must raise
        NotImplementedError, never silently return a default/zero/None as
        if that were a legitimate computed value."""
        s = load_raw_series("benchmark_total_return_close", manifest)
        with pytest.raises(NotImplementedError, match="no EMPIRICAL estimator registered"):
            compute_derived_raw("realized_volatility", s, "2020-01-01")

    def test_register_and_compute_a_stub_estimator(self, manifest):
        """Proves the injection SEAM works mechanically, without asserting
        anything about what a real formula should output — the registered
        function here is an obviously-fake placeholder, not a candidate
        production formula."""
        s = load_raw_series("benchmark_total_return_close", manifest)

        def _fake_estimator(series, as_of):
            return 42.0

        register_derived_raw_estimator("realized_volatility", _fake_estimator)
        try:
            result = compute_derived_raw("realized_volatility", s, "2020-01-01")
            assert result == 42.0
        finally:
            # Clean up global registry state so this test doesn't leak into
            # other tests — a real design smell worth flagging (see solo
            # review note in Message[171]): a module-level mutable registry
            # is not itself thread-safe or test-isolated. Acceptable for
            # Slice 2's interface-definition purpose; a later slice choosing
            # real estimators should reconsider this pattern.
            from v5_1.raw_features import _DERIVED_RAW_ESTIMATORS
            del _DERIVED_RAW_ESTIMATORS["realized_volatility"]

    def test_register_rejects_unknown_name(self):
        with pytest.raises(ValueError, match="not a recognized derived-raw feature"):
            register_derived_raw_estimator("not_a_real_derived_feature", lambda series, as_of: 1.0)

    def test_compute_rejects_unknown_name(self, manifest):
        s = load_raw_series("vix_level", manifest)
        with pytest.raises(ValueError, match="not a recognized derived-raw feature"):
            compute_derived_raw("not_a_real_derived_feature", s, "2020-01-01")


# ---------------------------------------------------------------------------
# Deterministic replay
# ---------------------------------------------------------------------------

class TestDeterministicReplay:
    def test_scalar_load_is_repeatable(self, manifest):
        s1 = load_raw_series("vix_level", manifest)
        s2 = load_raw_series("vix_level", manifest)
        assert s1.observations == s2.observations

    def test_collection_load_is_repeatable(self, manifest):
        c1 = load_raw_collection("breadth_member_observations", manifest)
        c2 = load_raw_collection("breadth_member_observations", manifest)
        assert set(c1.members.keys()) == set(c2.members.keys())
        for path in c1.members:
            assert c1.members[path].observations == c2.members[path].observations
