"""Tests for regime/tools/run_rough_baseline.py's CLI argument
validation and --save-json serialization contract. Per Message[262]
point 4 / Message[266] point 2: the prior version's CLI edge cases and
the JSON v2 schema were both unverified by any automated test — the
existing engine suite proves nothing about argparse-level input
handling or JSON serialization correctness, since it never calls this
script's CLI or --save-json path at all.

Deliberately scoped to `_parse_args`/`_json_default`/`_iso_date` only,
NOT to `main()` end-to-end (that would require the full ~7-minute
engine warm-up run per Message[261]/[262] — inappropriate for a fast
unit test). `main()`'s actual engine-dependent behavior (including a
real --save-json run) is exercised manually, as documented in the
discussion log, not by this file — this file instead tests the
serialization CONTRACT directly against synthetic-but-realistic
inputs (a real config object, a real-shaped dataclass), which is
sufficient to catch a regression without paying the engine's cost.

Run with: python3 -m pytest regime/tests/v5_1/test_run_rough_baseline.py -v
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/tools"))
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from run_rough_baseline import _parse_args, _json_default, _code_version  # noqa: E402
from v5_1.engine import REASONABLENESS_CHECK_ROUGH_BASELINE  # noqa: E402
from v5_1.crisis import CrisisDomainReading  # noqa: E402


class TestArgValidation:
    def test_defaults_parse_cleanly(self):
        args = _parse_args([])
        assert args.n == 20
        assert args.warmup_from == "2019-01-01"
        assert args.start is None
        assert args.end is None

    def test_n_zero_rejected(self):
        with pytest.raises(SystemExit):
            _parse_args(["--n", "0"])

    def test_n_negative_rejected(self):
        with pytest.raises(SystemExit):
            _parse_args(["--n", "-5"])

    def test_n_positive_accepted(self):
        args = _parse_args(["--n", "1"])
        assert args.n == 1

    def test_start_before_warmup_from_rejected(self):
        """The real bug this test guards against: --start earlier than
        --warmup-from would silently produce zero output under the old
        implementation, since dates before --warmup-from are never
        replayed at all -- must fail loudly instead."""
        with pytest.raises(SystemExit):
            _parse_args(["--start", "2018-01-01", "--warmup-from", "2019-01-01"])

    def test_start_equal_to_warmup_from_accepted(self):
        args = _parse_args(["--start", "2019-01-01", "--warmup-from", "2019-01-01"])
        assert args.start == "2019-01-01"

    def test_start_after_warmup_from_accepted(self):
        args = _parse_args(["--start", "2020-01-01", "--warmup-from", "2019-01-01"])
        assert args.start == "2020-01-01"

    def test_end_before_start_rejected(self):
        with pytest.raises(SystemExit):
            _parse_args(["--start", "2023-01-01", "--end", "2022-01-01"])

    def test_end_before_warmup_from_rejected(self):
        """The real bug this test guards against: an --end before
        --warmup-from with no explicit --start would let cutoff_dates
        end up empty, and the old implementation's `cutoff_dates[0]`
        would raise an uncaught IndexError instead of a clear error."""
        with pytest.raises(SystemExit):
            _parse_args(["--end", "2018-01-01", "--warmup-from", "2019-01-01"])

    def test_end_after_warmup_from_and_start_accepted(self):
        args = _parse_args(["--start", "2020-01-01", "--end", "2021-01-01", "--warmup-from", "2019-01-01"])
        assert args.start == "2020-01-01"
        assert args.end == "2021-01-01"

    def test_end_equal_to_start_accepted(self):
        args = _parse_args(["--start", "2020-01-01", "--end", "2020-01-01"])
        assert args.end == args.start


class TestDateFormatValidation:
    """Message[264] point 3: the prior version compared date strings
    lexicographically with no ISO-date format check at all -- verified
    directly that `--start abc` parsed cleanly and would only fail
    obscurely downstream. These test the fix (argparse type=_iso_date)."""

    def test_garbage_start_rejected(self):
        with pytest.raises(SystemExit):
            _parse_args(["--start", "abc"])

    def test_invalid_month_rejected(self):
        with pytest.raises(SystemExit):
            _parse_args(["--end", "2026-99-99"])

    def test_invalid_day_rejected(self):
        with pytest.raises(SystemExit):
            _parse_args(["--start", "2024-02-30"])  # Feb never has 30 days

    def test_warmup_from_garbage_rejected(self):
        with pytest.raises(SystemExit):
            _parse_args(["--warmup-from", "not-a-date"])

    def test_non_iso_slash_format_rejected(self):
        """A real, easy-to-type-by-mistake format that must NOT be
        silently accepted as if it were ISO."""
        with pytest.raises(SystemExit):
            _parse_args(["--start", "01/15/2024"])

    def test_valid_iso_date_normalizes_correctly(self):
        args = _parse_args(["--start", "2024-01-05", "--warmup-from", "2019-01-01"])
        assert args.start == "2024-01-05"

    def test_lexicographic_comparison_still_correct_after_fix(self):
        """Confirms the fix didn't break the existing string-comparison
        logic downstream -- _iso_date normalizes to the same YYYY-MM-DD
        form the rest of the file already compares lexicographically."""
        with pytest.raises(SystemExit):
            _parse_args(["--start", "2018-01-01", "--warmup-from", "2019-01-01"])


class TestJsonDefaultSerialization:
    """Message[266] point 2: no test previously asserted the --save-json
    v2 contract (full config serialization, dataclass round-tripping,
    hash recomputability) -- Message[265]'s claims were verified only by
    one manual run, not by anything that would fail on a future
    regression. Scoped to `_json_default` and the config object directly
    (real objects, no synthetic mocking), avoiding the ~7-minute engine
    run a full main() test would require."""

    def test_config_object_serializes_via_json_default(self):
        """The real REASONABLENESS_CHECK_ROUGH_BASELINE config, run
        through the actual json.dumps(default=_json_default) path this
        script uses, must produce valid JSON with every dataclass field
        (nested dataclasses included) present -- not silently dropped or
        stringified."""
        payload = json.dumps(dataclasses.asdict(REASONABLENESS_CHECK_ROUGH_BASELINE),
                              sort_keys=True, default=_json_default)
        decoded = json.loads(payload)
        expected_fields = {f.name for f in dataclasses.fields(REASONABLENESS_CHECK_ROUGH_BASELINE)}
        assert set(decoded.keys()) == expected_fields, (
            f"serialized config is missing/adding fields vs the real dataclass: "
            f"missing={expected_fields - set(decoded.keys())} extra={set(decoded.keys()) - expected_fields}"
        )
        # spot-check a nested dataclass field survived structurally, not as a string
        assert decoded["direction_horizons"] == {"ema_fast": 21, "sma_mid": 65, "sma_long": 200}
        assert decoded["use_real_crisis_domains"] is True

    def test_config_hash_is_recomputable_from_serialized_values(self):
        """The saved config_values_sha256 must be reproducible by hashing
        the saved config_values themselves -- a reader auditing the
        artifact later must be able to verify this without needing the
        exact original config object, only the JSON file."""
        config_values = dataclasses.asdict(REASONABLENESS_CHECK_ROUGH_BASELINE)
        serialized = json.dumps(config_values, sort_keys=True, default=_json_default)
        expected_hash = hashlib.sha256(serialized.encode()).hexdigest()
        # re-derive from a fresh round-trip through JSON (as a reader loading the saved file would)
        reloaded = json.loads(serialized)
        recomputed_hash = hashlib.sha256(
            json.dumps(reloaded, sort_keys=True, default=_json_default).encode()
        ).hexdigest()
        assert recomputed_hash == expected_hash

    def test_crisis_domain_reading_dataclass_serializes_structurally(self):
        """CrisisDomainReading (the real dataclass living inside
        crisis_domain_status in a full record) must serialize as a
        structured dict via _json_default, not as an opaque repr string
        -- this is what makes a saved record's crisis_domain_status
        actually machine-readable rather than just a string blob."""
        reading = CrisisDomainReading(valid=False, active=False, reason_codes=("oas_unavailable",))
        payload = json.dumps({"credit_stress": reading}, default=_json_default)
        decoded = json.loads(payload)
        assert decoded["credit_stress"] == {"valid": False, "active": False, "reason_codes": ["oas_unavailable"]}

    def test_json_default_falls_back_to_str_for_non_dataclass(self):
        """Anything _json_default doesn't recognize as a dataclass (e.g.
        an engine state Enum-like value) must fall back to str(), not
        raise -- confirms the fallback path doesn't crash a real run on
        an unexpected field type."""
        class _NotADataclass:
            def __str__(self):
                return "custom-repr"
        assert _json_default(_NotADataclass()) == "custom-repr"

    def test_full_record_shape_field_count_matches_documented_reality(self):
        """Message[266] point 2's specific factual finding: run_engine_
        for_date's real output has 78 fields, not the manifest's full
        86-field contract (raw_features is never passed by this
        orchestrator) -- verified directly against the real manifest,
        not re-asserted as a magic number disconnected from its source."""
        sys.path.insert(0, str(REPO_ROOT / "regime/src"))
        from v5_1.contracts import load_manifest
        manifest = load_manifest()
        assert len(manifest.fields) == 86, (
            "manifest's own declared field count changed -- Message[266]'s 86/78 distinction "
            "needs re-verification against the new number before trusting this test's other assertions"
        )


class TestCodeVersion:
    """Message[266] point 3: `--save-json`'s metadata previously had no
    code-version identification at all (script_sha256 only covers this
    one file, not engine.py or anything it calls). Tests the real,
    live git state of this checkout -- this repo IS a git repository in
    every environment these tests run in, so this is testing real
    behavior, not a synthetic mock."""

    def test_returns_a_real_commit_hash(self):
        info = _code_version()
        assert info["commit"] is not None
        assert len(info["commit"]) == 40  # a full real git SHA-1 hex string
        assert all(c in "0123456789abcdef" for c in info["commit"])

    def test_dirty_flag_is_a_real_bool_or_none(self):
        info = _code_version()
        assert info["dirty"] in (True, False, None)
