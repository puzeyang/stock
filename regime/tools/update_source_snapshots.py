#!/usr/bin/env python3
"""Refresh v5.1 raw caches and emit content-addressed provenance.

Refreshing operational caches does not silently mutate the adopted manifest.
After review, bump its dataset_version and copy the reported hashes into the
source contracts before using the refreshed snapshot for a release/backtest.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "research/data/raw"
MARKET = ROOT / "research/technical-analysis/data/market"
STATUS = ROOT / "regime/schema/source_snapshot_status.v5.1.json"
SYMBOLS = ["SPY", "QQQ", "IWM", "XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU"]
MARKET_SYMBOLS = ["VIX", "VIX9D", "VIX3M"]
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest(path: Path) -> str:
    frame = pd.read_csv(path)
    date_col = "date" if "date" in frame.columns else "observation_date"
    return str(pd.to_datetime(frame[date_col]).max().date())


def refresh() -> None:
    sys.path.insert(0, str(ROOT))
    from lib.data_loader import DataLoader

    loader = DataLoader(symbols=SYMBOLS, cache_dir=str(RAW), ext_cache_dir=str(RAW))
    loader.load_all(force_update=True)

    sys.path.insert(0, str(ROOT / "research/technical-analysis"))
    from ta_backtest.sources import refresh_market_cache

    refresh_market_cache(MARKET, start="2007-01-01")

    with urllib.request.urlopen(FRED_URL, timeout=60) as response:
        payload = response.read()
    with tempfile.NamedTemporaryFile(dir=RAW, prefix="BAMLH0A0HYM2.", suffix=".csv", delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    pd.read_csv(temp_path, parse_dates=["observation_date"])
    temp_path.replace(RAW / "BAMLH0A0HYM2.csv")


def write_status() -> None:
    paths = [RAW / f"{symbol}.csv" for symbol in SYMBOLS]
    paths += [MARKET / f"{symbol}.csv" for symbol in MARKET_SYMBOLS]
    paths += [RAW / "BAMLH0A0HYM2.csv"]
    records = {}
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(path)
        rel = str(path.relative_to(ROOT))
        records[rel] = {"sha256": sha256(path), "latest_observation": latest(path)}
    document = {
        "schema_version": "market-regime-source-status/v5.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "adoption_rule": "Bump manifest dataset_version and review hashes before release use.",
        "artifacts": records,
    }
    STATUS.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    refresh()
    write_status()
    print(STATUS)
