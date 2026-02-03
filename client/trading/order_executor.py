# client/trading/order_executor.py - Order execution logic with hybrid SL/TP
import logging
import random
import time
from typing import Dict, Any, Optional, TYPE_CHECKING

from client.services.exchange_client import ExchangeClient
from client.trading.position_sizer import PositionSizer
from client.trading.position_manager import PositionManager
from client.config import (
    MIN_TRADE_VALUE_USDT, MIN_FUTURES_TRADE_VALUE, is_pair_supported, get_exchange_symbol,
    MAX_CONCURRENT_POSITIONS, PREFER_FUTURES, MIN_CONFIDENCE_FOR_SPOT
)

if TYPE_CHECKING:
    from client.trading.sl_tp_monitor import SLTPMonitor

logger = logging.getLogger(__name__)


class OrderExecutor:
    """Execute orders based on signals with hybrid SL/TP management"""

    def __init__(
        self,
        exchange_client: ExchangeClient,
        position_sizer: PositionSizer,
        position_manager: PositionManager,
        sl_tp_monitor: Optional["SLTPMonitor"] = None
    ):
        self.exchange = exchange_client
        self.sizer = position_sizer
        self.manager = position_manager
        self.monitor = sl_tp_monitor

        # Configuration for hybrid approach
        self.place_tp_on_exchange = True  # Place TP limit orders on exchange
        self.use_trailing_stop = True     # Enable trailing stop

        # Anti-front-running: Random execution delay (disabled by default)
        self.use_execution_delay = False
        self.min_delay_seconds = 5
        self.max_delay_seconds = 45

        # Track recently stopped out pairs to prevent immediate re-entry
        self._recent_stopouts: Dict[str, float] = {}
        self._stopout_cooldown_seconds = 300  # 5 minutes

    def _apply_execution_delay(self, signal: Dict) -> Dict[str, Any]:
        """
        Apply random delay before execution to avoid front-running.
        SMART DELAY: After waiting, validates if trade is still worth taking.

        Returns dict with:
            - delay: seconds waited
            - should_execute: bool - whether to proceed with trade
            - new_price: updated price after delay
            - reason: why trade was skipped (if applicable)
        """
        if not self.use_execution_delay:
            return {'delay': 0, 'should_execute': True, 'new_price': None, 'reason': None}

        pair = signal.get('pair', '')
        side = signal.get('side', '').lower()
        entry_price = float(signal.get('entry_price', 0))
        stop_loss = float(signal.get('stop_loss', 0))
        take_profit = float(signal.get('target_price') or signal.get('take_profit', 0))

        # Longer delay for high-confidence signals (more likely to be crowded)
        confidence = signal.get('confidence', 0.5)
        if confidence > 0.8:
            delay = random.uniform(self.min_delay_seconds + 10, self.max_delay_seconds)
        elif confidence > 0.65:
            delay = random.uniform(self.min_delay_seconds, self.max_delay_seconds - 10)
        else:
            delay = random.uniform(self.min_delay_seconds, self.min_delay_seconds + 15)

        logger.info(f"Anti-front-run delay: waiting {delay:.1f}s before execution...")
        time.sleep(delay)

        # === SMART VALIDATION AFTER DELAY ===
        try:
            new_price = self.exchange.get_current_price(pair)
            price_change_pct = (new_price - entry_price) / entry_price * 100

            logger.info(f"Price after {delay:.1f}s delay: ${new_price:.4f} ({price_change_pct:+.2f}%)")

            # CHECK 1: Did price already hit TP? (move is done)
            if side in ['long', 'buy'] and take_profit > 0:
                if new_price >= take_profit:
                    logger.warning(f"SKIP: Price ${new_price:.2f} already hit TP ${take_profit:.2f} - move is done")
                    return {'delay': delay, 'should_execute': False, 'new_price': new_price,
                            'reason': f'Price already at TP - move done'}
                # Also skip if price moved >70% toward TP (most of the move is done)
                tp_distance = take_profit - entry_price
                current_progress = new_price - entry_price
                if tp_distance > 0 and current_progress / tp_distance > 0.7:
                    logger.warning(f"SKIP: Price already moved 70%+ toward TP - late entry")
                    return {'delay': delay, 'should_execute': False, 'new_price': new_price,
                            'reason': f'Already 70%+ to TP - too late'}

            if side in ['short', 'sell'] and take_profit > 0:
                if new_price <= take_profit:
                    logger.warning(f"SKIP: Price ${new_price:.2f} already hit TP ${take_profit:.2f} - move is done")
                    return {'delay': delay, 'should_execute': False, 'new_price': new_price,
                            'reason': f'Price already at TP - move done'}
                tp_distance = entry_price - take_profit
                current_progress = entry_price - new_price
                if tp_distance > 0 and current_progress / tp_distance > 0.7:
                    logger.warning(f"SKIP: Price already moved 70%+ toward TP - late entry")
                    return {'delay': delay, 'should_execute': False, 'new_price': new_price,
                            'reason': f'Already 70%+ to TP - too late'}

            # CHECK 2: Did price crash through SL? (terrible entry)
            if side in ['long', 'buy'] and stop_loss > 0:
                if new_price <= stop_loss:
                    logger.warning(f"SKIP: Price ${new_price:.2f} crashed through SL ${stop_loss:.2f}")
                    return {'delay': delay, 'should_execute': False, 'new_price': new_price,
                            'reason': f'Price below SL - signal invalidated'}

            if side in ['short', 'sell'] and stop_loss > 0:
                if new_price >= stop_loss:
                    logger.warning(f"SKIP: Price ${new_price:.2f} crashed through SL ${stop_loss:.2f}")
                    return {'delay': delay, 'should_execute': False, 'new_price': new_price,
                            'reason': f'Price above SL - signal invalidated'}

            # CHECK 3: Price moved too much against us (>1.5% worse entry)
            if side in ['long', 'buy'] and price_change_pct > 1.5:
                logger.warning(f"SKIP: Price moved {price_change_pct:.2f}% up - entry too expensive now")
                return {'delay': delay, 'should_execute': False, 'new_price': new_price,
                        'reason': f'Price up {price_change_pct:.1f}% - bad entry'}

            if side in ['short', 'sell'] and price_change_pct < -1.5:
                logger.warning(f"SKIP: Price moved {price_change_pct:.2f}% down - entry too cheap now")
                return {'delay': delay, 'should_execute': False, 'new_price': new_price,
                        'reason': f'Price down {abs(price_change_pct):.1f}% - bad entry'}

            # All checks passed - proceed with trade
            return {'delay': delay, 'should_execute': True, 'new_price': new_price, 'reason': None}

        except Exception as e:
            logger.warning(f"Price check after delay failed: {e} - proceeding anyway")
            return {'delay': delay, 'should_execute': True, 'new_price': None, 'reason': None}

    def execute_signal(self, signal: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
        """
        Execute a trading signal.

        For LONG/BUY signals: Buy with USDT
        For SHORT/SELL signals: Sell existing asset if available, otherwise skip

        Args:
            signal: Signal dict with pair, side, entry_price, stop_loss, etc.
            dry_run: If True, don't actually place orders

        Returns:
            Execution result dict
        """
        try:
            pair = signal.get('pair', '').upper()
            side = signal.get('side', 'hold').lower()
            entry_price = float(signal.get('entry_price', 0))
            stop_loss = float(signal.get('stop_loss', 0))
            take_profit = float(signal.get('target_price') or signal.get('take_profit', 0))
            confidence = float(signal.get('confidence', 0.5))
            regime = signal.get('regime', None)  # Extract regime for adaptive sizing

            # Validate signal
            if side == 'hold' or side not in ['long', 'short', 'buy', 'sell']:
                return {
                    'success': False,
                    'reason': f"Invalid or hold signal: {side}",
                    'order': None
                }

            # CHECK: Circuit breaker - is trading allowed?
            balance = self.exchange.get_balance()
            circuit_check = self.manager.check_circuit_breaker(balance)
            if not circuit_check['trading_allowed']:
                return {
                    'success': False,
                    'reason': circuit_check['reason'],
                    'order': None,
                    'circuit_breaker': True,
                    'stats': circuit_check['stats']
                }

            # CHECK: Is this pair supported on the connected exchange?
            exchange_name = self.exchange.exchange_name
            if not is_pair_supported(exchange_name, pair):
                return {
                    'success': False,
                    'reason': f"{pair} is not supported on {exchange_name.upper()} - skipping",
                    'order': None,
                    'unsupported_pair': True
                }

            # CHECK: Is this symbol actually tradeable on the exchange?
            tradeable_check = self.exchange.is_symbol_tradeable(pair)
            if not tradeable_check['tradeable']:
                logger.warning(f"Symbol {pair} not tradeable on {exchange_name}: {tradeable_check['reason']}")
                return {
                    'success': False,
                    'reason': f"{pair} not tradeable on {exchange_name.upper()}: {tradeable_check['reason']}",
                    'order': None,
                    'symbol_not_tradeable': True
                }

            # Validate signal prices are reasonable (not $0 or missing)
            if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
                return {
                    'success': False,
                    'reason': f"Invalid signal prices: entry=${entry_price}, SL=${stop_loss}, TP=${take_profit}",
                    'order': None
                }

            # CRITICAL: Validate SL is not same as entry (guarantees instant stop loss)
            sl_distance_pct = abs(entry_price - stop_loss) / entry_price * 100
            if sl_distance_pct < 0.5:  # Less than 0.5% = basically same price
                logger.error(f"INVALID SIGNAL {pair}: SL=${stop_loss:.4f} too close to entry=${entry_price:.4f} ({sl_distance_pct:.2f}%)")
                return {
                    'success': False,
                    'reason': f"Invalid SL: too close to entry ({sl_distance_pct:.2f}% - needs >0.5%)",
                    'order': None,
                    'invalid_sl': True
                }

            # Validate SL is on correct side of entry
            if side in ['long', 'buy'] and stop_loss >= entry_price:
                logger.error(f"INVALID SIGNAL {pair}: LONG with SL=${stop_loss:.4f} >= entry=${entry_price:.4f}")
                return {
                    'success': False,
                    'reason': f"Invalid LONG signal: SL ${stop_loss:.4f} must be BELOW entry ${entry_price:.4f}",
                    'order': None,
                    'invalid_sl': True
                }
            elif side in ['short', 'sell'] and stop_loss <= entry_price:
                logger.error(f"INVALID SIGNAL {pair}: SHORT with SL=${stop_loss:.4f} <= entry=${entry_price:.4f}")
                return {
                    'success': False,
                    'reason': f"Invalid SHORT signal: SL ${stop_loss:.4f} must be ABOVE entry ${entry_price:.4f}",
                    'order': None,
                    'invalid_sl': True
                }

            # CHECK: Position limit - don't open too many positions (fee drag on small accounts)
            current_positions = len(self.manager.get_all_positions())
            if current_positions >= MAX_CONCURRENT_POSITIONS:
                # Check if this is an existing position (update allowed)
                if not self.manager.get_position(pair):
                    return {
                        'success': False,
                        'reason': f"Position limit reached ({current_positions}/{MAX_CONCURRENT_POSITIONS}) - close existing positions first",
                        'order': None,
                        'position_limit': True
                    }

            # CHECK: For SPOT trades, require higher confidence (spot has higher fees)
            if side in ['long', 'buy'] and confidence < MIN_CONFIDENCE_FOR_SPOT:
                # Check if futures is available for SHORT instead
                if PREFER_FUTURES and self.exchange.futures_enabled:
                    return {
                        'success': False,
                        'reason': f"Spot confidence too low ({confidence:.0%} < {MIN_CONFIDENCE_FOR_SPOT:.0%}) - waiting for futures signal",
                        'order': None,
                        'low_confidence_spot': True
                    }

            # CHECK: Don't open if price is already close to TP (prevents fee churning)
            # If >50% of the move is already done, skip the trade
            if side in ['long', 'buy']:
                tp_distance = take_profit - entry_price
                current_progress = self.exchange.get_current_price(pair) - entry_price if entry_price > 0 else 0
            else:  # short
                tp_distance = entry_price - take_profit
                current_progress = entry_price - self.exchange.get_current_price(pair) if entry_price > 0 else 0

            if tp_distance > 0 and current_progress > 0:
                progress_pct = (current_progress / tp_distance) * 100
                if progress_pct > 50:
                    return {
                        'success': False,
                        'reason': f"Price already {progress_pct:.0f}% toward TP - too late to enter",
                        'order': None,
                        'late_entry': True
                    }

            # CHECK: Recent stopout cooldown (prevents immediate re-entry after stop loss)
            if pair in self._recent_stopouts:
                elapsed = time.time() - self._recent_stopouts[pair]
                remaining = self._stopout_cooldown_seconds - elapsed
                if remaining > 0:
                    mins = int(remaining // 60)
                    secs = int(remaining % 60)
                    return {
                        'success': False,
                        'reason': f"Stopout cooldown: {pair} hit SL recently ({mins}m {secs}s left)",
                        'order': None,
                        'cooldown': True
                    }
                else:
                    del self._recent_stopouts[pair]

            # CRITICAL: Validate bid/ask spread - prevents trading with huge slippage
            try:
                spread_check = self.exchange.validate_spread(pair, max_spread_pct=2.0)
                if not spread_check['valid']:
                    logger.warning(f"SPREAD INVALID {pair}: {spread_check['reason']} (bid=${spread_check['bid']:.4f}, ask=${spread_check['ask']:.4f})")
                    return {
                        'success': False,
                        'reason': f"Wide spread on {pair}: bid=${spread_check['bid']:.4f}, ask=${spread_check['ask']:.4f} ({spread_check['spread_pct']:.1f}% spread)",
                        'order': None,
                        'spread_too_wide': True
                    }
                logger.info(f"{pair} spread OK: bid=${spread_check['bid']:.4f}, ask=${spread_check['ask']:.4f} ({spread_check['spread_pct']:.2f}%)")
            except Exception as e:
                logger.warning(f"Could not validate spread for {pair}: {e}")

            # CRITICAL: Validate signal entry price matches actual exchange price
            # Prevents executing trades when signal is from wrong exchange
            # STRICT 1.5% limit after 9% loss incidents
            PRICE_MISMATCH_THRESHOLD = 1.5  # Maximum allowed difference in %

            try:
                actual_price = self.exchange.get_current_price(pair)
                if actual_price is None or actual_price <= 0:
                    logger.error(f"❌ {pair}: Could not get exchange price (returned {actual_price})")
                    return {
                        'success': False,
                        'reason': f"Could not get current price for {pair}",
                        'order': None,
                        'price_check_error': True
                    }

                price_diff_pct = abs(actual_price - entry_price) / entry_price * 100

                # Log EVERY price check for debugging
                logger.info(f"PRICE CHECK {pair}: Signal=${entry_price:.4f} vs Exchange=${actual_price:.4f} (diff={price_diff_pct:.2f}%)")

                # STRICT: 1.5% max to prevent catastrophic losses
                if price_diff_pct > PRICE_MISMATCH_THRESHOLD:
                    logger.warning(f"❌ PRICE MISMATCH BLOCKED {pair}: Signal ${entry_price:.4f} vs Exchange ${actual_price:.4f} ({price_diff_pct:.2f}% diff > {PRICE_MISMATCH_THRESHOLD}%)")
                    return {
                        'success': False,
                        'reason': f"Price mismatch: Signal ${entry_price:.2f} vs Exchange ${actual_price:.2f} ({price_diff_pct:.1f}% diff) - server may be using wrong exchange",
                        'order': None,
                        'price_mismatch': True
                    }
                else:
                    logger.info(f"✅ Price check PASSED for {pair} (diff={price_diff_pct:.2f}% < {PRICE_MISMATCH_THRESHOLD}%)")
            except Exception as e:
                logger.error(f"⚠️ PRICE CHECK FAILED for {pair}: {e} - BLOCKING trade for safety")
                return {
                    'success': False,
                    'reason': f"Could not validate price: {e}",
                    'order': None,
                    'price_check_error': True
                }

            # Check if we have existing position
            existing_position = self.manager.get_position(pair)
            if existing_position:
                existing_side = existing_position.get('side', '').lower()

                # Get current thesis (may be different from actual holding)
                current_thesis = existing_position.get('thesis', existing_side)

                # Case 1: Opposite signal → FLIP thesis instead of closing (SAVES FEES!)
                # SHORT signal on LONG thesis → flip to SHORT thesis
                # LONG signal on SHORT thesis → flip to LONG thesis
                if (side in ['short', 'sell'] and current_thesis in ['long', 'buy']) or \
                   (side in ['long', 'buy'] and current_thesis in ['short', 'sell']):

                    logger.info(f"FLIP {pair}: {current_thesis.upper()} → {side.upper()} (NO TRADING FEE)")

                    if not dry_run:
                        # Flip the position thesis without trading
                        flip_success = self.manager.flip_position(
                            pair=pair,
                            new_thesis=side,
                            new_entry=entry_price,
                            new_stop_loss=stop_loss,
                            new_take_profit=take_profit
                        )

                        if flip_success:
                            return {
                                'success': True,
                                'pair': pair,
                                'side': side,
                                'action': 'flipped',
                                'message': f"Flipped to {side.upper()} thesis (no fee)",
                                'entry_price': entry_price,
                                'stop_loss': stop_loss,
                                'take_profit': take_profit,
                                'fee_saved': True
                            }

                    return {'success': False, 'reason': 'Failed to flip position'}

                # Case 2: Same direction signal → just update SL/TP
                elif (side in ['short', 'sell'] and current_thesis in ['short', 'sell']) or \
                     (side in ['long', 'buy'] and current_thesis in ['long', 'buy']):
                    # Already have same thesis, just update levels
                    logger.info(f"Updating {pair} {current_thesis.upper()} SL/TP")
                    self.manager.flip_position(
                        pair=pair,
                        new_thesis=current_thesis,
                        new_entry=entry_price,
                        new_stop_loss=stop_loss,
                        new_take_profit=take_profit
                    )
                    return {
                        'success': True,
                        'pair': pair,
                        'side': side,
                        'action': 'updated',
                        'message': f"Updated {side.upper()} SL/TP levels"
                    }

            # Handle LONG/BUY signals - buy with USDT
            if side in ['long', 'buy']:
                # Don't buy if we already have a LONG position (avoid stacking longs)
                if existing_position and existing_position.get('side', '').lower() in ['long', 'buy']:
                    return {
                        'success': False,
                        'reason': f"Already have LONG position for {pair} - wait for SHORT signal or close position",
                        'order': None
                    }

                # Apply anti-front-running delay before execution
                if not dry_run:
                    delay_result = self._apply_execution_delay(signal)

                    # Check if trade should be skipped
                    if not delay_result['should_execute']:
                        return {
                            'success': False,
                            'reason': f"Trade skipped after delay: {delay_result['reason']}",
                            'order': None,
                            'skipped': True,
                            'delay': delay_result['delay']
                        }

                    # Update entry price if we got a new price
                    if delay_result['new_price']:
                        entry_price = delay_result['new_price']

                # CHECK: Use FUTURES for LONG if enabled (lower fees: 0.04% vs 0.1%)
                if PREFER_FUTURES and self.exchange.futures_enabled and self.exchange.futures_connected:
                    return self._execute_futures_long(pair, entry_price, stop_loss, take_profit, confidence, dry_run, regime)

                return self._execute_buy(pair, entry_price, stop_loss, take_profit, confidence, dry_run, regime)

            # Handle SHORT/SELL signals
            elif side in ['short', 'sell']:
                # Don't sell if we already have a SHORT position (avoid stacking shorts)
                if existing_position and existing_position.get('side', '').lower() in ['short', 'sell']:
                    return {
                        'success': False,
                        'reason': f"Already have SHORT position for {pair} - wait for LONG signal",
                        'order': None
                    }

                # CHECK: Use FUTURES for SHORT if enabled (allows shorting without owning asset)
                if self.exchange.futures_enabled and self.exchange.futures_connected:
                    # Apply anti-front-running delay before execution
                    if not dry_run:
                        delay_result = self._apply_execution_delay(signal)
                        if not delay_result['should_execute']:
                            return {
                                'success': False,
                                'reason': f"Trade skipped after delay: {delay_result['reason']}",
                                'order': None,
                                'skipped': True,
                                'delay': delay_result['delay']
                            }
                        if delay_result['new_price']:
                            entry_price = delay_result['new_price']

                    return self._execute_futures_short(pair, entry_price, stop_loss, take_profit, confidence, dry_run, regime)

                # SPOT FALLBACK - Don't try to sell if we don't have the asset
                asset_info = self.exchange.has_asset_balance(pair, min_value_usdt=MIN_TRADE_VALUE_USDT)
                if not asset_info.get('has_balance'):
                    return {
                        'success': False,
                        'reason': f"No {asset_info.get('currency', 'asset')} to sell (SHORT requires holding asset on spot)",
                        'order': None
                    }

                # Apply anti-front-running delay before execution
                if not dry_run:
                    delay_result = self._apply_execution_delay(signal)

                    # Check if trade should be skipped
                    if not delay_result['should_execute']:
                        return {
                            'success': False,
                            'reason': f"Trade skipped after delay: {delay_result['reason']}",
                            'order': None,
                            'skipped': True,
                            'delay': delay_result['delay']
                        }

                    # Update entry price if we got a new price
                    if delay_result['new_price']:
                        entry_price = delay_result['new_price']

                return self._execute_sell(pair, entry_price, stop_loss, take_profit, confidence, dry_run, regime)

            return {
                'success': False,
                'reason': f"Unknown signal side: {side}",
                'order': None
            }

        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            return {
                'success': False,
                'reason': str(e),
                'order': None
            }

    def can_execute_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if a signal can be executed based on user's portfolio.
        Returns helpful info about why a signal can or cannot be executed.
        """
        try:
            pair = signal.get('pair', '').upper()
            side = signal.get('side', 'hold').lower()

            if side in ['long', 'buy']:
                # For LONG signals, need USDT
                usdt_balance = self.exchange.get_balance('USDT')
                if usdt_balance >= MIN_TRADE_VALUE_USDT:
                    return {
                        'can_execute': True,
                        'reason': f"Can BUY with ${usdt_balance:.2f} USDT",
                        'balance': usdt_balance
                    }
                else:
                    return {
                        'can_execute': False,
                        'reason': f"Insufficient USDT (${usdt_balance:.2f} < ${MIN_TRADE_VALUE_USDT})",
                        'balance': usdt_balance
                    }

            elif side in ['short', 'sell']:
                # For SHORT signals, need the asset
                asset_info = self.exchange.has_asset_balance(pair, min_value_usdt=MIN_TRADE_VALUE_USDT)
                if asset_info['has_balance']:
                    return {
                        'can_execute': True,
                        'reason': f"Can SELL {asset_info['amount']:.6f} {asset_info['currency']} (${asset_info['usdt_value']:.2f})",
                        'balance': asset_info['usdt_value'],
                        'asset': asset_info['currency'],
                        'amount': asset_info['amount']
                    }
                else:
                    return {
                        'can_execute': False,
                        'reason': f"No {asset_info['currency']} to sell. SHORT signals require holding the asset.",
                        'balance': asset_info.get('usdt_value', 0),
                        'hint': "Wait for LONG signal to buy first, then you can sell on SHORT signals."
                    }

            return {'can_execute': False, 'reason': 'Invalid signal side'}

        except Exception as e:
            return {'can_execute': False, 'reason': str(e)}

    def _execute_buy(self, pair: str, entry_price: float, stop_loss: float,
                     take_profit: float, confidence: float, dry_run: bool,
                     regime: str = None) -> Dict[str, Any]:
        """Execute a BUY/LONG order using USDT balance"""
        # Get USDT balance and calculate size (with regime-based adjustment)
        balance = self.exchange.get_balance('USDT')
        size_result = self.sizer.calculate_position_size(
            balance, entry_price, stop_loss, confidence, regime=regime
        )

        if not size_result['valid']:
            return {
                'success': False,
                'reason': size_result.get('reason', 'Position sizing failed'),
                'order': None
            }

        quantity = size_result['quantity']
        usdt_value = size_result['usdt_value']

        logger.info(f"Executing BUY {pair}: qty={quantity:.6f}, value=${usdt_value:.2f}")

        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'pair': pair,
                'side': 'buy',
                'quantity': quantity,
                'usdt_value': usdt_value,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit
            }

        # Place market buy order
        order = self.exchange.place_market_order(pair, 'buy', quantity)

        # Get fill price
        fill_price = float(order.get('average') or order.get('price') or entry_price)

        # === CRITICAL: Recalculate SL/TP based on actual fill price ===
        # If there was slippage, the original SL/TP may be invalid
        slippage_pct = abs(fill_price - entry_price) / entry_price * 100 if entry_price > 0 else 0

        if slippage_pct > 0.1:  # More than 0.1% slippage
            logger.info(f"Slippage detected: signal entry ${entry_price:.4f} -> fill ${fill_price:.4f} ({slippage_pct:.2f}%)")

        # Recalculate SL based on fill price - maintain same % distance
        if stop_loss > 0 and entry_price > 0:
            sl_distance_pct = (entry_price - stop_loss) / entry_price
            adjusted_stop_loss = fill_price * (1 - sl_distance_pct)
            # Ensure SL is below entry for LONG
            if adjusted_stop_loss >= fill_price:
                adjusted_stop_loss = fill_price * 0.98  # Force 2% below
            stop_loss = adjusted_stop_loss
            logger.debug(f"Adjusted SL for LONG: ${stop_loss:.4f}")

        # Recalculate TP based on fill price - maintain same % distance
        if take_profit > 0 and entry_price > 0:
            tp_distance_pct = (take_profit - entry_price) / entry_price
            adjusted_take_profit = fill_price * (1 + tp_distance_pct)
            # Ensure TP is above entry for LONG
            if adjusted_take_profit <= fill_price:
                adjusted_take_profit = fill_price * 1.04  # Force 4% above
                logger.warning(f"TP was invalid for LONG, forcing to ${adjusted_take_profit:.4f}")
            take_profit = adjusted_take_profit
            logger.debug(f"Adjusted TP for LONG: ${take_profit:.4f}")

        # Final validation - TP MUST be above fill_price for LONG
        if take_profit <= fill_price:
            logger.error(f"CRITICAL: TP ${take_profit:.4f} still <= fill ${fill_price:.4f}, forcing 4% above")
            take_profit = fill_price * 1.04

        # Register position (with exchange for fee calculation)
        self.manager.add_position(
            pair=pair,
            side='long',
            entry_price=fill_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=order.get('id'),
            exchange=self.exchange.exchange_name
        )

        logger.info(f"BUY order executed: {pair} {quantity:.6f} @ ${fill_price:.2f} | SL: ${stop_loss:.4f} | TP: ${take_profit:.4f}")

        # === HYBRID SL/TP SETUP ===
        tp_order_id = None

        # 1. Place TP limit order on exchange (guaranteed profit taking)
        # CRITICAL: Only place if TP is above fill price
        if self.place_tp_on_exchange and take_profit > fill_price * 1.005:  # At least 0.5% above
            try:
                tp_order = self.exchange.place_limit_order(pair, 'sell', quantity, take_profit)
                tp_order_id = tp_order.get('id')
                logger.info(f"TP order placed on exchange: {pair} sell @ ${take_profit:.4f}")
            except Exception as e:
                logger.warning(f"Failed to place TP order on exchange: {e} - will monitor locally")

        # 2. Start SL/trailing stop monitoring
        if self.monitor:
            self.monitor.start_monitoring(pair, tp_order_id)
            logger.info(f"Started SL/TP monitoring for {pair} (trailing stop enabled)")

        return {
            'success': True,
            'order': order,
            'pair': pair,
            'side': 'buy',
            'quantity': quantity,
            'fill_price': fill_price,
            'usdt_value': quantity * fill_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'tp_order_id': tp_order_id,
            'monitoring': self.monitor is not None
        }

    def _execute_sell(self, pair: str, entry_price: float, stop_loss: float,
                      take_profit: float, confidence: float, dry_run: bool,
                      regime: str = None) -> Dict[str, Any]:
        """
        Execute a SELL/SHORT order.

        Checks if user has the asset and sells it.
        E.g., for BTCUSDT SHORT signal, checks if user has BTC and sells it.
        """
        # Check if user has the asset
        asset_info = self.exchange.has_asset_balance(pair, min_value_usdt=MIN_TRADE_VALUE_USDT)

        if not asset_info['has_balance']:
            # User doesn't have this asset - check if they have USDT to short
            usdt_balance = self.exchange.get_balance('USDT')
            if usdt_balance < MIN_TRADE_VALUE_USDT:
                return {
                    'success': False,
                    'reason': f"No {asset_info['currency']} to sell and insufficient USDT. "
                              f"You have {asset_info['amount']:.6f} {asset_info['currency']} "
                              f"(${asset_info['usdt_value']:.2f})",
                    'order': None
                }
            # If they have USDT but no asset, we can't short on spot
            return {
                'success': False,
                'reason': f"Cannot short on spot market. No {asset_info['currency']} balance to sell. "
                          f"Available: {asset_info['amount']:.6f} {asset_info['currency']}",
                'order': None
            }

        # User has the asset - calculate how much to sell
        available_amount = asset_info['amount']
        available_usdt_value = asset_info['usdt_value']
        current_price = asset_info.get('price', entry_price)

        # Calculate optimal sell amount based on confidence and risk
        # For sells, we sell a portion based on confidence
        sell_percent = min(0.25 + (confidence * 0.5), 0.9)  # 25% to 75% based on confidence
        quantity = available_amount * sell_percent

        # Ensure minimum trade value
        sell_value = quantity * current_price
        if sell_value < MIN_TRADE_VALUE_USDT:
            # Sell all if partial is too small
            if available_usdt_value >= MIN_TRADE_VALUE_USDT:
                quantity = available_amount * 0.95  # Sell 95% to avoid dust
                sell_value = quantity * current_price
            else:
                return {
                    'success': False,
                    'reason': f"Asset value too small to sell. "
                              f"{asset_info['currency']}: {available_amount:.6f} (${available_usdt_value:.2f})",
                    'order': None
                }

        logger.info(f"Executing SELL {pair}: qty={quantity:.6f} {asset_info['currency']}, "
                    f"value=${sell_value:.2f} (selling {sell_percent:.0%} of holdings)")

        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'pair': pair,
                'side': 'sell',
                'quantity': quantity,
                'usdt_value': sell_value,
                'entry_price': current_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'asset_sold': asset_info['currency']
            }

        # Place market sell order
        order = self.exchange.place_market_order(pair, 'sell', quantity)

        # Get fill price
        fill_price = float(order.get('average') or order.get('price') or current_price)

        # === CRITICAL: Recalculate SL/TP based on actual fill price for SHORT ===
        slippage_pct = abs(fill_price - entry_price) / entry_price * 100 if entry_price > 0 else 0

        if slippage_pct > 0.1:  # More than 0.1% slippage
            logger.info(f"Slippage detected: signal entry ${entry_price:.4f} -> fill ${fill_price:.4f} ({slippage_pct:.2f}%)")

        # Recalculate SL based on fill price - for SHORT, SL is ABOVE entry
        if stop_loss > 0 and entry_price > 0:
            sl_distance_pct = (stop_loss - entry_price) / entry_price
            adjusted_stop_loss = fill_price * (1 + sl_distance_pct)
            # Ensure SL is above entry for SHORT
            if adjusted_stop_loss <= fill_price:
                adjusted_stop_loss = fill_price * 1.02  # Force 2% above
            stop_loss = adjusted_stop_loss
            logger.debug(f"Adjusted SL for SHORT: ${stop_loss:.4f}")

        # Recalculate TP based on fill price - for SHORT, TP is BELOW entry
        if take_profit > 0 and entry_price > 0:
            tp_distance_pct = (entry_price - take_profit) / entry_price
            adjusted_take_profit = fill_price * (1 - tp_distance_pct)
            # Ensure TP is below entry for SHORT
            if adjusted_take_profit >= fill_price:
                adjusted_take_profit = fill_price * 0.96  # Force 4% below
                logger.warning(f"TP was invalid for SHORT, forcing to ${adjusted_take_profit:.4f}")
            take_profit = adjusted_take_profit
            logger.debug(f"Adjusted TP for SHORT: ${take_profit:.4f}")

        # Final validation - TP MUST be below fill_price for SHORT
        if take_profit >= fill_price:
            logger.error(f"CRITICAL: TP ${take_profit:.4f} still >= fill ${fill_price:.4f}, forcing 4% below")
            take_profit = fill_price * 0.96

        # Register position (as a short/sell for tracking, with exchange for fees)
        self.manager.add_position(
            pair=pair,
            side='short',
            entry_price=fill_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=order.get('id'),
            exchange=self.exchange.exchange_name
        )

        logger.info(f"SELL order executed: {pair} {quantity:.6f} @ ${fill_price:.4f} | SL: ${stop_loss:.4f} | TP: ${take_profit:.4f}")

        # === HYBRID SL/TP SETUP FOR SHORT ===
        tp_order_id = None

        # For SHORT: place buy order at TP (to close at profit)
        # CRITICAL: Only place if TP is below fill price
        if self.place_tp_on_exchange and take_profit < fill_price * 0.995:  # At least 0.5% below
            try:
                tp_order = self.exchange.place_limit_order(pair, 'buy', quantity, take_profit)
                tp_order_id = tp_order.get('id')
                logger.info(f"TP order placed on exchange: {pair} buy @ ${take_profit:.4f}")
            except Exception as e:
                logger.warning(f"Failed to place TP order on exchange: {e} - will monitor locally")

        # Start SL/trailing stop monitoring
        if self.monitor:
            self.monitor.start_monitoring(pair, tp_order_id)
            logger.info(f"Started SL/TP monitoring for {pair} (trailing stop enabled)")

        return {
            'success': True,
            'order': order,
            'pair': pair,
            'side': 'sell',
            'quantity': quantity,
            'fill_price': fill_price,
            'usdt_value': quantity * fill_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'asset_sold': asset_info['currency'],
            'tp_order_id': tp_order_id,
            'monitoring': self.monitor is not None
        }

    def _execute_futures_long(self, pair: str, entry_price: float, stop_loss: float,
                               take_profit: float, confidence: float, dry_run: bool,
                               regime: str = None) -> Dict[str, Any]:
        """
        Execute a LONG order on FUTURES market (1x leverage).
        Lower fees than spot (0.04% vs 0.1%).
        """
        # Get futures USDT balance
        futures_balance = self.exchange.get_futures_balance()

        # CRITICAL: Check if futures wallet has funds
        if futures_balance < MIN_FUTURES_TRADE_VALUE:
            spot_balance = self.exchange.get_balance('USDT')

            if spot_balance >= MIN_FUTURES_TRADE_VALUE:
                logger.warning(f"Futures wallet ${futures_balance:.2f} too low, falling back to spot (has ${spot_balance:.2f})")
                # Fall back to spot trading
                return self._execute_buy(pair, entry_price, stop_loss, take_profit, confidence, dry_run, regime)
            else:
                return {
                    'success': False,
                    'reason': f"Insufficient balance: Futures ${futures_balance:.2f}, Spot ${spot_balance:.2f}",
                    'order': None,
                    'insufficient_funds': True
                }

        bybit_min_notional = 5.0 if self.exchange.exchange_name == 'bybit' else MIN_FUTURES_TRADE_VALUE

        logger.info(f"Futures LONG: balance=${futures_balance:.2f} (min required: ${bybit_min_notional})")

        # Calculate position size
        size_result = self.sizer.calculate_position_size(
            futures_balance, entry_price, stop_loss, confidence,
            min_trade_value=max(MIN_FUTURES_TRADE_VALUE, bybit_min_notional),
            regime=regime
        )

        if not size_result['valid']:
            # Try spot fallback
            spot_balance = self.exchange.get_balance('USDT')
            if spot_balance >= MIN_TRADE_VALUE_USDT:
                logger.info(f"Futures sizing failed, falling back to spot")
                return self._execute_buy(pair, entry_price, stop_loss, take_profit, confidence, dry_run, regime)
            return {
                'success': False,
                'reason': f"Futures sizing failed: {size_result.get('reason', 'Unknown')} (balance: ${futures_balance:.2f})",
                'order': None
            }

        quantity = size_result['quantity']
        usdt_value = size_result['usdt_value']

        logger.info(f"Executing FUTURES LONG {pair}: qty={quantity:.6f}, value=${usdt_value:.2f} (1x leverage)")

        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'pair': pair,
                'side': 'long',
                'quantity': quantity,
                'usdt_value': usdt_value,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'market': 'futures'
            }

        # Place futures market buy order (LONG)
        order = self.exchange.place_futures_market_order(pair, 'buy', quantity)

        # Get fill price
        fill_price = float(order.get('average') or order.get('price') or entry_price)

        # Recalculate SL/TP based on fill price for LONG
        slippage_pct = abs(fill_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
        if slippage_pct > 0.1:
            logger.info(f"Slippage detected: signal ${entry_price:.4f} -> fill ${fill_price:.4f} ({slippage_pct:.2f}%)")

        # Adjust SL (below entry for LONG)
        if stop_loss > 0 and entry_price > 0:
            sl_distance_pct = (entry_price - stop_loss) / entry_price
            adjusted_stop_loss = fill_price * (1 - sl_distance_pct)
            if adjusted_stop_loss >= fill_price:
                adjusted_stop_loss = fill_price * 0.98  # Force 2% below
            stop_loss = adjusted_stop_loss

        # Adjust TP (above entry for LONG)
        if take_profit > 0 and entry_price > 0:
            tp_distance_pct = (take_profit - entry_price) / entry_price
            adjusted_take_profit = fill_price * (1 + tp_distance_pct)
            if adjusted_take_profit <= fill_price:
                adjusted_take_profit = fill_price * 1.04  # Force 4% above
            take_profit = adjusted_take_profit

        # Register position
        self.manager.add_position(
            pair=pair,
            side='long',
            entry_price=fill_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=order.get('id'),
            exchange=self.exchange.exchange_name,
            market='futures'
        )

        logger.info(f"FUTURES LONG executed: {pair} {quantity:.6f} @ ${fill_price:.4f} | SL: ${stop_loss:.4f} | TP: ${take_profit:.4f}")

        # Set SL/TP orders on futures exchange
        sl_order_id = None
        tp_order_id = None

        try:
            sl_order = self.exchange.set_futures_stop_loss(pair, 'sell', stop_loss, quantity)
            sl_order_id = sl_order.get('id')
            logger.info(f"Futures SL order placed: sell @ ${stop_loss:.4f}")
        except Exception as e:
            logger.warning(f"Failed to place futures SL order: {e} - will monitor locally")

        try:
            tp_order = self.exchange.set_futures_take_profit(pair, 'sell', take_profit, quantity)
            tp_order_id = tp_order.get('id')
            logger.info(f"Futures TP order placed: sell @ ${take_profit:.4f}")
        except Exception as e:
            logger.warning(f"Failed to place futures TP order: {e} - will monitor locally")

        if self.monitor:
            self.monitor.start_monitoring(pair, tp_order_id)
            logger.info(f"Started backup SL/TP monitoring for futures {pair}")

        return {
            'success': True,
            'order': order,
            'pair': pair,
            'side': 'long',
            'quantity': quantity,
            'fill_price': fill_price,
            'usdt_value': quantity * fill_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'sl_order_id': sl_order_id,
            'tp_order_id': tp_order_id,
            'market': 'futures',
            'leverage': '1x'
        }

    def _execute_futures_short(self, pair: str, entry_price: float, stop_loss: float,
                                take_profit: float, confidence: float, dry_run: bool,
                                regime: str = None) -> Dict[str, Any]:
        """
        Execute a SHORT order on FUTURES market (1x leverage).
        This allows shorting without owning the asset.
        """
        # Get futures USDT balance
        futures_balance = self.exchange.get_futures_balance()

        # CRITICAL: Check if futures wallet has funds
        # Bybit/Binance have separate Spot and Derivatives wallets
        if futures_balance < MIN_FUTURES_TRADE_VALUE:
            # Check if user might have funds in spot instead
            spot_balance = self.exchange.get_balance('USDT')

            if spot_balance >= MIN_FUTURES_TRADE_VALUE:
                logger.warning(f"Futures wallet balance ${futures_balance:.2f} too low, but Spot wallet has ${spot_balance:.2f}")
                return {
                    'success': False,
                    'reason': f"Futures wallet: ${futures_balance:.2f} (need ${MIN_FUTURES_TRADE_VALUE}). "
                              f"Your Spot wallet has ${spot_balance:.2f}. "
                              f"TRANSFER funds from Spot to Derivatives wallet in {self.exchange.exchange_name.upper()} app/website.",
                    'order': None,
                    'wallet_transfer_needed': True,
                    'spot_balance': spot_balance,
                    'futures_balance': futures_balance
                }
            else:
                return {
                    'success': False,
                    'reason': f"Insufficient balance: Futures wallet ${futures_balance:.2f}, Spot wallet ${spot_balance:.2f}. "
                              f"Minimum required: ${MIN_FUTURES_TRADE_VALUE}",
                    'order': None,
                    'insufficient_funds': True
                }

        # Bybit-specific: Check minimum notional requirements
        # Bybit futures minimum notional varies by pair but is typically $5-10
        bybit_min_notional = 5.0 if self.exchange.exchange_name == 'bybit' else MIN_FUTURES_TRADE_VALUE

        logger.info(f"Futures balance: ${futures_balance:.2f} (min required: ${bybit_min_notional})")

        # Calculate position size based on risk (use lower minimum for futures + regime-based sizing)
        size_result = self.sizer.calculate_position_size(
            futures_balance, entry_price, stop_loss, confidence,
            min_trade_value=max(MIN_FUTURES_TRADE_VALUE, bybit_min_notional),
            regime=regime
        )

        if not size_result['valid']:
            return {
                'success': False,
                'reason': f"Futures sizing failed: {size_result.get('reason', 'Unknown')} "
                          f"(balance: ${futures_balance:.2f})",
                'order': None
            }

        quantity = size_result['quantity']
        usdt_value = size_result['usdt_value']

        logger.info(f"Executing FUTURES SHORT {pair}: qty={quantity:.6f}, value=${usdt_value:.2f} (1x leverage)")

        if dry_run:
            return {
                'success': True,
                'dry_run': True,
                'pair': pair,
                'side': 'short',
                'quantity': quantity,
                'usdt_value': usdt_value,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'market': 'futures'
            }

        # Place futures market sell order (SHORT)
        order = self.exchange.place_futures_market_order(pair, 'sell', quantity)

        # Get fill price
        fill_price = float(order.get('average') or order.get('price') or entry_price)

        # Recalculate SL/TP based on fill price for SHORT
        slippage_pct = abs(fill_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
        if slippage_pct > 0.1:
            logger.info(f"Slippage detected: signal ${entry_price:.4f} -> fill ${fill_price:.4f} ({slippage_pct:.2f}%)")

        # Adjust SL (above entry for SHORT)
        if stop_loss > 0 and entry_price > 0:
            sl_distance_pct = (stop_loss - entry_price) / entry_price
            adjusted_stop_loss = fill_price * (1 + sl_distance_pct)
            if adjusted_stop_loss <= fill_price:
                adjusted_stop_loss = fill_price * 1.02  # Force 2% above
            stop_loss = adjusted_stop_loss

        # Adjust TP (below entry for SHORT)
        if take_profit > 0 and entry_price > 0:
            tp_distance_pct = (entry_price - take_profit) / entry_price
            adjusted_take_profit = fill_price * (1 - tp_distance_pct)
            if adjusted_take_profit >= fill_price:
                adjusted_take_profit = fill_price * 0.96  # Force 4% below
            take_profit = adjusted_take_profit

        # Register position
        self.manager.add_position(
            pair=pair,
            side='short',
            entry_price=fill_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            order_id=order.get('id'),
            exchange=self.exchange.exchange_name,
            market='futures'  # Mark as futures position
        )

        logger.info(f"FUTURES SHORT executed: {pair} {quantity:.6f} @ ${fill_price:.4f} | SL: ${stop_loss:.4f} | TP: ${take_profit:.4f}")

        # Set SL/TP orders on futures exchange
        sl_order_id = None
        tp_order_id = None

        try:
            # Place stop loss order on futures
            sl_order = self.exchange.set_futures_stop_loss(pair, 'buy', stop_loss, quantity)
            sl_order_id = sl_order.get('id')
            logger.info(f"Futures SL order placed: buy @ ${stop_loss:.4f}")
        except Exception as e:
            logger.warning(f"Failed to place futures SL order: {e} - will monitor locally")

        try:
            # Place take profit order on futures
            tp_order = self.exchange.set_futures_take_profit(pair, 'buy', take_profit, quantity)
            tp_order_id = tp_order.get('id')
            logger.info(f"Futures TP order placed: buy @ ${take_profit:.4f}")
        except Exception as e:
            logger.warning(f"Failed to place futures TP order: {e} - will monitor locally")

        # Start local monitoring as backup
        if self.monitor:
            self.monitor.start_monitoring(pair, tp_order_id)
            logger.info(f"Started backup SL/TP monitoring for futures {pair}")

        return {
            'success': True,
            'order': order,
            'pair': pair,
            'side': 'short',
            'quantity': quantity,
            'fill_price': fill_price,
            'usdt_value': quantity * fill_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'sl_order_id': sl_order_id,
            'tp_order_id': tp_order_id,
            'market': 'futures',
            'leverage': '1x'
        }

    def set_monitor(self, monitor: "SLTPMonitor"):
        """Set the SL/TP monitor instance"""
        self.monitor = monitor
        logger.info("SL/TP monitor attached to order executor")

    def _close_position(self, pair: str, position: Dict) -> Optional[Dict]:
        """Close an existing position"""
        try:
            side = position.get('side', '').lower()
            stored_quantity = position.get('quantity', 0)

            logger.info(f"Attempting to close {pair} {side} position, stored qty: {stored_quantity}")

            # Stop monitoring and cancel any TP orders FIRST
            if self.monitor:
                # Cancel TP order on exchange if exists
                if pair in self.monitor.tp_order_ids:
                    try:
                        self.exchange.cancel_order(self.monitor.tp_order_ids[pair], pair)
                        logger.info(f"Cancelled TP order for {pair}")
                    except Exception as e:
                        logger.warning(f"Failed to cancel TP order: {e}")
                self.monitor.stop_monitoring(pair)

            # Get ACTUAL balance from exchange (more reliable than stored quantity)
            # This handles cases where stored qty is wrong or partial fills occurred
            asset_info = self.exchange.has_asset_balance(pair, min_value_usdt=1.0)
            actual_balance = asset_info.get('amount', 0)

            logger.info(f"Actual exchange balance for {pair}: {actual_balance}")

            # Use actual balance if available, otherwise fall back to stored
            if actual_balance > 0:
                quantity = actual_balance * 0.999  # Sell 99.9% to avoid dust issues
            elif stored_quantity > 0:
                quantity = stored_quantity
            else:
                logger.warning(f"No balance to close for {pair}")
                self.manager.remove_position(pair)  # Clean up stale position
                return None

            if quantity <= 0:
                logger.warning(f"Quantity is 0, removing stale position for {pair}")
                self.manager.remove_position(pair)
                return None

            # Opposite side to close
            close_side = 'sell' if side in ['long', 'buy'] else 'buy'

            # Check if the position value is above minimum notional
            current_price = asset_info.get('price', 0)
            position_value = quantity * current_price if current_price > 0 else 0

            if position_value < 5.0:  # Below Binance minimum
                logger.warning(f"Position value ${position_value:.2f} below minimum notional. "
                             f"Cannot close on exchange - removing from tracking.")
                self.manager.remove_position(pair)
                # Return a "success" dict indicating position was cleaned up
                return {'status': 'cleaned', 'reason': 'Position too small to sell'}

            logger.info(f"Closing {pair}: {close_side} {quantity:.8f} (value: ${position_value:.2f})")
            order = self.exchange.place_market_order(pair, close_side, quantity)

            self.manager.remove_position(pair)
            logger.info(f"Closed position: {pair} {side} {quantity:.6f}")

            return order

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to close position {pair}: {error_msg}")

            # Handle NOTIONAL error specifically
            if 'NOTIONAL' in error_msg.upper():
                logger.warning(f"Position too small to sell. Removing from tracking.")
                self.manager.remove_position(pair)
                return {'status': 'cleaned', 'reason': 'Position below minimum notional'}

            # Still try to remove from position manager to avoid stale entries
            try:
                self.manager.remove_position(pair)
            except Exception:
                pass  # Position may not exist
            return None

    def close_position(self, pair: str) -> Dict[str, Any]:
        """Close a specific position"""
        position = self.manager.get_position(pair)
        if not position:
            return {'success': False, 'reason': f"No position for {pair}"}

        order = self._close_position(pair, position)
        if order:
            return {'success': True, 'order': order, 'pair': pair}
        return {'success': False, 'reason': 'Close order failed'}

    def close_all_positions(self) -> Dict[str, Any]:
        """Close all open positions"""
        positions = self.manager.get_all_positions()
        results = []

        if not positions:
            return {
                'success': True,
                'results': [],
                'closed_count': 0,
                'message': 'No positions to close'
            }

        for pair, position in list(positions.items()):  # Use list() to avoid dict mutation issues
            try:
                logger.info(f"Closing position: {pair} {position.get('side')} qty={position.get('quantity')}")
                result = self.close_position(pair)
                result['pair'] = pair
                results.append(result)

                if result.get('success'):
                    logger.info(f"Successfully closed {pair}")
                else:
                    logger.warning(f"Failed to close {pair}: {result.get('reason')}")

            except Exception as e:
                logger.error(f"Exception closing {pair}: {e}")
                results.append({
                    'success': False,
                    'pair': pair,
                    'reason': str(e)
                })

        return {
            'success': all(r.get('success') for r in results),
            'results': results,
            'closed_count': sum(1 for r in results if r.get('success'))
        }

    def check_stop_loss(self, pair: str) -> Optional[Dict]:
        """Check if stop loss is hit for a position"""
        position = self.manager.get_position(pair)
        if not position:
            return None

        try:
            current_price = self.exchange.get_current_price(pair)
            stop_loss = position.get('stop_loss', 0)
            side = position.get('side', '').lower()

            if side in ['long', 'buy'] and current_price <= stop_loss:
                logger.warning(f"Stop loss hit for {pair}: ${current_price} <= ${stop_loss}")
                return self._close_position(pair, position)

            elif side in ['short', 'sell'] and current_price >= stop_loss:
                logger.warning(f"Stop loss hit for {pair}: ${current_price} >= ${stop_loss}")
                return self._close_position(pair, position)

        except Exception as e:
            logger.error(f"Stop loss check failed for {pair}: {e}")

        return None

    def check_take_profit(self, pair: str) -> Optional[Dict]:
        """Check if take profit is hit for a position"""
        position = self.manager.get_position(pair)
        if not position:
            return None

        try:
            current_price = self.exchange.get_current_price(pair)
            take_profit = position.get('take_profit', 0)
            side = position.get('side', '').lower()

            if not take_profit:
                return None

            if side in ['long', 'buy'] and current_price >= take_profit:
                logger.info(f"Take profit hit for {pair}: ${current_price} >= ${take_profit}")
                return self._close_position(pair, position)

            elif side in ['short', 'sell'] and current_price <= take_profit:
                logger.info(f"Take profit hit for {pair}: ${current_price} <= ${take_profit}")
                return self._close_position(pair, position)

        except Exception as e:
            logger.error(f"Take profit check failed for {pair}: {e}")

        return None

    def record_stopout(self, pair: str):
        """Record that a pair was stopped out - prevents immediate re-entry"""
        self._recent_stopouts[pair] = time.time()
        logger.info(f"Recorded stopout for {pair} - {self._stopout_cooldown_seconds}s cooldown active")

    def clear_stopout(self, pair: str):
        """Clear stopout cooldown for a pair"""
        if pair in self._recent_stopouts:
            del self._recent_stopouts[pair]
            logger.info(f"Cleared stopout cooldown for {pair}")

    def force_liquidate_all_to_usdt(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Force sell ALL spot holdings and convert to USDT.

        ⚠️ WARNING: This will incur trading fees (~0.1% per trade)

        Use this when funds are locked in positions and you need liquidity.

        Args:
            dry_run: If True, calculate fees but don't execute

        Returns:
            Summary with positions closed, fees paid, USDT recovered
        """
        results = {
            'success': False,
            'dry_run': dry_run,
            'positions_closed': [],
            'total_value_before': 0,
            'total_fees': 0,
            'usdt_recovered': 0,
            'errors': []
        }

        # Get all tracked positions
        positions = self.manager.get_all_positions()

        if not positions:
            logger.info("No positions to liquidate")
            results['success'] = True
            results['message'] = "No positions to close"
            return results

        # Calculate total value and estimated fees BEFORE executing
        fee_rate = 0.001  # 0.1% Binance fee
        total_value = 0
        estimated_fees = 0

        for pair, position in positions.items():
            try:
                # Only close SPOT positions (futures have different handling)
                if position.get('market') == 'futures':
                    logger.info(f"Skipping futures position {pair}")
                    continue

                current_price = self.exchange.get_current_price(pair)
                quantity = position.get('quantity', 0)
                value = current_price * quantity
                fee = value * fee_rate

                total_value += value
                estimated_fees += fee

                results['positions_closed'].append({
                    'pair': pair,
                    'quantity': quantity,
                    'price': current_price,
                    'value': round(value, 2),
                    'fee': round(fee, 4),
                    'side': position.get('side'),
                    'thesis': position.get('thesis')
                })

            except Exception as e:
                logger.error(f"Error calculating {pair}: {e}")
                results['errors'].append({'pair': pair, 'error': str(e)})

        results['total_value_before'] = round(total_value, 2)
        results['total_fees'] = round(estimated_fees, 4)
        results['usdt_recovered'] = round(total_value - estimated_fees, 2)

        # Show warning
        logger.warning("=" * 50)
        logger.warning("⚠️  FORCE LIQUIDATION WARNING  ⚠️")
        logger.warning(f"Positions to close: {len(results['positions_closed'])}")
        logger.warning(f"Total value: ${results['total_value_before']:.2f}")
        logger.warning(f"Estimated fees: ${results['total_fees']:.4f}")
        logger.warning(f"USDT after fees: ${results['usdt_recovered']:.2f}")
        logger.warning("=" * 50)

        if dry_run:
            logger.info("DRY RUN - No trades executed")
            results['success'] = True
            return results

        # Execute sells
        closed_count = 0
        actual_fees = 0
        actual_usdt = 0

        for pos_info in results['positions_closed']:
            pair = pos_info['pair']
            try:
                # Stop monitoring first
                if self.monitor:
                    self.monitor.stop_monitoring(pair)

                # Get actual balance (more reliable than stored)
                asset_info = self.exchange.has_asset_balance(pair, min_value_usdt=1.0)
                if not asset_info.get('has_balance'):
                    logger.warning(f"{pair}: No balance on exchange, removing from tracking")
                    self.manager.remove_position(pair)
                    continue

                quantity = asset_info['amount'] * 0.999  # Sell 99.9% to avoid dust

                # Place market sell
                logger.info(f"Selling {pair}: {quantity:.6f}")
                order = self.exchange.place_market_order(pair, 'sell', quantity)

                fill_price = float(order.get('average') or order.get('price') or pos_info['price'])
                actual_value = fill_price * quantity
                fee = actual_value * fee_rate

                actual_fees += fee
                actual_usdt += (actual_value - fee)

                # Remove from position tracking
                self.manager.remove_position(pair)
                closed_count += 1

                logger.info(f"✅ Sold {pair}: ${actual_value:.2f} (fee: ${fee:.4f})")

            except Exception as e:
                logger.error(f"❌ Failed to sell {pair}: {e}")
                results['errors'].append({'pair': pair, 'error': str(e)})

        results['success'] = closed_count > 0
        results['closed_count'] = closed_count
        results['actual_fees'] = round(actual_fees, 4)
        results['actual_usdt_recovered'] = round(actual_usdt, 2)

        logger.info("=" * 50)
        logger.info(f"LIQUIDATION COMPLETE")
        logger.info(f"Closed: {closed_count} positions")
        logger.info(f"Fees paid: ${actual_fees:.4f}")
        logger.info(f"USDT recovered: ${actual_usdt:.2f}")
        logger.info("=" * 50)

        return results
