# client/trading/position_manager.py - Active position tracking
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json
import os

from client.config import (
    get_trading_fee, get_round_trip_cost,
    MAX_DAILY_DRAWDOWN_PERCENT, MAX_WEEKLY_DRAWDOWN_PERCENT,
    CIRCUIT_BREAKER_COOLDOWN_HOURS, MAX_CONSECUTIVE_LOSSES, MIN_WIN_RATE_THRESHOLD
)

logger = logging.getLogger(__name__)


class PositionManager:
    """Manage active trading positions"""

    def __init__(self, persist_file: str = "positions.json"):
        self.positions: Dict[str, Dict[str, Any]] = {}
        self.persist_file = persist_file
        self.trade_history: List[Dict] = []

        # Load persisted positions
        self._load_positions()

    def add_position(
        self,
        pair: str,
        side: str,
        entry_price: float,
        quantity: float,
        stop_loss: float = 0,
        take_profit: float = 0,
        order_id: str = None,
        exchange: str = "binance",
        market: str = "spot"
    ):
        """Add a new position (spot or futures)"""
        # Calculate entry fee
        entry_fee = entry_price * quantity * get_trading_fee(exchange)

        self.positions[pair.upper()] = {
            'pair': pair.upper(),
            'side': side.lower(),           # Actual holding: 'long' = bought asset
            'thesis': side.lower(),          # Current thesis: can flip without trading
            'thesis_entry': entry_price,     # Entry price for current thesis
            'entry_price': entry_price,      # Original buy price
            'market': market,                # 'spot' or 'futures'
            'quantity': quantity,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'order_id': order_id,
            'exchange': exchange,
            'entry_fee': entry_fee,
            'entry_time': datetime.utcnow().isoformat(),
            'flip_count': 0,                 # Track how many times position was flipped
            'unrealized_pnl': 0,
            'unrealized_pnl_pct': 0,
            'unrealized_pnl_net': 0,  # P&L after fees
        }

        market_label = f"[{market.upper()}]" if market != "spot" else ""
        logger.info(f"Position added: {pair} {side} {quantity:.6f} @ ${entry_price:.2f} {market_label} (fee: ${entry_fee:.4f})")
        self._save_positions()

    def flip_position(
        self,
        pair: str,
        new_thesis: str,
        new_entry: float,
        new_stop_loss: float,
        new_take_profit: float
    ) -> bool:
        """
        Flip position thesis WITHOUT trading (saves fees).

        Example: Have LONG (bought BTC), flip to SHORT thesis
        - Still hold BTC, but now betting price goes DOWN
        - SL is now ABOVE current price
        - TP is now BELOW current price
        - Only actually sell when SL or TP is hit

        Returns True if flipped successfully.
        """
        pair = pair.upper()
        if pair not in self.positions:
            logger.warning(f"Cannot flip {pair}: no position exists")
            return False

        position = self.positions[pair]
        old_thesis = position.get('thesis', position['side'])

        if old_thesis == new_thesis.lower():
            logger.info(f"{pair} already has {new_thesis} thesis, updating SL/TP only")
        else:
            logger.info(f"FLIP {pair}: {old_thesis.upper()} → {new_thesis.upper()} (NO FEE)")

        # Update thesis and levels
        position['thesis'] = new_thesis.lower()
        position['thesis_entry'] = new_entry
        position['stop_loss'] = new_stop_loss
        position['take_profit'] = new_take_profit
        position['flip_count'] = position.get('flip_count', 0) + 1
        position['last_flip_time'] = datetime.utcnow().isoformat()

        self._save_positions()
        return True

    def get_thesis(self, pair: str) -> Optional[str]:
        """Get current thesis for a position (may differ from actual holding)"""
        position = self.get_position(pair)
        if position:
            return position.get('thesis', position.get('side'))
        return None

    def remove_position(self, pair: str) -> Optional[Dict]:
        """Remove a position and add to history"""
        pair = pair.upper()
        if pair in self.positions:
            position = self.positions.pop(pair)

            # Add to trade history
            position['exit_time'] = datetime.utcnow().isoformat()
            self.trade_history.append(position)

            logger.info(f"Position removed: {pair}")
            self._save_positions()
            return position
        return None

    def get_position(self, pair: str) -> Optional[Dict]:
        """Get position for a pair"""
        return self.positions.get(pair.upper())

    def get_all_positions(self) -> Dict[str, Dict]:
        """Get all active positions"""
        return self.positions.copy()

    def has_position(self, pair: str) -> bool:
        """Check if position exists for pair"""
        return pair.upper() in self.positions

    def update_unrealized_pnl(self, pair: str, current_price: float):
        """Update unrealized P&L for a position based on THESIS (including fees)"""
        pair = pair.upper()
        if pair not in self.positions:
            return

        position = self.positions[pair]
        # Use THESIS entry for P&L calculation (not original buy price)
        thesis = position.get('thesis', position['side']).lower()
        thesis_entry = position.get('thesis_entry', position['entry_price'])
        quantity = position['quantity']
        exchange = position.get('exchange', 'binance')
        entry_fee = position.get('entry_fee', 0)

        # Calculate gross P&L based on THESIS direction
        if thesis in ['long', 'buy']:
            pnl_gross = (current_price - thesis_entry) * quantity
            pnl_pct_gross = ((current_price - thesis_entry) / thesis_entry) * 100
        else:  # SHORT thesis
            pnl_gross = (thesis_entry - current_price) * quantity
            pnl_pct_gross = ((thesis_entry - current_price) / thesis_entry) * 100

        # Calculate exit fee (estimated) - only pay this once when actually exiting
        exit_fee = current_price * quantity * get_trading_fee(exchange)

        # For flipped positions, we only pay exit fee (no entry fee for the flip)
        flip_count = position.get('flip_count', 0)
        if flip_count > 0:
            # Position was flipped - only count exit fee
            total_fees = exit_fee
        else:
            # Original position - count entry + exit fee
            total_fees = entry_fee + exit_fee

        # Net P&L = Gross P&L - Total Fees
        pnl_net = pnl_gross - total_fees
        position_value = thesis_entry * quantity
        pnl_pct_net = (pnl_net / position_value) * 100 if position_value > 0 else 0

        position['unrealized_pnl'] = round(pnl_gross, 4)
        position['unrealized_pnl_pct'] = round(pnl_pct_gross, 2)
        position['unrealized_pnl_net'] = round(pnl_net, 4)
        position['unrealized_pnl_pct_net'] = round(pnl_pct_net, 2)
        position['current_price'] = current_price
        position['estimated_fees'] = round(total_fees, 4)

    def get_total_exposure(self) -> float:
        """Get total USDT exposure across all positions"""
        total = 0
        for position in self.positions.values():
            total += position['entry_price'] * position['quantity']
        return total

    def get_position_count(self) -> int:
        """Get number of open positions"""
        return len(self.positions)

    def get_total_unrealized_pnl(self) -> float:
        """Get total unrealized P&L"""
        return sum(p.get('unrealized_pnl', 0) for p in self.positions.values())

    def get_trade_stats(self) -> Dict[str, Any]:
        """Get trading statistics from history"""
        if not self.trade_history:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0
            }

        wins = [t for t in self.trade_history if t.get('unrealized_pnl', 0) > 0]
        losses = [t for t in self.trade_history if t.get('unrealized_pnl', 0) <= 0]

        total_trades = len(self.trade_history)
        win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

        avg_win = sum(t.get('unrealized_pnl', 0) for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t.get('unrealized_pnl', 0) for t in losses) / len(losses)) if losses else 0

        total_wins = sum(t.get('unrealized_pnl', 0) for t in wins)
        total_losses = abs(sum(t.get('unrealized_pnl', 0) for t in losses))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0

        return {
            'total_trades': total_trades,
            'win_count': len(wins),
            'loss_count': len(losses),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'total_pnl': total_wins - total_losses
        }

    def _save_positions(self):
        """Persist positions to file"""
        try:
            data = {
                'positions': self.positions,
                'trade_history': self.trade_history[-100:]  # Keep last 100 trades
            }
            with open(self.persist_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save positions: {e}")

    def _load_positions(self):
        """Load positions from file"""
        try:
            if os.path.exists(self.persist_file):
                with open(self.persist_file, 'r') as f:
                    data = json.load(f)
                    self.positions = data.get('positions', {})
                    self.trade_history = data.get('trade_history', [])
                    logger.info(f"Loaded {len(self.positions)} positions")
                    # Validate and fix loaded positions
                    self._validate_and_fix_positions()
        except Exception as e:
            logger.error(f"Failed to load positions: {e}")

    def _validate_and_fix_positions(self, expected_exchange: str = None):
        """Validate all positions and fix any corrupted SL/TP values"""
        fixed_count = 0
        removed_count = 0
        to_remove = []

        for pair, position in self.positions.items():
            # Use THESIS for SL/TP validation (SL/TP are based on thesis direction)
            thesis = position.get('thesis', position.get('side', '')).lower()
            thesis_entry = position.get('thesis_entry', position.get('entry_price', 0))
            stop_loss = position.get('stop_loss', 0)
            take_profit = position.get('take_profit', 0)
            side = position.get('side', '').lower()
            position_exchange = position.get('exchange', 'unknown')

            # Validate exchange matches if specified
            if expected_exchange and position_exchange != expected_exchange:
                logger.warning(f"REMOVING {pair}: Position from {position_exchange} but connected to {expected_exchange}")
                to_remove.append(pair)
                removed_count += 1
                continue

            # Remove positions with missing required fields
            if not side:
                logger.warning(f"REMOVING {pair}: Missing 'side' field")
                to_remove.append(pair)
                removed_count += 1
                continue

            if not position.get('quantity'):
                logger.warning(f"REMOVING {pair}: Missing 'quantity' field")
                to_remove.append(pair)
                removed_count += 1
                continue

            # Remove positions with zero or corrupted entry
            if thesis_entry <= 0:
                logger.warning(f"REMOVING {pair}: Invalid thesis entry price {thesis_entry}")
                to_remove.append(pair)
                removed_count += 1
                continue

            # Fix positions based on THESIS direction (not holding side)
            if thesis in ['long', 'buy']:
                # For LONG thesis: SL must be below thesis_entry
                if stop_loss >= thesis_entry:
                    old_sl = stop_loss
                    position['stop_loss'] = thesis_entry * 0.98  # 2% below
                    logger.warning(f"FIXED {pair} LONG thesis SL: ${old_sl:.4f} -> ${position['stop_loss']:.4f}")
                    fixed_count += 1

                # For LONG thesis: TP must be above thesis_entry
                if take_profit <= thesis_entry:
                    old_tp = take_profit
                    position['take_profit'] = thesis_entry * 1.04  # 4% above
                    logger.warning(f"FIXED {pair} LONG thesis TP: ${old_tp:.4f} -> ${position['take_profit']:.4f}")
                    fixed_count += 1

            # Fix SHORT thesis positions
            elif thesis in ['short', 'sell']:
                # For SHORT thesis: SL must be above thesis_entry
                if stop_loss <= thesis_entry:
                    old_sl = stop_loss
                    position['stop_loss'] = thesis_entry * 1.02  # 2% above
                    logger.warning(f"FIXED {pair} SHORT thesis SL: ${old_sl:.4f} -> ${position['stop_loss']:.4f}")
                    fixed_count += 1

                # For SHORT thesis: TP must be below thesis_entry
                if take_profit >= thesis_entry:
                    old_tp = take_profit
                    position['take_profit'] = thesis_entry * 0.96  # 4% below
                    logger.warning(f"FIXED {pair} SHORT thesis TP: ${old_tp:.4f} -> ${position['take_profit']:.4f}")
                    fixed_count += 1

        # Remove corrupted positions
        for pair in to_remove:
            del self.positions[pair]

        if fixed_count > 0 or removed_count > 0:
            logger.info(f"Position validation: fixed {fixed_count} values, removed {removed_count} corrupted positions")
            self._save_positions()

    def fix_all_positions(self, exchange: str = None) -> Dict[str, Any]:
        """Manually trigger position validation and fixing. Returns summary."""
        before_count = len(self.positions)
        self._validate_and_fix_positions(expected_exchange=exchange)
        after_count = len(self.positions)
        return {
            'before': before_count,
            'after': after_count,
            'removed': before_count - after_count,
            'positions': list(self.positions.keys())
        }

    def clear_all_positions(self) -> int:
        """Clear all positions (useful when switching exchanges)"""
        count = len(self.positions)
        self.positions = {}
        self._save_positions()
        logger.info(f"Cleared {count} positions")
        return count

    def filter_by_exchange(self, exchange: str) -> Dict[str, Any]:
        """Remove positions from other exchanges"""
        return self.fix_all_positions(exchange=exchange)

    # ===================== CIRCUIT BREAKER METHODS =====================

    def check_circuit_breaker(self, starting_balance: float) -> Dict[str, Any]:
        """
        Check if trading should be paused due to drawdown or losses.

        Args:
            starting_balance: Balance at start of session (for daily drawdown)

        Returns:
            Dict with:
                - trading_allowed: bool
                - reason: str (if paused)
                - stats: dict of current stats
        """
        result = {
            'trading_allowed': True,
            'reason': None,
            'stats': {}
        }

        # Get recent trade history
        now = datetime.utcnow()
        one_day_ago = now - timedelta(days=1)
        one_week_ago = now - timedelta(days=7)

        daily_trades = []
        weekly_trades = []
        consecutive_losses = 0

        for trade in reversed(self.trade_history):
            exit_time_str = trade.get('exit_time')
            if exit_time_str:
                try:
                    exit_time = datetime.fromisoformat(exit_time_str)

                    if exit_time > one_day_ago:
                        daily_trades.append(trade)

                    if exit_time > one_week_ago:
                        weekly_trades.append(trade)
                except:
                    pass

        # Calculate daily P&L
        daily_pnl = sum(t.get('unrealized_pnl_net', t.get('unrealized_pnl', 0)) for t in daily_trades)
        daily_pnl_pct = (daily_pnl / starting_balance * 100) if starting_balance > 0 else 0

        # Calculate weekly P&L
        weekly_pnl = sum(t.get('unrealized_pnl_net', t.get('unrealized_pnl', 0)) for t in weekly_trades)
        weekly_pnl_pct = (weekly_pnl / starting_balance * 100) if starting_balance > 0 else 0

        # Count consecutive losses
        for trade in reversed(self.trade_history):
            pnl = trade.get('unrealized_pnl_net', trade.get('unrealized_pnl', 0))
            if pnl < 0:
                consecutive_losses += 1
            else:
                break

        # Calculate win rate (last 10+ trades)
        recent_trades = self.trade_history[-20:] if len(self.trade_history) >= 10 else []
        wins = sum(1 for t in recent_trades if t.get('unrealized_pnl', 0) > 0)
        win_rate = (wins / len(recent_trades)) if recent_trades else 0.5

        result['stats'] = {
            'daily_trades': len(daily_trades),
            'daily_pnl': daily_pnl,
            'daily_pnl_pct': daily_pnl_pct,
            'weekly_pnl': weekly_pnl,
            'weekly_pnl_pct': weekly_pnl_pct,
            'consecutive_losses': consecutive_losses,
            'win_rate': win_rate
        }

        # CHECK 1: Daily drawdown
        if daily_pnl_pct < -MAX_DAILY_DRAWDOWN_PERCENT:
            result['trading_allowed'] = False
            result['reason'] = f"CIRCUIT BREAKER: Daily drawdown {daily_pnl_pct:.1f}% exceeds -{MAX_DAILY_DRAWDOWN_PERCENT}%"
            logger.error(result['reason'])
            return result

        # CHECK 2: Weekly drawdown
        if weekly_pnl_pct < -MAX_WEEKLY_DRAWDOWN_PERCENT:
            result['trading_allowed'] = False
            result['reason'] = f"CIRCUIT BREAKER: Weekly drawdown {weekly_pnl_pct:.1f}% exceeds -{MAX_WEEKLY_DRAWDOWN_PERCENT}%"
            logger.error(result['reason'])
            return result

        # CHECK 3: Consecutive losses
        if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            result['trading_allowed'] = False
            result['reason'] = f"CIRCUIT BREAKER: {consecutive_losses} consecutive losses (max {MAX_CONSECUTIVE_LOSSES})"
            logger.error(result['reason'])
            return result

        # CHECK 4: Win rate (only if 10+ trades)
        if len(recent_trades) >= 10 and win_rate < MIN_WIN_RATE_THRESHOLD:
            result['trading_allowed'] = False
            result['reason'] = f"CIRCUIT BREAKER: Win rate {win_rate:.0%} below {MIN_WIN_RATE_THRESHOLD:.0%}"
            logger.error(result['reason'])
            return result

        return result

    def get_daily_pnl(self) -> Dict[str, float]:
        """Get today's P&L summary"""
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        today_trades = []
        for trade in self.trade_history:
            exit_time_str = trade.get('exit_time')
            if exit_time_str:
                try:
                    exit_time = datetime.fromisoformat(exit_time_str)
                    if exit_time >= today_start:
                        today_trades.append(trade)
                except:
                    pass

        total_pnl = sum(t.get('unrealized_pnl_net', t.get('unrealized_pnl', 0)) for t in today_trades)
        wins = sum(1 for t in today_trades if t.get('unrealized_pnl', 0) > 0)
        losses = len(today_trades) - wins

        return {
            'trades': len(today_trades),
            'wins': wins,
            'losses': losses,
            'total_pnl': total_pnl,
            'win_rate': (wins / len(today_trades) * 100) if today_trades else 0
        }

    # ===================== ORPHAN POSITION IMPORT =====================

    def import_orphaned_positions(
        self,
        exchange_client,
        min_value_usdt: float = 1.0,
        default_sl_pct: float = 5.0,
        default_tp_pct: float = 10.0
    ) -> Dict[str, Any]:
        """
        Import untracked spot positions from exchange.

        Scans exchange balances and creates position entries for assets
        that aren't already being tracked. Uses current price as entry
        and sets default SL/TP.

        Args:
            exchange_client: ExchangeClient instance
            min_value_usdt: Minimum value to import (default $1)
            default_sl_pct: Default stop loss % below entry (default 5%)
            default_tp_pct: Default take profit % above entry (default 10%)

        Returns:
            Dict with imported positions and summary
        """
        imported = []
        skipped = []
        errors = []

        try:
            # Get all spot balances
            balances = exchange_client.get_all_balances(min_value_usdt=min_value_usdt)
            exchange_name = exchange_client.exchange_name

            for currency, balance_info in balances.items():
                # Skip USDT (it's not a position)
                if currency == 'USDT':
                    continue

                pair = f"{currency}USDT"
                amount = balance_info.get('amount', 0)
                usdt_value = balance_info.get('usdt_value', 0)
                price = balance_info.get('price', 0)

                # Skip if already tracked
                if self.has_position(pair):
                    skipped.append({
                        'pair': pair,
                        'reason': 'already_tracked',
                        'amount': amount,
                        'value': usdt_value
                    })
                    continue

                # Skip if no valid price
                if price <= 0:
                    errors.append({
                        'pair': pair,
                        'reason': 'no_price',
                        'amount': amount
                    })
                    continue

                # Calculate default SL/TP (assume LONG position since we hold the asset)
                stop_loss = price * (1 - default_sl_pct / 100)
                take_profit = price * (1 + default_tp_pct / 100)

                # Add position
                self.add_position(
                    pair=pair,
                    side='long',  # We hold the asset, so it's a long position
                    entry_price=price,  # Use current price (we don't know actual entry)
                    quantity=amount,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    exchange=exchange_name,
                    market='spot'
                )

                imported.append({
                    'pair': pair,
                    'amount': amount,
                    'entry_price': price,
                    'usdt_value': usdt_value,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit
                })

                logger.info(f"📥 Imported orphan: {pair} {amount:.6f} @ ${price:.4f} "
                           f"(SL: ${stop_loss:.4f}, TP: ${take_profit:.4f})")

        except Exception as e:
            logger.error(f"Error importing orphaned positions: {e}")
            errors.append({'error': str(e)})

        result = {
            'imported_count': len(imported),
            'imported': imported,
            'skipped_count': len(skipped),
            'skipped': skipped,
            'error_count': len(errors),
            'errors': errors,
            'total_imported_value': sum(p['usdt_value'] for p in imported)
        }

        logger.info(f"Orphan import complete: {len(imported)} imported, "
                   f"{len(skipped)} skipped, {len(errors)} errors")

        return result
