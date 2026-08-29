"""continuous_domain_diagnostic_panel_v0 -- Panel B, Test B (fixed-
denominator member influence), per Message[253]'s exact specification,
corrected per Message[255]/[256]'s finding that the prior version
computed `active` using the REAL unperturbed 5-day speed value while
the current-day count was counterfactually flipped -- an internally
inconsistent result. Fixed here by NEVER mixing a perturbed count with
an unperturbed drop_50_5d: every scenario either holds speed fixed
at its real value AND doesn't report speed-dependent flags as
perturbation-driven, or perturbs speed explicitly via one of the three
scenario classes below.

Keeps the real 9-member universe and its real denominator FIXED at
every date. Runs FOUR separate, non-overlapping scenario classes, never
combined into one score:

1. level_state_flip: for each (date, sector), flip that ONE member's
   real above/below-SMA50 state (or, in a second pass, above/below-
   SMA200 state) at date t, keeping the real drop_50_5d UNCHANGED, and
   report short_collapse/long_collapse/extreme transitions only.
   `speed_collapse`/`active` are NOT reported for this scenario class
   (excluding, not silently mixing, the inconsistency Message[255]
   found) -- see class 2-4 below for speed-aware scenarios.
2. speed_t_only: flip the member's SMA50 state at date t only,
   recompute drop_50_5d = pct50(t-5, real) - pct50(t, flipped).
3. speed_t5_only: flip the member's SMA50 state at date t-5 only,
   recompute drop_50_5d = pct50(t-5, flipped) - pct50(t, real).
4. speed_paired_path: flip the SAME member's SMA50 state consistently
   at BOTH t and t-5 (same direction), recompute drop_50_5d from both
   flipped endpoints.

For classes 2-4, `active` (which depends on speed_collapse) is
reported and IS trustworthy, because both endpoints feeding
drop_50_5d are handled explicitly and consistently within each class.

No thresholds changed. crisis.py/engine.py NOT modified. Output is
written to outputs/test_b_<scenario_class>.json.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import (
    load_real_data, new_transition_matrix, record_transition, write_output,
    k_cell, D4_THRESHOLDS,
)
from v5_1.breadth import compute_participation, BreadthUnavailableError, _sma
from v5_1.engine import _D4_MIN_COVERAGE, _breadth_dates_ending, _D4_SPEED_LOOKBACK_SESSIONS, _D4_SPEED_DROP_PP_THRESHOLD

SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_DIR = SCRIPT_PATH.parent / "outputs"

manifest, raw_bundle, dates, member_paths = load_real_data()
breadth = raw_bundle.breadth
N = len(member_paths)


def real_member_states(as_of):
    """Real per-member above/below-SMA50 and above/below-SMA200 state on
    a date -- direct read from real series, no perturbation."""
    above50, above200 = {}, {}
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


def flags_level_only(above50_count, eligible50, above200_count, eligible200):
    """short_collapse/long_collapse/extreme only -- NO speed_collapse, NO
    active. Used for scenario class 1, where speed is deliberately held
    fixed and therefore active cannot be honestly reported."""
    if eligible50 == 0 or eligible200 == 0:
        return None
    pct50 = above50_count / eligible50
    pct200 = above200_count / eligible200
    return {
        "pct50": pct50, "pct200": pct200,
        "short_collapse": pct50 <= D4_THRESHOLDS["short_collapse_threshold"],
        "long_collapse": pct200 <= D4_THRESHOLDS["long_collapse_threshold"],
        "extreme": pct50 <= D4_THRESHOLDS["extreme_short_threshold"] and pct200 <= D4_THRESHOLDS["extreme_long_threshold"],
    }


def flags_with_speed(pct50, pct200, drop_50_5d):
    """Full flag set including speed_collapse/active -- only ever called
    with an explicitly, consistently derived drop_50_5d (classes 2-4)."""
    short_collapse = pct50 <= D4_THRESHOLDS["short_collapse_threshold"]
    long_collapse = pct200 <= D4_THRESHOLDS["long_collapse_threshold"]
    speed_collapse = drop_50_5d is not None and drop_50_5d >= D4_THRESHOLDS["speed_drop_pp_threshold"]
    extreme = pct50 <= D4_THRESHOLDS["extreme_short_threshold"] and pct200 <= D4_THRESHOLDS["extreme_long_threshold"]
    active = extreme or sum([short_collapse, long_collapse, speed_collapse]) >= 2
    return {"pct50": pct50, "pct200": pct200, "short_collapse": short_collapse,
            "long_collapse": long_collapse, "speed_collapse": speed_collapse,
            "extreme": extreme, "active": active}


print("Computing real baseline per date (t and t-5 states)...")
baseline = {}
for d in dates:
    try:
        pct50, pct200, eligible, total = compute_participation(breadth, d, 50, 200)
    except BreadthUnavailableError:
        continue
    if total == 0 or eligible / total < _D4_MIN_COVERAGE:
        continue
    if eligible != N or total != N:
        continue  # explicit full-coverage requirement, same as Test A

    above50, above200 = real_member_states(d)

    drop_50_5d = None
    past_date = None
    past_above50 = None
    past_pct50 = None
    try:
        past_dates = _breadth_dates_ending(breadth, d, _D4_SPEED_LOOKBACK_SESSIONS + 1)
        if past_dates is not None:
            past_date = past_dates[0]
            pct50_past, _pct200_past, eligible_past, total_past = compute_participation(breadth, past_date, 50, 200)
            if total_past > 0 and eligible_past / total_past >= _D4_MIN_COVERAGE:
                drop_50_5d = pct50_past - pct50
                past_pct50 = pct50_past
                past_above50, _ = real_member_states(past_date)
    except BreadthUnavailableError:
        pass

    baseline[d] = {
        "pct50": pct50, "pct200": pct200, "above50": above50, "above200": above200,
        "drop_50_5d": drop_50_5d, "past_date": past_date, "past_above50": past_above50, "past_pct50": past_pct50,
        "flags_level": flags_level_only(sum(above50.values()), len(above50), sum(above200.values()), len(above200)),
        "flags_full": flags_with_speed(pct50, pct200, drop_50_5d),
    }
print(f"Baseline valid, full-coverage ({N}/{N}) dates: {len(baseline)} / {len(dates)}\n")

LEVEL_FLAGS = ("short_collapse", "long_collapse", "extreme")
FULL_FLAGS = ("short_collapse", "long_collapse", "speed_collapse", "extreme", "active")

# ============================================================
# Scenario class 1: level_state_flip (speed held fixed, NOT reported for active)
# ============================================================
print("=== Test B, class 1: level_state_flip (short/long/extreme ONLY, speed excluded) ===")
for leg_name, above_key in [("sma50", "above50"), ("sma200", "above200")]:
    matrix_by_sector = {p: {f: {"0->0": 0, "0->1": 0, "1->0": 0, "1->1": 0} for f in LEVEL_FLAGS} for p in member_paths}
    scenario_count = 0
    for d, base in baseline.items():
        if base["flags_level"] is None:
            continue
        above_map = base[above_key]
        above50_count = sum(base["above50"].values())
        above200_count = sum(base["above200"].values())
        for p in member_paths:
            if p not in above_map:
                continue
            flipped_state = not above_map[p]
            if leg_name == "sma50":
                new_a50 = above50_count + (1 if flipped_state else -1)
                new_flags = flags_level_only(new_a50, len(base["above50"]), above200_count, len(base["above200"]))
            else:
                new_a200 = above200_count + (1 if flipped_state else -1)
                new_flags = flags_level_only(above50_count, len(base["above50"]), new_a200, len(base["above200"]))
            if new_flags is None:
                continue
            scenario_count += 1
            for flag in LEVEL_FLAGS:
                record_transition(matrix_by_sector[p], flag, base["flags_level"][flag], new_flags[flag])

    for p in member_paths:
        sector_name = p.split("/")[-1]
        out = write_output(OUTPUT_DIR, f"test_b_class1_{leg_name}_{sector_name.replace('.csv','')}.json", {
            "scenario_class": "level_state_flip", "leg": leg_name, "sector": p,
            "note": "speed_collapse/active deliberately excluded -- speed held at real value, not a valid perturbation for this class",
            "transition_matrix": matrix_by_sector[p],
        }, manifest=manifest, script_path=SCRIPT_PATH)
    print(f"  leg={leg_name}: {scenario_count} scenarios, per-sector outputs written")

# ============================================================
# Scenario classes 2-4: speed-aware, active IS reported
# ============================================================
print("\n=== Test B, classes 2-4: speed-aware scenarios (active reported) ===")
class_results = {"speed_t_only": {p: new_transition_matrix() for p in member_paths},
                  "speed_t5_only": {p: new_transition_matrix() for p in member_paths},
                  "speed_paired_path": {p: new_transition_matrix() for p in member_paths}}
class_counts = {"speed_t_only": 0, "speed_t5_only": 0, "speed_paired_path": 0}

for d, base in baseline.items():
    if base["drop_50_5d"] is None or base["past_above50"] is None:
        continue  # speed unavailable this date -- cannot run speed-aware scenarios
    above50_now = base["above50"]
    above50_past = base["past_above50"]
    above50_count_now = sum(above50_now.values())
    above50_count_past = sum(above50_past.values())
    eligible_now = len(above50_now)
    eligible_past = len(above50_past)
    pct200_now = base["pct200"]

    for p in member_paths:
        if p not in above50_now or p not in above50_past:
            continue

        # class 2: flip t only
        flipped_now = not above50_now[p]
        new_count_now = above50_count_now + (1 if flipped_now else -1)
        new_pct50_now = new_count_now / eligible_now
        new_drop = base["past_pct50"] - new_pct50_now
        new_flags = flags_with_speed(new_pct50_now, pct200_now, new_drop)
        class_counts["speed_t_only"] += 1
        for flag in FULL_FLAGS:
            record_transition(class_results["speed_t_only"][p], flag, base["flags_full"][flag], new_flags[flag])

        # class 3: flip t-5 only
        flipped_past = not above50_past[p]
        new_count_past = above50_count_past + (1 if flipped_past else -1)
        new_pct50_past = new_count_past / eligible_past
        new_drop2 = new_pct50_past - base["pct50"]
        new_flags2 = flags_with_speed(base["pct50"], pct200_now, new_drop2)
        class_counts["speed_t5_only"] += 1
        for flag in FULL_FLAGS:
            record_transition(class_results["speed_t5_only"][p], flag, base["flags_full"][flag], new_flags2[flag])

        # class 4: flip both t and t-5 consistently (same member, same direction)
        new_drop3 = new_pct50_past - new_pct50_now
        new_flags3 = flags_with_speed(new_pct50_now, pct200_now, new_drop3)
        class_counts["speed_paired_path"] += 1
        for flag in FULL_FLAGS:
            record_transition(class_results["speed_paired_path"][p], flag, base["flags_full"][flag], new_flags3[flag])

for class_name, per_sector in class_results.items():
    for p in member_paths:
        sector_name = p.split("/")[-1]
        write_output(OUTPUT_DIR, f"test_b_{class_name}_{sector_name.replace('.csv','')}.json", {
            "scenario_class": class_name, "sector": p,
            "transition_matrix": per_sector[p],
        }, manifest=manifest, script_path=SCRIPT_PATH)
    active_flips = {p.split("/")[-1]: per_sector[p]["active"]["0->1"] + per_sector[p]["active"]["1->0"] for p in member_paths}
    print(f"  {class_name} ({class_counts[class_name]} scenarios): active flips by sector = {active_flips}")

write_output(OUTPUT_DIR, "test_b_summary.json", {
    "baseline_dates": len(baseline),
    "class_scenario_counts": class_counts,
}, manifest=manifest, script_path=SCRIPT_PATH)

print(f"\nAll outputs persisted under {OUTPUT_DIR}")
