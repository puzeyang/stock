#!/usr/bin/env python3
"""Build the pinned, versioned expected-session calendar artifact per msg 148
item 3 (and hardened per msg 150 item 1): a real, content-addressed,
family-scoped calendar derived from an INDEPENDENT authority for each family
— never a hand-rolled rule applied naively, and never derived from the same
file the verifier is meant to audit.

v2 (msg 150 correction): the round-8 artifact derived XNYS/Cboe expectations
from the UNION of each family's own observed vendor files, and derived
FRED_OAS directly from BAMLH0A0HYM2.csv — the exact file the verifier audits.
ChatGPT correctly identified this as still circular: a closure or omission
present in every correlated input (shared vendor/ingestion failure modes)
would silently propagate into the "expected" set, and copied-row mutation
tests only prove the frozen artifact detects POST-BUILD drift, not that the
artifact's own construction is independent.

XNYS_ETF_BREADTH and CBOE_VIX now use a from-first-principles XNYS holiday
RULE calendar (a citable, static rule set — not observed vendor rows), with
a hand-curated, explicitly cited list of one-off extraordinary closures
layered on top. This was independently reconciled against the full-history
SPY.csv snapshot (1993-01-29 through the pinned end date) during
construction and required FOUR real fixes beyond a naive federal calendar
before it matched:
  1. XNYS's Saturday-New-Year's-Day rule differs from the federal government's:
     when Jan 1 falls on a Saturday, XNYS simply trades normally on the prior
     Friday (Dec 31) — there is no substitute-Friday closure, unlike the
     federal "nearest workday" observance. Directly confirmed: SPY.csv has a
     real row on every Dec 31 immediately preceding a Saturday Jan 1 in its
     full history (1994, 2000, 2005, 2011, 2022). New Year's Day uses a
     "sunday_to_monday" rule: only a SUNDAY holiday shifts (to the following
     Monday); a Saturday holiday is simply absorbed by the weekend.
  2. NYSE did not observe Martin Luther King Jr. Day as a market holiday
     until 1998, despite it being a federal holiday since 1986. Directly
     confirmed: SPY.csv has real rows on the MLK-Day Mondays of 1994-1997
     (1994-01-17, 1995-01-16, 1996-01-15, 1997-01-20) — the exchange traded
     on all four. The XNYS MLK rule below is start_date-gated to 1998.
  3. Juneteenth (June 19) became a federal holiday in 2021 but XNYS did not
     observe it as a market closure until its first full calendar year,
     2022. Directly confirmed: SPY.csv has a real row on 2021-06-18 (XNYS
     traded) and no row on 2022-06-20 (the observed Monday closure, June 19
     2022 being a Sunday) — the XNYS Juneteenth rule below is start_date-
     gated to 2022.
  4. FOUND AND FIXED IN ROUND 10 (msg 150 item 1): Independence Day and
     Christmas do NOT use the same sunday_to_monday-only rule as New Year's.
     A round-9 draft applied sunday_to_monday uniformly and then
     misclassified the resulting 10 real closures (Fridays preceding a
     Saturday July 4th/Christmas — 1993-12-24, 1998-07-03, 1999-12-24,
     2004-12-24, 2009-07-03, 2010-12-24, 2015-07-03, 2020-07-03, 2021-12-24,
     2026-07-03) as "vendor gaps" rather than recognizing them as real
     full-day holiday closures. ChatGPT correctly identified this: the code
     found SPY had no rows on those dates but drew the wrong conclusion.
     Independence Day and Christmas use "nearest_workday" (Saturday shifts
     to the PRECEDING Friday, Sunday shifts to the FOLLOWING Monday) — this
     is the correct, holiday-specific rule, confirmed by reconciling all 10
     dates as real closures with zero remaining discrepancy once fixed.
These four corrections were found by a full-range reconciliation against
SPY.csv during THIS build, not asserted from memory — see
`reconcile_calendar_against_source()` below, which is re-run every time this
script executes and fails loudly (raises) on any unexplained discrepancy.

One further real discrepancy is handled explicitly rather than silently
absorbed into the rule set:
  - Extraordinary, non-recurring closures (not derivable from any holiday
    RULE — genuine one-off market-wide shutdowns): 1994-04-27 (Nixon state
    funeral), 2001-09-11 through 2001-09-14 (post-9/11 closure), 2004-06-11
    (Reagan state funeral), 2007-01-02 (Ford state funeral), 2012-10-29 and
    2012-10-30 (Hurricane Sandy), 2018-12-05 (Bush Sr. state funeral),
    2025-01-09 (Carter state funeral). These are compiled from general
    knowledge of well-documented, widely reported NYSE closure history (not
    fetched live this session, per the human's explicit "no need
    cross-checked for now" — see discussion msg 151/152) and are
    hand-curated in EXTRAORDINARY_CLOSURES below with an inline citation
    note per entry.

No "known vendor half-day gap" exception list exists as of round 10 — the
corrected holiday rule (item 4 above) predicts all such closures directly,
so no separate data-quality exception is needed for them.

FRED_OAS's expected-release calendar is now built independently of
BAMLH0A0HYM2.csv: FRED's own documented publication policy for daily/business-
day series is Monday-Friday, U.S. Federal Reserve/banking holidays excluded —
this is the PLAIN US FEDERAL HOLIDAY calendar (not the XNYS calendar), used
here as a citable, independent proxy for "days FRED's data desk would not
publish a new business-day observation," separate from the OAS series' own
observed rows. msg 148 found the OAS file has real values on several federal
holidays; those are FRED's own carry-forward convention for a market-derived
series and are treated as a documented EXCEPTION to the federal-holiday
expectation (FRED_OAS_CARRY_FORWARD_HOLIDAYS below), not as evidence that no
independent expected-release calendar exists.

Run this script to regenerate the artifact after a data refresh or a rule
correction. It is exit-code-gated: if `reconcile_calendar_against_source`
finds any XNYS/Cboe discrepancy against the pinned SPY.csv beyond the
documented exception lists, the script raises and refuses to write the
artifact — so a stale or incorrect rule change cannot silently produce a
new pinned "authority."
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "regime/schema/expected_session_calendar.v1.0.json"

SPY_PATH = "research/data/raw/SPY.csv"
CBOE_UNION_FILES = [
    "research/technical-analysis/data/market/VIX.csv",
    "research/technical-analysis/data/market/VIX9D.csv",
    "research/technical-analysis/data/market/VIX3M.csv",
]
FRED_OAS_FILE = "research/data/raw/BAMLH0A0HYM2.csv"

# One-off extraordinary XNYS closures — hand-curated from general knowledge of
# well-documented NYSE closure history (see module docstring). Each entry
# cites its occasion; these are not derivable from any recurring rule.
EXTRAORDINARY_CLOSURES = {
    "1994-04-27": "Richard Nixon state funeral (NYSE closed)",
    "2001-09-11": "September 11 attacks — NYSE closed",
    "2001-09-12": "September 11 attacks aftermath — NYSE closed",
    "2001-09-13": "September 11 attacks aftermath — NYSE closed",
    "2001-09-14": "September 11 attacks aftermath — NYSE closed",
    "2004-06-11": "Ronald Reagan state funeral (NYSE closed)",
    "2007-01-02": "Gerald Ford state funeral (NYSE closed)",
    "2012-10-29": "Hurricane Sandy — NYSE closed",
    "2012-10-30": "Hurricane Sandy — NYSE closed",
    "2018-12-05": "George H.W. Bush state funeral (NYSE closed)",
    "2025-01-09": "Jimmy Carter state funeral (NYSE closed)",
}

# REMOVED per msg 150 round-10 review: the 10 dates formerly classified here
# as "known vendor half-day gaps" (1993-12-24, 1998-07-03, 1999-12-24,
# 2004-12-24, 2009-07-03, 2010-12-24, 2015-07-03, 2020-07-03, 2021-12-24,
# 2026-07-03) are NOT vendor gaps at all — they are real, full-day XNYS
# holiday closures under the correct nearest_workday observance rule for
# Independence Day/Christmas (see build_xnys_holiday_calendar). The round-9
# builder misclassified them as vendor gaps because it applied
# sunday_to_monday uniformly to every holiday, which is only correct for New
# Year's Day. No exception list is needed now that the holiday rule itself
# is correct — these dates are simply holidays, and the reconciliation gate
# confirmed zero remaining discrepancies once the rule was fixed.

# Known EXTRA vendor rows in the pinned Cboe VIX.csv on dates the exchange
# calendar rule says XNYS was closed — found by this script's own
# reconciliation gate, not asserted in advance. 2026-05-25 (Memorial Day) has
# a real OHLC row in VIX.csv despite being a documented XNYS closure, and
# 2026-08-25 has a row because it is the live-fetch date at the time of this
# build (an intraday/just-closed value captured by an automated updater, not
# a settled historical session). Neither VIX9D.csv nor VIX3M.csv has a row on
# either date, confirming this is a VIX-specific vendor quirk, not a real
# full-family trading session.
#
# Per msg 150 round-10 item 2: this is a DATA-QUALITY classification, kept
# strictly separate from calendar truth. These dates are NEVER merged into
# families.CBOE_VIX (the normative expected-session set) — Memorial Day
# remains a real closure, and a vendor anomaly is recorded as metadata only,
# not promoted into the schedule the verifier checks other contracts against.
KNOWN_VENDOR_EXTRA_CBOE_SESSIONS = {
    "2026-05-25": "VIX.csv has a real OHLC row on Memorial Day (documented XNYS closure); VIX9D/VIX3M do not. Classified as an observed-extra data-quality anomaly, NOT added to the expected-session schedule.",
    "2026-08-25": "VIX.csv has a real OHLC row for the live-fetch date at build time (intraday/just-closed value); VIX9D/VIX3M do not. Classified as an observed-extra data-quality anomaly, NOT added to the expected-session schedule.",
}

# FRED's own carry-forward/observation convention: real published OAS values
# exist on these federal holidays even though FRED's documented business-day
# publication policy would not normally add a new observation. Confirmed
# directly against the pinned OAS file. Treated as a documented exception to
# the independent federal-holiday expectation, not evidence against having one.
FRED_OAS_CARRY_FORWARD_HOLIDAYS_NOTE = (
    "FRED_OAS's expected-release calendar is the plain US federal holiday "
    "calendar (Mon-Fri, federal holidays excluded), per FRED's documented "
    "business-day publication policy. The pinned OAS file has been confirmed "
    "to carry real published values on several federal holidays (e.g. "
    "2023-09-04, 2023-10-09, 2023-11-10, 2024-01-15, 2024-06-19, 2024-11-11) "
    "via FRED's own carry-forward convention for a market-derived series; "
    "these are additional real observations beyond the minimum expected "
    "federal-business-day set, not evidence the federal-business-day "
    "expectation is wrong — a carry-forward value on a holiday is a bonus "
    "observation, not a violated expectation, so no exception list is needed "
    "on the expectation side for FRED_OAS."
)


def build_xnys_holiday_calendar(start: str, end: str) -> set[str]:
    """From-first-principles XNYS holiday RULE calendar, independent of any
    observed vendor file. See module docstring for the three corrections
    (Saturday-New-Year's, pre-1998 MLK, pre-2022 Juneteenth) found by
    reconciling this rule set against SPY.csv during development."""
    from pandas.tseries.holiday import (
        AbstractHolidayCalendar, Holiday, sunday_to_monday, nearest_workday,
        USMartinLutherKingJr, USPresidentsDay, USMemorialDay, USLaborDay,
        USThanksgivingDay, GoodFriday,
    )

    # MLK Day needs a start_date gate (not observed as an XNYS closure until
    # 1998) combined with an offset-based recurrence rule (3rd Monday of
    # January) — computed directly below via USMartinLutherKingJr.dates()
    # rather than as a single Holiday rule, since pandas' Holiday class does
    # not cleanly compose an offset rule with a start_date gate.
    #
    # Observance rules differ BY HOLIDAY, not uniformly (msg 150 round-10
    # finding, confirmed via full-range reconciliation): New Year's Day uses
    # sunday_to_monday ONLY — a Saturday Jan 1 has no substitute closure,
    # XNYS simply trades the preceding Friday (confirmed via real SPY rows on
    # every such Friday). Independence Day and Christmas instead use
    # nearest_workday (Saturday shifts to the PRECEDING Friday, Sunday shifts
    # to the FOLLOWING Monday) — confirmed via real SPY absences on all 10
    # Fridays preceding a Saturday July 4th/Christmas across full history.
    class XNYSHolidayCalendarFixed(AbstractHolidayCalendar):
        rules = [
            Holiday("New Years Day", month=1, day=1, observance=sunday_to_monday),
            USPresidentsDay,
            GoodFriday,
            USMemorialDay,
            Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=sunday_to_monday),
            Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
            USLaborDay,
            USThanksgivingDay,
            Holiday("Christmas", month=12, day=25, observance=nearest_workday),
        ]

    cal = XNYSHolidayCalendarFixed()
    hols = cal.holidays(start=start, end=end)
    holiday_set = {d.strftime("%Y-%m-%d") for d in hols}

    # MLK Day, gated to 1998 onward (see docstring item 2).
    mlk_full = USMartinLutherKingJr.dates(start, end)
    holiday_set |= {d.strftime("%Y-%m-%d") for d in mlk_full if d.year >= 1998}

    return holiday_set


def build_federal_holiday_calendar(start: str, end: str) -> set[str]:
    """Plain US federal holiday calendar, independent of any data file's own
    rows — used for FRED_OAS's expected-release calendar per FRED's
    documented business-day publication policy."""
    from pandas.tseries.holiday import USFederalHolidayCalendar

    cal = USFederalHolidayCalendar()
    hols = cal.holidays(start=start, end=end)
    return {d.strftime("%Y-%m-%d") for d in hols}


def build_expected_sessions(start: str, end: str, holiday_set: set[str], exclude: set[str]) -> set[str]:
    """All weekdays in [start, end] that are not a holiday and not in an
    explicit vendor-gap exclusion list."""
    import datetime

    d = datetime.date.fromisoformat(start)
    e = datetime.date.fromisoformat(end)
    expected = set()
    while d <= e:
        iso = d.isoformat()
        if d.weekday() < 5 and iso not in holiday_set and iso not in exclude:
            expected.add(iso)
        d += datetime.timedelta(days=1)
    return expected


def load_dates(rel_path: str) -> set[str]:
    path = REPO_ROOT / rel_path
    with path.open() as f:
        reader = csv.reader(f)
        header = next(reader)
        col = "date" if "date" in header else "observation_date"
        idx = header.index(col)
        return {row[idx] for row in reader if len(row) > idx}


def reconcile_calendar_against_source(expected: set[str], observed: set[str], label: str) -> None:
    """Full-range reconciliation: raise loudly if the rule-based expected set
    and the real observed data disagree anywhere not already covered by a
    documented, cited exception. This is what caught the Saturday-New-Year's,
    pre-1998-MLK, and pre-2022-Juneteenth errors during development, and what
    prevents this script from silently writing a new incorrect artifact if
    the rule set regresses."""
    missing_from_observed = sorted(expected - observed)
    extra_in_observed = sorted(observed - expected)
    problems = []
    if missing_from_observed:
        problems.append(f"{len(missing_from_observed)} expected session(s) absent from {label}: {missing_from_observed[:20]}")
    if extra_in_observed:
        problems.append(f"{len(extra_in_observed)} real {label} row(s) not expected by the calendar rule: {extra_in_observed[:20]}")
    if problems:
        raise SystemExit(
            f"CALENDAR RECONCILIATION FAILED for {label} — refusing to write the artifact.\n"
            + "\n".join(problems)
            + "\nEither the rule set needs another documented correction, or a new "
              "extraordinary-closure/vendor-gap exception needs to be added explicitly."
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    spy_dates = load_dates(SPY_PATH)
    lo, hi = min(spy_dates), max(spy_dates)

    xnys_holidays = build_xnys_holiday_calendar(lo, hi)
    xnys_exclude = set(EXTRAORDINARY_CLOSURES.keys())
    xnys_expected = build_expected_sessions(lo, hi, xnys_holidays, xnys_exclude)
    reconcile_calendar_against_source(xnys_expected, spy_dates, "SPY.csv (XNYS_ETF_BREADTH)")

    # Cboe VIX-family sessions are XNYS-aligned; reuse the same expected set,
    # but reconcile against the Cboe files' own union separately (Cboe
    # inception dates differ from SPY's, so this is a real independent check,
    # not a duplicate of the XNYS reconciliation above). Per msg 150 round-10
    # item 2: known observed-extra VIX.csv-only rows (see
    # KNOWN_VENDOR_EXTRA_CBOE_SESSIONS) are accepted by the RECONCILIATION
    # CHECK only — subtracted from the observed set before comparison — and
    # are NEVER added to cboe_expected_full_range (the normative schedule
    # written to the artifact). A vendor anomaly is data-quality metadata,
    # not a promotion into calendar truth.
    cboe_union = set()
    for f in CBOE_UNION_FILES:
        cboe_union |= load_dates(f)
    cboe_lo, cboe_hi = min(cboe_union), max(cboe_union)
    cboe_expected_full_range = build_expected_sessions(lo, hi, xnys_holidays, xnys_exclude)
    cboe_expected_in_range = {d for d in cboe_expected_full_range if cboe_lo <= d <= cboe_hi}
    cboe_observed_in_range = {d for d in cboe_union if cboe_lo <= d <= cboe_hi}
    # Known observed-extra dates are excluded from the OBSERVED side of this
    # comparison only (they are real rows that would otherwise appear as
    # "unexpected"), never added to the expected side — keeping calendar
    # truth and data-quality classification strictly separate (item 2).
    cboe_observed_for_reconciliation = cboe_observed_in_range - set(KNOWN_VENDOR_EXTRA_CBOE_SESSIONS)
    reconcile_calendar_against_source(cboe_expected_in_range, cboe_observed_for_reconciliation, "Cboe VIX-family union")

    fred_dates = load_dates(FRED_OAS_FILE)
    fred_lo, fred_hi = min(fred_dates), max(fred_dates)
    fred_holidays = build_federal_holiday_calendar(fred_lo, fred_hi)
    fred_expected_in_range = build_expected_sessions(fred_lo, fred_hi, fred_holidays, set())
    # FRED carry-forward means observed can be a SUPERSET of expected (extra
    # values on holidays) — only check expected-but-missing, not the reverse.
    fred_missing = sorted(fred_expected_in_range - fred_dates)
    if fred_missing:
        raise SystemExit(
            f"CALENDAR RECONCILIATION FAILED for FRED_OAS — "
            f"{len(fred_missing)} expected federal-business-day session(s) absent from the pinned OAS file: "
            f"{fred_missing[:20]}\nEither this is a real reporting gap (investigate before proceeding), "
            f"or the OAS coverage window needs adjustment."
        )

    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None

    artifact = {
        "calendar_version": "3.0",
        "generated_by": "regime/tools/build_expected_session_calendar.py",
        "generation_method": (
            "XNYS_ETF_BREADTH and CBOE_VIX: an independent, from-first-principles XNYS holiday RULE "
            "calendar (New Year's [sunday_to_monday only]/MLK-from-1998/Presidents/Good Friday/Memorial/"
            "Juneteenth-from-2022/Independence [nearest_workday]/Labor/Thanksgiving/Christmas "
            "[nearest_workday]), MINUS a hand-curated, cited list of one-off extraordinary closures "
            "(see EXTRAORDINARY_CLOSURES in the generator script) — independent of any family's own "
            "observed vendor rows. Reconciled against the full-history SPY.csv and Cboe VIX-family union "
            "during generation; the generator refuses to write this artifact if reconciliation finds any "
            "undocumented discrepancy. Known observed-extra Cboe vendor rows (see "
            "KNOWN_VENDOR_EXTRA_CBOE_SESSIONS) are classified as data-quality metadata and excluded from "
            "the reconciliation comparison, but are NEVER merged into the expected-session schedule itself. "
            "FRED_OAS: the plain US federal holiday calendar (Mon-Fri, federal holidays excluded), per "
            "FRED's documented business-day publication policy — independent of the OAS file's own rows. "
            "FRED's real carry-forward values on some federal holidays are additional observations beyond "
            "this minimum expectation, not a violation of it."
        ),
        "xnys_calendar_notes": {
            "extraordinary_closures": EXTRAORDINARY_CLOSURES,
            "known_vendor_extra_cboe_sessions": KNOWN_VENDOR_EXTRA_CBOE_SESSIONS,
            "rule_corrections_found_during_reconciliation": [
                "Saturday New Year's Day: XNYS trades on the preceding Friday (no substitute closure); only a Sunday holiday shifts to Monday.",
                "Martin Luther King Jr. Day: not observed as an XNYS closure until 1998, despite being a federal holiday since 1986.",
                "Juneteenth: not observed as an XNYS closure until 2022, its first full calendar year as a federal holiday (2021-06-18 traded).",
                "Independence Day/Christmas: use nearest_workday (Saturday shifts to preceding Friday, Sunday shifts to following Monday), NOT the sunday_to_monday-only rule that correctly applies to New Year's Day — a round-9 draft applied sunday_to_monday uniformly and misclassified 10 real Friday closures as vendor gaps; fixed in round 10 per msg 150 item 1.",
            ],
        },
        "fred_oas_calendar_notes": FRED_OAS_CARRY_FORWARD_HOLIDAYS_NOTE,
        "source_commit_at_generation": commit,
        "reconciled_against": {
            "XNYS_ETF_BREADTH": SPY_PATH,
            "CBOE_VIX": CBOE_UNION_FILES,
            "FRED_OAS": FRED_OAS_FILE,
        },
        "reconciled_source_sha256_at_generation": {
            SPY_PATH: sha256_file(REPO_ROOT / SPY_PATH),
            **{f: sha256_file(REPO_ROOT / f) for f in CBOE_UNION_FILES},
            FRED_OAS_FILE: sha256_file(REPO_ROOT / FRED_OAS_FILE),
        },
        "families": {
            "XNYS_ETF_BREADTH": sorted(xnys_expected),
            "CBOE_VIX": sorted(cboe_expected_in_range),
            "FRED_OAS": sorted(fred_expected_in_range),
        },
    }

    OUTPUT_PATH.write_text(json.dumps(artifact, indent=2) + "\n")
    print(f"wrote {OUTPUT_PATH}")
    print(f"  XNYS_ETF_BREADTH: {len(xnys_expected)} expected sessions (rule-derived, reconciled OK)")
    print(f"  CBOE_VIX:         {len(cboe_expected_in_range)} expected sessions (rule-derived, reconciled OK)")
    print(f"  FRED_OAS:         {len(fred_expected_in_range)} expected sessions (federal-calendar-derived, reconciled OK)")
    print(f"  artifact sha256:  {sha256_file(OUTPUT_PATH)}")


if __name__ == "__main__":
    main()
