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
    "AMD", "AVGO", "ARM", "MRVL", "ON", "QCOM", "MU",
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


def tech_symbols() -> list[str]:
    return sorted(TECH_UNIVERSE)


def sp500_symbols(date: str = "2026-06-13") -> list[str]:
    """S&P 500 constituents — tries live fetch, falls back to curated subset."""
    try:
        import sys
        from pathlib import Path
        _stock_root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(_stock_root))
        from research.src.regime_data import _get_sp500_constituents
        return sorted(_get_sp500_constituents(date))
    except Exception:
        return sorted(SP500_UNIVERSE)
