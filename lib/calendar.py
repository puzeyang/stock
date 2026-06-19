"""Trading calendar utilities — business days, US market hours, ET staleness."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pytz

ET = pytz.timezone("US/Eastern")
_MARKET_OPEN = (9, 30)   # 9:30 AM ET
_MARKET_CLOSE = (16, 0)  # 4:00 PM ET


def now_et() -> datetime:
    return datetime.now(ET)


def is_market_open() -> bool:
    """True if US equity market is currently open (weekdays 9:30–16:00 ET, no holidays)."""
    t = now_et()
    if t.weekday() >= 5:
        return False
    open_dt = t.replace(hour=_MARKET_OPEN[0], minute=_MARKET_OPEN[1], second=0, microsecond=0)
    close_dt = t.replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1], second=0, microsecond=0)
    return open_dt <= t < close_dt


def last_trading_day(as_of: Optional[datetime] = None) -> pd.Timestamp:
    """Most recent completed trading day (Mon–Fri) relative to as_of (default: now ET)."""
    t = (as_of or now_et()).date()
    day = pd.Timestamp(t)
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)
    return day


def business_days(n: int, end: Optional[str] = None) -> pd.DatetimeIndex:
    """Return the last n business days ending on end (default: today)."""
    end_date = pd.Timestamp(end) if end else pd.Timestamp(now_et().date())
    return pd.bdate_range(end=end_date, periods=n)


def is_data_stale(path: Path) -> bool:
    """True if the CSV at path is missing today's data (needs a refresh).

    Mirrors the staleness logic in DataLoader._is_data_current:
    - Saturday: expects last Friday
    - Sunday: expects last Friday
    - Weekday: expects yesterday (skipping Sunday → Friday)
    """
    if not path.exists():
        return True
    try:
        df = pd.read_csv(path, parse_dates=["date"])
        if df.empty:
            return True
        latest = df["date"].max().date()
    except Exception:
        return True

    today = now_et().date()
    weekday = today.weekday()
    if weekday == 5:
        expected = today - timedelta(days=1)
    elif weekday == 6:
        expected = today - timedelta(days=2)
    else:
        expected = today - timedelta(days=1)
        if expected.weekday() == 6:
            expected -= timedelta(days=2)
    return latest < expected
