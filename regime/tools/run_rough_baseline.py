#!/usr/bin/env python3
"""Run the v5.1 engine end-to-end against real pinned data using
`REASONABLENESS_CHECK_ROUGH_BASELINE` (engine.py) — every real-scale
window fix this investigation has found so far (Direction 21/65/200,
Breadth 50/200, Impulse 5/20, real CRISIS domains via
use_real_crisis_domains=True), combined into one runnable config.

**THIS IS NOT A CALIBRATED PRODUCTION CONFIGURATION.** Pillar weights
are still equal 25% placeholders; hard_veto_rules/soft_cap_rules are
still empty; risk_appetite_weights/stability_weights/
trend_quality_weights are still equal-split placeholders; every D1-D4
numeric threshold inside crisis.py/engine.py is still Message[211]'s
original uncalibrated guess. This exists to answer "does the pipeline
run coherently on real-scale windows" (per the human's explicit
"Option a" direction) — NOT "is this state label correct/trustworthy
for real decisions". Per Message[262]'s review, a run of this script
should be reported as a pipeline SMOKE RUN, not as a market-state or
CRISIS-correctness check — the tool prints validity/reason-code detail
specifically so a reader can judge that for themselves, not so it can
be silently trusted.

Usage:
    python3 regime/tools/run_rough_baseline.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--n N]

WARM-UP, CORRECTED (Message[262] point 1 — a real error in the prior
version, not just imprecise wording): `--warmup-from` does NOT affect
any raw-series lookback window. D1/D2/Direction/Breadth all read their
windows directly from the FULLY LOADED raw series via
`RawSeries.window_ending(as_of, N)`, independent of which date the
caller starts calling `run_engine_for_date` from — verified directly:
D1 requires only VIX (real coverage from 2007-01-03, so its 504-session
window has been satisfiable since ~2009) plus a same-day VIX9D point
value (real coverage from 2018-06-22, the actual reason CRISIS cannot
be jointly evaluated before that date — confirmed directly:
`_d1_volatility_term_structure_evaluator` shows `valid=False` on
2018-06-21 and `valid=True` on 2018-06-22, with NO additional 504-
session wait after that date). `--warmup-from` instead controls how
much STATEFUL REPLAY HISTORY `RunningEngineState` accumulates before
the first printed date — Direction's pending-confirmation counter,
the ordinary/CRISIS/TRENDING state machines' own hysteresis counters,
and Impulse's `condition_score_history` (needed for its own horizon
lookups) all depend on how many prior bars were actually replayed
through this specific run, not on any raw-series availability.

PERFORMANCE NOTE (measured directly): the default --warmup-from
2019-01-01 to present is ~1900 real trading days; a full run through
all 12 modules (dominated by D1/D2's 504-session causal_midrank
recomputation every single bar) takes roughly 7 minutes wall-clock on
this machine, regardless of how few dates are actually --n printed at
the end. Not fast; run in the background for anything beyond a quick
check.

Output columns (per Message[262] point 2/3 — printing
crisis_active_domain_count alone cannot distinguish "genuinely calm"
from "domains unavailable", and an unavailable/degraded record needs
its reason surfaced, not silently omitted):
  date, state, current (state_is_current), condition_score,
  direction, crisis_valid/active (X/4 format — read active only when
  valid==4), crisis_reason_codes (any domain's non-empty reason codes,
  union across all four), top_reason_codes (the record's own top-level
  `reason_codes` and `unavailable_reason_codes`, when either is
  non-empty/non-None).
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.engine import (  # noqa: E402
    load_raw_series_bundle, new_running_engine_state, run_engine_for_date,
    REASONABLENESS_CHECK_ROUGH_BASELINE,
)


def _iso_date(value: str) -> str:
    """argparse `type=` validator (Message[264] point 3 -- the prior
    version compared date strings lexicographically with no format
    check at all; verified directly that `--start abc` parsed cleanly
    and would only fail obscurely later). Parses via
    `datetime.date.fromisoformat` and returns the canonical
    YYYY-MM-DD string, so downstream string comparisons stay correct
    (ISO date strings sort lexicographically the same as the dates
    they represent, which the rest of this file already relies on)."""
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"not a valid ISO date (YYYY-MM-DD): {value!r} ({e})")


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=_iso_date, default=None, help="first real trading date to include (YYYY-MM-DD)")
    parser.add_argument("--end", type=_iso_date, default=None, help="last real trading date to include (YYYY-MM-DD)")
    parser.add_argument("--n", type=int, default=20, help="if --start not given, show the last N real trading days (default 20, must be >0)")
    parser.add_argument("--warmup-from", type=_iso_date, default="2019-01-01",
                         help="controls how much STATEFUL REPLAY history RunningEngineState accumulates before "
                              "the first printed date (Direction pending-confirmation, state-machine hysteresis "
                              "counters, Impulse's condition_score_history) -- does NOT affect any raw-series "
                              "lookback window (see module docstring). Default 2019-01-01 is a practical choice, "
                              "not a real threshold tied to any specific window length.")
    parser.add_argument("--save-json", default=None, metavar="PATH",
                         help="also persist the COMPLETE, UNMODIFIED per-date output record (every field "
                              "run_engine_for_date produces, not a curated subset -- Message[264] point 2) as "
                              "JSON to this path, with metadata (script hash, manifest hash, the config's full "
                              "field-value serialization plus its own hash, date range).")
    args = parser.parse_args(argv)

    if args.n <= 0:
        parser.error(f"--n must be > 0, got {args.n}")
    if args.start is not None and args.start < args.warmup_from:
        parser.error(f"--start ({args.start}) is before --warmup-from ({args.warmup_from}) -- "
                     f"dates before --warmup-from are never replayed by this run, so --start there would "
                     f"silently produce no output. Lower --warmup-from instead if you need earlier dates.")
    if args.end is not None and args.start is not None and args.end < args.start:
        parser.error(f"--end ({args.end}) is before --start ({args.start})")
    if args.end is not None and args.end < args.warmup_from:
        parser.error(f"--end ({args.end}) is before --warmup-from ({args.warmup_from}) -- no real trading day "
                     f"in range would ever be replayed.")
    return args


def _json_default(obj):
    """json.dumps `default=` for --save-json: makes any plain dataclass
    (e.g. crisis_domain_status's CrisisDomainReading values, or the
    config object itself) serialize as its field dict via
    dataclasses.asdict, so a full record round-trips without a curated
    field allowlist (Message[264] point 2). Falls back to str() for
    anything else JSON can't natively handle (e.g. an Enum-like state
    value)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return str(obj)


def _code_version() -> dict:
    """Real git commit hash + dirty-working-tree flag for the repo this
    script lives in (Message[266] point 3 -- narrows "which code
    produced this run" to a checkable point; still not a full
    reproducibility guarantee, see the metadata note where this is
    used). Never raises: if git is unavailable or this isn't a git
    checkout, returns None for both fields rather than crashing a run
    over metadata."""
    repo_root = Path(__file__).resolve().parents[2]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo_root, capture_output=True, text=True, timeout=10,
        )
        if commit.returncode != 0:
            return {"commit": None, "dirty": None}
        return {"commit": commit.stdout.strip(), "dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None}
    except (subprocess.SubprocessError, OSError):
        return {"commit": None, "dirty": None}


def _crisis_summary(record: dict) -> tuple[str, str]:
    """(valid/active count string, union of non-empty per-domain reason
    codes) -- so a reader can tell 'genuinely calm' (valid==4,
    active==0) apart from 'some domain unavailable' (valid<4) without
    guessing, per Message[262] point 2."""
    status = record.get("crisis_domain_status") or {}
    valid_count = record.get("crisis_valid_domain_count")
    active_count = record.get("crisis_active_domain_count")
    reasons = set()
    for reading in status.values():
        rc = getattr(reading, "reason_codes", None)
        if rc:
            reasons.update(rc)
    return f"{active_count}/{valid_count}(active/valid of 4)", ",".join(sorted(reasons)) if reasons else "-"


def _top_level_reasons(record: dict) -> str:
    """Message[262] point 3: a degraded/unavailable record must surface
    WHY, not just that it happened."""
    parts = []
    urc = record.get("unavailable_reason_codes")
    if urc:
        parts.append(f"unavailable={urc}")
    rc = record.get("reason_codes")
    if rc:
        parts.append(f"reason_codes={rc}")
    if not record.get("state_is_current", True):
        veto = record.get("active_veto_ids")
        cap = record.get("active_cap_ids")
        if veto:
            parts.append(f"active_vetoes={veto}")
        if cap:
            parts.append(f"active_caps={cap}")
    return " ".join(parts) if parts else "-"


def main(argv=None) -> None:
    args = _parse_args(argv)

    print("REASONABLENESS_CHECK_ROUGH_BASELINE -- NOT a calibrated production configuration.", file=sys.stderr)
    print("Pillar weights, veto/cap rules, and every D1-D4 threshold remain uncalibrated placeholders.", file=sys.stderr)
    print("This is a pipeline SMOKE RUN, not a market-state or CRISIS-correctness check (Message[262]).\n", file=sys.stderr)

    manifest = load_manifest()
    raw_bundle = load_raw_series_bundle(manifest)
    config = REASONABLENESS_CHECK_ROUGH_BASELINE
    state = new_running_engine_state(config)

    all_dates = [o.date for o in raw_bundle.benchmark.observations if o.date >= args.warmup_from]
    if not all_dates:
        print(f"No real trading days found on/after --warmup-from {args.warmup_from}.", file=sys.stderr)
        return

    if args.start:
        print_from = args.start
    else:
        cutoff_dates = [d for d in all_dates if args.end is None or d <= args.end]
        if not cutoff_dates:
            print(f"No real trading day in range (--warmup-from {args.warmup_from}, --end {args.end}).", file=sys.stderr)
            return
        print_from = cutoff_dates[-args.n] if len(cutoff_dates) >= args.n else cutoff_dates[0]

    header = (f"{'date':12s} {'state':10s} {'current':8s} {'condition':>10s} {'direction':16s} "
              f"{'crisis(act/valid)':>18s} {'crisis_reasons':30s} top_level_reasons")
    print(header)
    saved_rows = []
    for d in all_dates:
        if args.end is not None and d > args.end:
            break
        record = run_engine_for_date(d, raw_bundle, state, config=config, manifest=manifest)
        if d < print_from:
            continue
        cond = record.get("condition_score")
        cond_str = f"{cond:.4f}" if cond is not None else "None"
        crisis_str, crisis_reasons = _crisis_summary(record)
        top_reasons = _top_level_reasons(record)
        print(f"{d:12s} {str(record['state']):10s} {str(record['state_is_current']):8s} "
              f"{cond_str:>10s} {str(record.get('direction_structure')):16s} "
              f"{crisis_str:>18s} {crisis_reasons:30s} {top_reasons}")
        if args.save_json:
            # Message[264] point 2 -- the prior version saved ~16 hand-
            # picked fields and called it "the full per-date record",
            # which it was not. This saves the ENTIRE assembled record
            # unmodified (via _json_default's dataclass-aware fallback,
            # e.g. crisis_domain_status's CrisisDomainReading objects),
            # not a curated subset -- a complete per-date engine-output
            # artifact, not a summary dressed up as one. Message[266]
            # point 3: this is NOT called "reproducible" -- see the
            # metadata note below for why, and what would actually be
            # needed for that stronger claim.
            saved_rows.append(record)

    if args.save_json:
        script_path = Path(__file__).resolve()
        code_version = _code_version()
        out = {
            "schema_version": "run_rough_baseline.outputs.v2",
            "metadata": {
                "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
                "manifest_sha256": manifest.manifest_sha256,
                # Message[266] point 3: script_sha256 alone only covers
                # THIS file -- the code that actually produces the
                # numbers (engine.py and every module it calls) was
                # previously unidentified. git_commit + git_dirty
                # narrows "which code produced this" to a real, checkable
                # point, though it is still not a full reproducibility
                # guarantee (Python/dependency versions and the OS/
                # platform are not captured) -- see "artifact_kind" below
                # for the honest claim this metadata actually supports.
                "git_commit": code_version["commit"],
                "git_dirty": code_version["dirty"],
                "python_version": sys.version,
                "config_name": "REASONABLENESS_CHECK_ROUGH_BASELINE",
                # Message[264] point 2 -- the prior version's "config":
                # "REASONABLENESS_CHECK_ROUGH_BASELINE" was a bare name,
                # not the field values it implied. Full config
                # serialization (asdict, since every field is itself a
                # plain dataclass -- verified directly, no RawSeries or
                # callables embedded) plus a real hash of that
                # serialization, so a reader can verify which exact
                # config values produced this run without re-deriving
                # them from engine.py's source at a possibly-different
                # commit.
                "config_values": dataclasses.asdict(config),
                "config_values_sha256": hashlib.sha256(
                    json.dumps(dataclasses.asdict(config), sort_keys=True, default=_json_default).encode()
                ).hexdigest(),
                "warmup_from": args.warmup_from, "start": args.start, "end": args.end, "n": args.n,
                # Message[266] point 3: "reproducible artifact" overclaimed
                # what script_sha256+manifest_sha256 alone could guarantee.
                # This is a "full_engine_output_artifact" -- a complete,
                # unmodified snapshot of what this run produced, traceable
                # to a specific git commit/dirty-state and config, but NOT
                # a guarantee that re-running it elsewhere reproduces the
                # exact same output (Python/dependency/OS versions are not
                # pinned here).
                "artifact_kind": "full_engine_output_artifact",
                "note": "pipeline smoke run, NOT a calibrated production configuration (Message[261]/[262]/[264]/[266])",
            },
            "rows": saved_rows,
        }
        out_path = Path(args.save_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, sort_keys=True, default=_json_default))
        print(f"\nSaved {len(saved_rows)} full records to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
