"""continuous_domain_diagnostic_panel_v0 -- Panel C (D1 relative-only vs
absolute-trigger spell duration + subsequent max-drawdown distribution),
per Message[247]'s pre-registered item (C): "D1 relative-only与
absolute-trigger spell的持续时间/后续最大回撤分布".

Pure descriptive diagnostic. Full real timeline 2018-06-22 to present.
NO thresholds generated, NO overall pass/fail labels, NOT touching
crisis.py/engine.py.

Classifies each real trading day's D1 level_stress activation as:
  - absolute_trigger: current VIX >= _D1_VIX_LEVEL_THRESHOLD (the
    absolute leg is true, regardless of the relative leg)
  - relative_only: level_stress is true ONLY via vix_pct504>=90 (the
    absolute leg is false)
  - neither: level_stress false on both legs

Groups each category into contiguous real-session spells, reports
spell count/duration distribution, and for each spell computes the
REAL forward max drawdown over the next 20/60 real trading sessions
following the spell's last day (using the benchmark series' own real
peak-to-trough definition over that forward window, not D3's trailing
252-session estimator, since this asks a different question: "what
happened AFTER this D1 state", not "what is D3's own current reading").

No thresholds changed. crisis.py/engine.py NOT modified. Output
persisted to outputs/panel_c_*.json.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import load_real_data, write_output, find_spells
from v5_1.engine import _D1_VIX_LEVEL_THRESHOLD, _D1_VIX_PCT504_THRESHOLD
from v5_1.normalization import causal_midrank, InsufficientHistoryError, REQUIRED_WINDOW_SIZE

SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_DIR = SCRIPT_PATH.parent / "outputs"
FORWARD_WINDOWS = (20, 60)  # real trading sessions

manifest, raw_bundle, dates, member_paths = load_real_data()
vix = raw_bundle.vix
vix9d = raw_bundle.vix9d
benchmark = raw_bundle.benchmark
benchmark_dates = [o.date for o in benchmark.observations]
benchmark_by_date = {o.date: o.value for o in benchmark.observations}

print("Classifying each real day's D1 level_stress leg...")
classification = {}  # date -> "absolute_trigger" | "relative_only" | "neither"
skipped = 0
for d in dates:
    v = vix.value_on(d)
    v9 = vix9d.value_on(d)
    if v is None or v9 is None or v == 0:
        skipped += 1
        continue
    window = vix.window_ending(d, REQUIRED_WINDOW_SIZE)
    if window is None:
        skipped += 1
        continue
    try:
        vix_pct504 = causal_midrank([o.value for o in window], v)
    except InsufficientHistoryError:
        skipped += 1
        continue

    abs_leg = v >= _D1_VIX_LEVEL_THRESHOLD
    rel_leg = vix_pct504 >= _D1_VIX_PCT504_THRESHOLD

    if abs_leg:
        classification[d] = "absolute_trigger"
    elif rel_leg:
        classification[d] = "relative_only"
    else:
        classification[d] = "neither"

valid_dates = [d for d in dates if d in classification]
print(f"Real trading days from {dates[0]}: {len(dates)}; classified: {len(valid_dates)}; skipped: {skipped}\n")

counts = {"absolute_trigger": 0, "relative_only": 0, "neither": 0}
for c in classification.values():
    counts[c] += 1
print("Classification counts:")
for k, v in counts.items():
    print(f"  {k:20s}: {v:5d} ({100*v/len(valid_dates):5.2f}%)")


def forward_max_drawdown(spell_end_date: str, n_sessions: int) -> float | None:
    """Real max drawdown (peak-to-trough, as a positive fraction) over
    the n_sessions real trading days STRICTLY AFTER spell_end_date,
    using the benchmark's own real closes -- returns None if fewer than
    n_sessions real days remain after spell_end_date in the pinned data."""
    if spell_end_date not in benchmark_by_date:
        return None
    end_idx = benchmark_dates.index(spell_end_date)
    forward = benchmark_dates[end_idx + 1: end_idx + 1 + n_sessions]
    if len(forward) < n_sessions:
        return None
    # peak includes the spell's own last close as the starting reference point
    closes = [benchmark_by_date[spell_end_date]] + [benchmark_by_date[d] for d in forward]
    peak = closes[0]
    max_dd = 0.0
    for c in closes[1:]:
        peak = max(peak, c)
        dd = (peak - c) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd


results = {}
for category in ("absolute_trigger", "relative_only"):
    cat_dates = sorted(d for d in valid_dates if classification[d] == category)
    spells = find_spells(cat_dates, dates)
    spell_records = []
    for start, end in spells:
        start_idx = dates.index(start)
        end_idx = dates.index(end)
        duration = end_idx - start_idx + 1
        record = {"start": start, "end": end, "duration_sessions": duration}
        for n in FORWARD_WINDOWS:
            record[f"forward_max_dd_{n}d"] = forward_max_drawdown(end, n)
        spell_records.append(record)

    durations = [r["duration_sessions"] for r in spell_records]
    results[category] = {
        "spell_count": len(spells),
        "duration_sessions": durations,
        "duration_min": min(durations) if durations else None,
        "duration_max": max(durations) if durations else None,
        "duration_median": sorted(durations)[len(durations)//2] if durations else None,
        "spells": spell_records,
    }
    print(f"\n{category}: {len(spells)} real contiguous spells")
    if durations:
        print(f"  duration (sessions): min={min(durations)} median={sorted(durations)[len(durations)//2]} max={max(durations)}")
    for n in FORWARD_WINDOWS:
        vals = [r[f"forward_max_dd_{n}d"] for r in spell_records if r[f"forward_max_dd_{n}d"] is not None]
        if vals:
            vals_sorted = sorted(vals)
            print(f"  forward {n}d max_dd: n={len(vals)} min={vals_sorted[0]:.4f} "
                  f"median={vals_sorted[len(vals_sorted)//2]:.4f} max={vals_sorted[-1]:.4f}")

out = write_output(OUTPUT_DIR, "panel_c_d1_relative_spells.json", {
    "classification_counts": counts,
    "results": results,
    "forward_windows_sessions": FORWARD_WINDOWS,
}, manifest=manifest, script_path=SCRIPT_PATH, thresholds={
    "vix_level_threshold": _D1_VIX_LEVEL_THRESHOLD,
    "vix_pct504_threshold": _D1_VIX_PCT504_THRESHOLD,
})
print(f"\nSaved: {out}")
