#!/usr/bin/env python3
"""Verify freshness_injection_registry.v1.0.json against the requirements in
Freshness_Threshold_Experiment_v1.0.md Sections 1, 1.1, and 4.

v5 (msg 146 correction round): closes five real gaps found in msg 146's
independent retest of v4, plus two second-order bugs my own fixes for those
gaps then exposed under self-test (documented below since they were caught
by verification, not by ChatGPT's review — the discipline working as
intended):
(1) FRED_OAS used its own OAS rows as its "reference," so the circularity
    v4 fixed for XNYS/Cboe still existed for FRED — removing an adjacent
    OAS row shrank the window to fit. Fixed with a deterministic calendar,
    independent of any file's own rows (see (1a) below for why this was
    then extended to all three families).
(1a) SECOND-ORDER BUG found via self-test: fixing FRED with a calendar while
    XNYS/Cboe still used "the reference contract's own rows" turned out to
    still be circular for THOSE families too — removing a row from a COPY of
    BENCHMARK_V5_1/SPY and re-deriving the window from that same copy simply
    re-centered the window around the remaining rows. All three families now
    use a purely rule-based calendar window (never any file's own rows,
    including a designated "reference" file's), which is the only construction
    that makes a removed adjacent row detectable in every case.
(1b) THIRD-ORDER BUG found via self-test: a single federal-holiday calendar
    applied to XNYS/Cboe flagged the real, correct absence of 2020-04-10
    (Good Friday) in SPY.csv as a "missing session," because Good Friday is
    an XNYS market closure but NOT a federal holiday. XNYS_ETF_BREADTH and
    CBOE_VIX now use a dedicated XNYS calendar (federal holidays minus
    Columbus Day/Veterans Day, which XNYS trades through, plus Good Friday,
    which XNYS observes); FRED_OAS keeps the plain federal calendar.
(2) The requested adjacent-expected-row-removal mutation tests were absent.
    Added literal removal tests against a copied date index for: an XNYS
    family file, a VIX-family file, the FRED OAS file, and SPY itself
    (formerly the file-based "reference," now just a normal required file).
(3) SPY was used as a silent stand-in for "expected VIX-family session"
    without acknowledging real, non-trivial divergence: independently
    measured VIX9D and VIX3M are each missing 51 real SPY-overlap sessions
    (a genuine snapshot-staleness gap in their own files, confirmed via
    direct date-set comparison, not a modeling error, and concentrated in a
    recent tail that does not reach any currently registered anchor —
    verified directly). Resolved architecturally by (1a)/(1b): the verifier
    no longer treats any single file as ground truth for any family, so this
    divergence no longer matters to correctness, only to disclosure.
(4) Traceability checked hashes at fixed paths but never validated the
    registry's stored path strings matched those exact paths; source_commit
    was not validated as 40 hex characters; source_tree_state accepted
    arbitrary nonempty prose. All three are now enforced. (This surfaced one
    real registry gap: the `specification` path key was missing entirely —
    added.)
(5) superseded_entry validated only key names. Now validates ISO date/
    timestamp parse, nonempty correction_reason, correction time not before
    original registration time, and that the entry's current start_date
    actually differs from original_start_date.

One real registry defect was found and fixed as a direct consequence of (1a):
FRED-DEV-ORD-001's anchor (2023-08-28) sat only 1 business day after the OAS
file's actual coverage start (2023-08-25); its calendar-derived ±5-session
window correctly detected that 4 expected sessions fall before the file's own
coverage begins. This was never a real outage — it was the anchor sitting too
close to the pinned snapshot's left edge — and has been corrected to
2023-09-05 with a superseded_entry record.

v6 (msg 148 correction round): the v5 hand-rolled XNYS calendar rule (federal
holidays minus Columbus/Veterans Day plus Good Friday) was independently
proven wrong on real history — confirmed directly against pinned SPY.csv: it
expected 11 sessions that never existed (real one-off closures — 1994 Nixon
funeral, the 2001-09-11 through 09-14 post-9/11 closure, 2004 Reagan funeral,
2007 Ford funeral, 2012 Hurricane Sandy, 2018 Bush Sr. funeral, 2025 Carter
funeral) and misclassified 6 real trading days as holidays (year-end
"observed" dates when New Year's Day falls on a weekend, and 2021-06-18's
first Juneteenth observance). FRED's "federal business day" assumption was
also confirmed wrong — the pinned OAS file has real published values on
several federal holidays (2023-09-04, 2023-10-09, 2023-11-10, 2024-01-15,
2024-06-19, 2024-11-11), via FRED's own carry-forward/observation convention.

No exchange-calendar library (e.g. pandas_market_calendars) is available in
this environment, so rather than add that dependency or keep patching a
hand-rolled rule set, the expected-session window is now read from a PINNED,
VERSIONED ARTIFACT (regime/schema/expected_session_calendar.v1.0.json,
generated once by the new build_expected_session_calendar.py, never live
inside the verifier): the UNION of each family's own independent pinned
source files' observed trading dates for XNYS_ETF_BREADTH (12 tickers) and
CBOE_VIX (3 tickers), and the pinned OAS_V5_1 file's own dates directly for
FRED_OAS (its only contract). This is real observed market data from
independent tickers, not an inferred rule, and directly confirmed to
reproduce all 11 "phantom session" absences and all 6 "misclassified holiday"
presences correctly. The artifact's own path/hash is now part of registry
traceability (`expected_session_calendar`/`expected_session_calendar_sha256_at_registry_build`),
validated the same way as every other traceability entry. Six new self-test
cases prove: the calendar hash is checked; the 9/11 closure is correctly
excluded; the 1999-12-31 observed-holiday exception is correctly included;
the 2021-06-18 pre-adoption Juneteenth exception is correctly included; the
2023-10-09 OAS federal-holiday observation is correctly included; and the
artifact exactly reconciles against a live re-derivation from its declared
source files (catching a stale or hand-edited artifact).

Exits 0 and prints PASS with a summary if every check passes.
Exits 1 and prints every failing check if any check fails.
"""
from __future__ import annotations

import copy
import csv
import datetime
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

REQUIRED_LENGTHS = {1, 2, 3, 5}
REQUIRED_STRATA = {"ordinary", "crisis", "trend"}
MIN_HOLDOUT_ENTRIES_PER_FAMILY = 2
GAP_TOLERANCE_CALENDAR_DAYS = 4  # a weekend is a 3-day gap; > 4 flags a real missing session
WINDOW_SESSIONS = 5

# Exact per-family contract-ID sets, from spec Section 1's table. A family's
# registered entries must use exactly this set — no substitution, omission,
# duplication, or addition of a different manifest contract.
FAMILY_CONTRACT_IDS = {
    "XNYS_ETF_BREADTH": {"BENCHMARK_V5_1", "BREADTH_V5_1", "QQQ_V5_1", "IWM_V5_1"},
    "CBOE_VIX": {"VIX_V5_1", "VIX9D_V5_1", "VIX3M_DIAGNOSTIC_V5_1"},
    "FRED_OAS": {"OAS_V5_1"},
}
REQUIRED_FAMILIES = set(FAMILY_CONTRACT_IDS.keys())

# Every family's expected-session window is read from a PINNED, VERSIONED
# ARTIFACT (regime/schema/expected_session_calendar.v1.0.json,
# generated by build_expected_session_calendar.py) — never derived live from
# any data file, and never from a hand-rolled calendar rule set. Two earlier
# approaches were tried and both proved wrong under self-test/independent
# review: (a) deriving the window from a dedicated "reference contract's" own
# rows is circular — removing a row from a COPY of that same file just
# re-centers the window around whatever remains; (b) a hand-built rule-based
# calendar (federal holidays with XNYS-specific adjustments) was independently
# proven materially wrong in both directions — it expected 11 sessions that
# never existed (real one-off closures: 1994 Nixon funeral, 9/11 close
# 2001-09-11 through 09-14, 2004 Reagan funeral, 2007 Ford funeral, 2012
# Hurricane Sandy, 2018 Bush Sr. funeral, 2025 Carter funeral) and misclassified
# 6 real trading days as holidays (year-end "observed" dates, and 2021-06-18's
# first Juneteenth observance). The pinned artifact is instead the UNION of
# each family's own independent pinned source files' observed trading dates
# (12 XNYS-family tickers for XNYS_ETF_BREADTH; 3 Cboe tickers for CBOE_VIX)
# — confirmed directly to reproduce all 11 "phantom session" absences and all
# 6 "misclassified holiday" presences correctly, since it is real observed
# data from independent tickers rather than an inferred rule. FRED_OAS uses
# its own pinned file's dates directly (there is only one contract in that
# family, and FRED's real publication convention — including values on some
# federal holidays via carry-forward — is not modeled correctly by any
# business-day rule, confirmed directly against real OAS rows on
# 2023-09-04/2023-10-09/2023-11-10/2024-01-15/2024-06-19/2024-11-11, all
# federal holidays with real published values).

REQUIRED_ENTRY_FIELDS = {
    "injection_id", "family", "contract_ids", "outage_length", "start_date",
    "selection_rationale", "calendar_status_at_injection",
    "surrounding_completeness", "regime_stratum", "split", "registered_at",
    "registered_by",
}
ALLOWED_SPLITS = {"development", "holdout"}
INJECTION_ID_PATTERN = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)*$")
COMMIT_HASH_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_TREE_STATES = {"clean", "dirty"}

EXPECTED_REASON_MAPPING = {
    "CURRENT": [None, "SOURCE_LATE_WITHIN_GRACE"],
    "STALE": ["SOURCE_STALE"],
    "MISSING": ["SOURCE_MISSING"],
    "MISALIGNED": ["SOURCE_MISALIGNED"],
}

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "regime/schema/freshness_injection_registry.v1.0.json"
SPEC_PATH = REPO_ROOT / "regime/docs/Freshness_Threshold_Experiment_v1.0.md"
MANIFEST_PATH = REPO_ROOT / "regime/schema/market_regime_fields.v5.1.json"
SCHEMA_PATH = REPO_ROOT / "regime/schema/market_regime_field_manifest.schema.v1.0.0.json"
DESIGN_DOC_PATH = REPO_ROOT / "regime/docs/Market_Regime_Design_v5.1.md"
VERIFIER_PATH = Path(__file__).resolve()
CALENDAR_BUILDER_PATH = REPO_ROOT / "regime/tools/build_expected_session_calendar.py"

CALENDAR_ARTIFACT_PATH = REPO_ROOT / "regime/schema/expected_session_calendar.v1.0.json"

TRACEABILITY_FILE_CHECKS = [
    # (hash_key, path_key, real_path)
    ("design_document_sha256", "design_document", DESIGN_DOC_PATH),
    ("manifest_sha256_at_registry_build", "manifest_at_registry_build", MANIFEST_PATH),
    ("manifest_schema_sha256_at_registry_build", "manifest_schema_at_registry_build", SCHEMA_PATH),
    ("specification_sha256_at_registry_build", "specification", SPEC_PATH),
    ("verifier_sha256_at_registry_build", "verifier", VERIFIER_PATH),
    ("expected_session_calendar_sha256_at_registry_build", "expected_session_calendar", CALENDAR_ARTIFACT_PATH),
    ("expected_session_calendar_builder_sha256_at_registry_build", "expected_session_calendar_builder", CALENDAR_BUILDER_PATH),
]


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest_contracts() -> dict[str, dict]:
    with MANIFEST_PATH.open() as f:
        manifest = json.load(f)
    contracts: dict[str, dict] = {}
    for c in manifest.get("source_contracts", []):
        cid = c["source_contract_id"]
        snapshot_hashes = c.get("snapshot_sha256", {})
        paths = [(rel, REPO_ROOT / rel) for rel in c.get("snapshot_paths", [])]
        contracts[cid] = {"raw": c, "paths": paths, "snapshot_sha256": snapshot_hashes}
    return contracts


def load_date_rows(csv_path: Path) -> tuple[set[str] | None, str | None]:
    """Return (set_of_dates, error) for a date-indexed CSV.
    error is None on success; if error is set, the caller MUST fail closed.
    (None, None) means "no date column found" — the caller decides whether
    that is acceptable (only for a contract not required by any registered
    family) or itself an error."""
    if not csv_path.exists():
        return None, f"declared source file {csv_path} does not exist on disk"
    try:
        with csv_path.open() as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, f"{csv_path} is empty (no header row)"
            date_col = None
            for candidate in ("date", "observation_date"):
                if candidate in header:
                    date_col = header.index(candidate)
                    break
            if date_col is None:
                return None, None
            dates = set()
            for row in reader:
                if len(row) > date_col:
                    dates.add(row[date_col])
            return dates, None
    except (OSError, csv.Error) as exc:
        return None, f"{csv_path} could not be read: {exc}"


def load_calendar_artifact(path: Path = CALENDAR_ARTIFACT_PATH) -> tuple[dict | None, str | None]:
    """Load the pinned, versioned expected-session calendar — generated once
    by build_expected_session_calendar.py from an independent XNYS holiday
    rule (XNYS_ETF_BREADTH/CBOE_VIX) or the federal holiday calendar
    (FRED_OAS), never re-derived live inside this function.
    Returns (artifact, error)."""
    if not path.exists():
        return None, f"expected-session calendar artifact {path} does not exist — run build_expected_session_calendar.py"
    try:
        with path.open() as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"expected-session calendar artifact {path} could not be parsed: {exc}"
    families = data.get("families")
    if not isinstance(families, dict):
        return None, f"expected-session calendar artifact {path} has no 'families' object"
    return data, None


def check_calendar_artifact_integrity(calendar_artifact: dict | None, errors: list[str]) -> None:
    """Validate the calendar artifact's own declared metadata and reconciled
    source files (msg 150 item 3): generation_method/calendar_version present,
    every declared reconciled source file's CURRENT hash matches what the
    artifact recorded at generation time (so a source file drifting after the
    artifact was built is detected), and all three families are present with
    nonempty session lists."""
    if not isinstance(calendar_artifact, dict):
        errors.append("calendar artifact could not be loaded or is not an object")
        return

    for key in ("calendar_version", "generation_method"):
        if not calendar_artifact.get(key):
            errors.append(f"calendar artifact missing required key '{key}'")

    families = calendar_artifact.get("families", {})
    for fam in REQUIRED_FAMILIES:
        dates = families.get(fam)
        if not isinstance(dates, list) or not dates:
            errors.append(f"calendar artifact has no nonempty session list for family {fam}")

    declared_hashes = calendar_artifact.get("reconciled_source_sha256_at_generation", {})
    if not declared_hashes:
        errors.append("calendar artifact has no 'reconciled_source_sha256_at_generation' — cannot verify it was built from real, identified source files")
    for rel_path, declared_hash in declared_hashes.items():
        actual = sha256_file(REPO_ROOT / rel_path)
        if actual is None:
            errors.append(f"calendar artifact declares reconciled source {rel_path}, but that file no longer exists on disk")
        elif actual != declared_hash:
            errors.append(
                f"calendar artifact's reconciled source {rel_path} has drifted: declared hash {declared_hash} "
                f"at generation time, current hash {actual} — the artifact may be stale; re-run build_expected_session_calendar.py"
            )


def get_reference_window(family: str, anchor: str, calendar_families: dict) -> list[str] | None:
    """Resolve the family's canonical expected-session window from the pinned
    calendar artifact's own recorded session list for that family — an
    ordinary sorted-index lookup, but critically over a SEPARATE, pinned file
    that is never the file under test, so a mutation to a copied data file
    (in the self-test, or in reality) cannot affect the window it's being
    checked against. (Two earlier constructions were tried and both proved
    circular under self-test: deriving the window from "a reference contract's
    own rows," and deriving it from a live hand-rolled holiday rule set that
    was independently proven wrong on both real closures and real trading
    days — see the module docstring.)"""
    dates = calendar_families.get(family)
    if not isinstance(dates, list) or not dates:
        return None
    if anchor not in dates:
        return None
    idx = dates.index(anchor)
    lo = max(0, idx - WINDOW_SESSIONS)
    hi = min(len(dates), idx + WINDOW_SESSIONS + 1)
    return dates[lo:hi]


def check_source_integrity_and_calendar(
    entries: list[dict], contracts: dict[str, dict], calendar_families: dict, errors: list[str]
) -> None:
    """contracts is injectable (not always the real manifest) so callers —
    including the self-test — can mutate a copy: point a path at a
    nonexistent file, corrupt a pinned hash, or remove rows from a copied
    date index, and prove rejection without touching the real manifest or
    data files. calendar_families is likewise injectable (a copy of the
    pinned calendar artifact's "families" dict) so a self-test can prove the
    window itself is used correctly without ever needing to mutate the real
    artifact file."""
    date_cache: dict[Path, tuple[set[str] | None, str | None]] = {}
    hash_cache: dict[Path, str | None] = {}
    window_cache: dict[tuple[str, str], list[str] | None] = {}

    for e in entries:
        if not isinstance(e, dict):
            continue
        iid = e.get("injection_id", "<unknown>")
        family = e.get("family")
        start_date = e.get("start_date")
        entry_cids = e.get("contract_ids")

        # Exact family -> contract-ID set enforcement.
        if family in FAMILY_CONTRACT_IDS:
            expected = FAMILY_CONTRACT_IDS[family]
            actual = set(entry_cids) if isinstance(entry_cids, list) else set()
            if actual != expected:
                errors.append(
                    f"{iid}: contract_ids {sorted(actual)} != exact required set "
                    f"for family {family}: {sorted(expected)}"
                )

        ref_seq = None
        if isinstance(family, str) and isinstance(start_date, str):
            cache_key = (family, start_date)
            if cache_key not in window_cache:
                window_cache[cache_key] = get_reference_window(family, start_date, calendar_families)
            ref_seq = window_cache[cache_key]

        for cid in (entry_cids or []):
            if not isinstance(cid, str) or cid not in contracts:
                errors.append(f"{iid}: contract_id {cid!r} does not exist in the manifest's source_contracts")
                continue
            for rel_path, abs_path in contracts[cid]["paths"]:
                if abs_path not in hash_cache:
                    hash_cache[abs_path] = sha256_file(abs_path)
                actual_hash = hash_cache[abs_path]
                pinned_hash = contracts[cid]["snapshot_sha256"].get(rel_path)
                if actual_hash is None:
                    errors.append(f"{iid}: source file {abs_path} for contract {cid} does not exist on disk")
                    continue
                if not pinned_hash:
                    errors.append(
                        f"{iid}: contract {cid} path {rel_path} has no pinned snapshot_sha256 in the manifest "
                        f"— a family-required source must have a pinned hash to compare against"
                    )
                elif actual_hash != pinned_hash:
                    errors.append(
                        f"{iid}: source file {abs_path} for contract {cid} has SHA-256 {actual_hash}, "
                        f"but the manifest pins {pinned_hash} — file has drifted from the pinned snapshot"
                    )

                if abs_path not in date_cache:
                    date_cache[abs_path] = load_date_rows(abs_path)
                dates, load_error = date_cache[abs_path]
                if load_error is not None:
                    errors.append(f"{iid}: {load_error} (contract {cid})")
                    continue
                if dates is None:
                    if family in FAMILY_CONTRACT_IDS:
                        errors.append(
                            f"{iid}: contract {cid} (path {rel_path}) has no recognizable date column "
                            f"but is required by family {family} — a date-indexed family source must resolve dates"
                        )
                    continue
                if not isinstance(start_date, str) or start_date not in dates:
                    errors.append(f"{iid}: start_date {start_date!r} has no row in {abs_path.name} (contract {cid})")
                    continue

                if ref_seq is None:
                    errors.append(f"{iid}: could not build a canonical reference window around {start_date} for family {family}")
                    continue
                missing_sessions = [d for d in ref_seq if d not in dates]
                if missing_sessions:
                    errors.append(
                        f"{iid}: {abs_path.name} (contract {cid}) is missing {len(missing_sessions)} session(s) "
                        f"present in the family's canonical reference window around {start_date}: {missing_sessions} "
                        f"— surrounding_completeness claim not supported"
                    )
                for a, b in zip(ref_seq, ref_seq[1:]):
                    da = datetime.date.fromisoformat(a)
                    db = datetime.date.fromisoformat(b)
                    if (db - da).days > GAP_TOLERANCE_CALENDAR_DAYS:
                        errors.append(
                            f"{iid}: canonical reference window for family {family} has a session gap of "
                            f"{(db - da).days} calendar days between {a} and {b} around {start_date} "
                            f"— natural gap in the reference calendar itself"
                        )


def check_traceability(registry: dict, errors: list[str]) -> None:
    """Compare the registry's own stored traceability hashes AND paths to the
    current bytes/declared paths, source_commit as exact 40-hex against live
    git HEAD, and source_tree_state against an enumerated value set."""
    trace = registry.get("traceability")
    if not isinstance(trace, dict):
        errors.append("'traceability' block is missing or not an object")
        return

    for hash_key, path_key, real_path in TRACEABILITY_FILE_CHECKS:
        stored_hash = trace.get(hash_key)
        stored_path = trace.get(path_key)
        expected_rel = str(real_path.relative_to(REPO_ROOT))
        if stored_path != expected_rel:
            errors.append(f"traceability.{path_key} = {stored_path!r}, expected {expected_rel!r}")
        if not stored_hash or "PENDING" in str(stored_hash):
            errors.append(f"traceability.{hash_key} is missing or a pending placeholder — must be a real hash before freeze")
            continue
        actual = sha256_file(real_path)
        if actual != stored_hash:
            errors.append(f"traceability.{hash_key} = {stored_hash}, but {real_path} currently hashes to {actual}")

    stored_commit = trace.get("source_commit")
    if not stored_commit:
        errors.append("traceability.source_commit is missing or empty")
    elif not COMMIT_HASH_PATTERN.match(stored_commit):
        errors.append(f"traceability.source_commit {stored_commit!r} is not a 40-character lowercase hex SHA-1")
    try:
        real_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        if stored_commit and COMMIT_HASH_PATTERN.match(stored_commit) and stored_commit != real_commit:
            errors.append(f"traceability.source_commit = {stored_commit!r}, but current HEAD is {real_commit!r}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        errors.append(f"could not verify traceability.source_commit against git HEAD: {exc}")

    tree_state = trace.get("source_tree_state")
    if not isinstance(tree_state, str) or not tree_state.split(" — ")[0].split(" (")[0].strip() in ALLOWED_TREE_STATES:
        # accept "clean" / "dirty" as the leading token, with explanatory prose following
        leading = tree_state.strip().split()[0].rstrip(",:;") if isinstance(tree_state, str) and tree_state.strip() else None
        if leading not in ALLOWED_TREE_STATES:
            errors.append(f"traceability.source_tree_state must start with one of {sorted(ALLOWED_TREE_STATES)}, got {tree_state!r}")


def check_superseded_entry(iid: str, e: dict, errors: list[str]) -> None:
    se = e.get("superseded_entry")
    if se is None:
        return
    required_se_fields = {"original_start_date", "original_registered_at", "correction_registered_at", "correction_reason"}
    if not isinstance(se, dict) or set(se.keys()) != required_se_fields:
        errors.append(f"{iid}: superseded_entry must be an object with exactly {sorted(required_se_fields)}")
        return

    reason = se.get("correction_reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append(f"{iid}: superseded_entry.correction_reason must be a nonempty string")

    orig_date = se.get("original_start_date")
    if not isinstance(orig_date, str):
        errors.append(f"{iid}: superseded_entry.original_start_date must be a string")
    else:
        try:
            datetime.date.fromisoformat(orig_date)
        except ValueError:
            errors.append(f"{iid}: superseded_entry.original_start_date {orig_date!r} does not parse as ISO date")
        if orig_date == e.get("start_date"):
            errors.append(f"{iid}: superseded_entry.original_start_date equals the current start_date — no actual correction occurred")

    orig_ts, corr_ts = se.get("original_registered_at"), se.get("correction_registered_at")
    parsed_orig = parsed_corr = None
    for label, ts in (("original_registered_at", orig_ts), ("correction_registered_at", corr_ts)):
        if not isinstance(ts, str) or not ts.endswith("Z"):
            errors.append(f"{iid}: superseded_entry.{label} must be an ISO-8601 UTC timestamp ending in 'Z'")
            continue
        try:
            parsed = datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            errors.append(f"{iid}: superseded_entry.{label} {ts!r} does not match %Y-%m-%dT%H:%M:%SZ")
            continue
        if label == "original_registered_at":
            parsed_orig = parsed
        else:
            parsed_corr = parsed

    if parsed_orig is not None and parsed_corr is not None and parsed_corr < parsed_orig:
        errors.append(f"{iid}: superseded_entry.correction_registered_at ({corr_ts}) is before original_registered_at ({orig_ts})")


def verify(registry, contracts: dict[str, dict], calendar_artifact: dict | None = None) -> list[str]:
    """Never raises on malformed input — every access is guarded and a shape
    problem is appended as a collected error, not an exception.
    calendar_artifact, if omitted, is loaded fresh from the real pinned
    CALENDAR_ARTIFACT_PATH; callers (notably the self-test) can pass a
    mutated copy instead."""
    errors: list[str] = []

    if not isinstance(registry, dict):
        return [f"registry root must be a JSON object, got {type(registry).__name__}"]

    if calendar_artifact is None:
        calendar_artifact, cal_err = load_calendar_artifact()
        if cal_err is not None:
            errors.append(cal_err)
            calendar_artifact = {"families": {}}
    calendar_families = calendar_artifact.get("families", {}) if isinstance(calendar_artifact, dict) else {}

    raw_entries = registry.get("injections")
    if not isinstance(raw_entries, list):
        errors.append(f"'injections' must be a list, got {type(raw_entries).__name__ if raw_entries is not None else 'missing'}")
        entries: list[dict] = []
    else:
        entries = raw_entries

    valid_entries: list[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            errors.append(f"an entry in 'injections' is not an object: {e!r}")
            continue
        valid_entries.append(e)

    for e in valid_entries:
        iid = e.get("injection_id", "<unknown>")
        missing = REQUIRED_ENTRY_FIELDS - set(e.keys())
        if missing:
            errors.append(f"{iid}: missing required fields {sorted(missing)}")
        extra = set(e.keys()) - REQUIRED_ENTRY_FIELDS - {"superseded_entry"}
        if extra:
            errors.append(f"{iid}: unexpected extra fields {sorted(extra)}")

        if not isinstance(iid, str) or not INJECTION_ID_PATTERN.match(iid):
            errors.append(f"{iid!r}: injection_id must match {INJECTION_ID_PATTERN.pattern}")

        for field in ("selection_rationale", "calendar_status_at_injection", "surrounding_completeness"):
            val = e.get(field)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"{iid}: {field} must be a nonempty string, got {val!r}")

        cids = e.get("contract_ids")
        if not isinstance(cids, list) or not cids or not all(isinstance(c, str) for c in cids):
            errors.append(f"{iid}: contract_ids must be a nonempty list of strings, got {cids!r}")
        elif len(set(cids)) != len(cids):
            errors.append(f"{iid}: contract_ids contains duplicates: {cids}")

        if e.get("registered_by") not in ("CLAUDE", "CHATGPT", "human"):
            errors.append(f"{iid}: registered_by={e.get('registered_by')!r} not one of CLAUDE/CHATGPT/human")

        check_superseded_entry(iid, e, errors)

        if e.get("split") not in ALLOWED_SPLITS:
            errors.append(f"{iid}: split={e.get('split')!r} not in {ALLOWED_SPLITS}")

        n = e.get("outage_length")
        if not isinstance(n, int) or isinstance(n, bool) or n not in REQUIRED_LENGTHS:
            errors.append(f"{iid}: outage_length={n!r} not in approved set {sorted(REQUIRED_LENGTHS)}")

        if e.get("regime_stratum") not in REQUIRED_STRATA:
            errors.append(f"{iid}: regime_stratum={e.get('regime_stratum')!r} not in {REQUIRED_STRATA}")

        start_date = e.get("start_date")
        d = None
        if not isinstance(start_date, str):
            errors.append(f"{iid}: start_date {start_date!r} is not a string")
        else:
            try:
                d = datetime.date.fromisoformat(start_date)
            except ValueError:
                errors.append(f"{iid}: start_date {start_date!r} does not parse as ISO date")
        if d is not None and d.weekday() >= 5:
            errors.append(f"{iid}: start_date {start_date} falls on a weekend")

        ra = e.get("registered_at", "")
        if not (isinstance(ra, str) and ra.endswith("Z")):
            errors.append(f"{iid}: registered_at {ra!r} must be an ISO-8601 UTC timestamp ending in 'Z'")
        else:
            try:
                datetime.datetime.strptime(ra, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                errors.append(f"{iid}: registered_at {ra!r} does not match %Y-%m-%dT%H:%M:%SZ")

        if e.get("family") not in REQUIRED_FAMILIES:
            errors.append(f"{iid}: family={e.get('family')!r} not in {REQUIRED_FAMILIES}")

    ids = [e.get("injection_id") for e in valid_entries]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate injection_id values: {sorted(dupes)}")

    by_fam: dict[str, dict[str, set[int]]] = {
        fam: {"development": set(), "holdout": set()} for fam in REQUIRED_FAMILIES
    }
    holdout_count: dict[str, int] = {fam: 0 for fam in REQUIRED_FAMILIES}
    holdout_strata: dict[str, set[str]] = {fam: set() for fam in REQUIRED_FAMILIES}
    dev_dates: dict[str, set[str]] = {fam: set() for fam in REQUIRED_FAMILIES}
    hold_dates: dict[str, set[str]] = {fam: set() for fam in REQUIRED_FAMILIES}
    all_strata: dict[str, set[str]] = {fam: set() for fam in REQUIRED_FAMILIES}

    for e in valid_entries:
        fam = e.get("family")
        if fam not in REQUIRED_FAMILIES:
            continue
        split = e.get("split")
        length = e.get("outage_length")
        if split in ("development", "holdout") and isinstance(length, int):
            by_fam[fam][split].add(length)
        if split == "holdout":
            holdout_count[fam] += 1
            holdout_strata[fam].add(e.get("regime_stratum"))
            hold_dates[fam].add(e.get("start_date"))
        elif split == "development":
            dev_dates[fam].add(e.get("start_date"))
        all_strata[fam].add(e.get("regime_stratum"))

    for fam in REQUIRED_FAMILIES:
        missing_dev = REQUIRED_LENGTHS - by_fam[fam]["development"]
        if missing_dev:
            errors.append(f"{fam}: development split missing outage lengths {sorted(missing_dev)}")
        missing_hold = REQUIRED_LENGTHS - by_fam[fam]["holdout"]
        if missing_hold:
            errors.append(f"{fam}: holdout split missing outage lengths {sorted(missing_hold)}")
        if holdout_count[fam] < MIN_HOLDOUT_ENTRIES_PER_FAMILY:
            errors.append(f"{fam}: only {holdout_count[fam]} holdout entries, minimum is {MIN_HOLDOUT_ENTRIES_PER_FAMILY}")
        missing_strata_all = REQUIRED_STRATA - all_strata[fam]
        if missing_strata_all:
            errors.append(f"{fam}: missing regime strata overall {sorted(missing_strata_all)}")
        missing_strata_hold = REQUIRED_STRATA - holdout_strata[fam]
        if missing_strata_hold:
            errors.append(f"{fam}: holdout split missing regime strata {sorted(missing_strata_hold)}")
        overlap = dev_dates[fam] & hold_dates[fam]
        if overlap:
            errors.append(f"{fam}: development/holdout start_date overlap {sorted(overlap)} (leakage risk)")

    contract_map = registry.get("reason_code_contract")
    if contract_map is None:
        errors.append("top-level key 'reason_code_contract' is missing or null")
    elif not isinstance(contract_map, dict):
        errors.append(f"'reason_code_contract' must be an object, got {type(contract_map).__name__}")
    else:
        if set(contract_map.keys()) != set(EXPECTED_REASON_MAPPING.keys()):
            errors.append(f"reason_code_contract states {sorted(contract_map.keys())} != expected {sorted(EXPECTED_REASON_MAPPING.keys())}")
        for state, expected_codes in EXPECTED_REASON_MAPPING.items():
            actual = contract_map.get(state)
            if actual != expected_codes:
                errors.append(f"reason_code_contract[{state!r}] = {actual!r}, expected exactly {expected_codes!r}")

    if "known_outstanding_items" not in registry:
        errors.append("'known_outstanding_items' key is missing — must be present and exactly [] at freeze")
    elif registry.get("known_outstanding_items") != []:
        errors.append(f"'known_outstanding_items' = {registry.get('known_outstanding_items')!r}, must be exactly [] at freeze")

    check_calendar_artifact_integrity(calendar_artifact, errors)
    check_source_integrity_and_calendar(valid_entries, contracts, calendar_families, errors)
    check_traceability(registry, errors)

    return errors


# ---------------------------------------------------------------------------
# Negative-test suite: prove the verifier actually rejects each named defect
# class, not just that it accepts a clean registry.
# ---------------------------------------------------------------------------

def _check(registry, contracts, description: str, expect_error_substring: str | None = None, calendar=None) -> str | None:
    errs = verify(registry, contracts, calendar_artifact=calendar)
    if not errs:
        return f"NEGATIVE TEST FAILED: '{description}' did not produce any verification error"
    if expect_error_substring and not any(expect_error_substring in e for e in errs):
        return (
            f"NEGATIVE TEST WEAK: '{description}' produced errors but none contained "
            f"expected substring {expect_error_substring!r}: {errs[:3]}"
        )
    return None


def _positive_check(registry, contracts, description: str, calendar=None) -> str | None:
    """The inverse of _check: assert a registry PASSES (no errors). Used for
    reconciliation proof cases — a real anchor near a known extraordinary
    closure, observed-holiday exception, or pre-adoption holiday that MUST
    still validate cleanly against the pinned calendar artifact."""
    errs = verify(registry, contracts, calendar_artifact=calendar)
    if errs:
        return f"POSITIVE RECONCILIATION TEST FAILED: '{description}' should have passed but got errors: {errs[:5]}"
    return None


def _remove_row_from_copied_contract(contracts: dict, cid: str, date_to_remove: str) -> dict:
    """Return a deep copy of `contracts` where `cid`'s CSV rows are pre-loaded
    with `date_to_remove` excluded, by monkeypatching the path to a temp file
    with that row stripped. Used for the requested adjacent-row-removal tests."""
    import tempfile

    c = copy.deepcopy(contracts)
    rel_path, abs_path = c[cid]["paths"][0]
    with abs_path.open() as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    date_col = next(i for i, h in enumerate(header) if h in ("date", "observation_date"))
    filtered = [r for r in rows if not (len(r) > date_col and r[date_col] == date_to_remove)]

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    writer = csv.writer(tmp)
    writer.writerow(header)
    writer.writerows(filtered)
    tmp.close()
    c[cid]["paths"] = [(rel_path, Path(tmp.name))]
    # Blank the pinned hash for this mutated copy so the byte-hash check (which
    # is a separate, already-tested defect class) doesn't also fire here and
    # confound this test's specific assertion about the missing-session check.
    c[cid]["snapshot_sha256"] = {rel_path: "0" * 64}
    return c


def run_self_test() -> int:
    with REGISTRY_PATH.open() as f:
        base_registry = json.load(f)
    base_contracts = load_manifest_contracts()
    base_calendar, cal_err = load_calendar_artifact()
    if cal_err is not None:
        print(f"NEGATIVE-TEST SUITE FAIL: could not load calendar artifact: {cal_err}")
        return 1

    results: list[tuple[str, str | None]] = []

    def run(desc, registry, contracts=None, expect=None, calendar=None):
        r = _check(
            registry,
            contracts if contracts is not None else base_contracts,
            desc,
            expect,
            calendar=calendar if calendar is not None else base_calendar,
        )
        results.append((desc, r))

    def run_positive(desc, registry, contracts=None, calendar=None):
        r = _positive_check(
            registry,
            contracts if contracts is not None else base_contracts,
            desc,
            calendar=calendar if calendar is not None else base_calendar,
        )
        results.append((desc, r))

    # --- family/contract-set defects ---
    r = copy.deepcopy(base_registry)
    r["injections"][0]["contract_ids"] = ["OAS_V5_1"]
    run("wrong/substituted contract for a family", r, expect="!= exact required set")

    r = copy.deepcopy(base_registry)
    r["injections"][0]["contract_ids"] = r["injections"][0]["contract_ids"][:-1]
    run("missing contract from required set", r, expect="!= exact required set")

    r = copy.deepcopy(base_registry)
    r["injections"][0]["contract_ids"] = r["injections"][0]["contract_ids"] + ["OAS_V5_1"]
    run("extra contract beyond required set", r, expect="!= exact required set")

    # --- outage length ---
    r = copy.deepcopy(base_registry)
    r["injections"][0]["outage_length"] = 4
    run("unapproved outage_length (4)", r, expect="not in approved set")

    # --- reason codes ---
    r = copy.deepcopy(base_registry)
    r["reason_code_contract"]["STALE"] = ["WRONG_CODE"]
    run("wrong reason code value", r, expect="reason_code_contract")

    r = copy.deepcopy(base_registry)
    r["reason_code_contract"]["CURRENT"] = ["null", "SOURCE_LATE_WITHIN_GRACE"]
    run("JSON string 'null' instead of actual null", r, expect="reason_code_contract")

    # --- source path / hash defects (injectable contracts copy) ---
    c = copy.deepcopy(base_contracts)
    c["OAS_V5_1"]["paths"] = [(rel, Path("/nonexistent/path/does-not-exist.csv")) for rel, _ in c["OAS_V5_1"]["paths"]]
    run("missing source file path", copy.deepcopy(base_registry), contracts=c, expect="does not exist on disk")

    c = copy.deepcopy(base_contracts)
    for rel in list(c["OAS_V5_1"]["snapshot_sha256"].keys()):
        c["OAS_V5_1"]["snapshot_sha256"][rel] = "f" * 64
    run("wrong pinned source hash", copy.deepcopy(base_registry), contracts=c, expect="has drifted from the pinned snapshot")

    c = copy.deepcopy(base_contracts)
    c["OAS_V5_1"]["snapshot_sha256"] = {}
    run("missing pinned source hash entirely", copy.deepcopy(base_registry), contracts=c, expect="no pinned snapshot_sha256")

    # --- date-column / calendar defects ---
    c = copy.deepcopy(base_contracts)
    c["OAS_V5_1"]["paths"] = [(rel, VERIFIER_PATH) for rel, _ in c["OAS_V5_1"]["paths"]]  # a real file, not a dated CSV
    run("required family source with no date column", copy.deepcopy(base_registry), contracts=c, expect="no recognizable date column")

    r = copy.deepcopy(base_registry)
    r["injections"][0]["start_date"] = "2019-08-17"
    run("date with no row in the source file", r, expect="has no row in")

    # --- adjacent-expected-row-removal tests (msg 146 item 2), proven against
    # the calendar-derived window so they cannot be defeated by re-centering ---
    c = _remove_row_from_copied_contract(base_contracts, "QQQ_V5_1", "2019-08-14")  # a day adjacent to a real XNYS anchor
    run("row removed from an XNYS family file (QQQ)", copy.deepcopy(base_registry), contracts=c, expect="missing")

    c = _remove_row_from_copied_contract(base_contracts, "VIX9D_V5_1", "2019-08-14")
    run("row removed from a VIX-family file (VIX9D)", copy.deepcopy(base_registry), contracts=c, expect="missing")

    # FRED-DEV-ORD-001's anchor is 2023-09-05; remove an adjacent business day from its window.
    c = _remove_row_from_copied_contract(base_contracts, "OAS_V5_1", "2023-08-29")
    run("row removed from FRED OAS file (independent of calendar self-reference)", copy.deepcopy(base_registry), contracts=c, expect="missing")

    # SPY/BENCHMARK_V5_1 is a normal required family contract, not a special
    # "reference contract" under the calendar-only design — removing one of its
    # rows must be caught exactly like any other family file's missing row,
    # proving the calendar window cannot be defeated even by editing the file
    # that (in the earlier, file-based design) would have BEEN the reference.
    c = _remove_row_from_copied_contract(base_contracts, "BENCHMARK_V5_1", "2019-08-14")
    run("row removed from SPY itself (formerly the file-based reference)", copy.deepcopy(base_registry), contracts=c, expect="missing")

    # --- dev/holdout leakage ---
    r = copy.deepcopy(base_registry)
    dev_date = next(e["start_date"] for e in r["injections"] if e["family"] == "XNYS_ETF_BREADTH" and e["split"] == "development")
    for e in r["injections"]:
        if e["family"] == "XNYS_ETF_BREADTH" and e["split"] == "holdout":
            e["start_date"] = dev_date
            break
    run("development/holdout start_date overlap", r, expect="overlap")

    # --- timestamp / traceability ---
    r = copy.deepcopy(base_registry)
    r["injections"][0]["registered_at"] = "not-a-timestamp"
    run("malformed registered_at timestamp", r, expect="ISO-8601")

    r = copy.deepcopy(base_registry)
    r["traceability"]["manifest_sha256_at_registry_build"] = "0" * 64
    run("wrong traceability hash", r, expect="currently hashes to")

    r = copy.deepcopy(base_registry)
    r["traceability"]["manifest_at_registry_build"] = "some/wrong/path.json"
    run("wrong traceability path", r, expect="expected")

    r = copy.deepcopy(base_registry)
    r["traceability"]["source_commit"] = "0" * 40
    run("wrong source_commit", r, expect="current HEAD is")

    r = copy.deepcopy(base_registry)
    del r["traceability"]["source_commit"]
    run("missing source_commit", r, expect="source_commit is missing")

    r = copy.deepcopy(base_registry)
    r["traceability"]["source_commit"] = "not-40-hex"
    run("malformed source_commit (not 40-hex)", r, expect="40-character")

    r = copy.deepcopy(base_registry)
    r["traceability"]["source_tree_state"] = "some arbitrary prose with no leading clean/dirty token"
    run("source_tree_state not enumerated", r, expect="source_tree_state")

    # --- superseded_entry validation ---
    r = copy.deepcopy(base_registry)
    superseded_entry_holder = next(e for e in r["injections"] if "superseded_entry" in e)
    superseded_entry_holder["superseded_entry"]["correction_reason"] = ""
    run("superseded_entry empty correction_reason", r, expect="correction_reason")

    r = copy.deepcopy(base_registry)
    holder = next(e for e in r["injections"] if "superseded_entry" in e)
    holder["superseded_entry"]["correction_registered_at"] = "2000-01-01T00:00:00Z"  # before original
    run("superseded_entry correction before original registration", r, expect="is before")

    r = copy.deepcopy(base_registry)
    holder = next(e for e in r["injections"] if "superseded_entry" in e)
    holder["superseded_entry"]["original_start_date"] = holder["start_date"]
    run("superseded_entry original_start_date equals current (no real correction)", r, expect="no actual correction")

    # --- structural mutations ---
    r = copy.deepcopy(base_registry)
    del r["injections"][0]["selection_rationale"]
    run("missing required field", r, expect="missing required fields")

    r = copy.deepcopy(base_registry)
    r["injections"][0]["unexpected_field"] = "x"
    run("unexpected extra field", r, expect="unexpected extra fields")

    r = copy.deepcopy(base_registry)
    r["injections"][0]["contract_ids"] = [123, 456]
    run("non-string contract_ids", r, expect="contract_ids must be a nonempty list of strings")

    r = copy.deepcopy(base_registry)
    r["injections"].append(copy.deepcopy(r["injections"][0]))
    run("duplicate injection_id", r, expect="duplicate injection_id")

    r = copy.deepcopy(base_registry)
    r["known_outstanding_items"] = ["something unresolved"]
    run("nonempty known_outstanding_items", r, expect="known_outstanding_items")

    r = copy.deepcopy(base_registry)
    if "known_outstanding_items" in r:
        del r["known_outstanding_items"]
    run("missing known_outstanding_items key", r, expect="known_outstanding_items")

    # --- malformed-registry crash paths: must return errors, not raise ---
    r = copy.deepcopy(base_registry)
    r["injections"][0] = {}
    run("empty entry dict (no injection_id at all)", r, expect="missing required fields")

    r = copy.deepcopy(base_registry)
    r["injections"] = "not-a-list"
    run("injections is not a list", r, expect="'injections' must be a list")

    r = copy.deepcopy(base_registry)
    del r["injections"]
    run("no injections key at all", r, expect="'injections' must be a list")

    r = copy.deepcopy(base_registry)
    r["traceability"] = None
    run("traceability is null", r, expect="traceability")

    # --- calendar artifact traceability (msg 148 item 3) ---
    r = copy.deepcopy(base_registry)
    r["traceability"]["expected_session_calendar_sha256_at_registry_build"] = "0" * 64
    run("wrong expected_session_calendar hash", r, expect="currently hashes to")

    # --- calendar reconciliation proof cases (msg 148 item 3): POSITIVE
    # assertions (the pinned calendar artifact must correctly reflect real
    # extraordinary closures, observed-holiday exceptions, and pre-adoption
    # holiday history), tracked separately from the negative mutation tests
    # above since "pass" here means the check found no discrepancy, not that
    # a deliberate defect was rejected. ---
    reconciliation_results: list[tuple[str, str | None]] = []
    xnys_dates = set(base_calendar["families"]["XNYS_ETF_BREADTH"])
    fred_dates = set(base_calendar["families"]["FRED_OAS"])

    # (a) extraordinary XNYS closure: must NOT be present as a session (9/11).
    extraordinary_closure_ok = "2001-09-11" not in xnys_dates
    reconciliation_results.append((
        "extraordinary XNYS closure (2001-09-11) correctly excluded",
        None if extraordinary_closure_ok else "RECONCILIATION FAILED: 2001-09-11 (9/11 closure) present in calendar as a session",
    ))

    # (b) year-end observed-holiday exception: must BE present (XNYS traded).
    observed_holiday_ok = "1999-12-31" in xnys_dates
    reconciliation_results.append((
        "year-end observed-holiday exception (1999-12-31) correctly included",
        None if observed_holiday_ok else "RECONCILIATION FAILED: 1999-12-31 (real trading day) absent from calendar",
    ))

    # (c) pre-adoption holiday: Juneteenth's first observance (2021-06-18) —
    # XNYS traded, since the holiday was signed into law with one day's notice.
    pre_adoption_ok = "2021-06-18" in xnys_dates
    reconciliation_results.append((
        "pre-adoption holiday exception (2021-06-18 Juneteenth) correctly included",
        None if pre_adoption_ok else "RECONCILIATION FAILED: 2021-06-18 (real trading day, pre-adoption) absent from calendar",
    ))

    # (c2) msg 150 item 1: direct invariant tests, checked purely against the
    # frozen artifact's own data (independent of the builder functions, per
    # item 3) — proving the holiday-specific observance fix is actually
    # reflected in the pinned artifact, not just in the generator's logic.
    # 2020-07-03 and 2021-12-24 are real full-day closures (Friday preceding
    # a Saturday July 4th/Christmas, nearest_workday rule) and must be
    # EXCLUDED; 2021-12-31 is a distinct case (Friday preceding a Saturday
    # New Year's Day, sunday_to_monday-only rule) and must be INCLUDED —
    # proving the two rules are not conflated.
    july4_observed_excluded = "2020-07-03" not in xnys_dates
    reconciliation_results.append((
        "Independence Day observed closure (2020-07-03) correctly excluded as a real holiday, not a vendor gap",
        None if july4_observed_excluded else "RECONCILIATION FAILED: 2020-07-03 present in calendar as a session (should be excluded — real Independence Day observed closure)",
    ))
    christmas_observed_excluded = "2021-12-24" not in xnys_dates
    reconciliation_results.append((
        "Christmas observed closure (2021-12-24) correctly excluded as a real holiday, not a vendor gap",
        None if christmas_observed_excluded else "RECONCILIATION FAILED: 2021-12-24 present in calendar as a session (should be excluded — real Christmas observed closure)",
    ))
    new_years_distinct_rule_ok = "2021-12-31" in xnys_dates
    reconciliation_results.append((
        "New Year's Day distinct rule (2021-12-31) correctly remains included, not conflated with Independence Day/Christmas observance",
        None if new_years_distinct_rule_ok else "RECONCILIATION FAILED: 2021-12-31 absent from calendar (should be included — New Year's Day uses sunday_to_monday only, no Friday substitution)",
    ))

    # (c3) msg 150 item 2: known Cboe vendor-extra dates must NEVER be part of
    # the normative CBOE_VIX expected-session schedule — a data-quality
    # classification must not be promoted into calendar truth.
    cboe_dates_check = set(base_calendar["families"]["CBOE_VIX"])
    vendor_extras_not_normative = all(d not in cboe_dates_check for d in ("2026-05-25", "2026-08-25"))
    reconciliation_results.append((
        "known Cboe vendor-extra dates (2026-05-25, 2026-08-25) are NOT part of the normative CBOE_VIX schedule",
        None if vendor_extras_not_normative else "RECONCILIATION FAILED: a known vendor-extra date was found in families.CBOE_VIX — data-quality classification was incorrectly promoted into calendar truth",
    ))

    # (d) OAS federal-holiday carry-forward observation: under the v2/round-9
    # model, expected_session_calendar's FRED_OAS list is the MINIMUM expected
    # federal-business-day set (independent of the OAS file's own rows); a
    # real published OAS value on a federal holiday (FRED's carry-forward
    # convention) is a BONUS observation, correctly NOT part of that minimum
    # expectation. Confirm both halves: the real OAS file has the row
    # (independent of the artifact), and the artifact correctly does not
    # claim that holiday as an expected session (since it's not guaranteed —
    # claiming it would make the expectation file-dependent again).
    import csv as _csv
    with (REPO_ROOT / "research/data/raw/BAMLH0A0HYM2.csv").open() as _f:
        _reader = _csv.reader(_f)
        next(_reader)
        _real_oas_dates = {row[0] for row in _reader if row}
    oas_row_present = "2023-10-09" in _real_oas_dates  # Columbus Day 2023, real published OAS value
    oas_not_falsely_expected = "2023-10-09" not in fred_dates  # correctly excluded from the minimum expectation
    reconciliation_results.append((
        "OAS federal-holiday carry-forward observation (2023-10-09): real row present, correctly not claimed as an expected minimum session",
        None if (oas_row_present and oas_not_falsely_expected)
        else f"RECONCILIATION FAILED: 2023-10-09 — real OAS row present={oas_row_present} (expected True), falsely claimed as expected session={not oas_not_falsely_expected} (expected False)",
    ))

    # (e) full re-derivation reconciliation for ALL THREE families (msg 150
    # item 3: "the verifier reconciles only the XNYS union, not Cboe or
    # FRED"): re-run the builder's own independent calendar-derivation
    # functions fresh and confirm the pinned artifact's stored session lists
    # exactly match — proves the artifact wasn't hand-edited or left stale
    # after a rule/source change, for every family, not just XNYS.
    import importlib.util as _ilu

    builder_spec = _ilu.spec_from_file_location("_calendar_builder", CALENDAR_BUILDER_PATH)
    builder = _ilu.module_from_spec(builder_spec)
    builder_spec.loader.exec_module(builder)

    spy_dates_live = builder.load_dates(builder.SPY_PATH)
    lo_live, hi_live = min(spy_dates_live), max(spy_dates_live)
    xnys_holidays_live = builder.build_xnys_holiday_calendar(lo_live, hi_live)
    xnys_exclude_live = set(builder.EXTRAORDINARY_CLOSURES.keys())
    xnys_expected_live = builder.build_expected_sessions(lo_live, hi_live, xnys_holidays_live, xnys_exclude_live)
    reconciliation_results.append((
        "XNYS_ETF_BREADTH artifact exactly reconciles with a fresh independent re-derivation",
        None if xnys_dates == xnys_expected_live else f"RECONCILIATION FAILED: artifact has {len(xnys_dates)} XNYS dates, fresh re-derivation has {len(xnys_expected_live)}",
    ))

    cboe_union_live = set()
    for f in builder.CBOE_UNION_FILES:
        cboe_union_live |= builder.load_dates(f)
    cboe_lo_live, cboe_hi_live = min(cboe_union_live), max(cboe_union_live)
    # Per msg 150 item 2 (and its round-10 fix in the builder): known Cboe
    # vendor-extra dates are NEVER merged into the expected schedule — the
    # fresh re-derivation must match that, or this test would itself
    # reintroduce the bug it's meant to catch.
    cboe_expected_full_live = xnys_expected_live
    cboe_expected_in_range_live = {d for d in cboe_expected_full_live if cboe_lo_live <= d <= cboe_hi_live}
    reconciliation_results.append((
        "CBOE_VIX artifact exactly reconciles with a fresh independent re-derivation",
        None if set(base_calendar["families"]["CBOE_VIX"]) == cboe_expected_in_range_live
        else f"RECONCILIATION FAILED: artifact has {len(base_calendar['families']['CBOE_VIX'])} Cboe dates, fresh re-derivation has {len(cboe_expected_in_range_live)}",
    ))

    fred_dates_live = builder.load_dates(builder.FRED_OAS_FILE)
    fred_lo_live, fred_hi_live = min(fred_dates_live), max(fred_dates_live)
    fred_holidays_live = builder.build_federal_holiday_calendar(fred_lo_live, fred_hi_live)
    fred_expected_live = builder.build_expected_sessions(fred_lo_live, fred_hi_live, fred_holidays_live, set())
    reconciliation_results.append((
        "FRED_OAS artifact exactly reconciles with a fresh independent re-derivation",
        None if set(base_calendar["families"]["FRED_OAS"]) == fred_expected_live
        else f"RECONCILIATION FAILED: artifact has {len(base_calendar['families']['FRED_OAS'])} FRED dates, fresh re-derivation has {len(fred_expected_live)}",
    ))

    failures = [(d, r) for d, r in results if r is not None]
    for d, r in results:
        if r is None:
            print(f"  [reject OK] {d}")
    reconciliation_failures = [(d, r) for d, r in reconciliation_results if r is not None]
    for d, r in reconciliation_results:
        if r is None:
            print(f"  [reconciled OK] {d}")

    all_failures = failures + reconciliation_failures
    if all_failures:
        print(f"\nNEGATIVE-TEST SUITE FAIL ({len(failures)}/{len(results)} mutation blind spots, {len(reconciliation_failures)}/{len(reconciliation_results)} reconciliation failures):")
        for d, r in all_failures:
            print(f" - {r}")
        return 1
    print(
        f"\nNEGATIVE-TEST SUITE PASS ({len(results)}/{len(results)} mutations correctly rejected, "
        f"{len(reconciliation_results)}/{len(reconciliation_results)} calendar reconciliation checks passed)"
    )
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        try:
            return run_self_test()
        except Exception as exc:
            print(f"NEGATIVE-TEST SUITE FAIL: verifier raised {type(exc).__name__}: {exc}")
            return 1

    with REGISTRY_PATH.open() as f:
        registry = json.load(f)

    contracts = load_manifest_contracts()
    try:
        errors = verify(registry, contracts)
    except Exception as exc:
        print(f"FAIL: verifier raised {type(exc).__name__}: {exc} (verify() must not raise on malformed input)")
        return 1

    print(f"registry file:          {REGISTRY_PATH}")
    print(f"registry sha256:        {sha256_file(REGISTRY_PATH)}")
    print(f"spec file:              {SPEC_PATH}")
    print(f"spec sha256:            {sha256_file(SPEC_PATH)}")
    print(f"manifest file:          {MANIFEST_PATH}")
    print(f"manifest sha256:        {sha256_file(MANIFEST_PATH)}")
    print(f"manifest schema file:   {SCHEMA_PATH}")
    print(f"manifest schema sha256: {sha256_file(SCHEMA_PATH)}")
    print(f"verifier file:          {VERIFIER_PATH}")
    print(f"verifier sha256:        {sha256_file(VERIFIER_PATH)}")
    print(f"calendar file:          {CALENDAR_ARTIFACT_PATH}")
    print(f"calendar sha256:        {sha256_file(CALENDAR_ARTIFACT_PATH)}")
    print()

    if errors:
        print(f"FAIL ({len(errors)} check(s) failed)")
        for e in errors:
            print(f" - {e}")
        return 1

    print(f"PASS — all checks passed ({len(registry.get('injections', []))} entries checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
