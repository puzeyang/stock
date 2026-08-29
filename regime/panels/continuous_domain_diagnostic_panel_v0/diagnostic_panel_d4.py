"""Pure exploration (NOT touching crisis.py/engine.py): trace D4
(participation_collapse)'s actual firing behavior against real Breadth
data across the 8 labeled episodes, with the same per-date granularity
D1/D2/D3 already received in Messages[212]/[213]/[225-228]. D4's own
docstring in engine.py currently cites only ONE verified date
(2020-03-23) versus D1/D2/D3's four each -- this fills that gap.

No code changes. No conclusions written to the discussion log yet --
this is exploration only, per the human's explicit "先做纯探索" pattern
established throughout this investigation.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path("regime/src")))

from dataclasses import replace
from v5_1.contracts import load_manifest
from v5_1.engine import (
    load_raw_series_bundle, TEST_SCAFFOLDING_CONFIG,
    _d4_participation_collapse_evaluator,
    _D4_SHORT_COLLAPSE_THRESHOLD, _D4_LONG_COLLAPSE_THRESHOLD,
    _D4_EXTREME_SHORT, _D4_EXTREME_LONG, _D4_SPEED_DROP_PP_THRESHOLD,
)
from v5_1.crisis import CrisisEvaluationContext
from v5_1.breadth import compute_participation
from v5_1.crisis_validation import LABELED_EPISODES, episode_dates

manifest = load_manifest()
raw_bundle = load_raw_series_bundle(manifest)
d4_eval = _d4_participation_collapse_evaluator(raw_bundle.breadth)

print(f"D4 thresholds: short<=~{_D4_SHORT_COLLAPSE_THRESHOLD}, long<=~{_D4_LONG_COLLAPSE_THRESHOLD}, "
      f"extreme(short<=~{_D4_EXTREME_SHORT} AND long<=~{_D4_EXTREME_LONG}), "
      f"speed_drop>=~{_D4_SPEED_DROP_PP_THRESHOLD} in 5 sessions\n")

for ep in LABELED_EPISODES:
    dates = episode_dates(ep, raw_bundle)
    if not dates:
        print(f"{ep.name:50s} NO REAL TRADING DAYS IN RANGE (skipped)")
        continue

    active_dates = []
    valid_count = 0
    invalid_reasons = set()
    min_pct50 = None
    min_pct50_date = None

    for d in dates:
        ctx = CrisisEvaluationContext(as_of=d, price_damage_components=None)
        reading = d4_eval(ctx)
        if not reading.valid:
            invalid_reasons.update(reading.reason_codes)
            continue
        valid_count += 1
        try:
            pct50, pct200, eligible, total = compute_participation(raw_bundle.breadth, d, 50, 200)
        except Exception:
            pct50 = None
        if pct50 is not None and (min_pct50 is None or pct50 < min_pct50):
            min_pct50 = pct50
            min_pct50_date = d
        if reading.active:
            active_dates.append((d, reading.reason_codes))

    label = "POSITIVE" if ep.is_crisis_positive else "NEGATIVE"
    print(f"{ep.name:50s} {label:9s} valid={valid_count}/{len(dates)} active_dates={len(active_dates)} "
          f"min_pct50={min_pct50!r} on {min_pct50_date}")
    if invalid_reasons:
        print(f"    invalid reason_codes seen: {sorted(invalid_reasons)}")
    if active_dates:
        first_d, first_reasons = active_dates[0]
        last_d, last_reasons = active_dates[-1]
        print(f"    first active: {first_d} {first_reasons}")
        if len(active_dates) > 1:
            print(f"    last  active: {last_d} {last_reasons}")
        # tally which reason codes appear across all active dates
        from collections import Counter
        tally = Counter()
        for _, reasons in active_dates:
            tally.update(reasons)
        print(f"    reason-code tally across all active dates: {dict(tally)}")
    print()
