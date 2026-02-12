# client/trading/position_sizer.py - Position sizing calculations
import logging
from typing import Dict, Any

from client.config import DEFAULT_RISK_PERCENT, MAX_RISK_PERCENT, MIN_TRADE_VALUE_USDT, MIN_FUTURES_TRADE_VALUE, MAX_POSITION_PERCENT

logger = logging.getLogger(__name__)


class PositionSizer:
    """Calculate position sizes based on risk management rules"""

    def __init__(
        self,
        risk_percent: float = DEFAULT_RISK_PERCENT,
        max_position_percent: float = MAX_POSITION_PERCENT
    ):
        self.risk_percent = min(risk_percent, MAX_RISK_PERCENT)
        self.max_position_percent = max_position_percent

    def set_risk_percent(self, risk_percent: float):
        """Update risk percent"""
        self.risk_percent = min(risk_percent, MAX_RISK_PERCENT)

    def calculate_position_size(
        self,
        balance: float,
        entry_price: float,
        stop_loss: float,
        confidence: float = 1.0,
        min_trade_value: float = None,
        regime: str = None
    ) -> Dict[str, Any]:
        """
        Calculate position size based on risk management.

        Args:
            balance: Available USDT balance
            entry_price: Entry price
            stop_loss: Stop loss price
            confidence: Signal confidence (0-1)
            min_trade_value: Minimum trade value (uses MIN_TRADE_VALUE_USDT if not specified)
            regime: Market regime for adaptive sizing

        Returns:
            Dict with quantity, usdt_value, risk_amount, etc.
        """
        # Use provided minimum or default to spot minimum
        min_value = min_trade_value if min_trade_value is not None else MIN_TRADE_VALUE_USDT

        # Log input parameters for debugging
        logger.info(f"Position sizing: balance=${balance:.2f}, entry=${entry_price:.4f}, "
                    f"SL=${stop_loss:.4f}, confidence={confidence:.2f}, min_value=${min_value}")

        # Early validation
        if balance <= 0:
            logger.warning(f"Position sizing failed: balance is ${balance:.2f}")
            return {
                'valid': False,
                'reason': f"No balance available (${balance:.2f})",
                'quantity': 0,
                'usdt_value': 0
            }

        if balance < min_value:
            logger.warning(f"Balance ${balance:.2f} below minimum trade value ${min_value}")
            return {
                'valid': False,
                'reason': f"Balance ${balance:.2f} below minimum ${min_value}",
                'quantity': 0,
                'usdt_value': 0
            }

        try:
            # Calculate stop loss distance
            stop_distance = abs(entry_price - stop_loss)
            stop_distance_percent = stop_distance / entry_price if entry_price > 0 else 0.02

            if stop_distance_percent <= 0:
                stop_distance_percent = 0.02  # Default 2% stop

            # ===== REGIME-BASED RISK ADJUSTMENT =====
            # Risk LESS in choppy markets, more in strong trends
            regime_multiplier = 1.0
            if regime:
                if regime in ['LOW_VOLATILITY', 'SIDEWAYS']:
                    regime_multiplier = 0.8  # Was 0.5 - too small on small accounts, fees ate profit
                elif regime in ['RANGING_EXTREME']:
                    regime_multiplier = 0.7  # Was 0.5
                elif regime in ['RANGING_NORMAL']:
                    regime_multiplier = 0.85  # Was 0.7
                elif regime in ['TRENDING_UP_STRONG', 'TRENDING_DOWN_STRONG']:
                    regime_multiplier = 1.2  # Risk 20% more in strong trends
                elif regime in ['HIGH_VOLATILITY']:
                    regime_multiplier = 0.7  # Was 0.6
                    logger.debug(f"Regime {regime}: Reducing risk by 30%")

            # Calculate risk per trade based on confidence AND regime
            effective_risk = self.risk_percent * max(confidence, 0.5) * regime_multiplier
            risk_amount = balance * (effective_risk / 100)

            # Calculate position size based on risk
            # Risk = Position Size * Stop Distance
            # Position Size = Risk / Stop Distance
            position_size_usdt = risk_amount / stop_distance_percent

            # Apply max position limit
            max_position_usdt = balance * (self.max_position_percent / 100)
            position_size_usdt = min(position_size_usdt, max_position_usdt)

            # For small accounts (< $100), use percentage-based sizing
            if balance < 100:
                min_size = balance * 0.10  # At least 10% of balance for small accounts
                position_size_usdt = max(position_size_usdt, min_size)
                logger.info(f"Small account: adjusted position to ${position_size_usdt:.2f}")

            # Ensure minimum trade value
            if position_size_usdt < min_value:
                # For very small balances, try to use minimum viable size
                if balance >= min_value * 1.2:  # Allow if balance is 20% above minimum
                    position_size_usdt = min_value
                    logger.info(f"Adjusted to minimum trade value: ${min_value}")
                else:
                    logger.warning(f"Position size ${position_size_usdt:.2f} below minimum ${min_value}")
                    return {
                        'valid': False,
                        'reason': f"Position size too small (min ${min_value})",
                        'quantity': 0,
                        'usdt_value': 0
                    }

            # Calculate quantity
            quantity = position_size_usdt / entry_price

            return {
                'valid': True,
                'quantity': quantity,
                'usdt_value': position_size_usdt,
                'risk_amount': risk_amount,
                'stop_distance_percent': stop_distance_percent * 100,
                'risk_reward_ratio': self._calculate_rr_ratio(entry_price, stop_loss, position_size_usdt),
                'position_percent': (position_size_usdt / balance) * 100
            }

        except Exception as e:
            logger.error(f"Position sizing error: {e}")
            return {
                'valid': False,
                'reason': str(e),
                'quantity': 0,
                'usdt_value': 0
            }

    def _calculate_rr_ratio(self, entry: float, stop: float, size: float) -> float:
        """Calculate risk/reward ratio assuming 2:1 target"""
        stop_distance = abs(entry - stop)
        target_distance = stop_distance * 2  # 2:1 ratio
        return 2.0  # Default 2:1

    def adjust_for_volatility(self, base_size: float, volatility: float, avg_volatility: float = 0.02) -> float:
        """Adjust position size based on current volatility"""
        if volatility <= 0:
            return base_size

        # Reduce size in high volatility, increase in low volatility
        volatility_ratio = avg_volatility / volatility
        adjusted_size = base_size * min(max(volatility_ratio, 0.5), 1.5)

        return adjusted_size

    def kelly_criterion(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """Calculate Kelly criterion for optimal bet sizing"""
        if avg_loss == 0 or win_rate <= 0:
            return self.risk_percent / 100

        win_loss_ratio = avg_win / avg_loss
        kelly = win_rate - (1 - win_rate) / win_loss_ratio

        # Use fractional Kelly (quarter Kelly for safety)
        fractional_kelly = kelly * 0.25

        return max(0, min(fractional_kelly, self.max_position_percent / 100))
