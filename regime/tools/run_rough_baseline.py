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
run coherently on real-scale windows and produce a plausible-looking
state sequence" (per the human's explicit "Option a" direction) — NOT
"is this state label correct/trustworthy for real decisions."

Usage:
    python3 regime/tools/run_rough_baseline.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--n N]

PERFORMANCE NOTE (measured directly, not estimated): the default
--warmup-from 2019-01-01 to present is ~1900 real trading days; a full
run through the engine's 12 modules (dominated by D1/D2's 504-session
causal_midrank recomputation every single bar) takes roughly 7 minutes
wall-clock on this machine, regardless of how few dates are actually
--n printed at the end -- every warm-up day still runs the full
pipeline to keep RunningEngineState's cross-bar history correct. Not
fast; run in the background for anything beyond a quick check.

Prints one line per real trading day in range: date, state,
condition_score, direction_structure, crisis_active_domain_count,
whether the record is current (state_is_current) or degraded.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "regime/src"))

from v5_1.contracts import load_manifest  # noqa: E402
from v5_1.engine import (  # noqa: E402
    load_raw_series_bundle, new_running_engine_state, run_engine_for_date,
    REASONABLENESS_CHECK_ROUGH_BASELINE,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default=None, help="first real trading date to include (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="last real trading date to include (YYYY-MM-DD)")
    parser.add_argument("--n", type=int, default=20, help="if --start not given, show the last N real trading days (default 20)")
    parser.add_argument("--warmup-from", default="2019-01-01",
                         help="engine state is warmed up from this date forward, before any printed date, "
                              "so long-window pillars (Direction 200-session, Breadth 200-session, CRISIS's "
                              "504-session D1/D2 windows, first satisfiable 2020-06-23 given VIX9D's real "
                              "2018-06-22 coverage floor) are genuinely satisfied by the time printed dates "
                              "are reached, not cold-started at --start itself. Default 2019-01-01 is a "
                              "practical middle ground, not itself a real threshold -- printed dates before "
                              "roughly 2020-06-23 will correctly show CRISIS domains as unavailable/invalid, "
                              "not falsely calm, per the engine's own fail-closed warm-up contract. Running "
                              "the full ~2900-real-day 2015-present range takes several minutes; shrink this "
                              "for faster iteration if CRISIS availability on very recent dates is all you need.")
    args = parser.parse_args()

    print("REASONABLENESS_CHECK_ROUGH_BASELINE -- NOT a calibrated production configuration.", file=sys.stderr)
    print("Pillar weights, veto/cap rules, and every D1-D4 threshold remain uncalibrated placeholders.\n", file=sys.stderr)

    manifest = load_manifest()
    raw_bundle = load_raw_series_bundle(manifest)
    config = REASONABLENESS_CHECK_ROUGH_BASELINE
    state = new_running_engine_state(config)

    all_dates = [o.date for o in raw_bundle.benchmark.observations if o.date >= args.warmup_from]
    if args.start:
        print_from = args.start
    elif args.n:
        real_dates_only = [o.date for o in raw_bundle.benchmark.observations if o.date >= args.warmup_from]
        cutoff_dates = [d for d in real_dates_only if args.end is None or d <= args.end]
        print_from = cutoff_dates[-args.n] if len(cutoff_dates) >= args.n else cutoff_dates[0]
    else:
        print_from = args.warmup_from

    print(f"{'date':12s} {'state':10s} {'current':8s} {'condition':>10s} {'direction':16s} {'crisis_active':>14s}")
    for d in all_dates:
        if args.end is not None and d > args.end:
            break
        record = run_engine_for_date(d, raw_bundle, state, config=config, manifest=manifest)
        if d < print_from:
            continue
        cond = record.get("condition_score")
        cond_str = f"{cond:.4f}" if cond is not None else "None"
        print(f"{d:12s} {str(record['state']):10s} {str(record['state_is_current']):8s} "
              f"{cond_str:>10s} {str(record.get('direction_structure')):16s} "
              f"{str(record.get('crisis_active_domain_count')):>14s}")


if __name__ == "__main__":
    main()
