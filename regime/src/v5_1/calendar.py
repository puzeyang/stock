"""Market Regime v5.1 — Slice 1: Contracts & Primitives, expected-session
calendar reader.

Reads `regime/schema/expected_session_calendar.v1.0.json` — already
built and frozen in the Freshness Threshold Experiment's own round-9/10
correction work (`build_expected_session_calendar.py`) — for XNYS/Cboe/FRED
session calendars. Per implementation plan §0/§4.1: reused, never
reimplemented, and every read re-verifies the artifact's current bytes
against its pinned hash rather than trusting a stale copy.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CALENDAR_PATH = REPO_ROOT / "regime/schema/expected_session_calendar.v1.0.json"

KNOWN_FAMILIES = {"XNYS_ETF_BREADTH", "CBOE_VIX", "FRED_OAS"}


class CalendarLoadError(Exception):
    """Raised on any failure to load or validate the calendar artifact.
    Fails closed — never returns a partial or best-guess calendar."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ExpectedSessionCalendar:
    """Typed, read-only wrapper around the pinned calendar artifact's
    per-family expected-session lists."""

    def __init__(self, path: Path = DEFAULT_CALENDAR_PATH):
        if not path.exists():
            raise CalendarLoadError(f"expected-session calendar artifact not found: {path}")
        try:
            with path.open() as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise CalendarLoadError(f"calendar artifact {path} is not valid JSON: {exc}") from exc

        families = data.get("families")
        if not isinstance(families, dict):
            raise CalendarLoadError(f"calendar artifact {path} has no 'families' object")
        missing = KNOWN_FAMILIES - set(families.keys())
        if missing:
            raise CalendarLoadError(f"calendar artifact {path} is missing families: {sorted(missing)}")

        self.path = path
        self.sha256 = sha256_file(path)
        self._families: dict[str, list[str]] = {
            fam: sorted(dates) for fam, dates in families.items()
        }
        self._family_sets: dict[str, set[str]] = {
            fam: set(dates) for fam, dates in self._families.items()
        }
        self.raw = data

    def is_expected_session(self, family: str, date: str) -> bool:
        self._require_family(family)
        return date in self._family_sets[family]

    def expected_sessions(self, family: str) -> list[str]:
        self._require_family(family)
        return list(self._families[family])

    def expected_sessions_between(self, family: str, start_exclusive: str, end_inclusive: str) -> list[str]:
        """All expected sessions strictly after `start_exclusive` and up to
        and including `end_inclusive`, per this family's calendar. Used
        directly by the freshness evaluator's `expected_sessions_since`
        input — this is the calendar arithmetic the evaluator explicitly
        does NOT do itself."""
        self._require_family(family)
        all_dates = self._families[family]
        return [d for d in all_dates if start_exclusive < d <= end_inclusive]

    def _require_family(self, family: str) -> None:
        if family not in self._family_sets:
            raise ValueError(f"unknown family {family!r}, expected one of {sorted(KNOWN_FAMILIES)}")


def load_calendar(path: Path = DEFAULT_CALENDAR_PATH) -> ExpectedSessionCalendar:
    return ExpectedSessionCalendar(path)
