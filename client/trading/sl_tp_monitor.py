# client/trading/sl_tp_monitor.py - Hybrid SL/TP monitoring with trailing stop
import logging
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ExitReason(Enum):
    """Reason for position exit"""
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    BREAKEVEN_STOP = "breakeven_stop"
    MANUAL = "manual"
    SIGNAL_REVERSAL = "signal_reversal"


class TrailingStopConfig:
    """Configuration for trailing stop behavior"""

    def __init__(
        self,
        enabled: bool = True,
        activation_pct: float = 3.5,      # Activate trailing after 3.5% profit (let it breathe)
        trail_pct: float = 0.8,            # Trail 0.8% behind peak (wider to avoid noise)
        breakeven_pct: float = 3.0,        # Move SL to breakeven after 3.0% profit (was 1.5% - fees ate profit)
        breakeven_buffer_pct: float = 0.15  # Add 0.15% buffer above entry for breakeven
    ):
        self.enabled = enabled
        self.activation_pct = activation_pct
        self.trail_pct = trail_pct
        self.breakeven_pct = breakeven_pct
        self.breakeven_buffer_pct = breakeven_buffer_pct


class SLTPMonitor:
    """
    Hybrid Stop Loss / Take Profit monitor for maximum profit.

    Features:
    - Real-time SL/TP monitoring
    - Trailing stop (locks in profits as price moves up)
    - Breakeven stop (moves SL to entry after X% profit)
    - Works with limit TP orders on exchange + local SL monitoring
    """

    def __init__(
        self,
        exchange_client,
        position_manager,
        trailing_config: TrailingStopConfig = None
    ):
        self.exchange = exchange_client
        self.manager = position_manager
        self.config = trailing_config or TrailingStopConfig()

        # Track peak prices for trailing stop
        self.peak_prices: Dict[str, float] = {}

        # Track if breakeven has been activated
        self.breakeven_activated: Dict[str, bool] = {}

        # Track if trailing stop is active
        self.trailing_active: Dict[str, bool] = {}

        # Track TP order IDs placed on exchange
        self.tp_order_ids: Dict[str, str] = {}

        # Track failed exit attempts to remove stale positions
        self._exit_failures: Dict[str, int] = {}
        self._max_exit_failures = 3  # Remove position after 3 failed exit attempts

        # Callbacks
        self.on_exit: Optional[Callable[[str, ExitReason, Dict], None]] = None
        self.on_sl_updated: Optional[Callable[[str, float, str], None]] = None

        logger.info("SL/TP Monitor initialized with trailing stop")

    def start_monitoring(self, pair: str, tp_order_id: str = None):
        """Start monitoring a position"""
        position = self.manager.get_position(pair)
        if not position:
            return

        # Use thesis_entry for tracking (SL/TP are based on thesis)
        thesis_entry = position.get('thesis_entry', position['entry_price'])
        thesis = position.get('thesis', position['side'])

        # Initialize tracking with thesis entry
        self.peak_prices[pair] = thesis_entry
        self.breakeven_activated[pair] = False
        self.trailing_active[pair] = False

        if tp_order_id:
            self.tp_order_ids[pair] = tp_order_id

        logger.info(f"Started monitoring {pair} ({thesis.upper()}) - Entry: ${thesis_entry:.2f}, "
                   f"SL: ${position['stop_loss']:.2f}, TP: ${position['take_profit']:.2f}")

    def stop_monitoring(self, pair: str):
        """Stop monitoring a position"""
        self.peak_prices.pop(pair, None)
        self.breakeven_activated.pop(pair, None)
        self.trailing_active.pop(pair, None)
        self.tp_order_ids.pop(pair, None)
        logger.info(f"Stopped monitoring {pair}")

    def check_position(self, pair: str) -> Optional[Dict[str, Any]]:
        """
        Check a single position for SL/TP/trailing conditions.

        Returns exit info if position should be closed, None otherwise.
        """
        position = self.manager.get_position(pair)
        if not position:
            return None

        # === MINIMUM HOLD TIME - Prevent fee churning ===
        # Don't check TP for first 10 minutes (let position develop)
        # SL is still checked immediately for protection
        from datetime import datetime
        entry_time_str = position.get('entry_time', '')
        min_hold_seconds = 180  # Minimum 3 minutes before TP can trigger (was 10 min - missed fast moves)

        try:
            entry_time = datetime.fromisoformat(entry_time_str)
            hold_duration = (datetime.utcnow() - entry_time).total_seconds()
            hold_hours = hold_duration / 3600
            position_too_new = hold_duration < min_hold_seconds
        except (ValueError, TypeError, AttributeError):
            # Failed to parse entry time, assume position is not too new
            logger.debug(f"Failed to parse entry_time for {pair}: {entry_time_str}")
            position_too_new = False
            hold_hours = 0

        # === TIME-BASED EXIT - Don't hold losers forever ===
        # If position is stuck for too long with minimal movement, close it
        max_hold_hours = 120  # Maximum 5 days (120 hours) - give trades time to work
        if hold_hours > max_hold_hours:
            logger.warning(f"⏰ {pair}: Position held for {hold_hours:.1f} hours (>{max_hold_hours}h) - forcing exit")
            thesis = position.get('thesis', position['side']).lower()
            return {
                'pair': pair,
                'reason': ExitReason.MANUAL,  # Time-based exit
                'exit_price': self.exchange.get_current_price(pair),
                'quantity': position['quantity'],
                'profit_pct': 0,
                'thesis': thesis,
                'actual_side': position['side'].lower(),
                'time_exit': True
            }

        # Check if TP order was filled on exchange (position closed externally)
        if pair in self.tp_order_ids:
            try:
                filled, order_exists = self.exchange.is_order_filled(self.tp_order_ids[pair], pair)

                if filled:
                    # Order was CONFIRMED filled - safe to remove position
                    take_profit = position.get('take_profit', 0)
                    self.manager.update_unrealized_pnl(pair, take_profit)
                    final_pnl = position.get('unrealized_pnl_net', 0)

                    logger.info(f"🎯 {pair} TP order filled on exchange @ ${take_profit:.2f}, P&L: ${final_pnl:.2f}")

                    # Callback for UI update
                    if self.on_exit:
                        self.on_exit(pair, ExitReason.TAKE_PROFIT, {
                            'fill_price': take_profit,
                            'pnl': final_pnl,
                            'order': None
                        })

                    self.manager.remove_position(pair)
                    self.stop_monitoring(pair)
                    return None  # Already closed, no action needed

                elif not order_exists:
                    # Order doesn't exist - could be filled, cancelled, or API error
                    # Check if this is a FUTURES position (symbol contains ':')
                    is_futures = ':' in pair

                    if is_futures:
                        # FUTURES: Check if position still exists via futures API
                        position_exists = self._check_futures_position_exists(pair)
                        logger.info(f"🔍 {pair} TP order missing - FUTURES position check: exists={position_exists}")

                        if position_exists:
                            # Position still open on exchange
                            logger.warning(f"⚠️ {pair} FUTURES TP order missing but position still exists! Continuing to monitor...")
                            del self.tp_order_ids[pair]
                            # DON'T remove position - continue monitoring
                        else:
                            # Futures position closed
                            take_profit = position.get('take_profit', 0)
                            self.manager.update_unrealized_pnl(pair, take_profit)
                            final_pnl = position.get('unrealized_pnl_net', 0)
                            logger.info(f"🎯 {pair} FUTURES position closed - assuming TP filled @ ${take_profit:.2f}")

                            if self.on_exit:
                                self.on_exit(pair, ExitReason.TAKE_PROFIT, {
                                    'fill_price': take_profit,
                                    'pnl': final_pnl,
                                    'order': None
                                })

                            self.manager.remove_position(pair)
                            self.stop_monitoring(pair)
                            return None
                    else:
                        # SPOT: Check TOTAL balance (free + used), not just free
                        asset_info = self.exchange.has_asset_balance(pair, min_value_usdt=1.0)

                        # Log detailed balance info for debugging
                        logger.info(f"🔍 {pair} TP order missing - SPOT balance check: "
                                   f"total={asset_info.get('amount', 0):.6f}, "
                                   f"free={asset_info.get('free', 0):.6f}, "
                                   f"used={asset_info.get('used', 0):.6f}, "
                                   f"value=${asset_info.get('usdt_value', 0):.2f}")

                        if asset_info.get('has_balance'):
                            # Asset still exists (either free or locked in orders)
                            used = asset_info.get('used', 0)
                            free = asset_info.get('free', 0)

                            if used > 0:
                                # Asset is locked in an order - check for open orders
                                logger.warning(f"⚠️ {pair} TP order missing but {used:.6f} assets locked in orders! "
                                             f"Checking for other open orders...")
                                try:
                                    open_orders = self.exchange.get_open_orders(pair)
                                    if open_orders:
                                        logger.info(f"📋 {pair} has {len(open_orders)} open order(s) - position still active")
                                        # Maybe TP was replaced with another order, clear our tracking
                                        del self.tp_order_ids[pair]
                                    else:
                                        logger.warning(f"⚠️ {pair} no open orders found but used balance exists - exchange state unclear")
                                        del self.tp_order_ids[pair]
                                except Exception as e:
                                    logger.warning(f"Could not check open orders: {e}")
                                    del self.tp_order_ids[pair]
                            else:
                                # Asset is free (not locked) - order was cancelled, NOT filled
                                logger.warning(f"⚠️ {pair} TP order missing but asset still FREE on exchange! "
                                             f"Balance: {free:.6f} - continuing to monitor")
                                del self.tp_order_ids[pair]

                            # DON'T remove position - continue monitoring
                        else:
                            # Truly no asset on exchange (free=0, used=0, total=0)
                            # Position was likely closed externally
                            take_profit = position.get('take_profit', 0)
                            self.manager.update_unrealized_pnl(pair, take_profit)
                            final_pnl = position.get('unrealized_pnl_net', 0)
                            logger.info(f"🎯 {pair} SPOT TP order gone and NO asset on exchange (free=0, used=0) - assuming filled @ ${take_profit:.2f}")

                            if self.on_exit:
                                self.on_exit(pair, ExitReason.TAKE_PROFIT, {
                                    'fill_price': take_profit,
                                    'pnl': final_pnl,
                                    'order': None
                                })

                            self.manager.remove_position(pair)
                            self.stop_monitoring(pair)
                            return None
            except Exception as e:
                logger.debug(f"Could not check TP order status: {e}")

        try:
            current_price = self.exchange.get_current_price(pair)
        except Exception as e:
            logger.warning(f"Failed to get price for {pair}: {e}")
            return None

        # Use THESIS for direction (can be flipped without trading)
        thesis = position.get('thesis', position['side']).lower()
        thesis_entry = position.get('thesis_entry', position['entry_price'])
        stop_loss = position['stop_loss']
        take_profit = position['take_profit']
        actual_side = position['side'].lower()  # What we actually hold
        quantity = position['quantity']

        # Update unrealized P&L based on THESIS
        self.manager.update_unrealized_pnl(pair, current_price)

        # Calculate profit percentage based on THESIS entry
        if thesis in ['long', 'buy']:
            profit_pct = ((current_price - thesis_entry) / thesis_entry) * 100
        else:
            profit_pct = ((thesis_entry - current_price) / thesis_entry) * 100

        # Update peak price for trailing stop (based on thesis direction)
        if pair not in self.peak_prices:
            self.peak_prices[pair] = thesis_entry

        if thesis in ['long', 'buy']:
            if current_price > self.peak_prices[pair]:
                self.peak_prices[pair] = current_price
                logger.debug(f"{pair} new peak: ${current_price:.2f}")
        else:  # SHORT thesis
            if current_price < self.peak_prices[pair]:
                self.peak_prices[pair] = current_price
                logger.debug(f"{pair} new low (short thesis): ${current_price:.2f}")

        # === CHECK EXIT CONDITIONS (based on THESIS direction) ===

        # 1. Check Stop Loss
        if self._check_stop_loss_hit(thesis, current_price, stop_loss):
            reason = ExitReason.TRAILING_STOP if self.trailing_active.get(pair) else ExitReason.STOP_LOSS
            if self.breakeven_activated.get(pair) and not self.trailing_active.get(pair):
                reason = ExitReason.BREAKEVEN_STOP

            return {
                'pair': pair,
                'reason': reason,
                'exit_price': current_price,
                'quantity': quantity,
                'profit_pct': profit_pct,
                'thesis': thesis,
                'actual_side': actual_side  # What we actually hold (always sell this)
            }

        # 2. Check Take Profit (if no TP order on exchange)
        # SKIP TP check if position is too new (prevents fee churning)
        if pair not in self.tp_order_ids and take_profit > 0:
            if position_too_new:
                logger.debug(f"{pair}: Position too new ({hold_duration:.0f}s < {min_hold_seconds}s), skipping TP check")
            elif self._check_take_profit_hit(thesis, current_price, take_profit):
                return {
                    'pair': pair,
                    'reason': ExitReason.TAKE_PROFIT,
                    'exit_price': current_price,
                    'quantity': quantity,
                    'profit_pct': profit_pct,
                    'thesis': thesis,
                    'actual_side': actual_side
                }

        # === UPDATE TRAILING STOP (based on THESIS) ===
        if self.config.enabled:
            self._update_trailing_stop(pair, position, current_price, profit_pct, thesis)

        return None

    def check_all_positions(self) -> list:
        """Check all positions and return list of exits needed"""
        exits = []
        positions = self.manager.get_all_positions()

        for pair in positions:
            result = self.check_position(pair)
            if result:
                exits.append(result)

        return exits

    def _check_stop_loss_hit(self, side: str, current_price: float, stop_loss: float) -> bool:
        """Check if stop loss is hit"""
        if stop_loss <= 0:
            return False

        if side in ['long', 'buy']:
            return current_price <= stop_loss
        else:
            return current_price >= stop_loss

    def _check_take_profit_hit(self, side: str, current_price: float, take_profit: float) -> bool:
        """Check if take profit is hit"""
        if take_profit <= 0:
            return False

        if side in ['long', 'buy']:
            return current_price >= take_profit
        else:
            return current_price <= take_profit

    def _update_trailing_stop(self, pair: str, position: Dict, current_price: float, profit_pct: float, thesis: str = None):
        """Update trailing stop based on current price and THESIS direction"""
        thesis_entry = position.get('thesis_entry', position['entry_price'])
        current_sl = position['stop_loss']
        # Use passed thesis or fall back to position thesis/side
        if thesis is None:
            thesis = position.get('thesis', position['side']).lower()

        # 1. Activate breakeven stop
        if not self.breakeven_activated.get(pair) and profit_pct >= self.config.breakeven_pct:
            if thesis in ['long', 'buy']:
                # Move SL to thesis entry + small buffer
                new_sl = thesis_entry * (1 + self.config.breakeven_buffer_pct / 100)
                if new_sl > current_sl:
                    self._update_stop_loss(pair, new_sl, "breakeven")
                    self.breakeven_activated[pair] = True
            else:  # SHORT thesis
                new_sl = thesis_entry * (1 - self.config.breakeven_buffer_pct / 100)
                if new_sl < current_sl:
                    self._update_stop_loss(pair, new_sl, "breakeven")
                    self.breakeven_activated[pair] = True

        # 2. Activate and update trailing stop
        if profit_pct >= self.config.activation_pct:
            self.trailing_active[pair] = True
            peak = self.peak_prices.get(pair, current_price)

            if thesis in ['long', 'buy']:
                # Trail below peak
                trail_sl = peak * (1 - self.config.trail_pct / 100)
                if trail_sl > current_sl:
                    self._update_stop_loss(pair, trail_sl, "trailing")
            else:  # SHORT thesis
                # Trail above trough (lowest point for short)
                trail_sl = peak * (1 + self.config.trail_pct / 100)
                if trail_sl < current_sl:
                    self._update_stop_loss(pair, trail_sl, "trailing")

    def _update_stop_loss(self, pair: str, new_sl: float, reason: str):
        """Update stop loss in position manager (thread-safe)"""
        # Use position manager's thread-safe update method
        success = self.manager.update_stop_loss(pair, new_sl, reason)

        if success and self.on_sl_updated:
            self.on_sl_updated(pair, new_sl, reason)

    def execute_exit(self, exit_info: Dict) -> Dict[str, Any]:
        """Execute an exit order"""
        pair = exit_info['pair']
        quantity = exit_info['quantity']
        # Use actual_side (what we hold) not thesis for execution
        actual_side = exit_info.get('actual_side', exit_info.get('thesis', exit_info.get('side', 'long')))
        thesis = exit_info.get('thesis', actual_side)
        reason = exit_info['reason']

        try:
            # Cancel any TP order on exchange
            if pair in self.tp_order_ids:
                try:
                    self.exchange.cancel_order(self.tp_order_ids[pair], pair)
                    logger.info(f"Cancelled TP order for {pair}")
                except Exception as e:
                    logger.warning(f"Failed to cancel TP order: {e}")

            # Place market exit order - ALWAYS based on actual holding
            # If we hold asset (bought it), we SELL to exit
            exit_side = 'sell' if actual_side in ['long', 'buy'] else 'buy'
            order = self.exchange.place_market_order(pair, exit_side, quantity)

            fill_price = float(order.get('average') or order.get('price') or exit_info['exit_price'])

            # Update position with final P&L
            self.manager.update_unrealized_pnl(pair, fill_price)
            position = self.manager.get_position(pair)
            final_pnl = position.get('unrealized_pnl_net', 0) if position else 0

            # Remove position
            self.manager.remove_position(pair)
            self.stop_monitoring(pair)

            logger.info(f"Exit executed: {pair} {reason.value} @ ${fill_price:.2f}, P&L: ${final_pnl:.2f}")

            if self.on_exit:
                self.on_exit(pair, reason, {
                    'fill_price': fill_price,
                    'pnl': final_pnl,
                    'order': order
                })

            return {
                'success': True,
                'pair': pair,
                'reason': reason.value,
                'fill_price': fill_price,
                'pnl': final_pnl,
                'order': order
            }

        except Exception as e:
            error_str = str(e).lower()
            logger.error(f"Exit execution failed for {pair}: {e}")

            # Track failed exit attempts
            self._exit_failures[pair] = self._exit_failures.get(pair, 0) + 1
            failures = self._exit_failures[pair]

            # Check for "insufficient funds" - means asset doesn't exist on exchange
            if 'insufficient' in error_str or 'balance' in error_str:
                logger.warning(f"Asset {pair} likely doesn't exist on exchange (attempt {failures}/{self._max_exit_failures})")

                # Remove stale position after max failures
                if failures >= self._max_exit_failures:
                    logger.warning(f"REMOVING STALE POSITION {pair} after {failures} failed exit attempts")
                    self.manager.remove_position(pair)
                    self.stop_monitoring(pair)
                    self._exit_failures.pop(pair, None)

                    return {
                        'success': True,  # Mark as "success" since we cleaned it up
                        'pair': pair,
                        'reason': 'stale_position_removed',
                        'error': 'Position removed - asset not available on exchange'
                    }

            return {
                'success': False,
                'pair': pair,
                'reason': reason.value,
                'error': str(e),
                'failures': failures
            }

    def place_tp_order_on_exchange(self, pair: str) -> Optional[str]:
        """
        Place a limit TP order on the exchange.
        Returns order ID if successful.
        """
        position = self.manager.get_position(pair)
        if not position:
            return None

        take_profit = position['take_profit']
        quantity = position['quantity']
        side = position['side'].lower()

        if take_profit <= 0:
            return None

        try:
            # For LONG, place limit sell at TP
            # For SHORT, place limit buy at TP
            order_side = 'sell' if side in ['long', 'buy'] else 'buy'

            order = self.exchange.place_limit_order(pair, order_side, quantity, take_profit)
            order_id = order.get('id')

            if order_id:
                self.tp_order_ids[pair] = order_id
                logger.info(f"TP order placed on exchange: {pair} {order_side} {quantity} @ ${take_profit:.2f}")

            return order_id

        except Exception as e:
            logger.error(f"Failed to place TP order for {pair}: {e}")
            return None

    def get_monitoring_status(self, pair: str) -> Dict[str, Any]:
        """Get monitoring status for a position"""
        position = self.manager.get_position(pair)
        if not position:
            return {'monitoring': False}

        return {
            'monitoring': True,
            'pair': pair,
            'entry_price': position['entry_price'],
            'current_sl': position['stop_loss'],
            'take_profit': position['take_profit'],
            'peak_price': self.peak_prices.get(pair),
            'breakeven_activated': self.breakeven_activated.get(pair, False),
            'trailing_active': self.trailing_active.get(pair, False),
            'tp_order_on_exchange': pair in self.tp_order_ids
        }

    def update_config(self, **kwargs):
        """Update trailing stop configuration"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        logger.info(f"Trailing config updated: {kwargs}")

    def _check_futures_position_exists(self, pair: str) -> bool:
        """
        Check if a futures position still exists on the exchange.

        Args:
            pair: Trading pair with futures suffix (e.g., 'ADAUSDT:USDT')

        Returns:
            True if position exists with non-zero contracts, False otherwise
        """
        try:
            if not self.exchange.futures_connected:
                logger.warning(f"Cannot check futures position - not connected to futures")
                return True  # Assume exists if we can't check (safer)

            position = self.exchange.get_futures_position(pair)

            if position:
                contracts = abs(float(position.get('contracts', 0) or 0))
                notional = abs(float(position.get('notional', 0) or 0))

                logger.debug(f"Futures position check {pair}: contracts={contracts}, notional={notional}")

                # Position exists if has contracts or notional value
                if contracts > 0 or notional > 0:
                    logger.info(f"✅ {pair} FUTURES position still exists: {contracts} contracts, ${notional:.2f}")
                    return True

            logger.info(f"❌ {pair} FUTURES position NOT found on exchange")
            return False

        except Exception as e:
            logger.warning(f"Error checking futures position {pair}: {e}")
            return True  # Assume exists on error (safer - don't remove position)

    def sync_positions_with_exchange(self) -> Dict[str, Any]:
        """
        Synchronize local positions with actual exchange balances.
        Handles both SPOT and FUTURES positions correctly.
        Removes stale positions that no longer exist on exchange.
        Returns summary of what was synced.
        """
        positions = self.manager.get_all_positions()
        removed = []
        kept = []
        issues = []

        for pair, position in list(positions.items()):
            try:
                # Check if this is a FUTURES position (symbol contains ':')
                is_futures = ':' in pair

                if is_futures:
                    # FUTURES: Check via futures API
                    position_exists = self._check_futures_position_exists(pair)

                    if not position_exists:
                        logger.warning(f"SYNC: {pair} FUTURES position tracked but NOT on exchange - removing")
                        self.manager.remove_position(pair)
                        self.stop_monitoring(pair)
                        removed.append({
                            'pair': pair,
                            'type': 'futures',
                            'reason': 'no_position_on_exchange',
                            'stored_qty': position.get('quantity', 0)
                        })
                    else:
                        kept.append(pair)
                        logger.info(f"SYNC: {pair} FUTURES position verified on exchange")

                else:
                    # SPOT: Check asset balance
                    asset_info = self.exchange.has_asset_balance(pair, min_value_usdt=1.0)

                    if not asset_info.get('has_balance'):
                        # No asset on exchange but we have position tracked
                        logger.warning(f"SYNC: {pair} SPOT position tracked but no asset on exchange - removing")
                        self.manager.remove_position(pair)
                        self.stop_monitoring(pair)
                        removed.append({
                            'pair': pair,
                            'type': 'spot',
                            'reason': 'no_asset_on_exchange',
                            'stored_qty': position.get('quantity', 0)
                        })
                    else:
                        # Asset exists - position is valid
                        actual_qty = asset_info.get('amount', 0)
                        stored_qty = position.get('quantity', 0)

                        # Check for quantity mismatch
                        if stored_qty > 0 and abs(actual_qty - stored_qty) / stored_qty > 0.1:
                            logger.warning(f"SYNC: {pair} quantity mismatch - stored: {stored_qty:.6f}, actual: {actual_qty:.6f}")
                            issues.append({
                                'pair': pair,
                                'issue': 'quantity_mismatch',
                                'stored': stored_qty,
                                'actual': actual_qty
                            })

                        kept.append(pair)
                        logger.info(f"SYNC: {pair} SPOT position verified on exchange")

            except Exception as e:
                logger.error(f"SYNC: Error checking {pair}: {e}")
                issues.append({'pair': pair, 'issue': str(e)})

        result = {
            'synced': True,
            'removed_count': len(removed),
            'removed': removed,
            'kept_count': len(kept),
            'kept': kept,
            'issues': issues
        }

        logger.info(f"Position sync complete: kept {len(kept)}, removed {len(removed)}, issues {len(issues)}")
        return result
