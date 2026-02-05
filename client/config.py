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
MIN_CONFIDENCE = 0.55  # Minimum confidence to execute trade (must match server)

# ===================== POSITION LIMITS (SMALL ACCOUNT OPTIMIZATION) =====================
# For accounts <$200, limit positions to reduce fee drag
MAX_CONCURRENT_POSITIONS = 3  # Max 3 positions at a time
PREFER_FUTURES = True  # Prefer futures over spot (0.04% vs 0.1% fees)
MIN_CONFIDENCE_FOR_SPOT = 0.60  # Only open spot if confidence >60%

# ===================== CIRCUIT BREAKERS (SAFETY) =====================
# Pause trading if drawdown exceeds threshold
MAX_DAILY_DRAWDOWN_PERCENT = 10.0  # Pause if lose 10% in 24h
MAX_WEEKLY_DRAWDOWN_PERCENT = 30.0  # Pause if lose 30% in 7 days
CIRCUIT_BREAKER_COOLDOWN_HOURS = 6  # Wait 6 hours before resuming
MAX_CONSECUTIVE_LOSSES = 5  # Pause after 5 consecutive losses
MIN_WIN_RATE_THRESHOLD = 0.30  # Pause if win rate drops below 30% (min 10 trades)

# ===================== FEE CONFIGURATION =====================
# Exchange trading fees (maker/taker) - used for P&L and position sizing
EXCHANGE_FEES: Dict[str, float] = {
    "binance": 0.001,   # 0.1% per trade
    "mexc": 0.001,      # 0.1% per trade (can be lower with MX token)
    "bybit": 0.001,     # 0.1% per trade
    "default": 0.001,
}
# Round trip fee = entry fee + exit fee
ROUND_TRIP_FEE_MULTIPLIER = 2  # Buy + Sell = 2x single fee

# Slippage buffer for market orders (added to fees for safety)
SLIPPAGE_BUFFER = 0.0005  # 0.05% slippage buffer

def get_trading_fee(exchange: str) -> float:
    """Get trading fee for exchange"""
    return EXCHANGE_FEES.get(exchange.lower(), EXCHANGE_FEES["default"])

def get_round_trip_cost(exchange: str) -> float:
    """Get total round trip cost (fees + slippage)"""
    fee = get_trading_fee(exchange)
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
        "WIFUSDT": {"price": 5, "qty": 1},
        "DEFAULT": {"price": 6, "qty": 3},
    }
}

# ===================== SUPPORTED PAIRS =====================
# High-liquidity pairs that work reliably on Binance, MEXC, and Bybit
SUPPORTED_PAIRS: List[str] = [
    "BTCUSDT",    # Bitcoin - highest liquidity
    "ETHUSDT",    # Ethereum - second highest
    "XRPUSDT",    # Ripple - high volume
    "SOLUSDT",    # Solana - very popular
    "DOGEUSDT",   # Dogecoin - high volume meme
    "ADAUSDT",    # Cardano - established
    "AVAXUSDT",   # Avalanche - popular L1
    "LINKUSDT",   # Chainlink - top oracle
    "LTCUSDT",    # Litecoin - established
    "TRXUSDT",    # Tron - high volume
    "SHIBUSDT",   # Shiba Inu - popular meme
    "PEPEUSDT",   # Pepe - trending meme
    "SUIUSDT",    # Sui - newer L1
    "NEARUSDT",   # Near Protocol
    "APTUSDT",    # Aptos - newer L1
    "TONUSDT",    # TON - Telegram coin, very high volume
    "INJUSDT",    # Injective - popular DeFi
    "WIFUSDT",    # dogwifhat - trending meme, high volume
]

# ===================== EXCHANGE-SPECIFIC UNSUPPORTED PAIRS =====================
# Pairs that are NOT supported or have issues on specific exchanges
UNSUPPORTED_PAIRS: Dict[str, List[str]] = {
    "mexc": [
        "BTCUSDT",    # MEXC spot API marks BTC/USDT as inactive - use other pairs
        "SHIBUSDT",   # Often has API issues on MEXC
        "PEPEUSDT",   # Low liquidity / API issues
        "WIFUSDT",    # May not be listed or have issues
        "APTUSDT",    # Check availability
    ],
    "bybit": [],
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
