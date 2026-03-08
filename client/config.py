# client/config.py - Client configuration
import os
from typing import Dict, List

# ===================== VERSION =====================
VERSION = "1.0.0"
VERSION_NAME = "SelfTrade Client"

# ===================== SERVER =====================
SERVER_URL = os.getenv("SELFTRADE_SERVER_URL", "https://www.selftrade.site")
WS_URL = os.getenv("SELFTRADE_WS_URL", "wss://www.selftrade.site/ws/signals")

# ===================== SUPPORTED EXCHANGES =====================
SUPPORTED_EXCHANGES = ["binance", "mexc", "bybit"]
DEFAULT_EXCHANGE = "binance"

# ===================== TRADING PARAMETERS =====================
DEFAULT_RISK_PERCENT = 1.0  # 1% of balance per trade (safer for small accounts)
MAX_RISK_PERCENT = 10.0
MIN_TRADE_VALUE_USDT = 12.0  # Binance SPOT minimum notional is ~$5-10, use $12 for safety
MIN_FUTURES_TRADE_VALUE = 6.0  # Binance FUTURES minimum notional is ~$5, use $6 for safety
MAX_POSITION_PERCENT = 25.0  # Max 25% of portfolio in single position
MIN_CONFIDENCE = 0.60  # 60%+ edge required — anything less isn't worth the fees

# ===================== POSITION LIMITS (DYNAMIC BY BALANCE) =====================
# Tiny accounts can't afford 4 positions — fees eat everything.
# Scale positions with account size.
MAX_CONCURRENT_POSITIONS = 4   # Default (overridden by get_max_positions)
PREFER_FUTURES = True  # Prefer futures over spot (0.04% vs 0.1% fees)
MIN_CONFIDENCE_FOR_SPOT = 0.48

def get_max_positions(balance: float) -> int:
    """Dynamic max positions based on account balance.
    Under $100: 2 positions max (each needs $30+ to overcome fees)
    $100-$500: 3 positions
    $500-$2000: 4 positions
    $2000+: 6 positions
    """
    if balance < 100:
        return 2
    elif balance < 500:
        return 3
    elif balance < 2000:
        return 4
    else:
        return 6

# ===================== CIRCUIT BREAKERS (SAFETY) =====================
# Pause trading if drawdown exceeds threshold
MAX_DAILY_DRAWDOWN_PERCENT = 15.0  # Pause if lose 15% in 24h (was 10% - too strict for small accounts)
MAX_WEEKLY_DRAWDOWN_PERCENT = 30.0  # Pause if lose 30% in 7 days
CIRCUIT_BREAKER_COOLDOWN_HOURS = 6  # Wait 6 hours before resuming
MAX_CONSECUTIVE_LOSSES = 5  # Pause after 5 consecutive losses
MIN_WIN_RATE_THRESHOLD = 0.30  # Pause if win rate drops below 30% (min 10 trades)

# ===================== FEE CONFIGURATION =====================
# SPOT fees: ~0.1% taker (0.075% with BNB on Binance)
# FUTURES fees: ~0.04% taker — THIS IS WHY WE PREFER FUTURES
# Wrong fees = wrong P&L = fake "wins" that are actually losses after fees
EXCHANGE_FEES_SPOT: Dict[str, float] = {
    "binance": 0.00075,  # 0.075% with BNB discount
    "mexc": 0.001,       # 0.1%
    "bybit": 0.001,      # 0.1%
    "default": 0.001,
}

EXCHANGE_FEES_FUTURES: Dict[str, float] = {
    "binance": 0.0004,   # 0.04% taker
    "mexc": 0.0004,      # 0.04% taker
    "bybit": 0.00055,    # 0.055% taker
    "default": 0.0005,
}

# Legacy compat
EXCHANGE_FEES: Dict[str, float] = EXCHANGE_FEES_SPOT

ROUND_TRIP_FEE_MULTIPLIER = 2
SLIPPAGE_BUFFER = 0.0003  # 0.03% (was 0.05%)

def get_trading_fee(exchange: str, market: str = "spot") -> float:
    """Get trading fee. market='spot' or 'futures'."""
    if market == "futures":
        return EXCHANGE_FEES_FUTURES.get(exchange.lower(), EXCHANGE_FEES_FUTURES["default"])
    return EXCHANGE_FEES_SPOT.get(exchange.lower(), EXCHANGE_FEES_SPOT["default"])

def get_round_trip_cost(exchange: str, market: str = "spot") -> float:
    """Get total round trip cost (fees + slippage)"""
    fee = get_trading_fee(exchange, market)
    return (fee * ROUND_TRIP_FEE_MULTIPLIER) + SLIPPAGE_BUFFER

# ===================== PRECISION RULES =====================
# Exchange-specific precision rules for quantity/price
PRECISION_RULES: Dict[str, Dict[str, Dict[str, int]]] = {
    "binance": {
        "BTCUSDT": {"price": 2, "qty": 5},
        "ETHUSDT": {"price": 2, "qty": 4},
        "BNBUSDT": {"price": 2, "qty": 3},
        "ADAUSDT": {"price": 5, "qty": 1},
        "SOLUSDT": {"price": 2, "qty": 2},
        "XRPUSDT": {"price": 4, "qty": 1},
        "DOGEUSDT": {"price": 5, "qty": 0},
        "AVAXUSDT": {"price": 2, "qty": 2},
        "LINKUSDT": {"price": 2, "qty": 2},
        "LTCUSDT": {"price": 2, "qty": 3},
        "TRXUSDT": {"price": 5, "qty": 0},
        "SHIBUSDT": {"price": 8, "qty": 0},
        "PEPEUSDT": {"price": 10, "qty": 0},
        "SUIUSDT": {"price": 4, "qty": 1},
        "NEARUSDT": {"price": 3, "qty": 1},
        "APTUSDT": {"price": 3, "qty": 2},
        "TONUSDT": {"price": 3, "qty": 2},
        "INJUSDT": {"price": 3, "qty": 2},
        "DOTUSDT": {"price": 3, "qty": 2},
        "ARBUSDT": {"price": 4, "qty": 1},
        "OPUSDT":  {"price": 4, "qty": 1},
        "FETUSDT": {"price": 5, "qty": 0},
        "RENDERUSDT": {"price": 4, "qty": 1},
        "WLDUSDT": {"price": 4, "qty": 1},
        "BONKUSDT": {"price": 9, "qty": 0},
        "FLOKIUSDT": {"price": 8, "qty": 0},
        "WIFUSDT": {"price": 4, "qty": 1},
        "DEFAULT": {"price": 6, "qty": 2},
    },
    "mexc": {
        "BTCUSDT": {"price": 2, "qty": 6},
        "ETHUSDT": {"price": 2, "qty": 5},
        "XRPUSDT": {"price": 4, "qty": 1},
        "SOLUSDT": {"price": 2, "qty": 3},
        "DOGEUSDT": {"price": 6, "qty": 0},
        "ADAUSDT": {"price": 5, "qty": 1},
        "AVAXUSDT": {"price": 2, "qty": 3},
        "LINKUSDT": {"price": 3, "qty": 2},
        "LTCUSDT": {"price": 2, "qty": 4},
        "TRXUSDT": {"price": 5, "qty": 0},
        "SHIBUSDT": {"price": 10, "qty": 0},
        "PEPEUSDT": {"price": 12, "qty": 0},
        "SUIUSDT": {"price": 4, "qty": 2},
        "NEARUSDT": {"price": 4, "qty": 1},
        "APTUSDT": {"price": 3, "qty": 3},
        "TONUSDT": {"price": 4, "qty": 2},
        "INJUSDT": {"price": 3, "qty": 3},
        "BNBUSDT": {"price": 2, "qty": 4},
        "DOTUSDT": {"price": 3, "qty": 2},
        "ARBUSDT": {"price": 4, "qty": 1},
        "OPUSDT":  {"price": 4, "qty": 1},
        "FETUSDT": {"price": 5, "qty": 0},
        "RENDERUSDT": {"price": 4, "qty": 1},
        "WLDUSDT": {"price": 4, "qty": 1},
        "BONKUSDT": {"price": 9, "qty": 0},
        "FLOKIUSDT": {"price": 8, "qty": 0},
        "WIFUSDT": {"price": 5, "qty": 1},
        "DEFAULT": {"price": 6, "qty": 3},
    },
    "bybit": {
        "BTCUSDT": {"price": 2, "qty": 6},
        "ETHUSDT": {"price": 2, "qty": 5},
        "XRPUSDT": {"price": 4, "qty": 1},
        "SOLUSDT": {"price": 2, "qty": 3},
        "DOGEUSDT": {"price": 6, "qty": 0},
        "ADAUSDT": {"price": 5, "qty": 1},
        "AVAXUSDT": {"price": 2, "qty": 3},
        "LINKUSDT": {"price": 3, "qty": 2},
        "LTCUSDT": {"price": 2, "qty": 4},
        "TRXUSDT": {"price": 5, "qty": 0},
        "SHIBUSDT": {"price": 10, "qty": 0},
        "PEPEUSDT": {"price": 12, "qty": 0},
        "SUIUSDT": {"price": 4, "qty": 2},
        "NEARUSDT": {"price": 4, "qty": 1},
        "APTUSDT": {"price": 3, "qty": 3},
        "TONUSDT": {"price": 4, "qty": 2},
        "INJUSDT": {"price": 3, "qty": 3},
        "BNBUSDT": {"price": 2, "qty": 4},
        "DOTUSDT": {"price": 3, "qty": 2},
        "ARBUSDT": {"price": 4, "qty": 1},
        "OPUSDT":  {"price": 4, "qty": 1},
        "FETUSDT": {"price": 5, "qty": 0},
        "RENDERUSDT": {"price": 4, "qty": 1},
        "WLDUSDT": {"price": 4, "qty": 1},
        "BONKUSDT": {"price": 9, "qty": 0},
        "FLOKIUSDT": {"price": 8, "qty": 0},
        "WIFUSDT": {"price": 5, "qty": 1},
        "DEFAULT": {"price": 6, "qty": 3},
    }
}

# ===================== SUPPORTED PAIRS =====================
# Must mirror server/config.py SUPPORTED_PAIRS exactly
SUPPORTED_PAIRS: List[str] = [
    # Tier 1: Highest liquidity
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "DOGEUSDT",
    # Tier 2: Established alts
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT", "DOTUSDT",
    "SUIUSDT", "NEARUSDT", "APTUSDT", "INJUSDT",
    # Tier 3: Newer / narrative tokens
    "ARBUSDT", "OPUSDT", "FETUSDT", "RENDERUSDT", "WLDUSDT",
    # Tier 4: High-volatility meme coins
    "PEPEUSDT", "SHIBUSDT", "WIFUSDT", "BONKUSDT", "FLOKIUSDT",
]

# ===================== EXCHANGE-SPECIFIC UNSUPPORTED PAIRS =====================
# Pairs that are NOT supported or have issues on specific exchanges
UNSUPPORTED_PAIRS: Dict[str, List[str]] = {
    "mexc": [
        "APTUSDT",    # Not listed on MEXC
        "WLDUSDT",    # Not listed on MEXC
    ],
    "bybit": [
        "WLDUSDT",    # Not listed on Bybit
    ],
    "binance": [],
}

# ===================== EXCHANGE SYMBOL MAPPING =====================
# Some exchanges use different symbol names
SYMBOL_MAPPING: Dict[str, Dict[str, str]] = {
    "mexc": {
        # "TONUSDT": "TONCOINUSDT",  # Uncomment if MEXC uses TONCOIN
    },
    "bybit": {},
    "binance": {},
}

def is_pair_supported(exchange: str, pair: str) -> bool:
    """Check if a trading pair is supported on the exchange"""
    unsupported = UNSUPPORTED_PAIRS.get(exchange.lower(), [])
    return pair.upper() not in unsupported

def get_exchange_symbol(exchange: str, pair: str) -> str:
    """Get the correct symbol name for an exchange"""
    mapping = SYMBOL_MAPPING.get(exchange.lower(), {})
    return mapping.get(pair.upper(), pair.upper())

# ===================== UI SETTINGS =====================
WINDOW_TITLE = f"SelfTrade Desktop Client v{VERSION}"
WINDOW_SIZE = (1200, 800)
UPDATE_INTERVAL_MS = 5000  # 5 seconds
LOG_MAX_LINES = 1000

# ===================== LOGGING =====================
LOG_FILE = "selftrade_client.log"
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_precision(exchange: str, symbol: str) -> Dict[str, int]:
    """Get precision rules for a symbol on an exchange"""
    exchange_rules = PRECISION_RULES.get(exchange.lower(), PRECISION_RULES["binance"])
    return exchange_rules.get(symbol.upper(), exchange_rules.get("DEFAULT", {"price": 6, "qty": 2}))
