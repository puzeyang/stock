"""Shared infrastructure for continuous_domain_diagnostic_panel_v0's D4
leave-one-sector-out scripts (panel_b_loo_matrix.py, panel_b_test_b.py).

Pure descriptive diagnostic support code. NOT part of crisis.py/engine.py
and NOT imported by them — this module has no effect on production
behavior. Its only job is to give both Test A and Test B one shared,
correct D4-flag computation and one shared output/metadata format, so
the scripts cannot drift out of sync with each other or with their own
docstrings the way Message[255]/[256] found panel_b_loo_matrix.py and
panel_b_test_b.py had.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from v5_1.contracts import load_manifest
from v5_1.engine import (
    load_raw_series_bundle,
    _D4_SHORT_COLLAPSE_THRESHOLD, _D4_LONG_COLLAPSE_THRESHOLD,
    _D4_EXTREME_SHORT, _D4_EXTREME_LONG, _D4_SPEED_DROP_PP_THRESHOLD,
    _D4_SPEED_LOOKBACK_SESSIONS, _D4_MIN_COVERAGE,
    _breadth_dates_ending,
)
from v5_1.breadth import compute_participation, BreadthUnavailableError, _sma

FLOOR = "2018-06-22"  # VIX9D's real coverage start -- the binding constraint for the whole investigation
FLAGS = ("short_collapse", "long_collapse", "speed_collapse", "extreme", "active")

D4_THRESHOLDS = {
    "short_collapse_threshold": _D4_SHORT_COLLAPSE_THRESHOLD,
    "long_collapse_threshold": _D4_LONG_COLLAPSE_THRESHOLD,
    "extreme_short_threshold": _D4_EXTREME_SHORT,
    "extreme_long_threshold": _D4_EXTREME_LONG,
    "speed_drop_pp_threshold": _D4_SPEED_DROP_PP_THRESHOLD,
    "speed_lookback_sessions": _D4_SPEED_LOOKBACK_SESSIONS,
    "min_coverage": _D4_MIN_COVERAGE,
}


def load_real_data():
    """Real manifest + raw bundle, loaded once, reused across every
    scenario in a run. Returns (manifest, raw_bundle, dates, member_paths)."""
    manifest = load_manifest()
    raw_bundle = load_raw_series_bundle(manifest)
    dates = tuple(o.date for o in raw_bundle.benchmark.observations if o.date >= FLOOR)
    member_paths = tuple(raw_bundle.breadth.members.keys())
    return manifest, raw_bundle, dates, member_paths


def d4_flags_for(collection, as_of: str) -> dict | None:
    """Real D4 subconditions + active for one collection/date, mirroring
    `_d4_participation_collapse_evaluator`'s exact logic. Returns None if
    unavailable (coverage below `_D4_MIN_COVERAGE` or speed history
    insufficient for the level legs themselves -- speed unavailability
    alone does not invalidate the other legs, matching the production
    evaluator's own fail-open-per-leg behavior)."""
    try:
        pct50_now, pct200_now, eligible_now, total_now = compute_participation(collection, as_of, 50, 200)
    except BreadthUnavailableError:
        return None
    if total_now == 0 or eligible_now / total_now < _D4_MIN_COVERAGE:
        return None

    speed_collapse = False
    pct50_past = None
    past_as_of = None
    try:
        past_dates = _breadth_dates_ending(collection, as_of, _D4_SPEED_LOOKBACK_SESSIONS + 1)
        if past_dates is not None:
            past_as_of = past_dates[0]
            pct50_past, _pct200_past, eligible_past, total_past = compute_participation(collection, past_as_of, 50, 200)
            if total_past > 0 and eligible_past / total_past >= _D4_MIN_COVERAGE:
                speed_collapse = (pct50_past - pct50_now) >= _D4_SPEED_DROP_PP_THRESHOLD
            else:
                pct50_past = None
    except BreadthUnavailableError:
        speed_collapse = False
        pct50_past = None

    short_collapse = pct50_now <= _D4_SHORT_COLLAPSE_THRESHOLD
    long_collapse = pct200_now <= _D4_LONG_COLLAPSE_THRESHOLD
    extreme = pct50_now <= _D4_EXTREME_SHORT and pct200_now <= _D4_EXTREME_LONG
    active = extreme or sum([short_collapse, long_collapse, speed_collapse]) >= 2

    return {
        "pct50": pct50_now, "pct200": pct200_now,
        # NOTE: compute_participation() returns ONE combined eligible count
        # (min(eligible_50, eligible_200), per its own documented fail-closed
        # design choice), not two separate window counts -- so eligible50/
        # eligible200 are always equal here by construction, not merely
        # coincidentally. Verified directly against the real 2018-06-22+
        # timeline: 0/2053 dates show them differing (the 9-member universe
        # is fully warmed up for both windows throughout this floor).
        "eligible50": eligible_now, "eligible200": eligible_now, "total50": total_now,
        "pct50_past": pct50_past, "past_as_of": past_as_of,
        "short_collapse": short_collapse, "long_collapse": long_collapse,
        "speed_collapse": speed_collapse, "extreme": extreme, "active": active,
    }


def new_transition_matrix() -> dict:
    """One (base,new) -> count dict per flag, covering all four cells --
    pre-populated with zeros so a persisted matrix is always complete,
    never sparse/implicit like the earlier scripts' print-only version."""
    return {flag: {"0->0": 0, "0->1": 0, "1->0": 0, "1->1": 0} for flag in FLAGS}


def record_transition(matrix: dict, flag: str, base_val: bool, new_val: bool) -> bool:
    """Record one (base,new) observation into a transition matrix cell;
    returns True if this was a flip (base != new)."""
    key = f"{int(base_val)}->{int(new_val)}"
    matrix[flag][key] += 1
    return base_val != new_val


def k_cell(pct: float, total_members: int) -> int:
    """Real member count implied by a [0,1] participation percentage,
    for k-stratified reporting (Message[247] point 5 / Message[253])."""
    return round(pct * total_members)


def sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_output(output_dir: Path, filename: str, payload: dict, *, manifest, script_path: Path) -> Path:
    """Persist one panel result as JSON with a standard metadata block --
    script hash, input manifest hash, thresholds, schema version. Fixes
    Message[255]/[256]'s finding that no result was ever actually saved."""
    output_dir.mkdir(parents=True, exist_ok=True)
    full = {
        "schema_version": "continuous_domain_diagnostic_panel_v0.outputs.v1",
        "metadata": {
            "script_path": str(script_path.relative_to(script_path.resolve().parents[3])),
            "script_sha256": sha256_of_file(script_path),
            "manifest_sha256": manifest.manifest_sha256,
            "d4_thresholds": D4_THRESHOLDS,
            "date_floor": FLOOR,
        },
        "payload": payload,
    }
    out_path = output_dir / filename
    out_path.write_text(json.dumps(full, indent=2, sort_keys=True))
    return out_path


def find_spells(sorted_true_dates: list[str], all_dates_in_order: list[str]) -> list[tuple[str, str]]:
    """Contiguous real-session runs of `sorted_true_dates` within the
    real trading calendar `all_dates_in_order` -- used for spell
    new/dropped/split/merged comparisons between baseline and a
    perturbation scenario."""
    if not sorted_true_dates:
        return []
    date_index = {d: i for i, d in enumerate(all_dates_in_order)}
    runs = []
    run_start = sorted_true_dates[0]
    prev_idx = date_index[sorted_true_dates[0]]
    for d in sorted_true_dates[1:]:
        idx = date_index[d]
        if idx != prev_idx + 1:
            runs.append((run_start, all_dates_in_order[prev_idx]))
            run_start = d
        prev_idx = idx
    runs.append((run_start, all_dates_in_order[prev_idx]))
    return runs
