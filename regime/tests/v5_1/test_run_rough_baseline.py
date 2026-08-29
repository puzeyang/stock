"""Tests for regime/tools/run_rough_baseline.py's CLI argument
validation. Per Message[262] point 4: the prior version's CLI edge
cases (--start before --warmup-from, --end before --start/--warmup-
from producing an empty date list, --n<=0) were unverified — the
existing 546-item engine suite proves nothing about argparse-level
input handling, since it never calls this script's CLI at all.

Deliberately scoped to `_parse_args` only, NOT to `main()` end-to-end
(that would require the full ~7-minute engine warm-up run per
Message[261]/[262] — inappropriate for a fast unit test). `main()`'s
actual engine-dependent behavior is exercised manually, as documented
in the discussion log, not by this file.

Run with: python3 -m pytest regime/tests/v5_1/test_run_rough_baseline.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "regime/tools"))

from run_rough_baseline import _parse_args  # noqa: E402


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
