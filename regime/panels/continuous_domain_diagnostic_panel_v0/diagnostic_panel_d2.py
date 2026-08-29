"""continuous_domain_diagnostic_panel_v0 -- Part A (D2 absolute/relative
branch contingency table), per Message[247]/[248]'s agreed protocol.

Pure descriptive diagnostic. Full real timeline 2018-06-22 (VIX9D's real
coverage floor) to present. NO thresholds generated, NO overall pass/fail
labels, NOT touching crisis.py/engine.py.

Question: on each real trading day, does D2's level_stress fire via the
absolute leg (current_level>=6.00pp), the relative leg (level_pct504>=90),
both, or neither? Contingency table + rate of relative-only firing, plus
the OAS absolute-level distribution conditional on each cell.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path("regime/src")))

from v5_1.contracts import load_manifest
from v5_1.engine import (
    load_raw_series_bundle,
    _D2_OAS_LEVEL_PP_THRESHOLD, _D2_OAS_LEVEL_PCT504_THRESHOLD,
)
from v5_1.normalization import causal_midrank, InsufficientHistoryError, REQUIRED_WINDOW_SIZE

manifest = load_manifest()
raw_bundle = load_raw_series_bundle(manifest)
oas = raw_bundle.oas

# real trading calendar from the benchmark series, floored at VIX9D's real coverage start
FLOOR = "2018-06-22"
dates = [o.date for o in raw_bundle.benchmark.observations if o.date >= FLOOR]

cells = {"abs_only": [], "rel_only": [], "both": [], "neither": []}
skipped_no_data = 0

for d in dates:
    level = oas.value_on(d)
    if level is None:
        skipped_no_data += 1
        continue
    window = oas.window_ending(d, REQUIRED_WINDOW_SIZE)
    if window is None:
        skipped_no_data += 1
        continue
    try:
        pct504 = causal_midrank([o.value for o in window], level)
    except InsufficientHistoryError:
        skipped_no_data += 1
        continue

    abs_leg = level >= _D2_OAS_LEVEL_PP_THRESHOLD
    rel_leg = pct504 >= _D2_OAS_LEVEL_PCT504_THRESHOLD

    if abs_leg and rel_leg:
        cells["both"].append((d, level, pct504))
    elif abs_leg:
        cells["abs_only"].append((d, level, pct504))
    elif rel_leg:
        cells["rel_only"].append((d, level, pct504))
    else:
        cells["neither"].append((d, level, pct504))

total_valid = sum(len(v) for v in cells.values())
print(f"Real trading days from {FLOOR}: {len(dates)}; valid (both level and pct504 available): {total_valid}; "
      f"skipped (insufficient history / missing OAS): {skipped_no_data}\n")

print(f"D2 level_stress absolute leg: current_level >= {_D2_OAS_LEVEL_PP_THRESHOLD}pp")
print(f"D2 level_stress relative leg: level_pct504 >= {_D2_OAS_LEVEL_PCT504_THRESHOLD}\n")

print("Contingency table (level_stress = abs OR rel):")
for cell, rows in cells.items():
    pct_of_total = 100 * len(rows) / total_valid if total_valid else 0.0
    print(f"  {cell:12s}: {len(rows):5d} days ({pct_of_total:5.2f}%)")

print()
if cells["rel_only"]:
    levels = [r[1] for r in cells["rel_only"]]
    pcts = [r[2] for r in cells["rel_only"]]
    print(f"rel_only cell OAS level range: [{min(levels):.2f}, {max(levels):.2f}]pp "
          f"(all comfortably below the {_D2_OAS_LEVEL_PP_THRESHOLD}pp absolute threshold by construction)")
    print(f"rel_only cell pct504 range: [{min(pcts):.1f}, {max(pcts):.1f}]")
    # show the real dates, not just counts -- which real periods trigger the relative-only branch?
    print(f"rel_only dates (first 5): {[r[0] for r in cells['rel_only'][:5]]}")
    print(f"rel_only dates (last 5): {[r[0] for r in cells['rel_only'][-5:]]}")

    # cluster into contiguous real-date runs to see if rel_only is one sustained regime or scattered
    rel_only_dates = sorted(r[0] for r in cells["rel_only"])
    date_index = {d: i for i, d in enumerate(dates)}
    runs = []
    run_start = rel_only_dates[0]
    prev_idx = date_index[rel_only_dates[0]]
    for d in rel_only_dates[1:]:
        idx = date_index[d]
        if idx != prev_idx + 1:
            runs.append((run_start, dates[prev_idx]))
            run_start = d
        prev_idx = idx
    runs.append((run_start, dates[prev_idx]))
    print(f"rel_only contiguous real-session runs: {len(runs)}")
    for start, end in runs[:15]:
        print(f"    {start} .. {end}")
    if len(runs) > 15:
        print(f"    ... and {len(runs)-15} more runs")

if cells["neither"]:
    levels = [r[1] for r in cells["neither"]]
    print(f"\nneither cell OAS level range (real calm-period baseline): [{min(levels):.2f}, {max(levels):.2f}]pp")
