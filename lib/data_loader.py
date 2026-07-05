"""DataLoader — downloads, caches, and serves OHLCV data via yfinance.

Features:
- Auto-downloads full history on first request
- Incremental updates for stale/missing data
- Respects US Eastern Time trading hours for staleness checks
- Retry logic for failed downloads
- Universe-level helpers: load(), load_all(), load_benchmark()
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pytz

try:
    import yfinance as yf
    HAS_YFINANCE = True
except ImportError:
    HAS_YFINANCE = False

try:
    import exchange_calendars as _xcals
    _NYSE = _xcals.get_calendar("XNYS")
    HAS_XCALS = True
except ImportError:
    HAS_XCALS = False

DEFAULT_SYMBOLS = ["QQQ", "NVDA", "TSLA"]

__all__ = ["DataLoader"]


class DataLoader:
    """Downloads and caches stock quote data with intelligent update logic.

    Basic usage (universe mode):
        dl = DataLoader(symbols=["QQQ", "NVDA"], cache_dir="data/raw")
        df = dl.load("QQQ")
        all_data = dl.load_all()
        spy = dl.load_benchmark()

    Direct access:
        dl = DataLoader(cache_dir="/path/to/cache")
        df = dl.get_quotes("AAPL", start_date="2020-01-01")
    """

    def __init__(
        self,
        symbols: list[str] = DEFAULT_SYMBOLS,
        cache_dir: str = "data/raw",
        ext_cache_dir: str = "data/external",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        self.symbols = symbols
        self.start_date = start_date
        self.end_date = end_date
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._ext_cache_dir = Path(ext_cache_dir)
        self._ext_cache_dir.mkdir(parents=True, exist_ok=True)
        self._eastern_tz = pytz.timezone("US/Eastern")

    # ── Universe helpers ───────────────────────────────────────────────────────

    def load(self, symbol: str, force_update: bool = False) -> Optional[pd.DataFrame]:
        """Load a single symbol, applying the instance's date range."""
        return self.get_quotes(
            symbol,
            force_update=force_update,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    def load_all(self, force_update: bool = False) -> dict[str, pd.DataFrame]:
        """Load all symbols in the universe."""
        return self.get_multiple_quotes(
            self.symbols,
            force_update=force_update,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    def load_benchmark(self, symbol: str = "SPY") -> Optional[pd.DataFrame]:
        """Load a benchmark symbol, cached separately in ext_cache_dir."""
        return self._get_quotes_from(
            symbol,
            cache_dir=self._ext_cache_dir,
            start_date=self.start_date,
            end_date=self.end_date,
        )

    # ── Core cache/download API ────────────────────────────────────────────────

    def get_quotes(
        self,
        symbol: str,
        force_update: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """Return OHLCV data for symbol, downloading/updating as needed."""
        return self._get_quotes_from(
            symbol,
            cache_dir=self.cache_dir,
            force_update=force_update,
            start_date=start_date,
            end_date=end_date,
        )

    def get_multiple_quotes(
        self,
        symbols: list[str],
        force_update: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict[str, pd.DataFrame]:
        """Return OHLCV data for multiple symbols."""
        results = {}
        for symbol in symbols:
            df = self.get_quotes(
                symbol,
                force_update=force_update,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None:
                results[symbol] = df
        return results

    # ── Cache internals ────────────────────────────────────────────────────────

    def _get_quotes_from(
        self,
        symbol: str,
        cache_dir: Path,
        force_update: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        quote_path = cache_dir / f"{symbol}.csv"
        if not quote_path.exists():
            print(f"{symbol} not in cache, downloading full history...")
            if not self._download_full_history(symbol, quote_path):
                return None
        elif force_update or not self._is_data_current(quote_path):
            if not self._update_incremental(symbol, quote_path):
                print(f"Warning: failed to update {symbol}, using cached data")

        return self._read_csv(quote_path, start_date=start_date, end_date=end_date)

    def _get_latest_date(self, path: Path) -> Optional[pd.Timestamp]:
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path, parse_dates=["date"])
            return df["date"].max() if len(df) > 0 else None
        except Exception as e:
            print(f"Warning: error reading {path}: {e}")
            return None

    def _is_data_current(self, path: Path) -> bool:
        latest_date = self._get_latest_date(path)
        if latest_date is None:
            return False
        now_et = datetime.now(self._eastern_tz)
        latest_date_only = latest_date.date()

        if HAS_XCALS:
            now_ts = pd.Timestamp(now_et)
            MARKET_CLOSE_HOUR = 16
            if now_et.hour >= MARKET_CLOSE_HOUR and _NYSE.is_session(now_ts.date()):
                expected_latest = now_ts.date()
            else:
                expected_latest = _NYSE.previous_close(now_ts).date()
        else:
            # Fallback: weekend/weekday logic without holiday awareness
            today_et = now_et.date()
            weekday = today_et.weekday()
            MARKET_CLOSE_HOUR = 16
            if weekday == 5:
                expected_latest = today_et - timedelta(days=1)
            elif weekday == 6:
                expected_latest = today_et - timedelta(days=2)
            elif now_et.hour >= MARKET_CLOSE_HOUR:
                expected_latest = today_et
            else:
                expected_latest = today_et - timedelta(days=1)
                if expected_latest.weekday() == 6:
                    expected_latest -= timedelta(days=2)

        return latest_date_only >= expected_latest

    def _download_with_retry(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_retries: int = 3,
    ) -> Optional[pd.DataFrame]:
        if not HAS_YFINANCE:
            raise ImportError("yfinance is required: pip install yfinance")
        for attempt in range(max_retries):
            try:
                ticker = yf.Ticker(symbol)
                if start_date is None and end_date is None:
                    df = ticker.history(period="max", auto_adjust=False)
                else:
                    df = ticker.history(start=start_date, end=end_date, auto_adjust=False)

                if df.empty:
                    print(f"  Warning: no data returned for {symbol}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return None

                df = df.reset_index()
                if "Date" in df.columns and hasattr(df["Date"].dtype, "tz") and df["Date"].dt.tz is not None:
                    df["Date"] = df["Date"].dt.tz_localize(None)

                df = df.rename(columns={
                    "Date": "date", "Open": "open", "High": "high",
                    "Low": "low", "Close": "close", "Volume": "volume",
                    "Adj Close": "adj_close",
                })
                required = ["date", "open", "high", "low", "close", "volume"]
                cols = required + [c for c in ["adj_close"] if c in df.columns]
                return df[cols]

            except Exception as e:
                print(f"  Error downloading {symbol}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    print(f"  Failed after {max_retries} attempts")
                    return None
        return None

    def _download_full_history(self, symbol: str, path: Path) -> bool:
        print(f"Downloading full history for {symbol}...")
        df = self._download_with_retry(symbol)
        if df is None:
            return False
        df.to_csv(path, index=False)
        print(f"  Saved {len(df)} rows to {path}")
        return True

    def _update_incremental(self, symbol: str, path: Path) -> bool:
        latest_date = self._get_latest_date(path)
        if latest_date is None:
            return self._download_full_history(symbol, path)

        start_date = (latest_date + timedelta(days=1)).strftime("%Y-%m-%d")
        print(f"Updating {symbol} from {start_date}...")

        df_new = self._download_with_retry(symbol, start_date=start_date)
        if df_new is None or len(df_new) == 0:
            print(f"  No new data available for {symbol}")
            return True

        df_existing = pd.read_csv(path, parse_dates=["date"])
        for df_part in [df_existing, df_new]:
            if pd.api.types.is_datetime64_any_dtype(df_part["date"]):
                if getattr(df_part["date"].dtype, "tz", None) is not None:
                    df_part["date"] = df_part["date"].dt.tz_localize(None)

        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined["date"] = pd.to_datetime(df_combined["date"], errors="coerce")
        if getattr(df_combined["date"].dtype, "tz", None) is not None:
            df_combined["date"] = df_combined["date"].dt.tz_localize(None)
        df_combined = (
            df_combined
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
        df_combined.to_csv(path, index=False)
        print(f"  Added {len(df_new)} rows (total: {len(df_combined)})")
        return True

    def _read_csv(
        self,
        path: Path,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        try:
            df = pd.read_csv(path, parse_dates=["date"])
            if pd.api.types.is_datetime64_any_dtype(df["date"]):
                if hasattr(df["date"].dtype, "tz") and df["date"].dtype.tz is not None:
                    df["date"] = df["date"].dt.tz_localize(None)
            if start_date:
                df = df[df["date"] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df["date"] <= pd.to_datetime(end_date)]
            return df
        except Exception as e:
            print(f"Error loading {path}: {e}")
            return None
