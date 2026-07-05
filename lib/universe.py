"""Shared symbol universe for the stock monorepo.

All projects import from here:
    from lib.universe import TECH_UNIVERSE, IV_WATCHLIST, MY_WATCHLIST
    from lib.universe import tech_symbols, sp500_symbols
"""

# ── IV / options watchlist (from ibkr/src/config.py) ─────────────────────────
IV_WATCHLIST: list[str] = [
    "NVDA", "SPY", "QQQ", "AMZN", "GOOGL", "AAPL", "MSFT", "META", "MRVL",
    "JPM", "TSLA", "MSTR", "IBIT", "CRCL", "TSEM", "AVGO", "AMD", "APLD",
    "PLTR", "HOOD", "TSM", "COIN", "GS", "CAT", "LLY", "INTC", "MRNA",
    "WMT", "GOOG",
]

# ── Personal watchlist (from research/stratlab/config/watchlist_stratlab.py) ──
MY_WATCHLIST: list[str] = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA",
    # Semis
    "AMD", "AVGO", "ARM", "MRVL", "ON", "QCOM", "MU", "FOTO", "TSEM",
    # Software / security
    "CRWD", "PANW", "PLTR", "APP", "DDOG", "FTNT", "ZS",
    # High-beta / crypto-adjacent
    "MSTR", "COIN", "HOOD",
    # ETFs
    "SPY", "QQQ", "TQQQ",
]

# ── Tech universe — QQQ/Nasdaq-100 tech names (from stratlab/src/universe.py) ─
TECH_UNIVERSE: dict[str, str] = {
    # Megacap platforms
    "AAPL": "hardware",
    "MSFT": "software",
    "NVDA": "semis",
    "AVGO": "semis",
    "META": "internet",
    "GOOGL": "internet",
    "AMZN": "internet",
    "NFLX": "internet",
    # Semiconductors & equipment
    "AMD": "semis",
    "QCOM": "semis",
    "TXN": "semis",
    "INTC": "semis",
    "MU": "semis",
    "ADI": "semis",
    "LRCX": "semi-equip",
    "KLAC": "semi-equip",
    "AMAT": "semi-equip",
    "ASML": "semi-equip",
    "NXPI": "semis",
    "MRVL": "semis",
    "MCHP": "semis",
    "ON": "semis",
    "ARM": "semis",
    "GFS": "semis",
    # Software & security
    "ADBE": "software",
    "INTU": "software",
    "ADSK": "software",
    "CDNS": "software",
    "SNPS": "software",
    "WDAY": "software",
    "TEAM": "software",
    "PANW": "security",
    "CRWD": "security",
    "FTNT": "security",
    "ZS": "security",
    "DDOG": "software",
    "APP": "software",
    "PLTR": "software",
    "MSTR": "software",
    "SHOP": "software",
    "CTSH": "it-services",
    # Internet / consumer tech
    "BKNG": "internet",
    "ABNB": "internet",
    "DASH": "internet",
    "MELI": "internet",
    "PDD": "internet",
    "TTD": "internet",
    "EA": "gaming",
    "TTWO": "gaming",
    # Hardware / networking
    "CSCO": "networking",
    "SMCI": "hardware",
    "TSLA": "ev-tech",
}

BENCHMARKS: list[str] = ["SPY", "QQQ"]

# ── S&P 500 curated subset (from stratlab/src/universe.py) ───────────────────
SP500_UNIVERSE: dict[str, str] = {
    # Financials
    "JPM": "financials", "BAC": "financials", "WFC": "financials",
    "GS": "financials", "MS": "financials", "BLK": "financials",
    "SCHW": "financials", "AXP": "financials", "COF": "financials",
    "USB": "financials", "PNC": "financials", "TFC": "financials",
    "SPGI": "financials", "MCO": "financials", "ICE": "financials",
    "CME": "financials", "CB": "financials", "AON": "financials",
    # Healthcare
    "UNH": "healthcare", "JNJ": "healthcare", "LLY": "healthcare",
    "ABBV": "healthcare", "MRK": "healthcare", "TMO": "healthcare",
    "ABT": "healthcare", "DHR": "healthcare", "BMY": "healthcare",
    "AMGN": "healthcare", "GILD": "healthcare", "ISRG": "healthcare",
    "SYK": "healthcare", "MDT": "healthcare", "CI": "healthcare",
    "HCA": "healthcare", "ELV": "healthcare", "CVS": "healthcare",
    # Consumer Discretionary
    "HD": "cons-disc", "MCD": "cons-disc", "NKE": "cons-disc",
    "SBUX": "cons-disc", "TJX": "cons-disc", "LOW": "cons-disc",
    "GM": "cons-disc", "F": "cons-disc", "MAR": "cons-disc",
    "HLT": "cons-disc", "YUM": "cons-disc", "CMG": "cons-disc",
    "ORLY": "cons-disc", "AZO": "cons-disc", "ROST": "cons-disc",
    # Consumer Staples
    "WMT": "cons-staples", "PG": "cons-staples", "KO": "cons-staples",
    "PEP": "cons-staples", "COST": "cons-staples", "PM": "cons-staples",
    "MO": "cons-staples", "CL": "cons-staples", "KMB": "cons-staples",
    "GIS": "cons-staples",
    # Industrials
    "CAT": "industrials", "HON": "industrials", "UPS": "industrials",
    "BA": "industrials", "RTX": "industrials", "LMT": "industrials",
    "DE": "industrials", "GE": "industrials", "MMM": "industrials",
    "ETN": "industrials", "EMR": "industrials", "ITW": "industrials",
    "PH": "industrials", "ROK": "industrials", "CMI": "industrials",
    "FDX": "industrials", "CSX": "industrials", "UNP": "industrials",
    "NSC": "industrials",
    # Energy
    "XOM": "energy", "CVX": "energy", "COP": "energy",
    "EOG": "energy", "SLB": "energy", "MPC": "energy",
    "PSX": "energy", "VLO": "energy", "OXY": "energy", "HAL": "energy",
    # Utilities
    "NEE": "utilities", "SO": "utilities", "DUK": "utilities",
    "AEP": "utilities", "EXC": "utilities", "SRE": "utilities",
    "PCG": "utilities", "XEL": "utilities", "ED": "utilities",
    # Real Estate
    "PLD": "realestate", "AMT": "realestate", "EQIX": "realestate",
    "SPG": "realestate", "O": "realestate", "CCI": "realestate",
    "WELL": "realestate", "AVB": "realestate", "EQR": "realestate",
    # Materials
    "LIN": "materials", "APD": "materials", "ECL": "materials",
    "SHW": "materials", "FCX": "materials", "NEM": "materials",
    "NUE": "materials", "VMC": "materials", "MLM": "materials",
    # Communication Services (non-tech)
    "DIS": "comm-services", "CMCSA": "comm-services",
    "T": "comm-services", "VZ": "comm-services", "CHTR": "comm-services",
    # Tech overlap with TECH_UNIVERSE
    "AAPL": "tech", "MSFT": "tech", "NVDA": "tech", "AVGO": "tech",
    "GOOGL": "tech", "META": "tech", "AMZN": "tech", "NFLX": "tech",
    "TSLA": "tech", "BKNG": "tech",
}


# ── Nasdaq-100 constituents (as of 2026-Q2) ──────────────────────────────────
# Source: Nasdaq.com / QQQ ETF holdings. Update quarterly.
# Used as the expanded evaluation universe for stratlab cross-universe runs.
QQQ_UNIVERSE: list[str] = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "GOOGL", "GOOG", "AVGO", "COST",
    "NFLX", "AMD", "PEP", "CSCO", "ADBE", "TMUS", "TXN", "QCOM", "ISRG", "INTU",
    "AMGN", "AMAT", "HON", "BKNG", "MU", "LRCX", "VRTX", "PANW", "ADP", "SBUX",
    "GILD", "KLAC", "MELI", "MDLZ", "REGN", "ADI", "CRWD", "CDNS", "SNPS", "MAR",
    "FTNT", "PYPL", "ORLY", "MNST", "CEG", "CTAS", "DASH", "ABNB", "MRVL", "TTD",
    "WDAY", "PCAR", "KDP", "FAST", "NXPI", "DXCM", "EXC", "TEAM", "ROST", "GEHC",
    "VRSK", "XEL", "ODFL", "IDXX", "FANG", "BKR", "KHC", "EA", "DDOG", "ZS",
    "CTSH", "LULU", "ON", "ANSS", "GFS", "MCHP", "WBD", "BIIB", "ILMN", "TTWO",
    "SIRI", "DLTR", "SMCI", "APP", "PLTR", "MSTR", "ARM", "ASML", "ADI", "MDB",
    "OKTA", "ZM", "BILL", "GTLB", "NET", "SNOW", "COIN", "SHOP", "NTNX", "IOT",
]


def tech_symbols() -> list[str]:
    return sorted(TECH_UNIVERSE)


def qqq_symbols() -> list[str]:
    """Current Nasdaq-100 constituents. Tries live fetch via yfinance, falls back to hardcoded list."""
    try:
        import yfinance as yf
        import pandas as pd
        # yfinance only exposes top 10 holdings for ETFs; use a Wikipedia scrape approach
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            storage_options={"User-Agent": "Mozilla/5.0"},
        )
        for t in tables:
            cols = [str(c).lower() for c in t.columns]
            if any("ticker" in c or "symbol" in c for c in cols):
                col = next(c for c, n in zip(t.columns, cols) if "ticker" in n or "symbol" in n)
                syms = t[col].dropna().str.strip().tolist()
                syms = [s for s in syms if s.isalpha() and 1 <= len(s) <= 5]
                if len(syms) >= 90:
                    return sorted(set(syms))
    except Exception:
        pass
    return sorted(set(QQQ_UNIVERSE))


def sp500_symbols(date: str = "2026-06-13") -> list[str]:
    """S&P 500 constituents — reads from lib/data/sp500/, falls back to curated subset.

    Data source: fja05680/sp500 (https://github.com/fja05680/sp500).
    Update by replacing the CSVs in lib/data/sp500/.
    """
    import glob
    import pandas as pd
    from pathlib import Path
    _sp500_dir = Path(__file__).resolve().parent / "data" / "sp500"
    csv_files = glob.glob(str(_sp500_dir / "S&P 500 Historical Components & Changes*.csv"))
    if not csv_files:
        return sorted(SP500_UNIVERSE)
    try:
        best_csv = max(csv_files, key=lambda p: pd.read_csv(p, index_col="date").index[-1])
        df = pd.read_csv(best_csv, index_col="date")
        snap = df[df.index <= date]
        if snap.empty:
            return sorted(SP500_UNIVERSE)
        tickers = snap.iloc[-1]["tickers"].split(",")
        return sorted(t.strip().replace(".", "-") for t in tickers if t.strip())
    except Exception:
        return sorted(SP500_UNIVERSE)
