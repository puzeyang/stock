"""Technical indicators and batch indicator pack."""
from __future__ import annotations
from typing import Optional

import numpy as np
import pandas as pd

__all__ = [
    "ema", "sma", "rsi",
    "macd_line", "macd_signal_line",
    "true_range", "atr", "bollinger",
    "adx", "chaikin_money_flow", "ichimoku",
    "rolling_skew", "rate_of_change",
    "historical_volatility",
    "vwap", "vwap_deviation",
    "weekly_ema", "weekly_price_position",
    "relative_strength",
    "mansfield_rs",
    "rsi_divergence", "macd_divergence",
    "obv", "volume_surge", "volume_dryup",
    "atr_percentile", "volatility_breakout",
    "swing_high_low", "higher_highs_lows", "lower_highs_lows",
    "gap_size", "gap_fill_percentage",
    "price_consolidation", "breakout_from_consolidation",
    "trend_strength", "support_resistance_touch",
    "linreg_slope", "linreg_r2",
    "weinstein_stage",
    "indicator_pack",
    "add_indicators",
]


# ── Core indicators ────────────────────────────────────────────────────────────

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    gain = up.ewm(alpha=1/length, adjust=False).mean()
    loss = down.ewm(alpha=1/length, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd_line(series: pd.Series, fast: int = 12, slow: int = 26) -> pd.Series:
    return ema(series, fast) - ema(series, slow)


def macd_signal_line(macd_ln: pd.Series, signal: int = 9) -> pd.Series:
    return ema(macd_ln, signal)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1/length, adjust=False).mean()


def bollinger(series: pd.Series, length: int = 20, stdev: float = 2.0):
    mid = sma(series, length)
    sd = series.rolling(length, min_periods=length).std()
    up = mid + stdev * sd
    dn = mid - stdev * sd
    width = (up - dn) / mid.replace(0, np.nan)
    return mid, up, dn, width


def adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.DataFrame:
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(high, low, close)
    atr_w = tr.ewm(alpha=1 / length, adjust=False).mean()
    plus_di = pd.Series(plus_dm, index=high.index).ewm(alpha=1 / length, adjust=False).mean()
    minus_di = pd.Series(minus_dm, index=high.index).ewm(alpha=1 / length, adjust=False).mean()
    plus_di = 100 * (plus_di / atr_w.replace(0, np.nan))
    minus_di = 100 * (minus_di / atr_w.replace(0, np.nan))
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    adx_series = dx.ewm(alpha=1 / length, adjust=False).mean()
    return pd.DataFrame({
        f"adx_{length}": adx_series,
        f"dx_plus_{length}": plus_di,
        f"dx_minus_{length}": minus_di,
    })


def chaikin_money_flow(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, length: int = 20) -> pd.Series:
    mfm = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    mfv = mfm * volume
    return (mfv.rolling(length).sum()) / (volume.rolling(length).sum())


def ichimoku(
    df: pd.DataFrame,
    tenkan_len: int = 9,
    kijun_len: int = 26,
    senkou_b_len: int = 52,
    shift: int = 26,
) -> pd.DataFrame:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tenkan = (high.rolling(tenkan_len).max() + low.rolling(tenkan_len).min()) / 2
    kijun = (high.rolling(kijun_len).max() + low.rolling(kijun_len).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(shift)
    span_b = ((high.rolling(senkou_b_len).max() + low.rolling(senkou_b_len).min()) / 2).shift(shift)
    chikou = close.shift(-shift)
    return pd.DataFrame({
        "ichimoku_tenkan": tenkan,
        "ichimoku_kijun": kijun,
        "ichimoku_span_a": span_a,
        "ichimoku_span_b": span_b,
        "ichimoku_chikou": chikou,
    })


def rolling_skew(returns: pd.Series, length: int = 60) -> pd.Series:
    return returns.rolling(length).skew()


def rate_of_change(series: pd.Series, length: int = 20) -> pd.Series:
    return series.pct_change(periods=length)


def historical_volatility(series: pd.Series, window: int) -> pd.Series:
    log_returns = np.log(series / series.shift(1))
    return log_returns.rolling(window=window, min_periods=window).std() * np.sqrt(252)


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    typical_price = (high + low + close) / 3
    return (typical_price * volume).rolling(window).sum() / volume.rolling(window).sum()


def vwap_deviation(close: pd.Series, vwap_series: pd.Series) -> pd.Series:
    return (close - vwap_series) / vwap_series.replace(0, np.nan)


def weekly_ema(df: pd.DataFrame, span: int, price_col: str = 'close') -> pd.Series:
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'date' in df.columns:
            df_indexed = df.set_index('date')
        else:
            raise ValueError("DataFrame must have datetime index or 'date' column")
    else:
        df_indexed = df
    weekly = df_indexed.resample('W-FRI').agg({price_col: 'last'})
    weekly_ema_val = weekly[price_col].ewm(span=span, adjust=False).mean()
    return weekly_ema_val.reindex(df_indexed.index, method='ffill')


def weekly_price_position(df: pd.DataFrame) -> pd.Series:
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'date' in df.columns:
            df_indexed = df.set_index('date')
        else:
            raise ValueError("DataFrame must have datetime index or 'date' column")
    else:
        df_indexed = df
    weekly = df_indexed.resample('W-FRI').agg({'high': 'max', 'low': 'min', 'close': 'last'})
    weekly_daily = weekly.reindex(df_indexed.index, method='ffill')
    weekly_range = weekly_daily['high'] - weekly_daily['low']
    return (df_indexed['close'] - weekly_daily['low']) / weekly_range.replace(0, np.nan)


def relative_strength(symbol_close: pd.Series, benchmark_close: pd.Series, window: int = 20) -> pd.Series:
    return symbol_close.pct_change(periods=window) - benchmark_close.pct_change(periods=window)


def mansfield_rs(
    symbol_close: pd.Series,
    benchmark_close: pd.Series,
    ma_weeks: int = 52,
) -> pd.Series:
    """Mansfield Relative Strength — the version Stan Weinstein used.

    Formula (weekly)
    ----------------
        RS           = weekly_close(stock) / weekly_close(benchmark)
        Mansfield RS = ((RS / SMA(RS, ma_weeks)) - 1) × 100

    Both series are resampled to weekly Friday closes before the ratio and
    MA are computed, then the result is forward-filled back to the daily
    index.  Positive = outperforming benchmark, negative = underperforming.

    Parameters
    ----------
    symbol_close    : Daily close prices of the stock (DatetimeIndex).
    benchmark_close : Daily close prices of the benchmark (e.g. SPY).
    ma_weeks        : SMA look-back in weeks (default 52).
    """
    sym_w   = symbol_close.resample("W-FRI").last()
    bench_w = benchmark_close.resample("W-FRI").last()
    ratio   = sym_w / bench_w.replace(0, np.nan)
    ratio_ma = ratio.rolling(ma_weeks, min_periods=ma_weeks).mean()
    mrs_weekly = ((ratio / ratio_ma.replace(0, np.nan)) - 1) * 100
    return mrs_weekly.reindex(symbol_close.index, method="ffill")


# ── Advanced indicators ────────────────────────────────────────────────────────

def rsi_divergence(close: pd.Series, rsi_series: pd.Series, lookback: int = 5) -> pd.Series:
    price_lower_low = close < close.shift(lookback)
    rsi_higher_low = rsi_series > rsi_series.shift(lookback)
    price_higher_high = close > close.shift(lookback)
    rsi_lower_high = rsi_series < rsi_series.shift(lookback)
    result = pd.Series(0, index=close.index)
    result[price_lower_low & rsi_higher_low] = 1
    result[price_higher_high & rsi_lower_high] = -1
    return result


def macd_divergence(close: pd.Series, macd_hist: pd.Series, lookback: int = 5) -> pd.Series:
    price_lower_low = close < close.shift(lookback)
    macd_higher_low = macd_hist > macd_hist.shift(lookback)
    price_higher_high = close > close.shift(lookback)
    macd_lower_high = macd_hist < macd_hist.shift(lookback)
    result = pd.Series(0, index=close.index)
    result[price_lower_low & macd_higher_low] = 1
    result[price_higher_high & macd_lower_high] = -1
    return result


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (np.sign(close.diff()) * volume).cumsum()


def volume_surge(volume: pd.Series, window: int = 20, threshold: float = 2.0) -> pd.Series:
    return (volume > volume.rolling(window).mean() * threshold).astype(int)


def volume_dryup(volume: pd.Series, window: int = 20, threshold: float = 0.5) -> pd.Series:
    return (volume < volume.rolling(window).mean() * threshold).astype(int)


def atr_percentile(atr_series: pd.Series, window: int = 252) -> pd.Series:
    def calc_percentile(x):
        if len(x) < 2:
            return np.nan
        return (x.iloc[-1] > x).sum() / len(x) * 100
    return atr_series.rolling(window).apply(calc_percentile, raw=False)


def volatility_breakout(close: pd.Series, atr_series: pd.Series, threshold: float = 2.0) -> pd.Series:
    price_change = close.diff().abs()
    breakout = price_change > (atr_series * threshold)
    direction = np.sign(close.diff())
    result = pd.Series(0, index=close.index)
    result[breakout] = direction[breakout]
    return result


# ── Price action & pattern recognition ────────────────────────────────────────

def swing_high_low(high: pd.Series, low: pd.Series, lookback: int = 5) -> tuple:
    swing_high = pd.Series(0, index=high.index)
    swing_low = pd.Series(0, index=low.index)
    for i in range(lookback, len(high) - lookback):
        window_high = high.iloc[i - lookback:i + lookback + 1]
        if high.iloc[i] == window_high.max() and window_high.max() > 0:
            swing_high.iloc[i] = 1
        window_low = low.iloc[i - lookback:i + lookback + 1]
        if low.iloc[i] == window_low.min() and window_low.min() > 0:
            swing_low.iloc[i] = 1
    swing_high = swing_high.shift(lookback).fillna(0).astype(int)
    swing_low = swing_low.shift(lookback).fillna(0).astype(int)
    return swing_high, swing_low


def higher_highs_lows(high: pd.Series, low: pd.Series, swing_high: pd.Series, swing_low: pd.Series) -> pd.Series:
    result = pd.Series(0, index=high.index)
    for idx_list, price_series in [
        (swing_high[swing_high == 1].index, high),
        (swing_low[swing_low == 1].index, low),
    ]:
        for i in range(1, len(idx_list)):
            curr, prev = idx_list[i], idx_list[i - 1]
            if price_series.loc[curr] > price_series.loc[prev]:
                result.loc[curr] = 1
    return result


def lower_highs_lows(high: pd.Series, low: pd.Series, swing_high: pd.Series, swing_low: pd.Series) -> pd.Series:
    result = pd.Series(0, index=high.index)
    for idx_list, price_series in [
        (swing_high[swing_high == 1].index, high),
        (swing_low[swing_low == 1].index, low),
    ]:
        for i in range(1, len(idx_list)):
            curr, prev = idx_list[i], idx_list[i - 1]
            if price_series.loc[curr] < price_series.loc[prev]:
                result.loc[curr] = 1
    return result


def gap_size(open_price: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return (open_price - prev_close) / prev_close.replace(0, np.nan)


def gap_fill_percentage(open_price: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    gap = open_price - prev_close
    result = pd.Series(0.0, index=close.index)
    gap_up_mask = gap > 0
    if gap_up_mask.any():
        retracement = open_price - low
        result[gap_up_mask] = (retracement[gap_up_mask] / gap[gap_up_mask].replace(0, np.nan)) * 100
    gap_down_mask = gap < 0
    if gap_down_mask.any():
        rally = high - open_price
        result[gap_down_mask] = (rally[gap_down_mask] / gap[gap_down_mask].abs().replace(0, np.nan)) * 100
    return result.clip(0, 200)


def price_consolidation(high: pd.Series, low: pd.Series, window: int = 10, threshold: float = 0.02) -> pd.Series:
    rolling_range = high.rolling(window).max() - low.rolling(window).min()
    avg_price = (high + low) / 2
    range_pct = rolling_range / avg_price.replace(0, np.nan)
    return (range_pct < threshold).astype(int)


def breakout_from_consolidation(close: pd.Series, high: pd.Series, low: pd.Series,
                                consolidation: pd.Series, lookback: int = 3) -> pd.Series:
    result = pd.Series(0, index=close.index)
    for i in range(lookback, len(close)):
        if consolidation.iloc[i - lookback:i].sum() >= lookback - 1:
            consol_high = high.iloc[i - lookback:i].max()
            consol_low = low.iloc[i - lookback:i].min()
            if close.iloc[i] > consol_high:
                result.iloc[i] = 1
            elif close.iloc[i] < consol_low:
                result.iloc[i] = -1
    return result


def trend_strength(close: pd.Series, ema_short: pd.Series, ema_long: pd.Series,
                   adx_series: pd.Series, window: int = 10) -> pd.Series:
    ema_sep = ((ema_short - ema_long).abs() / close.replace(0, np.nan)) * 100
    ema_sep_score = ema_sep.clip(0, 10) * 3.3
    ema_slope = (ema_short - ema_short.shift(window)) / ema_short.shift(window).replace(0, np.nan) * 100
    ema_slope_score = ema_slope.abs().clip(0, 10) * 3.3
    adx_score = (adx_series / 100 * 34).fillna(0)
    return (ema_sep_score + ema_slope_score + adx_score).clip(0, 100)


def support_resistance_touch(close: pd.Series, high: pd.Series, low: pd.Series,
                              swing_high: pd.Series, swing_low: pd.Series,
                              tolerance: float = 0.01) -> tuple:
    resistance_touch = pd.Series(0, index=close.index)
    support_touch = pd.Series(0, index=close.index)
    for i in range(20, len(close)):
        recent_highs = swing_high.iloc[max(0, i - 50):i]
        if recent_highs.sum() > 0:
            sh_idx = recent_highs[recent_highs == 1].index
            if len(sh_idx) > 0:
                level = high.loc[sh_idx[-1]]
                if abs(high.iloc[i] - level) / level < tolerance:
                    resistance_touch.iloc[i] = 1
        recent_lows = swing_low.iloc[max(0, i - 50):i]
        if recent_lows.sum() > 0:
            sl_idx = recent_lows[recent_lows == 1].index
            if len(sl_idx) > 0:
                level = low.loc[sl_idx[-1]]
                if abs(low.iloc[i] - level) / level < tolerance:
                    support_touch.iloc[i] = 1
    return resistance_touch, support_touch


# ── Regression indicators ─────────────────────────────────────────────────────

def linreg_slope(series: pd.Series, window: int = 20) -> pd.Series:
    """Normalised linear regression slope over a rolling window.

    Returns slope as % change per bar relative to the mean price of the window,
    so values are comparable across different price levels and time periods.
    """
    x = np.arange(window, dtype=float)
    x -= x.mean()
    x_ss = (x ** 2).sum()

    def _slope(y: np.ndarray) -> float:
        return float(np.dot(x, y) / x_ss / np.mean(y)) if np.mean(y) != 0 else np.nan

    return series.rolling(window, min_periods=window).apply(_slope, raw=True)


def linreg_r2(series: pd.Series, window: int = 20) -> pd.Series:
    """R² of the linear regression fit over a rolling window.

    Values near 1.0 = price moving cleanly in a straight line (strong trend).
    Values near 0.0 = choppy / no linear structure.
    """
    x = np.arange(window, dtype=float)
    x -= x.mean()
    x_ss = (x ** 2).sum()

    def _r2(y: np.ndarray) -> float:
        slope = np.dot(x, y) / x_ss
        intercept = np.mean(y) - slope * np.mean(np.arange(window, dtype=float))
        y_hat = slope * np.arange(window, dtype=float) + intercept
        ss_res = ((y - y_hat) ** 2).sum()
        ss_tot = ((y - np.mean(y)) ** 2).sum()
        return float(1.0 - ss_res / ss_tot) if ss_tot > 0 else np.nan

    return series.rolling(window, min_periods=window).apply(_r2, raw=True)


# ── Weinstein Stage Analysis ──────────────────────────────────────────────────

def weinstein_stage(
    df: pd.DataFrame,
    benchmark_close: Optional[pd.Series] = None,
    ma10w: int = 10,
    ma30w: int = 30,
    ma40w: int = 40,
    range_weeks: int = 13,
    rs_ma_weeks: int = 52,
) -> pd.DataFrame:
    """Stan Weinstein Stage Analysis on a daily OHLCV DataFrame.

    Computes weekly SMAs (10w / 30w / 40w) by resampling to weekly and
    forward-filling back to the daily index, then classifies each bar into
    one of four stages:

        Stage 1 – Basing / accumulation: price churning sideways between
                  the 30w and 40w MAs after a prior downtrend.
        Stage 2 – Advancing / uptrend: price above the 30w MA while the
                  30w MA slopes upward; breakout from a Stage-1 base.
        Stage 3 – Distribution / topping: price churning sideways between
                  the 30w and 40w MAs after a prior uptrend.
        Stage 4 – Declining / downtrend: price below the 30w MA while the
                  30w MA slopes downward; breakdown from a Stage-3 top.

    Returned columns
    ----------------
    ma_10w, ma_30w, ma_40w   : weekly SMAs forward-filled to daily
    high_13w, low_13w        : 13-week rolling high / low (daily forward-fill)
    mansfield_rs             : Mansfield RS vs benchmark (NaN if no benchmark)
    weinstein_stage          : integer 1-4 (0 = insufficient data)
    weinstein_stage_str      : human-readable label

    Parameters
    ----------
    df              : Daily OHLCV DataFrame with DatetimeIndex and 'close' column.
    benchmark_close : Optional daily close Series for Mansfield RS calculation.
    ma10w/30w/40w   : Week lengths for the three core moving averages.
    range_weeks     : Rolling-high/low window in weeks for 13w range.
    rs_ma_weeks     : MA look-back for Mansfield RS smoothing (default 52w).
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("weinstein_stage requires a DatetimeIndex")

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # ── Weekly OHLC (Friday close) ─────────────────────────────────────────────
    weekly = df[["high", "low", "close"]].resample("W-FRI").agg(
        {"high": "max", "low": "min", "close": "last"}
    )

    def _asof_daily(w_series: pd.Series) -> np.ndarray:
        """Map a weekly series to the daily index via last-known-value lookup.

        reindex(..., method="ffill") gaps when a W-FRI date falls on a market
        holiday and is absent from df.index.  merge_asof handles this correctly.
        """
        w_df = pd.DataFrame({"date": w_series.index, "val": w_series.values})
        d_df = pd.DataFrame({"date": df.index})
        merged = pd.merge_asof(d_df, w_df, on="date")
        return merged["val"].values

    def _weekly_sma(weeks: int) -> pd.Series:
        w_sma = weekly["close"].rolling(weeks, min_periods=weeks).mean()
        w_sma.name = f"ma{weeks}w"
        return pd.Series(_asof_daily(w_sma), index=df.index)

    ma10 = _weekly_sma(ma10w)
    ma30 = _weekly_sma(ma30w)
    ma40 = _weekly_sma(ma40w)

    # ── 13-week range ──────────────────────────────────────────────────────────
    weekly_high = weekly["high"].rolling(range_weeks, min_periods=range_weeks).max()
    weekly_low  = weekly["low"].rolling(range_weeks,  min_periods=range_weeks).min()
    weekly_high.name = "high_13w"
    weekly_low.name  = "low_13w"
    high_13w = pd.Series(_asof_daily(weekly_high), index=df.index)
    low_13w  = pd.Series(_asof_daily(weekly_low),  index=df.index)

    # ── Mansfield Relative Strength vs benchmark ──────────────────────────────
    if benchmark_close is not None:
        mrs = mansfield_rs(close, benchmark_close, ma_weeks=rs_ma_weeks)
    else:
        mrs = pd.Series(np.nan, index=df.index)

    # ── Stage classification (on weekly bars, then forward-fill to daily) ────────
    # Weinstein's stages are a weekly concept; classifying on daily bars against
    # weekly MAs produces noise.  We classify once per week on the Friday close
    # and carry that stage forward through the week.
    #
    # Stage 2: weekly close > ma30w  AND  ma30w is rising (slope > 0)
    # Stage 4: weekly close < ma30w  AND  ma30w is falling (slope <= 0)
    # Stage 1/3 (neutral): disambiguated by last confirmed directional stage —
    #   Stage 3 only follows Stage 2; Stage 1 follows Stage 4 or is initial.

    w_close = weekly["close"]
    w_ma30  = weekly["close"].rolling(ma30w, min_periods=ma30w).mean()
    w_ma40  = weekly["close"].rolling(ma40w, min_periods=ma40w).mean()
    w_slope = (w_ma30 - w_ma30.shift(1)) > 0   # week-on-week slope

    w_valid = w_ma30.notna() & w_ma40.notna()
    w_stage = np.zeros(len(w_close), dtype=int)
    last_directional = 1  # opening context: basing

    for i in range(len(w_close)):
        if not w_valid.iloc[i]:
            w_stage[i] = 0
            continue
        if w_close.iloc[i] > w_ma30.iloc[i] and w_slope.iloc[i]:
            w_stage[i] = 2
            last_directional = 2
        elif w_close.iloc[i] < w_ma30.iloc[i] and not w_slope.iloc[i]:
            w_stage[i] = 4
            last_directional = 4
        else:
            w_stage[i] = 3 if last_directional == 2 else 1

    weekly_stage = pd.Series(w_stage, index=weekly.index, dtype=int)
    # Map weekly stage to every trading day using asof (last-known-value lookup).
    stage_vals = _asof_daily(weekly_stage)
    stage = pd.Series(
        np.where(np.isnan(stage_vals.astype(float)), 0, stage_vals).astype(int),
        index=df.index,
    )

    _labels = {0: "Unknown", 1: "Stage 1 (Basing)", 2: "Stage 2 (Advancing)",
               3: "Stage 3 (Topping)", 4: "Stage 4 (Declining)"}
    stage_str = stage.map(_labels)

    return pd.DataFrame({
        "ma_10w": ma10,
        "ma_30w": ma30,
        "ma_40w": ma40,
        "high_13w": high_13w,
        "low_13w": low_13w,
        "mansfield_rs": mrs,
        "weinstein_stage": stage,
        "weinstein_stage_str": stage_str,
    }, index=df.index)


# ── Indicator pack ─────────────────────────────────────────────────────────────

def indicator_pack(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Calculate multiple technical indicators based on configuration.

    cfg shape: {"timeseries": {"indicators": {"ema": [20,50,200], "rsi": 14, ...}}}
    """
    out = df.copy()
    close = out["close"]
    adj = out.get("adj_close", close)
    high = out["high"]
    low = out["low"]
    vol = out["volume"]

    ind = cfg.get("timeseries", {}).get("indicators", {})

    # EMA
    for ln in ind.get("ema", [20, 50, 200]):
        out[f"ema_{ln}"] = ema(adj, ln)

    # MACD
    macdc = ind.get("macd", {"fast": 12, "slow": 26, "signal": 9})
    macd_ln = macd_line(adj, macdc["fast"], macdc["slow"])
    macd_sig = macd_signal_line(macd_ln, macdc["signal"])
    out["macd_line"] = macd_ln
    out["macd_signal"] = macd_sig
    out["macd_hist"] = macd_ln - macd_sig
    out["macd_hist_prev"] = out["macd_hist"].shift(1)

    macd_line_ema_span = ind.get("macd_line_ema_span", 9)
    mle = ema(macd_ln, macd_line_ema_span)
    out[f"macd_ema_{macd_line_ema_span}"] = mle
    out[f"macd_ema_{macd_line_ema_span}_prev"] = mle.shift(1)

    macd_hist_ema_span = ind.get("macd_hist_ema_span", 9)
    mhe = ema(out["macd_hist"], macd_hist_ema_span)
    out[f"macd_hist_ema_{macd_hist_ema_span}"] = mhe
    out[f"macd_hist_ema_{macd_hist_ema_span}_prev"] = mhe.shift(1)

    # RSI
    rsi_len = ind.get("rsi", 14)
    out["rsi_14"] = rsi(adj, rsi_len)
    out["rsi_delta_1"] = out["rsi_14"].diff()
    out["rsi_14_prev"] = out["rsi_14"].shift(1)

    rsi_ema_cfg = ind.get("rsi_ema_span", 9)
    rsi_ema_spans = sorted({int(s) for s in rsi_ema_cfg}) if isinstance(rsi_ema_cfg, (list, tuple, set)) else [int(rsi_ema_cfg)]
    for span in rsi_ema_spans:
        rv = ema(out["rsi_14"], span)
        out[f"rsi_ema_{span}"] = rv
        out[f"rsi_ema_{span}_prev"] = rv.shift(1)

    # ATR
    out["atr_14"] = atr(high, low, adj, ind.get("atr", 14))

    # Bollinger
    bb_cfg = ind.get("bollinger", {"len": 20, "stdev": 2.0})
    bb_mid, bb_up, bb_dn, bb_width = bollinger(adj, bb_cfg["len"], bb_cfg["stdev"])
    out["bb_mid_20"] = bb_mid
    out["bb_up_20"] = bb_up
    out["bb_dn_20"] = bb_dn
    out["bb_width_20"] = bb_width

    # ADX
    adx_df = adx(high, low, adj, ind.get("adx", 14))
    out = pd.concat([out, adx_df], axis=1)
    adx_ema_span = ind.get("adx_ema_span", 9)
    ae = ema(out["adx_14"], adx_ema_span)
    out[f"adx_ema_{adx_ema_span}"] = ae
    out[f"adx_ema_{adx_ema_span}_prev"] = ae.shift(1)

    # CMF
    cmf_len = ind.get("cmf", 20)
    out["cmf_20"] = chaikin_money_flow(high, low, close, vol, cmf_len)
    cmf_ema_span = ind.get("cmf_ema_span", 9)
    ce = ema(out["cmf_20"], cmf_ema_span)
    out[f"cmf_ema_{cmf_ema_span}"] = ce
    out[f"cmf_ema_{cmf_ema_span}_prev"] = ce.shift(1)

    # Ichimoku (optional)
    ichimoku_cfg = ind.get("ichimoku")
    if ichimoku_cfg:
        ichi = ichimoku(
            df,
            tenkan_len=int(ichimoku_cfg.get("tenkan", 9)),
            kijun_len=int(ichimoku_cfg.get("kijun", 26)),
            senkou_b_len=int(ichimoku_cfg.get("senkou_b", 52)),
            shift=int(ichimoku_cfg.get("shift", 26)),
        )
        out = pd.concat([out, ichi], axis=1)

    # Skew / ROC
    skew_len = ind.get("skew", 60)
    out["skew_60"] = rolling_skew(adj.pct_change(), skew_len)
    out["roc_20"] = rate_of_change(adj, ind.get("roc", 20))

    # Historical volatility
    for window in ind.get("hv", []):
        out[f"hv_{window}"] = historical_volatility(adj, int(window))

    # VWAP (optional)
    for window in ind.get("vwap", []):
        vw = vwap(high, low, close, vol, window=int(window))
        out[f"vwap_{window}"] = vw
        out[f"vwap_dev_{window}"] = vwap_deviation(close, vw)

    # Weekly (optional)
    weekly_cfg = ind.get("weekly", {})
    if weekly_cfg:
        has_date_col = 'date' in out.columns
        out_indexed = out.set_index('date') if has_date_col and not isinstance(out.index, pd.DatetimeIndex) else out
        for span in weekly_cfg.get("ema", []):
            wr = weekly_ema(out_indexed, int(span))
            out[f"weekly_ema_{span}"] = wr.values if hasattr(wr, 'values') else wr
        if weekly_cfg.get("price_position", False):
            wp = weekly_price_position(out_indexed)
            out["weekly_price_position"] = wp.values if hasattr(wp, 'values') else wp

    # Relative strength (optional)
    rs_cfg = ind.get("relative_strength", {})
    if rs_cfg:
        for benchmark in rs_cfg.get("benchmarks", []):
            bc = f"{benchmark.lower()}_close"
            if bc in out.columns:
                for w in rs_cfg.get("windows", [20]):
                    out[f"rs_{benchmark.lower()}_{w}"] = relative_strength(close, out[bc], int(w))

    # Divergence (optional)
    div_cfg = ind.get("divergence", {})
    if div_cfg:
        lb = div_cfg.get("lookback", 5)
        if "rsi_14" in out.columns:
            out[f"rsi_divergence_{lb}"] = rsi_divergence(close, out["rsi_14"], lb)
        if "macd_hist" in out.columns:
            out[f"macd_divergence_{lb}"] = macd_divergence(close, out["macd_hist"], lb)

    # Volume profile (optional)
    vp_cfg = ind.get("volume_profile", {})
    if vp_cfg:
        w = vp_cfg.get("window", 20)
        out["obv"] = obv(close, vol)
        out[f"volume_surge_{w}"] = volume_surge(vol, w, vp_cfg.get("surge_threshold", 2.0))
        out[f"volume_dryup_{w}"] = volume_dryup(vol, w, vp_cfg.get("dryup_threshold", 0.5))

    # Adaptive ATR (optional)
    aatr_cfg = ind.get("adaptive_atr", {})
    if aatr_cfg and "atr_14" in out.columns:
        pw = aatr_cfg.get("percentile_window", 252)
        bt = aatr_cfg.get("breakout_threshold", 2.0)
        out[f"atr_percentile_{pw}"] = atr_percentile(out["atr_14"], pw)
        out[f"volatility_breakout_{bt}x"] = volatility_breakout(close, out["atr_14"], bt)

    # Weinstein Stage Analysis (optional)
    ws_cfg = ind.get("weinstein", {})
    if ws_cfg:
        benchmark_col = ws_cfg.get("benchmark_close_col")
        bench = out[benchmark_col] if benchmark_col and benchmark_col in out.columns else None
        ws = weinstein_stage(
            out,
            benchmark_close=bench,
            ma10w=ws_cfg.get("ma10w", 10),
            ma30w=ws_cfg.get("ma30w", 30),
            ma40w=ws_cfg.get("ma40w", 40),
            range_weeks=ws_cfg.get("range_weeks", 13),
            rs_ma_weeks=ws_cfg.get("rs_ma_weeks", 52),
        )
        out = pd.concat([out, ws], axis=1)

    # Price action (optional)
    pa_cfg = ind.get("price_action", {})
    if pa_cfg:
        open_price = out["open"]
        swing_lb = pa_cfg.get("swing_lookback", 5)
        sh, sl = swing_high_low(high, low, swing_lb)
        out[f"swing_high_{swing_lb}"] = sh
        out[f"swing_low_{swing_lb}"] = sl
        if pa_cfg.get("trend_patterns", True):
            out[f"higher_highs_lows_{swing_lb}"] = higher_highs_lows(high, low, sh, sl)
            out[f"lower_highs_lows_{swing_lb}"] = lower_highs_lows(high, low, sh, sl)
        if pa_cfg.get("gaps", True):
            out["gap_size_pct"] = gap_size(open_price, close)
            out["gap_fill_pct"] = gap_fill_percentage(open_price, high, low, close)
        cw = pa_cfg.get("consolidation_window", 10)
        ct = pa_cfg.get("consolidation_threshold", 0.02)
        consol = price_consolidation(high, low, cw, ct)
        out[f"consolidation_{cw}"] = consol
        blb = pa_cfg.get("breakout_lookback", 3)
        out[f"breakout_{blb}"] = breakout_from_consolidation(close, high, low, consol, blb)
        if pa_cfg.get("trend_strength", True):
            es = pa_cfg.get("trend_ema_short", 20)
            el = pa_cfg.get("trend_ema_long", 50)
            tw = pa_cfg.get("trend_strength_window", 10)
            if f"ema_{es}" in out.columns and f"ema_{el}" in out.columns and "adx_14" in out.columns:
                out[f"trend_strength_{tw}"] = trend_strength(close, out[f"ema_{es}"], out[f"ema_{el}"], out["adx_14"], tw)
        if pa_cfg.get("support_resistance", True):
            tol = pa_cfg.get("sr_tolerance", 0.01)
            rt, st = support_resistance_touch(close, high, low, sh, sl, tol)
            out[f"resistance_touch_{swing_lb}"] = rt
            out[f"support_touch_{swing_lb}"] = st

    return out


# ── Convenience helper ─────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame, cfg: Optional[dict] = None) -> pd.DataFrame:
    """Apply the full indicator pack to an OHLCV DataFrame.

    cfg should match the strategy_config.yaml shape (timeseries.indicators).
    Defaults to EMA 20/50/200, RSI 14, MACD, ATR 14 if None.
    """
    if cfg is None:
        cfg = {
            "timeseries": {
                "indicators": {
                    "ema": [20, 50, 200],
                    "macd": {"fast": 12, "slow": 26, "signal": 9},
                    "rsi": 14,
                    "atr": 14,
                    "bollinger": {"len": 20, "stdev": 2.0},
                    "adx": 14,
                    "cmf": 20,
                    "hv": [10, 20, 30],
                }
            }
        }
    return indicator_pack(df, cfg)
