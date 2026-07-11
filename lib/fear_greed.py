"""CNN Fear & Greed Index — fetch + local cache.

Pulls the composite score and its 7 sub-indicators from CNN's (undocumented)
dataviz endpoint and caches them to ``lib/data/fear_greed/`` as parquet, so the
notebooks read a stable local copy and only hit the network on an explicit
refresh.

The endpoint bot-blocks plain requests (HTTP 418), so browser-like headers are
required; it may still rate-limit or change without notice. ``fetch`` raises on
failure — callers should fall back to the cached parquet.

Composite ``score`` is 0-100 (0 = extreme fear, 100 = extreme greed). Each
sub-indicator's ``y`` is its RAW underlying value (VIX level, S&P price, put/call
ratio, ...), NOT a 0-100 score — only the composite is normalized. Each series
also carries CNN's categorical ``rating`` ('extreme fear' … 'extreme greed').
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

# Appending /YYYY-MM-DD returns all history from that date forward. CNN retains
# data back to ~mid-2020 (earlier dates 500). Use a safe floor to pull the full
# available history; CNN clamps to what it actually has.
EARLIEST = "2020-07-15"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Origin": "https://www.cnn.com",
}

CACHE_DIR = Path(__file__).resolve().parent / "data" / "fear_greed"
INDEX_FILE = CACHE_DIR / "fear_greed_index.parquet"       # composite, 0-100
COMPONENTS_FILE = CACHE_DIR / "fear_greed_components.parquet"  # 7 sub-indicators (raw)

# CNN's sub-indicator keys -> friendly labels
COMPONENTS = {
    "market_momentum_sp500": "Market Momentum",
    "stock_price_strength": "Stock Price Strength",
    "stock_price_breadth": "Stock Price Breadth",
    "put_call_options": "Put/Call Options",
    "market_volatility_vix": "Market Volatility",
    "junk_bond_demand": "Junk Bond Demand",
    "safe_haven_demand": "Safe Haven Demand",
}

# CNN's verbatim subtitle for each component (from the site copy — not in the
# JSON feed). Kept exactly as CNN renders them.
DESCRIPTIONS = {
    "Market Momentum": "S&P 500 and its 125-day moving average",
    "Stock Price Strength": "Net new 52-week highs and lows on the NYSE",
    "Stock Price Breadth": "McClellan Volume Summation Index",
    "Put/Call Options": "5-day average put/call ratio",
    "Market Volatility": "VIX and its 50-day moving average",
    "Safe Haven Demand": "Difference in 20-day stock and bond returns",
    "Junk Bond Demand": "Yield spread: junk bonds vs. investment grade",
}

# CNN's y-axis presentation per component: (d3 tickformat, tick suffix). The feed
# values are already in display units (junk-bond 1.30 = 1.30%, not 0.013), so the
# percent panels use a plain number format + a '%' suffix — NOT d3 '%' (which would
# ×100).
AXIS_FORMAT = {
    "Market Momentum": (",.0f", ""),
    "Stock Price Strength": (".2f", "%"),
    "Stock Price Breadth": (",.0f", ""),
    "Put/Call Options": (".2f", ""),
    "Market Volatility": (".2f", ""),
    "Safe Haven Demand": (".2f", "%"),
    "Junk Bond Demand": (".2f", "%"),
}

# CNN's top/bottom in-chart annotations for the diverging panels.
BAND_LABELS = {
    "Stock Price Breadth": ("Market breadth strong", "Market breadth weak"),
    "Safe Haven Demand": ("Stocks outperforming Bonds", "Bonds outperforming Stocks"),
}

# Reference-MA series CNN overlays on a panel (indicator=blue, MA=orange, per CNN):
# parent key -> (ref feed key, indicator legend label, MA legend label)
_REFERENCE = {
    "market_momentum_sp500": ("market_momentum_sp125", "S&P 500", "125-day moving average"),
    "market_volatility_vix": ("market_volatility_vix_50", "VIX", "50-day moving average"),
}


def _get_json(start: str | None = None, timeout: float = 30.0) -> dict:
    url = f"{_URL}/{start}" if start else _URL
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _hist_frame(points: list, value_col: str) -> pd.DataFrame:
    """CNN historical [{x: ms, y: val, rating: str}] -> tidy daily DataFrame."""
    if not points:
        return pd.DataFrame(columns=["date", value_col, "rating"])
    df = pd.DataFrame(points)
    df["date"] = pd.to_datetime(df["x"], unit="ms", utc=True).dt.tz_localize(None).dt.normalize()
    df = df.rename(columns={"y": value_col})[["date", value_col, "rating"]]
    return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)


def fetch(save: bool = True, start: str | None = EARLIEST) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch the composite index + 7 components; optionally cache to parquet.

    ``start`` (YYYY-MM-DD) pulls all history from that date forward. Defaults to
    ``EARLIEST`` so the cache holds CNN's full available history (~mid-2020 on).
    Pass ``start=None`` for CNN's default ~1-year window (a lighter daily refresh).

    Returns (index_df, components_df).
      index_df       : date, score (0-100), rating
      components_df  : date, component, value (raw), point_rating,
                       node_score (0-100), node_rating

    IMPORTANT: each historical point's ``point_rating`` is UNRELIABLE — CNN tags
    it against the raw value with coarse/lagging buckets, so it often disagrees
    with what the site shows (e.g. Put/Call point_rating='extreme fear' while the
    site says 'greed'). The AUTHORITATIVE current reading is the NODE-level
    ``node_score`` (0-100) + ``node_rating`` — that's what CNN displays. Use those
    for labels/colors, and treat ``value`` (the raw underlying) as the line only.

    Raises on network / parse failure (the endpoint bot-blocks aggressively).
    """
    d = _get_json(start=start)

    index_df = _hist_frame(d["fear_and_greed_historical"]["data"], "score")

    frames = []
    for key, label in COMPONENTS.items():
        node = d.get(key, {})
        f = _hist_frame(node.get("data", []), "value")
        if f.empty:
            continue
        ref = _REFERENCE.get(key)
        # main indicator line — CNN labels it (e.g. 'S&P 500', 'VIX') on the MA panels
        main_label = ref[1] if ref else "indicator"
        f = f.rename(columns={"rating": "point_rating"})
        f.insert(1, "component", label)
        f["series"] = main_label
        # node-level current reading (the authoritative one CNN shows), constant
        # per component so it rides along on every row.
        f["node_score"] = node.get("score")
        f["node_rating"] = node.get("rating")
        frames.append(f)

        # CNN overlays a reference MA (orange) on some panels — 2nd series.
        if ref:
            ref_key, _main, ma_label = ref
            rf = _hist_frame(d.get(ref_key, {}).get("data", []), "value")
            if not rf.empty:
                rf = rf.rename(columns={"rating": "point_rating"})
                rf.insert(1, "component", label)
                rf["series"] = ma_label
                rf["node_score"] = node.get("score")
                rf["node_rating"] = node.get("rating")
                frames.append(rf)

    comp_df = (pd.concat(frames, ignore_index=True) if frames else
               pd.DataFrame(columns=["date", "component", "value", "point_rating",
                                     "series", "node_score", "node_rating"]))

    if save:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # MERGE with any existing cache so a daily refresh never loses history if
        # CNN's returned window shrinks — union on the natural keys, new rows win.
        index_df = _merge_cache(INDEX_FILE, index_df, ["date"])
        comp_df = _merge_cache(COMPONENTS_FILE, comp_df, ["date", "component", "series"])
        index_df.to_parquet(INDEX_FILE, index=False)
        comp_df.to_parquet(COMPONENTS_FILE, index=False)

    return index_df, comp_df


def _merge_cache(path: Path, fresh: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Union freshly-fetched rows with the on-disk cache, keeping the FRESH row on
    a key collision (so today's values update, older history is preserved)."""
    if not path.exists() or fresh.empty:
        return fresh.sort_values(keys).reset_index(drop=True)
    old = pd.read_parquet(path)
    old = old[[c for c in old.columns if c in fresh.columns]]
    combined = pd.concat([old, fresh], ignore_index=True)
    combined = combined.drop_duplicates(subset=keys, keep="last")
    return combined.sort_values(keys).reset_index(drop=True)


def load(refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load the cached index + components; fetch if missing or ``refresh=True``.

    Falls back to the cache if a refresh fetch fails (so a flaky endpoint never
    leaves you with nothing). Returns (index_df, components_df); either may be
    empty if there's no cache and the fetch failed.
    """
    have_cache = INDEX_FILE.exists() and COMPONENTS_FILE.exists()
    if refresh or not have_cache:
        try:
            return fetch(save=True)
        except Exception:
            if not have_cache:
                raise
            # refresh failed but we have a cache — use it
    return pd.read_parquet(INDEX_FILE), pd.read_parquet(COMPONENTS_FILE)


def rating_color(rating: str) -> str:
    """Map a CNN rating string to a color (fear = red … greed = green)."""
    return {
        "extreme fear": "#c0392b",
        "fear": "#e67e22",
        "neutral": "#f1c40f",
        "greed": "#27ae60",
        "extreme greed": "#145a32",
    }.get(str(rating).lower(), "#7f8c8d")


def rating_badge(rating: str) -> tuple[str, str]:
    """CNN-style badge colors for a rating: (border/text color, light fill).

    Matches the rounded pill CNN shows top-right of each panel — a saturated
    border+text over a very light tint of the same hue.
    """
    fg = {
        "extreme fear": "#c0392b",
        "fear": "#d97b2b",
        "neutral": "#b8960b",
        "greed": "#1e874e",
        "extreme greed": "#145a32",
    }.get(str(rating).lower(), "#666666")
    bg = {
        "extreme fear": "#f7e4e1",
        "fear": "#fbeede",
        "neutral": "#fbf4d6",
        "greed": "#e0f0e7",
        "extreme greed": "#dcebe1",
    }.get(str(rating).lower(), "#eeeeee")
    return fg, bg
