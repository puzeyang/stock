"""continuous_domain_diagnostic_panel_v0 -- Panel B Test B (fixed-
denominator member influence), per Message[253]'s exact specification.

Keeps the real 9-member universe and its real denominator FIXED at
every date. For each (date, sector) scenario, only counterfactually
flips that ONE member's real above/below-SMA50 or above/below-SMA200
state (computed from the real raw series, never edited) -- does not
touch eligible_count/total_count, does not re-run any SMA computation
on a modified series, does not pretend a different real price history
existed.

Speed leg is reported in three SEPARATE scenario classes per
Message[253]'s explicit requirement:
  - t-only: flip the member's SMA50 state at the CURRENT date only,
    recompute drop_50_5d using the flipped t and the REAL t-5.
  - t-5-only: flip the member's SMA50 state at the t-5 date only,
    recompute drop_50_5d using the REAL t and the flipped t-5.
  - paired-path: flip the SAME member's state at BOTH t and t-5
    consistently (both above or both below, whichever this scenario
    tests), used only to bound how a single member's persistent state
    could move drop_50_5d.
These are never averaged into one score.

No thresholds changed. crisis.py/engine.py NOT modified.
"""
import sys
sys.path.insert(0, str(__import__("pathlib").Path("regime/src")))

from collections import defaultdict
from v5_1.contracts import load_manifest
from v5_1.engine import (
    load_raw_series_bundle,
    _D4_SHORT_COLLAPSE_THRESHOLD, _D4_LONG_COLLAPSE_THRESHOLD,
    _D4_EXTREME_SHORT, _D4_EXTREME_LONG, _D4_SPEED_DROP_PP_THRESHOLD,
    _D4_SPEED_LOOKBACK_SESSIONS, _D4_MIN_COVERAGE,
    _breadth_dates_ending,
)
from v5_1.breadth import compute_participation, BreadthUnavailableError, _sma

manifest = load_manifest()
raw_bundle = load_raw_series_bundle(manifest)
breadth = raw_bundle.breadth
FLOOR = "2018-06-22"
dates = [o.date for o in raw_bundle.benchmark.observations if o.date >= FLOOR]
member_paths = list(breadth.members.keys())
N = len(member_paths)


def real_member_states(as_of):
    """Real per-member above/below-SMA50 and above/below-SMA200 state on
    a date, plus overall counts -- direct read, no perturbation."""
    above50 = {}
    above200 = {}
    for path, series in breadth.members.items():
        current = series.value_on(as_of)
        if current is None:
            continue
        w50 = series.window_ending(as_of, 50)
        if w50 is not None:
            above50[path] = current > _sma([o.value for o in w50])
        w200 = series.window_ending(as_of, 200)
        if w200 is not None:
            above200[path] = current > _sma([o.value for o in w200])
    return above50, above200


def flags_from_counts(above50_count, eligible50, above200_count, eligible200, drop_50_5d):
    if eligible50 == 0 or eligible200 == 0:
        return None
    pct50 = above50_count / eligible50
    pct200 = above200_count / eligible200
    short_collapse = pct50 <= _D4_SHORT_COLLAPSE_THRESHOLD
    long_collapse = pct200 <= _D4_LONG_COLLAPSE_THRESHOLD
    speed_collapse = drop_50_5d is not None and drop_50_5d >= _D4_SPEED_DROP_PP_THRESHOLD
    extreme = pct50 <= _D4_EXTREME_SHORT and pct200 <= _D4_EXTREME_LONG
    active = extreme or sum([short_collapse, long_collapse, speed_collapse]) >= 2
    return {"pct50": pct50, "pct200": pct200, "short_collapse": short_collapse,
            "long_collapse": long_collapse, "speed_collapse": speed_collapse,
            "extreme": extreme, "active": active}


FLAGS = ["short_collapse", "long_collapse", "speed_collapse", "extreme", "active"]


def new_matrix():
    return {flag: defaultdict(int) for flag in FLAGS}


# --- Baseline (real, unperturbed) per-date flags, reusing real compute_participation + speed ---
print("Computing real baseline per date (t and t-5 states)...")
baseline_full = {}
for d in dates:
    try:
        pct50, pct200, eligible50, total50 = compute_participation(breadth, d, 50, 200)
    except BreadthUnavailableError:
        continue
    if total50 == 0 or eligible50 / total50 < _D4_MIN_COVERAGE:
        continue
    above50, above200 = real_member_states(d)
    eligible200 = len(above200)
    above50_count = sum(above50.values())
    above200_count = sum(above200.values())

    drop_50_5d = None
    past_date = None
    past_above50 = None
    try:
        past_dates = _breadth_dates_ending(breadth, d, _D4_SPEED_LOOKBACK_SESSIONS + 1)
        if past_dates is not None:
            past_date = past_dates[0]
            pct50_past, _pct200_past, eligible_past, total_past = compute_participation(breadth, past_date, 50, 200)
            if total_past > 0 and eligible_past / total_past >= _D4_MIN_COVERAGE:
                drop_50_5d = pct50_past - pct50
                past_above50, _ = real_member_states(past_date)
    except BreadthUnavailableError:
        pass

    baseline_full[d] = {
        "above50": above50, "above200": above200,
        "above50_count": above50_count, "eligible50": eligible50,
        "above200_count": above200_count, "eligible200": eligible200,
        "drop_50_5d": drop_50_5d, "past_date": past_date, "past_above50": past_above50,
        "flags": flags_from_counts(above50_count, eligible50, above200_count, eligible200, drop_50_5d),
    }
print(f"Baseline valid dates: {len(baseline_full)}\n")

# ============================================================
# TEST B: fixed-denominator, single-member state flip
# ============================================================
print("=== TEST B: fixed-denominator member influence ===")

# --- B-short/B-long: flip one member's SMA50 or SMA200 state at date t only ---
for target_leg, above_key, count_key, eligible_key in [
    ("short_collapse_leg", "above50", "above50_count", "eligible50"),
    ("long_collapse_leg", "above200", "above200_count", "eligible200"),
]:
    print(f"\n--- Test B, {target_leg} (flip one member's above/below state at t) ---")
    matrix_by_sector = {p: new_matrix() for p in member_paths}
    for d, base in baseline_full.items():
        if base["flags"] is None:
            continue
        above_map = base[above_key]
        for p in member_paths:
            if p not in above_map:
                continue  # not eligible this date -- cannot flip a state that doesn't exist
            flipped_state = not above_map[p]
            new_count = base[count_key] + (1 if flipped_state else -1)
            if target_leg == "short_collapse_leg":
                new_flags = flags_from_counts(new_count, base["eligible50"], base["above200_count"], base["eligible200"], base["drop_50_5d"])
            else:
                new_flags = flags_from_counts(base["above50_count"], base["eligible50"], new_count, base["eligible200"], base["drop_50_5d"])
            if new_flags is None:
                continue
            for flag in FLAGS:
                b, n = int(base["flags"][flag]), int(new_flags[flag])
                matrix_by_sector[p][flag][(b, n)] += 1
    for p in member_paths:
        m = matrix_by_sector[p]
        flips = {flag: m[flag][(0,1)] + m[flag][(1,0)] for flag in FLAGS}
        total_flips = sum(flips.values())
        if total_flips:
            print(f"  {p.split('/')[-1]:10s}: " + " ".join(f"{f}={flips[f]}" for f in FLAGS if flips[f]))

print("\nTest B t-only/t-5-only/paired-path speed leg: see follow-up section (separate scenario classes).")
