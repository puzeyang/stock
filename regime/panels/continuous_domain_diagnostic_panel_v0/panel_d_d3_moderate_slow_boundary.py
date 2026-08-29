"""continuous_domain_diagnostic_panel_v0 -- Panel D (D3 moderate-slow
drawdown boundary spell duration + subsequent 20% extreme crossing),
per Message[247]'s pre-registered item (D): "D3 moderate-slow boundary
的持续时间与随后是否跨20% extreme".

The "moderate-slow boundary" is the known behavioral boundary
registered in Messages[242]/[243]/[244] as
`moderate_slow_drawdown_without_speed_confirmation`: real drawdown in
[12%, 20%) -- i.e. dd_stress=True but NOT extreme -- with NEITHER
shock_stress nor trend_damage true (so D3's active stays False despite
a real, threshold-crossing drawdown).

Pure descriptive diagnostic. Full real timeline 2018-06-22 to present.
NO thresholds generated, NO overall pass/fail labels, NOT touching
crisis.py/engine.py.

Classifies each real day into the moderate-slow boundary state, groups
into contiguous spells, reports duration, and for each spell asks:
did the REAL drawdown subsequently (any real trading day after the
spell's last day, no artificial forward-window cutoff, since this
question is literally "does it eventually cross 20%", not "within N
sessions") reach _D3_EXTREME_DRAWDOWN=0.20? If yes, reports the real
lag (real trading sessions from spell end to first >=20% crossing).

No thresholds changed. crisis.py/engine.py NOT modified. Output
persisted to outputs/panel_d_d3_moderate_slow_boundary.json.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import load_real_data, write_output, find_spells
from v5_1.engine import (
    _price_damage_components_estimator,
    _D3_DRAWDOWN_STRESS_THRESHOLD, _D3_SHOCK_5D_STRESS_THRESHOLD,
    _D3_TREND_DAMAGE_20D_THRESHOLD, _D3_EXTREME_DRAWDOWN, _D3_EXTREME_SHOCK_5D,
)

SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_DIR = SCRIPT_PATH.parent / "outputs"

manifest, raw_bundle, dates, member_paths = load_real_data()
benchmark = raw_bundle.benchmark
benchmark_dates = [o.date for o in benchmark.observations]

print("Classifying each real day's D3 moderate-slow boundary state...")
in_boundary = {}  # date -> True/False
raw_drawdown = {}  # date -> real drawdown value (for later "when did it cross 20%" lookups)
skipped = 0

for d in dates:
    components = _price_damage_components_estimator(benchmark, d)
    if components is None:
        skipped += 1
        continue
    dd = components.benchmark_drawdown
    raw_drawdown[d] = dd
    dd_stress = dd >= _D3_DRAWDOWN_STRESS_THRESHOLD
    shock_stress = components.return_shock_5d >= _D3_SHOCK_5D_STRESS_THRESHOLD
    trend_damage = components.return_shock_20d >= _D3_TREND_DAMAGE_20D_THRESHOLD
    is_extreme_already = dd >= _D3_EXTREME_DRAWDOWN or components.return_shock_5d >= _D3_EXTREME_SHOCK_5D
    # moderate-slow boundary: dd_stress true, NOT already extreme, AND neither speed leg confirms
    in_boundary[d] = dd_stress and not is_extreme_already and not shock_stress and not trend_damage

valid_dates = [d for d in dates if d in in_boundary]
boundary_dates = sorted(d for d in valid_dates if in_boundary[d])
print(f"Real trading days from {dates[0]}: {len(dates)}; classified: {len(valid_dates)}; skipped: {skipped}")
print(f"Moderate-slow-boundary days: {len(boundary_dates)} / {len(valid_dates)} ({100*len(boundary_dates)/len(valid_dates):.2f}%)\n")

spells = find_spells(boundary_dates, dates)
print(f"Real contiguous moderate-slow-boundary spells: {len(spells)}")


# A genuine methodological problem, caught while building this (not
# silently left in): an UNBOUNDED forward search for "did it ever cross
# 20%" conflates a plausibly-related continuation of the same drawdown
# episode with a much later, likely-UNRELATED crisis (e.g. a 2018-12
# spell "crossing" only because the real 2020-03 COVID crash happened
# ~300 sessions afterward). There is no way to distinguish "the same
# episode continued to deepen" from "an unrelated new episode arrived
# years later" using only this lag number. Reporting BOTH an unbounded
# search (labeled as such, not presented as if it answered "did THIS
# episode deepen") and a bounded search at a real, stated cutoff
# (60 real sessions, ~3 calendar months) chosen for transparency, not
# fit to the data -- the reader can judge either.
_RELATED_CROSSING_CUTOFF_SESSIONS = 60


def first_extreme_crossing_after(spell_end_date: str) -> dict:
    """Real, unbounded forward search for the first real trading day
    AFTER spell_end_date where drawdown reaches _D3_EXTREME_DRAWDOWN --
    reports both the unbounded result and whether it falls within
    _RELATED_CROSSING_CUTOFF_SESSIONS, explicitly flagging the
    unbounded-vs-bounded distinction rather than picking one silently."""
    if spell_end_date not in raw_drawdown:
        return {"crossed": False, "lag_sessions": None, "reason": "spell_end_date_itself_unavailable"}
    end_idx = dates.index(spell_end_date)
    for i, d in enumerate(dates[end_idx + 1:], start=1):
        dd = raw_drawdown.get(d)
        if dd is None:
            continue  # a gap in D3 availability -- skip, don't treat as non-crossing
        if dd >= _D3_EXTREME_DRAWDOWN:
            return {
                "crossed": True, "lag_sessions": i, "crossing_date": d, "crossing_drawdown": dd,
                "within_related_cutoff": i <= _RELATED_CROSSING_CUTOFF_SESSIONS,
            }
    return {"crossed": False, "lag_sessions": None, "reason": "never_reached_0.20_in_remaining_real_data"}


spell_records = []
for start, end in spells:
    start_idx = dates.index(start)
    end_idx = dates.index(end)
    duration = end_idx - start_idx + 1
    crossing = first_extreme_crossing_after(end)
    record = {"start": start, "end": end, "duration_sessions": duration, **crossing}
    spell_records.append(record)
    if crossing["crossed"]:
        cutoff_tag = "WITHIN cutoff" if crossing["within_related_cutoff"] else "OUTSIDE cutoff, likely unrelated later crisis"
        marker = f"CROSSED 20% after {crossing['lag_sessions']} sessions ({crossing.get('crossing_date')}, dd={crossing.get('crossing_drawdown', 0):.4f}) [{cutoff_tag}]"
    else:
        marker = "never crossed 20% in remaining data"
    print(f"  {start} .. {end} (dur={duration}): {marker}")

crossed_unbounded_count = sum(1 for r in spell_records if r["crossed"])
crossed_within_cutoff_count = sum(1 for r in spell_records if r["crossed"] and r["within_related_cutoff"])
durations = [r["duration_sessions"] for r in spell_records]
lags_unbounded = [r["lag_sessions"] for r in spell_records if r["crossed"]]
lags_within_cutoff = [r["lag_sessions"] for r in spell_records if r["crossed"] and r["within_related_cutoff"]]

print(f"\nSummary: {len(spells)} spells")
print(f"  UNBOUNDED search: {crossed_unbounded_count} ({100*crossed_unbounded_count/len(spells) if spells else 0:.1f}%) "
      f"eventually crossed 20% at ANY later real date -- includes likely-unrelated later crises, see script docstring")
print(f"  BOUNDED search (<={_RELATED_CROSSING_CUTOFF_SESSIONS} real sessions, plausibly the same episode): "
      f"{crossed_within_cutoff_count} ({100*crossed_within_cutoff_count/len(spells) if spells else 0:.1f}%)")
if durations:
    print(f"Spell duration (sessions): min={min(durations)} median={sorted(durations)[len(durations)//2]} max={max(durations)}")
if lags_unbounded:
    print(f"Lag to 20% crossing, UNBOUNDED (sessions): min={min(lags_unbounded)} median={sorted(lags_unbounded)[len(lags_unbounded)//2]} max={max(lags_unbounded)}")
if lags_within_cutoff:
    print(f"Lag to 20% crossing, WITHIN CUTOFF ONLY (sessions): min={min(lags_within_cutoff)} median={sorted(lags_within_cutoff)[len(lags_within_cutoff)//2]} max={max(lags_within_cutoff)}")

out = write_output(OUTPUT_DIR, "panel_d_d3_moderate_slow_boundary.json", {
    "boundary_day_count": len(boundary_dates),
    "valid_day_count": len(valid_dates),
    "spell_count": len(spells),
    "crossed_unbounded_count": crossed_unbounded_count,
    "crossed_within_cutoff_count": crossed_within_cutoff_count,
    "related_crossing_cutoff_sessions": _RELATED_CROSSING_CUTOFF_SESSIONS,
    "spells": spell_records,
}, manifest=manifest, script_path=SCRIPT_PATH, thresholds={
    "drawdown_stress_threshold": _D3_DRAWDOWN_STRESS_THRESHOLD,
    "extreme_drawdown_threshold": _D3_EXTREME_DRAWDOWN,
    "shock_5d_stress_threshold": _D3_SHOCK_5D_STRESS_THRESHOLD,
    "trend_damage_20d_threshold": _D3_TREND_DAMAGE_20D_THRESHOLD,
})
print(f"\nSaved: {out}")
