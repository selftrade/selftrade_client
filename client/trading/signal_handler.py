# client/trading/signal_handler.py - Signal validation and processing
import logging
import hmac
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from client.config import SUPPORTED_PAIRS

logger = logging.getLogger(__name__)


class SignalHandler:
    """Handle signal validation and processing"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key
        self.last_signals: Dict[str, Dict] = {}
        self.signal_ttl_seconds = 30

    def set_api_key(self, api_key: str):
        """Set API key for signature verification"""
        self.api_key = api_key

    def validate_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate incoming signal.

        Returns dict with 'valid' bool and 'reason' if invalid.
        """
        # Check required fields (timestamp is now optional - use current time if missing)
        required_fields = ['pair', 'side', 'entry_price', 'stop_loss']
        for field in required_fields:
            if field not in signal:
                return {'valid': False, 'reason': f"Missing required field: {field}"}

        # Add timestamp if missing (use current time)
        if 'timestamp' not in signal:
            signal['timestamp'] = int(datetime.now(timezone.utc).timestamp())

        # Validate pair
        pair = signal['pair'].upper().replace("/", "")
        if pair not in SUPPORTED_PAIRS:
            return {'valid': False, 'reason': f"Unsupported pair: {pair}"}

        # Validate side
        side = signal['side'].lower()
        if side not in ['long', 'short', 'buy', 'sell', 'hold']:
            return {'valid': False, 'reason': f"Invalid side: {side}"}

        # Check signal age
        timestamp = signal.get('timestamp', 0)
        current_time = int(datetime.now(timezone.utc).timestamp())
        signal_age = current_time - timestamp

        if signal_age > self.signal_ttl_seconds:
            return {'valid': False, 'reason': f"Signal expired (age: {signal_age}s)"}

        if signal_age < -5:  # Allow 5s clock drift
            return {'valid': False, 'reason': "Signal timestamp in future"}

        # Verify signature if API key is configured
        if self.api_key:
            # SECURITY: Require signature when API key is configured
            if 'signature' not in signal:
                return {'valid': False, 'reason': "Missing signature (required when API key configured)"}
            if not self._verify_signature(signal):
                return {'valid': False, 'reason': "Invalid signature"}

        # Check for duplicate signal
        if self._is_duplicate(signal):
            return {'valid': False, 'reason': "Duplicate signal"}

        # Validate price values
        entry_price = float(signal.get('entry_price', 0))
        stop_loss = float(signal.get('stop_loss', 0))

        if entry_price <= 0:
            return {'valid': False, 'reason': "Invalid entry price"}

        if stop_loss <= 0:
            return {'valid': False, 'reason': "Invalid stop loss"}

        # Check stop loss direction (with tolerance for floating point)
        # Allow 0.5% tolerance for slight variations
        tolerance = entry_price * 0.005

        if side in ['long', 'buy']:
            if stop_loss >= entry_price - tolerance:
                # Auto-correct stop loss for long
                logger.warning(f"Long signal has invalid SL ({stop_loss}), auto-correcting to 1.5% below entry")
                signal['stop_loss'] = entry_price * 0.985  # Set 1.5% below

        if side in ['short', 'sell']:
            if stop_loss <= entry_price + tolerance:
                # Auto-correct stop loss for short
                logger.warning(f"Short signal has invalid SL ({stop_loss}), auto-correcting to 1.5% above entry")
                signal['stop_loss'] = entry_price * 1.015  # Set 1.5% above

        # Validate stop loss direction (CRITICAL SAFETY CHECK)
        stop_loss = float(signal.get('stop_loss', 0))
        if stop_loss > 0:
            # Check SL is on correct side of entry
            if side in ['long', 'buy']:
                if stop_loss >= entry_price:
                    return {
                        'valid': False,
                        'reason': f"Invalid LONG signal: SL ${stop_loss:.4f} must be BELOW entry ${entry_price:.4f}"
                    }
            elif side in ['short', 'sell']:
                if stop_loss <= entry_price:
                    return {
                        'valid': False,
                        'reason': f"Invalid SHORT signal: SL ${stop_loss:.4f} must be ABOVE entry ${entry_price:.4f}"
                    }

            # Check minimum SL distance (prevent instant trigger)
            sl_distance_pct = abs(entry_price - stop_loss) / entry_price * 100
            if sl_distance_pct < 0.3:  # Less than 0.3% is too tight
                return {
                    'valid': False,
                    'reason': f"SL too close to entry ({sl_distance_pct:.2f}% - needs >0.3%)"
                }

        # Validate take profit direction and minimum distance
        take_profit = float(signal.get('target_price') or signal.get('take_profit', 0))
        if take_profit > 0:
            min_tp_distance_pct = 0.005  # Minimum 0.5% distance from entry

            if side in ['long', 'buy']:
                if take_profit <= entry_price * (1 + min_tp_distance_pct):
                    # Auto-correct TP for long - set to 2x SL distance or 3% above entry
                    sl_distance = entry_price - float(signal.get('stop_loss', entry_price * 0.985))
                    corrected_tp = entry_price + max(sl_distance * 2, entry_price * 0.03)
                    logger.warning(f"Long signal has invalid TP ({take_profit}), auto-correcting to ${corrected_tp:.4f}")
                    signal['target_price'] = corrected_tp
                    signal['take_profit'] = corrected_tp

            if side in ['short', 'sell']:
                if take_profit >= entry_price * (1 - min_tp_distance_pct):
                    # Auto-correct TP for short - set to 2x SL distance or 3% below entry
                    sl_distance = float(signal.get('stop_loss', entry_price * 1.015)) - entry_price
                    corrected_tp = entry_price - max(sl_distance * 2, entry_price * 0.03)
                    logger.warning(f"Short signal has invalid TP ({take_profit}), auto-correcting to ${corrected_tp:.4f}")
                    signal['target_price'] = corrected_tp
                    signal['take_profit'] = corrected_tp

        # Validate confidence
        confidence = float(signal.get('confidence', 0.5))
        if confidence < 0 or confidence > 1:
            return {'valid': False, 'reason': f"Invalid confidence: {confidence}"}

        # Check minimum confidence - must match server threshold (60%)
        if confidence < 0.55:
            return {'valid': False, 'reason': f"Confidence too low: {confidence:.0%} (min 55%)"}

        # Signal is valid
        return {'valid': True, 'reason': None}

    def _verify_signature(self, signal: Dict) -> bool:
        """Verify HMAC signature of signal (REQUIRED when API key configured)"""
        if not self.api_key:
            logger.warning("Signal verification skipped - no API key configured (security risk)")
            return True  # Allow unsigned signals only when no API key is configured

        try:
            signature = signal.get('signature', '')
            if not signature:
                logger.error("Signal missing signature (required for authenticated signals)")
                return False

            payload = f"{signal['pair']}|{signal['side']}|{signal['timestamp']}"
            expected = hmac.new(
                self.api_key.encode(),
                payload.encode(),
                hashlib.sha256
            ).hexdigest()

            is_valid = hmac.compare_digest(expected, signature)
            if not is_valid:
                logger.error(f"Signature mismatch for {signal.get('pair')} signal")
            return is_valid
        except Exception as e:
            logger.error(f"Signature verification failed: {e}")
            return False

    def _is_duplicate(self, signal: Dict) -> bool:
        """Check if signal is duplicate of recent signal"""
        pair = signal['pair'].upper()
        current_time = int(datetime.now(timezone.utc).timestamp())

        # If signal is marked as "continuing" from server, it's not a duplicate
        # This allows valid ongoing signals to pass through
        if signal.get('continuing', False):
            return False

        if pair in self.last_signals:
            last = self.last_signals[pair]
            # Same side within 2 minutes with same entry price is duplicate
            # Reduced from 5 min to 2 min to allow faster re-entry on valid signals
            same_entry = abs(float(signal.get('entry_price', 0)) - float(last.get('entry_price', 0))) < 0.01
            if (last['side'] == signal['side'] and
                current_time - last['timestamp'] < 120 and same_entry):
                return True

        # Store signal
        self.last_signals[pair] = {
            'side': signal['side'],
            'timestamp': signal.get('timestamp', current_time),
            'entry_price': signal.get('entry_price', 0)
        }

        return False

    def process_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process and normalize a signal for execution.

        Returns processed signal dict ready for OrderExecutor.
        """
        # Normalize values
        processed = {
            'pair': signal['pair'].upper().replace("/", ""),
            'side': signal['side'].lower(),
            'entry_price': float(signal.get('entry_price', 0)),
            'stop_loss': float(signal.get('stop_loss', 0)),
            'take_profit': float(signal.get('target_price') or signal.get('take_profit', 0)),
            'confidence': float(signal.get('confidence', 0.5)),
            'regime': signal.get('regime', 'UNKNOWN'),
            'timestamp': signal.get('timestamp', int(datetime.now(timezone.utc).timestamp())),
            'indicators': signal.get('indicators', {}),
            'reasons': signal.get('reasons', [])
        }

        # Calculate default take profit if not provided
        if processed['take_profit'] == 0 and processed['entry_price'] > 0:
            stop_distance = abs(processed['entry_price'] - processed['stop_loss'])
            if processed['side'] in ['long', 'buy']:
                processed['take_profit'] = processed['entry_price'] + (stop_distance * 2)
            else:
                processed['take_profit'] = processed['entry_price'] - (stop_distance * 2)

        return processed

    def filter_by_regime(self, signal: Dict, allowed_regimes: list = None) -> bool:
        """Filter signal by market regime"""
        if allowed_regimes is None:
            allowed_regimes = [
                'TRENDING_UP', 'TRENDING_DOWN', 'RANGING_EXTREME',
                'TRENDING_UP_STRONG', 'TRENDING_DOWN_STRONG'
            ]

        regime = signal.get('regime', 'UNKNOWN')
        return regime in allowed_regimes

    def get_signal_summary(self, signal: Dict) -> str:
        """Get human-readable signal summary"""
        pair = signal.get('pair', 'UNKNOWN')
        side = signal.get('side', 'hold')
        entry = signal.get('entry_price', 0)
        stop = signal.get('stop_loss', 0)
        target = signal.get('take_profit') or signal.get('target_price', 0)
        confidence = signal.get('confidence', 0)
        regime = signal.get('regime', 'UNKNOWN')

        # For HOLD signals, show market analysis instead of trade details
        if side.lower() == 'hold':
            reason = signal.get('reason', 'Analyzing market...')
            trend = signal.get('trend', '')
            market_status = signal.get('market_status', '')
            indicators = signal.get('indicators', {})

            # Build informative hold message
            parts = [f"{pair} HOLD"]
            if regime and regime not in ['HOLD', 'UNKNOWN', 'ANALYZING']:
                parts.append(f"Regime: {regime}")
            if trend:
                parts.append(f"Trend: {trend}")
            if reason:
                parts.append(f"| {reason}")

            # Add key indicators if available
            if indicators:
                rsi = indicators.get('rsi')
                price = indicators.get('current_price')
                if rsi:
                    parts.append(f"| RSI: {rsi:.0f}")
                if price:
                    parts.append(f"| Price: ${price:,.2f}")

            return " ".join(parts)

        # For trade signals, show full details
        return (f"{pair} {side.upper()} | Entry: ${entry:.2f} | "
                f"SL: ${stop:.2f} | TP: ${target:.2f} | "
                f"Conf: {confidence:.0%} | Regime: {regime}")
