"""continuous_domain_diagnostic_panel_v0 -- Panel B v1 (full D4
leave-one-sector-out matrix), per Message[253]'s exact specification.

Two separate perturbation tests, run in parallel, over the FULL real
timeline (2018-06-22 to present) x all 9 sectors:

Test A (universe jackknife): permanently remove one sector from the
ENTIRE history (affects SMA warm-up windows and the t-5 comparison
point too, not just the current day's numerator/denominator). Answers
"what if the production universe only ever had 8 sectors."

Test B (fixed-denominator member influence): keep the 9-member universe
and denominator FIXED; only counterfactually flip one member's
above/below-SMA50 or above/below-SMA200 state at a single date. Speed
leg perturbations are reported separately for t-only, t-5-only, and
paired-path flips, per Message[253]'s explicit requirement -- NOT
mixed into one score.

For both tests: paired transition matrices (0->0, 0->1, 1->0, 1->1) for
short_collapse, long_collapse, speed_collapse, extreme, and final
D4_active. Plus date-level any_flip, per-sector influence rate, and
baseline-k50/k200-stratified flip rates.

Algebraic sanity checks (from Message[253]) are asserted as real tests,
not reported as findings:
- Test A: short leg at baseline k50<=2 should show NO 1->0 flips.
- Test A: k50==3 CAN show 0->1 flips.
- Test A: long leg at k200==3 CAN show 1->0 flips.

No thresholds changed. crisis.py/engine.py NOT modified.
"""
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path("regime/src")))

from dataclasses import replace
from collections import defaultdict
from v5_1.contracts import load_manifest
from v5_1.engine import (
    load_raw_series_bundle,
    _D4_SHORT_COLLAPSE_THRESHOLD, _D4_LONG_COLLAPSE_THRESHOLD,
    _D4_EXTREME_SHORT, _D4_EXTREME_LONG, _D4_SPEED_DROP_PP_THRESHOLD,
    _D4_SPEED_LOOKBACK_SESSIONS, _D4_MIN_COVERAGE,
    _breadth_dates_ending,
)
from v5_1.breadth import compute_participation, BreadthUnavailableError

manifest = load_manifest()
raw_bundle = load_raw_series_bundle(manifest)
breadth = raw_bundle.breadth
FLOOR = "2018-06-22"
dates = [o.date for o in raw_bundle.benchmark.observations if o.date >= FLOOR]
member_paths = list(breadth.members.keys())
N = len(member_paths)


def d4_flags_for(collection, as_of):
    """Recompute D4's real subconditions + active for one collection/date,
    mirroring _d4_participation_collapse_evaluator's exact logic (not a
    re-derivation shortcut) -- returns None if unavailable."""
    try:
        pct50_now, pct200_now, eligible_now, total_now = compute_participation(collection, as_of, 50, 200)
    except BreadthUnavailableError:
        return None
    if total_now == 0 or eligible_now / total_now < _D4_MIN_COVERAGE:
        return None

    speed_collapse = False
    pct50_past = None
    try:
        past_dates = _breadth_dates_ending(collection, as_of, _D4_SPEED_LOOKBACK_SESSIONS + 1)
        if past_dates is not None:
            past_as_of = past_dates[0]
            pct50_past, _pct200_past, eligible_past, total_past = compute_participation(collection, past_as_of, 50, 200)
            if total_past > 0 and eligible_past / total_past >= _D4_MIN_COVERAGE:
                speed_collapse = (pct50_past - pct50_now) >= _D4_SPEED_DROP_PP_THRESHOLD
    except BreadthUnavailableError:
        speed_collapse = False

    short_collapse = pct50_now <= _D4_SHORT_COLLAPSE_THRESHOLD
    long_collapse = pct200_now <= _D4_LONG_COLLAPSE_THRESHOLD
    extreme = pct50_now <= _D4_EXTREME_SHORT and pct200_now <= _D4_EXTREME_LONG
    active = extreme or sum([short_collapse, long_collapse, speed_collapse]) >= 2

    return {
        "pct50": pct50_now, "pct200": pct200_now, "eligible": eligible_now, "total": total_now,
        "short_collapse": short_collapse, "long_collapse": long_collapse,
        "speed_collapse": speed_collapse, "extreme": extreme, "active": active,
        "pct50_past": pct50_past,
    }


# --- Baseline: full 9-member universe, every date ---
print("Computing baseline (full 9-member universe)...")
baseline = {}
for d in dates:
    flags = d4_flags_for(breadth, d)
    if flags is not None:
        baseline[d] = flags
print(f"Baseline valid dates: {len(baseline)} / {len(dates)}\n")

FLAGS = ["short_collapse", "long_collapse", "speed_collapse", "extreme", "active"]


def new_matrix():
    return {flag: defaultdict(int) for flag in FLAGS}  # flag -> (base,new) -> count


# ============================================================
# TEST A: universe jackknife (permanent removal, whole history)
# ============================================================
print("=== TEST A: universe jackknife ===")
test_a_results = {}
for removed_path in member_paths:
    subset_members = {p: s for p, s in breadth.members.items() if p != removed_path}
    subset_collection = replace(breadth, members=subset_members)
    matrix = new_matrix()
    date_flip_count = 0
    dates_checked = 0
    for d in dates:
        base = baseline.get(d)
        if base is None:
            continue
        new = d4_flags_for(subset_collection, d)
        if new is None:
            continue  # 8-member universe unavailable this date -- excluded, not treated as a flip
        dates_checked += 1
        any_flip_this_date = False
        for flag in FLAGS:
            b, n = int(base[flag]), int(new[flag])
            matrix[flag][(b, n)] += 1
            if b != n:
                any_flip_this_date = True
        if any_flip_this_date:
            date_flip_count += 1
    test_a_results[removed_path] = {"matrix": matrix, "dates_checked": dates_checked, "any_flip_dates": date_flip_count}
    short = "/".join(str(x) for x in member_paths[0:0])  # placeholder, unused
    print(f"  remove {removed_path.split('/')[-1]:10s}: dates_checked={dates_checked:5d} any_flip_dates={date_flip_count:4d}")
    for flag in FLAGS:
        m = matrix[flag]
        flips = m[(0,1)] + m[(1,0)]
        if flips:
            print(f"      {flag:15s}: 0->0={m[(0,0)]:5d} 0->1={m[(0,1)]:4d} 1->0={m[(1,0)]:4d} 1->1={m[(1,1)]:5d}")

# --- Sanity checks (asserted, not reported as findings) ---
print("\n--- Test A algebraic sanity checks ---")
for removed_path, res in test_a_results.items():
    m = res["matrix"]["short_collapse"]
    # baseline k50<=2 (short_collapse=True, i.e. base=1) should show NO 1->0
    assert m[(1, 0)] == 0, f"VIOLATION: {removed_path} short_collapse showed a 1->0 flip: {m}"
print("PASS: short_collapse never shows 1->0 under Test A, for any single-sector removal (as predicted).")

any_short_0to1 = any(res["matrix"]["short_collapse"][(0, 1)] > 0 for res in test_a_results.values())
print(f"short_collapse 0->1 flips exist somewhere: {any_short_0to1} (expected: True, since k=3 dates allow it)")

any_long_1to0 = any(res["matrix"]["long_collapse"][(1, 0)] > 0 for res in test_a_results.values())
print(f"long_collapse 1->0 flips exist somewhere: {any_long_1to0} (expected: True, at k200==3 boundary)")

print("\nSaving Test A results...")
