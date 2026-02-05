# client/services/exchange_client.py - CCXT wrapper for exchanges
import ccxt
import logging
from typing import Optional, Dict, Any, List
from decimal import Decimal, ROUND_DOWN

from client.config import SUPPORTED_EXCHANGES, get_precision

logger = logging.getLogger(__name__)


class ExchangeClient:
    """CCXT wrapper for exchange operations (spot + futures)"""

    def __init__(self, exchange_name: str = "binance"):
        self.exchange_name = exchange_name.lower()
        self.exchange: Optional[ccxt.Exchange] = None
        self.futures_exchange: Optional[ccxt.Exchange] = None  # Separate instance for futures
        self.connected = False
        self.futures_connected = False
        self.futures_enabled = False
        self.markets: Dict = {}
        self.futures_markets: Dict = {}
        self.balance: Dict = {}
        self.futures_balance: Dict = {}

    def connect(self, api_key: str, api_secret: str, testnet: bool = False) -> bool:
        """Connect to exchange with credentials"""
        if self.exchange_name not in SUPPORTED_EXCHANGES:
            raise ValueError(f"Unsupported exchange: {self.exchange_name}")

        try:
            exchange_class = getattr(ccxt, self.exchange_name)
            config = {
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot',
                    'adjustForTimeDifference': True,
                    'recvWindow': 60000,
                    'warnOnFetchOpenOrdersWithoutSymbol': False,
                }
            }

            # MEXC-specific configuration
            if self.exchange_name == 'mexc':
                config['options'].update({
                    'defaultType': 'spot',
                    'broker': 'ccxt',  # Required for some MEXC endpoints
                })

            if testnet:
                config['sandbox'] = True

            self.exchange = exchange_class(config)

            # Test connection
            self.balance = self.exchange.fetch_balance()
            self.markets = self.exchange.load_markets()
            self.connected = True

            # Exchange connection successful
            logger.info(f"Connected to {self.exchange_name} exchange")

            return True

        except ccxt.AuthenticationError as e:
            logger.error(f"Authentication failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise

    def disconnect(self):
        """Disconnect from exchange"""
        self.exchange = None
        self.connected = False
        self.markets = {}
        self.balance = {}

    def get_balance(self, currency: str = "USDT") -> float:
        """Get available balance for a currency"""
        if not self.connected:
            raise RuntimeError("Not connected to exchange")

        try:
            self.balance = self.exchange.fetch_balance()

            # CCXT returns balance in format: {'free': x, 'used': y, 'total': z}
            currency_balance = self.balance.get(currency, {})

            # Try 'free' first (available for trading)
            free = float(currency_balance.get('free', 0) or 0)

            # Log for debugging
            total = float(currency_balance.get('total', 0) or 0)
            used = float(currency_balance.get('used', 0) or 0)

            if total != free:
                logger.info(f"{currency} balance: free={free}, used={used}, total={total}")

            return free
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            raise

    def get_all_balances(self, min_value_usdt: float = 1.0) -> Dict[str, Dict[str, float]]:
        """
        Get all non-zero balances with their USDT value.

        Returns dict like:
        {
            'BTC': {'free': 0.001, 'used': 0, 'total': 0.001, 'amount': 0.001, 'usdt_value': 95.0, 'price': 95000.0},
            'USDT': {'free': 100.0, 'used': 0, 'total': 100.0, 'amount': 100.0, 'usdt_value': 100.0, 'price': 1.0}
        }
        """
        if not self.connected:
            raise RuntimeError("Not connected to exchange")

        try:
            self.balance = self.exchange.fetch_balance()
            result = {}

            for currency, amounts in self.balance.items():
                if isinstance(amounts, dict) and ('free' in amounts or 'total' in amounts):
                    free_amount = float(amounts.get('free', 0) or 0)
                    used_amount = float(amounts.get('used', 0) or 0)
                    total_amount = float(amounts.get('total', 0) or 0)

                    # Use total if free is 0 but total exists
                    effective_amount = total_amount if total_amount > free_amount else free_amount

                    if effective_amount > 0:
                        # Calculate USDT value and get price
                        price = 0
                        if currency == 'USDT':
                            usdt_value = total_amount
                            price = 1.0
                        else:
                            try:
                                price = self.get_current_price(f"{currency}USDT")
                                usdt_value = total_amount * price
                            except Exception:
                                usdt_value = 0
                                price = 0

                        # Only include if above minimum value
                        if usdt_value >= min_value_usdt:
                            result[currency] = {
                                'free': free_amount,
                                'used': used_amount,
                                'total': total_amount,
                                'amount': total_amount,  # Add amount field for sync
                                'usdt_value': usdt_value,
                                'price': price  # Add price field for sync
                            }

            logger.info(f"Fetched {len(result)} balances: {list(result.keys())}")
            return result
        except Exception as e:
            logger.error(f"Failed to fetch all balances: {e}")
            raise

    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize a symbol to CCXT format.

        Handles:
        - Spot symbols: BTCUSDT -> BTC/USDT
        - Futures symbols: TRXUSDT:USDT -> TRX/USDT:USDT
        - Already normalized: BTC/USDT -> BTC/USDT
        """
        if '/' in symbol:
            return symbol  # Already normalized

        # Check for futures suffix (e.g., :USDT)
        futures_suffix = ''
        if ':' in symbol:
            base_part, futures_suffix = symbol.split(':', 1)
            futures_suffix = ':' + futures_suffix
        else:
            base_part = symbol

        # Convert spot part: BTCUSDT -> BTC/USDT
        if base_part.endswith('USDT'):
            normalized = base_part[:-4] + '/' + base_part[-4:]
        elif base_part.endswith('USD'):
            normalized = base_part[:-3] + '/' + base_part[-3:]
        elif base_part.endswith('BTC'):
            normalized = base_part[:-3] + '/' + base_part[-3:]
        else:
            normalized = base_part

        return normalized + futures_suffix

    def get_base_currency(self, symbol: str) -> str:
        """Extract base currency from trading pair (e.g., BTC from BTCUSDT)"""
        symbol = symbol.upper().replace('/', '')
        # Strip futures suffix if present
        if ':' in symbol:
            symbol = symbol.split(':')[0]
        if symbol.endswith('USDT'):
            return symbol[:-4]
        elif symbol.endswith('USD'):
            return symbol[:-3]
        elif symbol.endswith('BTC'):
            return symbol[:-3]
        return symbol

    def has_asset_balance(self, symbol: str, min_value_usdt: float = 5.0) -> Dict[str, Any]:
        """
        Check if user has balance in the base asset of a trading pair.

        IMPORTANT: Checks TOTAL balance, not just FREE balance.
        Assets locked in orders (e.g., limit sell/TP) count as having balance.

        Returns: {'has_balance': bool, 'currency': str, 'amount': float, 'free': float, 'used': float, 'usdt_value': float}
        """
        base_currency = self.get_base_currency(symbol)

        try:
            # Fetch fresh balance from exchange
            self.balance = self.exchange.fetch_balance()
            currency_balance = self.balance.get(base_currency, {})

            # Get all balance types
            free = float(currency_balance.get('free', 0) or 0)
            used = float(currency_balance.get('used', 0) or 0)  # Locked in orders
            total = float(currency_balance.get('total', 0) or 0)

            # Use TOTAL balance (free + used) - assets locked in orders still exist!
            amount = total if total > 0 else free

            if amount <= 0:
                logger.debug(f"{base_currency} balance check: free={free}, used={used}, total={total} - NO BALANCE")
                return {'has_balance': False, 'currency': base_currency, 'amount': 0, 'free': 0, 'used': 0, 'usdt_value': 0}

            # Get USDT value
            price = self.get_current_price(f"{base_currency}USDT")
            usdt_value = amount * price

            # Log detailed balance info for debugging
            if used > 0:
                logger.info(f"{base_currency} balance: free={free:.6f}, used={used:.6f} (in orders), total={total:.6f}, value=${usdt_value:.2f}")
            else:
                logger.debug(f"{base_currency} balance: {amount:.6f}, value=${usdt_value:.2f}")

            return {
                'has_balance': usdt_value >= min_value_usdt,
                'currency': base_currency,
                'amount': amount,
                'free': free,
                'used': used,
                'usdt_value': usdt_value,
                'price': price
            }
        except Exception as e:
            logger.warning(f"Could not check balance for {base_currency}: {e}")
            return {'has_balance': False, 'currency': base_currency, 'amount': 0, 'free': 0, 'used': 0, 'usdt_value': 0}

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Get current ticker for a symbol (spot or futures)"""
        # Convert to exchange format
        symbol = self._normalize_symbol(symbol)

        # Check if this is a futures symbol
        is_futures = ':' in symbol

        if is_futures:
            if not self.futures_connected:
                raise RuntimeError("Not connected to futures exchange")
            try:
                return self.futures_exchange.fetch_ticker(symbol)
            except Exception as e:
                logger.error(f"Failed to fetch ticker for {symbol}: {e}")
                raise
        else:
            if not self.connected:
                raise RuntimeError("Not connected to exchange")
            try:
                return self.exchange.fetch_ticker(symbol)
            except Exception as e:
                logger.error(f"Failed to fetch ticker for {symbol}: {e}")
                raise

    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol"""
        ticker = self.get_ticker(symbol)
        return float(ticker.get('last', 0))

    def is_symbol_tradeable(self, symbol: str) -> Dict[str, Any]:
        """
        Check if a symbol is tradeable on this exchange.
        Returns: {'tradeable': bool, 'reason': str, 'market_id': str}
        """
        if not self.connected:
            return {'tradeable': False, 'reason': 'Not connected', 'market_id': None}

        try:
            # Convert to exchange format
            symbol = self._normalize_symbol(symbol)

            # Check if symbol exists in loaded markets
            if symbol in self.markets:
                market = self.markets[symbol]
                if market.get('active', True):
                    return {
                        'tradeable': True,
                        'reason': 'Symbol available',
                        'market_id': market.get('id', symbol)
                    }
                else:
                    return {
                        'tradeable': False,
                        'reason': 'Symbol is inactive/suspended',
                        'market_id': market.get('id', symbol)
                    }

            # Symbol not in markets
            return {
                'tradeable': False,
                'reason': f'Symbol {symbol} not found on {self.exchange_name}',
                'market_id': None
            }

        except Exception as e:
            return {'tradeable': False, 'reason': str(e), 'market_id': None}

    def get_bid_ask_spread(self, symbol: str) -> Dict[str, float]:
        """
        Get bid/ask prices and spread for a symbol.
        Returns: {'bid': float, 'ask': float, 'spread_pct': float, 'last': float}
        """
        ticker = self.get_ticker(symbol)
        bid = float(ticker.get('bid', 0) or 0)
        ask = float(ticker.get('ask', 0) or 0)
        last = float(ticker.get('last', 0) or 0)

        if bid > 0 and ask > 0:
            spread_pct = ((ask - bid) / bid) * 100
        else:
            spread_pct = 0

        return {
            'bid': bid,
            'ask': ask,
            'last': last,
            'spread_pct': spread_pct
        }

    def validate_spread(self, symbol: str, max_spread_pct: float = 2.0) -> Dict[str, Any]:
        """
        Check if spread is acceptable for trading.
        Returns: {'valid': bool, 'spread_pct': float, 'bid': float, 'ask': float, 'reason': str}
        """
        try:
            spread_info = self.get_bid_ask_spread(symbol)
            bid = spread_info['bid']
            ask = spread_info['ask']
            spread_pct = spread_info['spread_pct']

            if bid <= 0 or ask <= 0:
                return {
                    'valid': False,
                    'spread_pct': spread_pct,
                    'bid': bid,
                    'ask': ask,
                    'reason': f"Invalid bid/ask: bid=${bid}, ask=${ask}"
                }

            if spread_pct > max_spread_pct:
                return {
                    'valid': False,
                    'spread_pct': spread_pct,
                    'bid': bid,
                    'ask': ask,
                    'reason': f"Spread too wide: {spread_pct:.2f}% (max {max_spread_pct}%)"
                }

            return {
                'valid': True,
                'spread_pct': spread_pct,
                'bid': bid,
                'ask': ask,
                'reason': None
            }
        except Exception as e:
            return {
                'valid': False,
                'spread_pct': 0,
                'bid': 0,
                'ask': 0,
                'reason': f"Spread check failed: {e}"
            }

    def place_market_order(self, symbol: str, side: str, amount: float) -> Dict[str, Any]:
        """Place a market order"""
        if not self.connected:
            raise RuntimeError("Not connected to exchange")

        try:
            # Convert to exchange format
            original_symbol = symbol
            symbol = self._normalize_symbol(symbol)

            # Verify symbol exists in markets
            if symbol not in self.markets:
                # Try to reload markets
                logger.warning(f"Symbol {symbol} not in cached markets, reloading...")
                self.markets = self.exchange.load_markets()
                if symbol not in self.markets:
                    raise ValueError(f"Symbol {symbol} not found on {self.exchange_name}")

            # Get market info
            market = self.markets[symbol]
            logger.debug(f"Market info for {symbol}: id={market.get('id')}, active={market.get('active')}")

            # Get precision
            precision = get_precision(self.exchange_name, symbol.replace('/', ''))
            qty_precision = precision['qty']

            # Round amount
            rounded_amount = float(Decimal(str(amount)).quantize(
                Decimal(f"0.{'0' * qty_precision}"), rounding=ROUND_DOWN
            ))

            if rounded_amount <= 0:
                raise ValueError("Order amount too small")

            logger.info(f"Placing market {side} order: {symbol} qty={rounded_amount} (exchange: {self.exchange_name})")

            # Place order
            try:
                if side.lower() == 'buy' or side.lower() == 'long':
                    order = self.exchange.create_market_buy_order(symbol, rounded_amount)
                else:
                    order = self.exchange.create_market_sell_order(symbol, rounded_amount)

                logger.info(f"Market {side} order placed: {symbol} {rounded_amount}")
                return order

            except ccxt.ExchangeError as e:
                error_str = str(e).lower()
                # MEXC specific: If market order fails, try aggressive limit order
                if self.exchange_name == 'mexc' and ('not support' in error_str or '10007' in error_str):
                    logger.warning(f"MEXC market order failed, trying aggressive limit order for {symbol}")
                    try:
                        ticker = self.exchange.fetch_ticker(symbol)
                        price_precision = precision.get('price', 2)

                        if side.lower() == 'buy' or side.lower() == 'long':
                            # Buy at slightly above ask price for immediate fill
                            raw_price = float(ticker.get('ask', 0)) * 1.002  # 0.2% above ask
                            limit_price = float(Decimal(str(raw_price)).quantize(
                                Decimal(f"0.{'0' * price_precision}"), rounding=ROUND_DOWN
                            ))
                            order = self.exchange.create_limit_buy_order(symbol, rounded_amount, limit_price)
                        else:
                            # Sell at slightly below bid price for immediate fill
                            raw_price = float(ticker.get('bid', 0)) * 0.998  # 0.2% below bid
                            limit_price = float(Decimal(str(raw_price)).quantize(
                                Decimal(f"0.{'0' * price_precision}"), rounding=ROUND_DOWN
                            ))
                            order = self.exchange.create_limit_sell_order(symbol, rounded_amount, limit_price)

                        logger.info(f"Aggressive limit {side} order placed: {symbol} {rounded_amount} @ {limit_price}")
                        return order
                    except Exception as limit_error:
                        logger.error(f"Limit order fallback also failed: {limit_error}")
                        raise limit_error
                else:
                    raise

        except ccxt.InsufficientFunds as e:
            logger.error(f"Insufficient funds: {e}")
            raise
        except ccxt.InvalidOrder as e:
            logger.error(f"Invalid order for {symbol}: {e}")
            raise
        except ccxt.ExchangeError as e:
            logger.error(f"Exchange error for {symbol} on {self.exchange_name}: {e}")
            raise
        except Exception as e:
            logger.error(f"Order failed for {symbol}: {e}")
            raise

    def place_limit_order(self, symbol: str, side: str, amount: float, price: float) -> Dict[str, Any]:
        """Place a limit order (spot or futures)"""
        # Convert to exchange format
        symbol = self._normalize_symbol(symbol)
        is_futures = ':' in symbol

        if is_futures:
            if not self.futures_connected:
                raise RuntimeError("Not connected to futures exchange")
            exchange = self.futures_exchange
        else:
            if not self.connected:
                raise RuntimeError("Not connected to exchange")
            exchange = self.exchange

        try:
            # Get precision (strip futures suffix for lookup)
            symbol_for_precision = symbol.replace('/', '').split(':')[0] + 'USDT'
            precision = get_precision(self.exchange_name, symbol_for_precision)
            qty_precision = precision['qty']
            price_precision = precision['price']

            # Round values
            rounded_amount = float(Decimal(str(amount)).quantize(
                Decimal(f"0.{'0' * qty_precision}"), rounding=ROUND_DOWN
            ))
            rounded_price = float(Decimal(str(price)).quantize(
                Decimal(f"0.{'0' * price_precision}"), rounding=ROUND_DOWN
            ))

            # Place order
            if side.lower() == 'buy' or side.lower() == 'long':
                order = exchange.create_limit_buy_order(symbol, rounded_amount, rounded_price)
            else:
                order = exchange.create_limit_sell_order(symbol, rounded_amount, rounded_price)

            logger.info(f"Limit {side} order placed: {symbol} {rounded_amount} @ {rounded_price}")
            return order

        except Exception as e:
            logger.error(f"Order failed: {e}")
            raise

    def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel an order (spot or futures)"""
        symbol = self._normalize_symbol(symbol)
        is_futures = ':' in symbol

        if is_futures:
            if not self.futures_connected:
                raise RuntimeError("Not connected to futures exchange")
            try:
                return self.futures_exchange.cancel_order(order_id, symbol)
            except Exception as e:
                logger.error(f"Cancel order failed: {e}")
                raise
        else:
            if not self.connected:
                raise RuntimeError("Not connected to exchange")
            try:
                return self.exchange.cancel_order(order_id, symbol)
            except Exception as e:
                logger.error(f"Cancel order failed: {e}")
                raise

    def get_open_orders(self, symbol: str = None) -> List[Dict]:
        """Get open orders"""
        if not self.connected:
            raise RuntimeError("Not connected to exchange")

        try:
            if symbol:
                symbol = self._normalize_symbol(symbol)

            return self.exchange.fetch_open_orders(symbol)
        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")
            raise

    def get_order_book(self, symbol: str, limit: int = 10) -> Dict[str, Any]:
        """Get order book for a symbol"""
        if not self.connected:
            raise RuntimeError("Not connected to exchange")

        try:
            symbol = self._normalize_symbol(symbol)

            return self.exchange.fetch_order_book(symbol, limit)
        except Exception as e:
            logger.error(f"Failed to fetch order book: {e}")
            raise

    def place_stop_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        stop_price: float
    ) -> Dict[str, Any]:
        """
        Place a stop-limit order (trigger order).
        For MEXC: Uses trigger orders via params.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: 'buy' or 'sell'
            amount: Quantity to trade
            price: Limit price (execution price)
            stop_price: Trigger price (when to activate)
        """
        if not self.connected:
            raise RuntimeError("Not connected to exchange")

        try:
            symbol = self._normalize_symbol(symbol)

            # Get precision
            precision = get_precision(self.exchange_name, symbol.replace('/', ''))
            qty_precision = precision['qty']
            price_precision = precision['price']

            # Round values
            rounded_amount = float(Decimal(str(amount)).quantize(
                Decimal(f"0.{'0' * qty_precision}"), rounding=ROUND_DOWN
            ))
            rounded_price = float(Decimal(str(price)).quantize(
                Decimal(f"0.{'0' * price_precision}"), rounding=ROUND_DOWN
            ))
            rounded_stop = float(Decimal(str(stop_price)).quantize(
                Decimal(f"0.{'0' * price_precision}"), rounding=ROUND_DOWN
            ))

            # Create stop-limit order with trigger price
            params = {
                'stopPrice': rounded_stop,
                'triggerPrice': rounded_stop,  # MEXC uses triggerPrice
            }

            order = self.exchange.create_order(
                symbol,
                'limit',
                side.lower(),
                rounded_amount,
                rounded_price,
                params
            )

            logger.info(f"Stop-limit {side} order placed: {symbol} {rounded_amount} "
                       f"@ ${rounded_price} (trigger: ${rounded_stop})")
            return order

        except Exception as e:
            logger.error(f"Stop-limit order failed: {e}")
            raise

    def get_order_status(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Get status of a specific order (spot or futures)"""
        symbol = self._normalize_symbol(symbol)
        is_futures = ':' in symbol

        if is_futures:
            if not self.futures_connected:
                raise RuntimeError("Not connected to futures exchange")
            try:
                return self.futures_exchange.fetch_order(order_id, symbol)
            except Exception as e:
                logger.error(f"Failed to fetch order status: {e}")
                raise
        else:
            if not self.connected:
                raise RuntimeError("Not connected to exchange")
            try:
                return self.exchange.fetch_order(order_id, symbol)
            except Exception as e:
                logger.error(f"Failed to fetch order status: {e}")
                raise

    def is_order_filled(self, order_id: str, symbol: str) -> tuple:
        """
        Check if an order has been filled.

        Returns:
            tuple: (filled: bool, order_exists: bool)
            - (True, True) = order exists and is filled
            - (False, True) = order exists but not filled
            - (False, False) = order does not exist (likely already filled or cancelled)
        """
        try:
            order = self.get_order_status(order_id, symbol)
            status = order.get('status', '')
            return (status == 'closed', True)
        except Exception as e:
            error_str = str(e).lower()
            # Order doesn't exist - likely already filled or cancelled
            if 'does not exist' in error_str or '-2013' in error_str:
                logger.info(f"Order {order_id} no longer exists - likely already filled or cancelled")
                return (False, False)
            logger.warning(f"Could not check order status: {e}")
            return (False, True)  # Unknown state, assume order still exists

    def cancel_all_orders(self, symbol: str = None) -> List[Dict]:
        """Cancel all open orders, optionally for a specific symbol"""
        if not self.connected:
            raise RuntimeError("Not connected to exchange")

        try:
            if symbol:
                symbol = self._normalize_symbol(symbol)

            cancelled = []
            open_orders = self.get_open_orders(symbol)

            for order in open_orders:
                try:
                    result = self.cancel_order(order['id'], order['symbol'])
                    cancelled.append(result)
                except Exception as e:
                    logger.warning(f"Failed to cancel order {order['id']}: {e}")

            logger.info(f"Cancelled {len(cancelled)} orders")
            return cancelled

        except Exception as e:
            logger.error(f"Cancel all orders failed: {e}")
            raise

    def get_trading_fee(self, symbol: str = None) -> float:
        """Get trading fee rate for the exchange"""
        # MEXC spot: 0.1% maker/taker (can be lower with MX token)
        # Binance spot: 0.1% (can be lower with BNB)
        fee_rates = {
            'mexc': 0.001,      # 0.1%
            'binance': 0.001,   # 0.1%
            'bybit': 0.001,     # 0.1%
        }
        return fee_rates.get(self.exchange_name, 0.001)

    # ==================== FUTURES TRADING SUPPORT ====================

    def connect_futures(self, api_key: str, api_secret: str, testnet: bool = False) -> bool:
        """
        Connect to futures exchange with 1x leverage and isolated margin.
        SAFETY: Only allows 1x leverage to minimize liquidation risk.
        """
        if self.exchange_name not in ['binance', 'bybit']:
            logger.warning(f"Futures not supported for {self.exchange_name}, only Binance/Bybit")
            return False

        try:
            exchange_class = getattr(ccxt, self.exchange_name)
            config = {
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',  # USDT-M Futures
                    'adjustForTimeDifference': True,
                    'recvWindow': 60000,
                }
            }

            if testnet:
                config['sandbox'] = True

            self.futures_exchange = exchange_class(config)

            # Test connection
            self.futures_balance = self.futures_exchange.fetch_balance()
            self.futures_markets = self.futures_exchange.load_markets()
            self.futures_connected = True

            logger.info(f"Connected to {self.exchange_name} FUTURES")

            # Setup safe trading parameters for all pairs
            self._setup_futures_safety()

            return True

        except Exception as e:
            logger.error(f"Futures connection failed: {e}")
            self.futures_connected = False
            return False

    def _setup_futures_safety(self):
        """
        Setup 1x leverage and isolated margin for safety.
        Called after futures connection.
        """
        if not self.futures_connected:
            return

        try:
            # Common trading pairs to setup
            pairs = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'ADA/USDT',
                     'DOGE/USDT', 'LINK/USDT', 'DOT/USDT', 'LTC/USDT', 'NEAR/USDT', 'TRX/USDT']

            for symbol in pairs:
                if symbol in self.futures_markets:
                    try:
                        # Set leverage to 1x (SAFEST)
                        self.futures_exchange.set_leverage(1, symbol)
                        logger.debug(f"Set {symbol} leverage to 1x")
                    except Exception as e:
                        # Some exchanges don't support per-symbol leverage
                        logger.debug(f"Could not set leverage for {symbol}: {e}")

                    try:
                        # Set isolated margin mode (only position margin at risk)
                        self.futures_exchange.set_margin_mode('isolated', symbol)
                        logger.debug(f"Set {symbol} margin mode to isolated")
                    except Exception as e:
                        logger.debug(f"Could not set margin mode for {symbol}: {e}")

            logger.info("Futures safety settings applied: 1x leverage, isolated margin")

        except Exception as e:
            logger.warning(f"Could not apply all futures safety settings: {e}")

    def enable_futures(self, enabled: bool = True):
        """Enable or disable futures trading"""
        if enabled and not self.futures_connected:
            logger.warning("Cannot enable futures - not connected to futures exchange")
            return False

        self.futures_enabled = enabled
        logger.info(f"Futures trading {'enabled' if enabled else 'disabled'}")
        return True

    def get_futures_balance(self, currency: str = "USDT") -> float:
        """Get available futures balance"""
        if not self.futures_connected:
            return 0.0

        try:
            self.futures_balance = self.futures_exchange.fetch_balance()
            currency_balance = self.futures_balance.get(currency, {})
            return float(currency_balance.get('free', 0) or 0)
        except Exception as e:
            logger.error(f"Failed to fetch futures balance: {e}")
            return 0.0

    def place_futures_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        reduce_only: bool = False
    ) -> Dict[str, Any]:
        """
        Place a futures market order with 1x leverage.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: 'buy' (long) or 'sell' (short)
            amount: Quantity in base currency
            reduce_only: If True, only reduces existing position
        """
        if not self.futures_connected:
            raise RuntimeError("Not connected to futures exchange")

        if not self.futures_enabled:
            raise RuntimeError("Futures trading is not enabled")

        try:
            # Convert to exchange format
            symbol = self._normalize_symbol(symbol)

            # Get precision
            precision = get_precision(self.exchange_name, symbol.replace('/', ''))
            qty_precision = precision['qty']

            # Round amount
            rounded_amount = float(Decimal(str(amount)).quantize(
                Decimal(f"0.{'0' * qty_precision}"), rounding=ROUND_DOWN
            ))

            if rounded_amount <= 0:
                raise ValueError("Order amount too small")

            # Ensure 1x leverage before placing order (extra safety)
            try:
                self.futures_exchange.set_leverage(1, symbol)
            except Exception:
                pass  # May already be set or not supported

            params = {}
            if reduce_only:
                params['reduceOnly'] = True

            logger.info(f"Placing FUTURES market {side} order: {symbol} qty={rounded_amount}")

            # Place order
            if side.lower() in ['buy', 'long']:
                order = self.futures_exchange.create_market_buy_order(symbol, rounded_amount, params)
            else:
                order = self.futures_exchange.create_market_sell_order(symbol, rounded_amount, params)

            logger.info(f"FUTURES market {side} order placed: {symbol} {rounded_amount}")
            return order

        except Exception as e:
            logger.error(f"Futures order failed: {e}")
            raise

    def close_futures_position(self, symbol: str) -> Dict[str, Any]:
        """
        Close an existing futures position.

        Returns the closing order details.
        """
        if not self.futures_connected:
            raise RuntimeError("Not connected to futures exchange")

        try:
            symbol = self._normalize_symbol(symbol)

            # Get current position
            positions = self.futures_exchange.fetch_positions([symbol])

            for pos in positions:
                if pos['symbol'] == symbol and float(pos.get('contracts', 0) or 0) != 0:
                    contracts = abs(float(pos['contracts']))
                    side = pos.get('side', '')

                    # Close by placing opposite order
                    if side == 'long':
                        order = self.place_futures_market_order(symbol, 'sell', contracts, reduce_only=True)
                    else:
                        order = self.place_futures_market_order(symbol, 'buy', contracts, reduce_only=True)

                    logger.info(f"Closed futures position: {symbol} {side} {contracts}")
                    return order

            logger.info(f"No open position found for {symbol}")
            return {}

        except Exception as e:
            logger.error(f"Failed to close futures position: {e}")
            raise

    def get_futures_positions(self) -> List[Dict[str, Any]]:
        """Get all open futures positions"""
        if not self.futures_connected:
            return []

        try:
            positions = self.futures_exchange.fetch_positions()
            # Filter to only positions with actual holdings
            active = [p for p in positions if float(p.get('contracts', 0) or 0) != 0]
            return active
        except Exception as e:
            logger.error(f"Failed to fetch futures positions: {e}")
            return []

    def get_futures_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get position info for a specific symbol"""
        if not self.futures_connected:
            return None

        try:
            symbol = self._normalize_symbol(symbol)

            positions = self.futures_exchange.fetch_positions([symbol])
            for pos in positions:
                if pos['symbol'] == symbol and float(pos.get('contracts', 0) or 0) != 0:
                    return pos
            return None
        except Exception as e:
            logger.error(f"Failed to fetch futures position for {symbol}: {e}")
            return None

    def set_futures_stop_loss(
        self,
        symbol: str,
        side: str,
        stop_price: float,
        amount: float
    ) -> Dict[str, Any]:
        """
        Set a stop-loss order for futures position.

        Args:
            symbol: Trading pair
            side: 'buy' to close short, 'sell' to close long
            stop_price: Trigger price
            amount: Quantity to close
        """
        if not self.futures_connected:
            raise RuntimeError("Not connected to futures exchange")

        try:
            symbol = self._normalize_symbol(symbol)

            precision = get_precision(self.exchange_name, symbol.replace('/', ''))
            rounded_amount = float(Decimal(str(amount)).quantize(
                Decimal(f"0.{'0' * precision['qty']}"), rounding=ROUND_DOWN
            ))
            rounded_stop = float(Decimal(str(stop_price)).quantize(
                Decimal(f"0.{'0' * precision['price']}"), rounding=ROUND_DOWN
            ))

            params = {
                'stopPrice': rounded_stop,
                'reduceOnly': True,
            }

            order = self.futures_exchange.create_order(
                symbol,
                'stop_market',
                side.lower(),
                rounded_amount,
                None,  # No limit price for stop market
                params
            )

            logger.info(f"Futures SL order: {symbol} {side} {rounded_amount} @ trigger ${rounded_stop}")
            return order

        except Exception as e:
            logger.error(f"Failed to set futures stop loss: {e}")
            raise

    def set_futures_take_profit(
        self,
        symbol: str,
        side: str,
        take_profit_price: float,
        amount: float
    ) -> Dict[str, Any]:
        """
        Set a take-profit order for futures position.
        """
        if not self.futures_connected:
            raise RuntimeError("Not connected to futures exchange")

        try:
            symbol = self._normalize_symbol(symbol)

            precision = get_precision(self.exchange_name, symbol.replace('/', ''))
            rounded_amount = float(Decimal(str(amount)).quantize(
                Decimal(f"0.{'0' * precision['qty']}"), rounding=ROUND_DOWN
            ))
            rounded_tp = float(Decimal(str(take_profit_price)).quantize(
                Decimal(f"0.{'0' * precision['price']}"), rounding=ROUND_DOWN
            ))

            params = {
                'stopPrice': rounded_tp,
                'reduceOnly': True,
            }

            order = self.futures_exchange.create_order(
                symbol,
                'take_profit_market',
                side.lower(),
                rounded_amount,
                None,
                params
            )

            logger.info(f"Futures TP order: {symbol} {side} {rounded_amount} @ trigger ${rounded_tp}")
            return order

        except Exception as e:
            logger.error(f"Failed to set futures take profit: {e}")
            raise

    def get_futures_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        """Get all open futures orders, optionally for a specific symbol"""
        if not self.futures_connected:
            return []

        try:
            if symbol:
                symbol = self._normalize_symbol(symbol)
                orders = self.futures_exchange.fetch_open_orders(symbol)
            else:
                orders = self.futures_exchange.fetch_open_orders()
            return orders
        except Exception as e:
            logger.error(f"Failed to fetch futures open orders: {e}")
            return []

    def cancel_futures_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel a specific futures order"""
        if not self.futures_connected:
            raise RuntimeError("Not connected to futures exchange")

        try:
            symbol = self._normalize_symbol(symbol)
            return self.futures_exchange.cancel_order(order_id, symbol)
        except Exception as e:
            logger.error(f"Failed to cancel futures order {order_id}: {e}")
            raise

    def cancel_all_futures_orders(self, symbol: str = None) -> List[Dict]:
        """Cancel all open futures orders for a symbol"""
        if not self.futures_connected:
            return []

        try:
            cancelled = []
            open_orders = self.get_futures_open_orders(symbol)

            for order in open_orders:
                try:
                    result = self.cancel_futures_order(order['id'], order['symbol'])
                    cancelled.append(result)
                except Exception as e:
                    logger.warning(f"Failed to cancel futures order {order['id']}: {e}")

            if cancelled:
                logger.info(f"Cancelled {len(cancelled)} futures orders")
            return cancelled

        except Exception as e:
            logger.error(f"Cancel all futures orders failed: {e}")
            return []
