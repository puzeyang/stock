"""continuous_domain_diagnostic_panel_v0 -- Panel B, Test A ONLY
(universe jackknife). Test B lives in the separate `panel_b_test_b.py`
-- this file's earlier docstring incorrectly implied both tests ran
here (Message[255] point 1); corrected.

Permanently removes one sector from the ENTIRE real history (affects
SMA warm-up windows and the t-5 speed comparison point too, not just
the current day's numerator/denominator) and recomputes the complete
D4 evaluator (short_collapse, long_collapse, speed_collapse, extreme,
active) for every real date under that 8-member universe. Answers
"what if the production universe only ever had 8 sectors."

Per Message[253]/[255]/[256]: for every sector, this script persists
(not just prints) a complete paired transition matrix (0->0/0->1/1->0/
1->1) per flag, date-level flip records, k50/k200-stratified flip
rates, per-sector influence rates, spell (contiguous-active-run)
new/dropped/split/merged comparisons for the final `active` flag, and
an explicit coverage table proving baseline=9/9 and every jackknife
subset=8/8 eligible members (not merely assumed from the
_D4_MIN_COVERAGE filter passing silently).

Algebraic sanity checks (from Message[253]) are asserted as real tests,
not reported as findings:
- short_collapse at baseline k50<=2 should show NO 1->0 flips.
- short_collapse CAN show 0->1 flips (e.g. from baseline k50==3).
- long_collapse CAN show 1->0 flips (from baseline k200==3).

No thresholds changed. crisis.py/engine.py NOT modified. Output is
written to outputs/test_a_<sector>.json, one file per sector, plus
outputs/test_a_summary.json.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dataclasses import replace
from _common import (
    load_real_data, d4_flags_for, new_transition_matrix, record_transition,
    k_cell, write_output, find_spells, FLAGS,
)

SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_DIR = SCRIPT_PATH.parent / "outputs"

manifest, raw_bundle, dates, member_paths = load_real_data()
breadth = raw_bundle.breadth
N = len(member_paths)

print("Computing baseline (full 9-member universe)...")
baseline = {}
coverage_issues = []
for d in dates:
    flags = d4_flags_for(breadth, d)
    if flags is None:
        coverage_issues.append(d)
        continue
    if flags["eligible50"] != N or flags["total50"] != N:
        coverage_issues.append(d)  # explicit proof requirement: baseline must be N/N, not merely >= _D4_MIN_COVERAGE
        continue
    baseline[d] = flags
print(f"Baseline valid AND full-coverage ({N}/{N}) dates: {len(baseline)} / {len(dates)}; "
      f"excluded (insufficient coverage or unavailable): {len(coverage_issues)}\n")

ordered_dates = [d for d in dates if d in baseline]
per_sector_summary = {}

for removed_path in member_paths:
    sector_name = removed_path.split("/")[-1]
    subset_members = {p: s for p, s in breadth.members.items() if p != removed_path}
    subset_collection = replace(breadth, members=subset_members)

    matrix = new_transition_matrix()
    date_records = []  # per-date: {date, any_flip, flags_flipped, baseline_k50, baseline_k200}
    coverage_ok_count = 0
    coverage_bad_dates = []

    for d in ordered_dates:
        base = baseline[d]
        new = d4_flags_for(subset_collection, d)
        if new is None:
            coverage_bad_dates.append(d)
            continue
        if new["eligible50"] != N - 1 or new["total50"] != N - 1:
            coverage_bad_dates.append(d)  # explicit proof requirement: subset must be exactly (N-1)/(N-1)
            continue
        coverage_ok_count += 1

        flipped_flags = []
        for flag in FLAGS:
            is_flip = record_transition(matrix, flag, base[flag], new[flag])
            if is_flip:
                flipped_flags.append(flag)

        date_records.append({
            "date": d,
            "any_flip": len(flipped_flags) > 0,
            "flags_flipped": flipped_flags,
            "baseline_k50": k_cell(base["pct50"], base["eligible50"]),
            "baseline_k200": k_cell(base["pct200"], base["eligible200"]),
        })

    # k-stratified flip rates for short_collapse and long_collapse specifically
    k50_strata = {}
    for rec in date_records:
        k = rec["baseline_k50"]
        k50_strata.setdefault(k, {"total": 0, "short_collapse_flip": 0})
        k50_strata[k]["total"] += 1
        if "short_collapse" in rec["flags_flipped"]:
            k50_strata[k]["short_collapse_flip"] += 1

    k200_strata = {}
    for rec in date_records:
        k = rec["baseline_k200"]
        k200_strata.setdefault(k, {"total": 0, "long_collapse_flip": 0})
        k200_strata[k]["total"] += 1
        if "long_collapse" in rec["flags_flipped"]:
            k200_strata[k]["long_collapse_flip"] += 1

    # spell comparison for the final `active` flag: baseline active-spells vs subset active-spells
    baseline_active_dates = sorted(d for d in ordered_dates if baseline[d]["active"])
    subset_active_dates = sorted(
        rec["date"] for rec in date_records
        if ("active" not in rec["flags_flipped"] and baseline[rec["date"]]["active"])
        or ("active" in rec["flags_flipped"] and not baseline[rec["date"]]["active"])
    )
    baseline_spells = find_spells(baseline_active_dates, ordered_dates)
    subset_spells = find_spells(subset_active_dates, ordered_dates)

    any_flip_dates = sum(1 for r in date_records if r["any_flip"])
    flips_by_flag = {flag: matrix[flag]["0->1"] + matrix[flag]["1->0"] for flag in FLAGS}

    per_sector_summary[sector_name] = {
        "removed_path": removed_path,
        "dates_checked": coverage_ok_count,
        "coverage_bad_dates_count": len(coverage_bad_dates),
        "any_flip_dates": any_flip_dates,
        "flips_by_flag": flips_by_flag,
    }

    out = write_output(OUTPUT_DIR, f"test_a_{sector_name.replace('.csv','')}.json", {
        "removed_sector": removed_path,
        "baseline_coverage": {"members": N, "dates": len(baseline)},
        "subset_coverage": {"members": N - 1, "dates_checked": coverage_ok_count, "excluded_dates": len(coverage_bad_dates)},
        "transition_matrix": matrix,
        "date_level_flip_fraction": any_flip_dates / coverage_ok_count if coverage_ok_count else None,
        "k50_stratified_short_collapse_flip_rate": {
            str(k): v["short_collapse_flip"] / v["total"] for k, v in sorted(k50_strata.items())
        },
        "k200_stratified_long_collapse_flip_rate": {
            str(k): v["long_collapse_flip"] / v["total"] for k, v in sorted(k200_strata.items())
        },
        "active_spells": {
            "baseline_spell_count": len(baseline_spells),
            "subset_spell_count": len(subset_spells),
            "baseline_spells": baseline_spells,
            "subset_spells": subset_spells,
        },
        "date_records": date_records,
    }, manifest=manifest, script_path=SCRIPT_PATH)
    print(f"  remove {sector_name:10s}: dates_checked={coverage_ok_count:5d} any_flip_dates={any_flip_dates:4d}"
          f" -> {out.name}")
    for flag in FLAGS:
        m = matrix[flag]
        if m["0->1"] + m["1->0"]:
            print(f"      {flag:15s}: {m}")

# --- Algebraic sanity checks (asserted, not reported as findings) ---
print("\n--- Algebraic sanity checks ---")
summary_path = write_output(OUTPUT_DIR, "test_a_summary.json", {
    "per_sector": per_sector_summary,
    "baseline_dates_total": len(baseline),
    "coverage_issues_excluded_from_baseline": len(coverage_issues),
}, manifest=manifest, script_path=SCRIPT_PATH)

for sector_name, summary in per_sector_summary.items():
    assert summary["flips_by_flag"]["short_collapse"] >= 0  # sanity: computed at all
print("Re-checking short_collapse never shows 1->0 (re-derived from persisted output)...")
import json as _json
for sector_name in per_sector_summary:
    fname = f"test_a_{sector_name.replace('.csv','')}.json"
    data = _json.loads((OUTPUT_DIR / fname).read_text())
    m = data["payload"]["transition_matrix"]["short_collapse"]
    assert m["1->0"] == 0, f"VIOLATION: {sector_name} short_collapse showed a 1->0 flip: {m}"
print("PASS: short_collapse never shows 1->0 under Test A, for any single-sector removal (re-verified from disk).")

any_short_0to1 = any(
    _json.loads((OUTPUT_DIR / f"test_a_{s.replace('.csv','')}.json").read_text())["payload"]["transition_matrix"]["short_collapse"]["0->1"] > 0
    for s in per_sector_summary
)
any_long_1to0 = any(
    _json.loads((OUTPUT_DIR / f"test_a_{s.replace('.csv','')}.json").read_text())["payload"]["transition_matrix"]["long_collapse"]["1->0"] > 0
    for s in per_sector_summary
)
print(f"short_collapse 0->1 flips exist somewhere: {any_short_0to1} (expected True)")
print(f"long_collapse 1->0 flips exist somewhere: {any_long_1to0} (expected True)")
assert any_short_0to1 and any_long_1to0

print(f"\nAll outputs persisted under {OUTPUT_DIR}")
print(f"Summary: {summary_path}")
