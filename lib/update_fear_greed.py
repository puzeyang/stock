"""Daily refresh of the CNN Fear & Greed cache (cron/systemd entrypoint).

Fetches from CNN and MERGES into lib/data/fear_greed/*.parquet (never shrinks
history — see fear_greed._merge_cache). Exits non-zero on failure so a cron
wrapper can log it; leaves the existing cache untouched on a failed fetch.

    python -m lib.update_fear_greed            # light 1-year refresh (default)
    python -m lib.update_fear_greed --full     # pull CNN's full history (~2020 on)

Run daily after the US close. The endpoint bot-blocks plain requests, so it needs
the browser headers already baked into fear_greed._HEADERS; it may still rate-limit
from a datacenter IP.
"""
from __future__ import annotations

import argparse
import sys

from lib import fear_greed as fg


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Refresh the CNN Fear & Greed parquet cache.")
    ap.add_argument("--full", action="store_true",
                    help="pull CNN's full available history (default: ~1-year window)")
    args = ap.parse_args(argv)

    start = fg.EARLIEST if args.full else None
    try:
        idx, comp = fg.fetch(save=True, start=start)
    except Exception as e:  # noqa: BLE001 — cron wrapper wants the reason, not a traceback
        print(f"fear_greed refresh FAILED: {e!r}", file=sys.stderr)
        return 1

    latest = idx.iloc[-1]
    print(f"fear_greed: {latest['score']:.0f} — {latest['rating']}  "
          f"(as of {latest['date'].date()}; index {len(idx)} rows, "
          f"components {len(comp)} rows; span {idx['date'].min().date()} → {idx['date'].max().date()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
