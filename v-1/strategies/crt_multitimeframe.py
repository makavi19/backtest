# strategies/crt_multitimeframe.py
# Strategy 9: CRT - Multi-Timeframe Candle Range Trading

from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge


class CRTMultitimeframe(BaseStrategy):
    """
    CRT (Candle Range Theory) Multi-Timeframe Strategy

    Core concepts:
    - Analyze candle ranges across M15, H1, H4
    - Session open ranges (London, NY) create key levels
    - Trade break of session range or rejection at range extreme
    - Multi-timeframe confluence for higher probability

    Best pairs: EURUSD, GBPUSD, XAUUSD
    Best session: Session opens (London 12:30, NY 17:30 IST)
    """

    NAME = "crt_multitimeframe"
    PREFERRED_SESSIONS = ['london', 'ny_overlap', 'pre_london']
    PREFERRED_PAIRS = ['EURUSD', 'GBPUSD', 'XAUUSD']
    BEST_REGIMES = ['trending', 'volatile', 'ranging']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol, direction, m15, h1, h4):
        """Detect CRT multi-timeframe setup"""

        # 1. Calculate session ranges
        session_ranges = self._calculate_session_ranges(h1)

        # 2. Check M15 candle structure
        m15_structure = self._m15_structure(m15, direction)

        # 3. Check H1 range expansion
        h1_expansion = self._h1_expansion(h1, direction)

        # 4. Check H4 context
        h4_context = self._h4_context(h4, direction)

        # 5. Range confluence
        confluence = self._range_confluence(session_ranges, m15, direction)

        # Score
        score = self._calculate_score(session_ranges, m15_structure, h1_expansion, h4_context, confluence)
        grade = self._grade_from_score(score)

        if grade in ['C', 'D']:
            return self._empty_signal(symbol, f"CRT score too low: {score:.2f}")

        # Calculate levels
        entry, stop, tp1, tp2, stop_pips = self._calculate_levels(session_ranges, m15, direction, symbol)

        risk_tier, risk_usd = self._assign_risk_tier(stop_pips, symbol)

        return StrategySignal(
            valid=True,
            strategy_name=self.NAME,
            symbol=symbol,
            direction='BUY' if direction == 'buy' else 'SELL',
            grade=grade,
            confidence=round(score, 2),
            entry_price=entry,
            entry_zone=(entry * 0.999, entry * 1.001),
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            stop_pips=stop_pips,
            risk_tier=risk_tier,
            recommended_risk_usd=risk_usd,
            reasons=[
                f"Session range: {session_ranges['current_range']:.1f} pips",
                f"M15 structure: {m15_structure}",
                f"H1 expansion: {'yes' if h1_expansion else 'no'}",
                f"H4 context: {h4_context}",
                f"Confluence: {confluence:.0f}%"
            ],
            warnings=["CRT: session-dependent, time-sensitive"] if not h1_expansion else [],
            detected_regime='volatile' if h1_expansion else 'ranging',
            htf_aligned=h4_context == 'aligned',
        )

    def _calculate_session_ranges(self, h1):
        """Calculate current and previous session ranges"""
        # Current session (last 5-8 hours)
        current = h1.tail(8)
        current_high = current['high'].max()
        current_low = current['low'].min()
        current_range = current_high - current_low

        # Previous session
        previous = h1.tail(16).head(8)
        prev_high = previous['high'].max()
        prev_low = previous['low'].min()
        prev_range = prev_high - prev_low

        # Average range
        avg_range = (current_range + prev_range) / 2

        return {
            'current_high': current_high,
            'current_low': current_low,
            'current_range': current_range,
            'prev_high': prev_high,
            'prev_low': prev_low,
            'prev_range': prev_range,
            'avg_range': avg_range,
            'midpoint': (current_high + current_low) / 2
        }

    def _m15_structure(self, m15, direction):
        """Analyze M15 candle structure"""
        recent = m15.tail(4)

        bodies = []
        ranges = []
        for i in range(len(recent)):
            candle = recent.iloc[i]
            body = abs(candle['close'] - candle['open'])
            range_size = candle['high'] - candle['low']
            bodies.append(body)
            ranges.append(range_size)

        avg_body = np.mean(bodies)
        avg_range = np.mean(ranges)

        if avg_range == 0:
            return 'neutral'

        body_ratio = avg_body / avg_range

        if body_ratio > 0.7:
            return 'strong_directional'
        elif body_ratio > 0.4:
            return 'moderate'
        else:
            return 'indecision'

    def _h1_expansion(self, h1, direction):
        """Check if H1 candles show range expansion"""
        recent = h1.tail(5)
        ranges = recent['high'].values - recent['low'].values

        if len(ranges) < 3:
            return False

        # Expanding ranges
        expanding = ranges[-1] > ranges[-2] > ranges[-3]

        # Above average
        avg_range = np.mean(ranges)
        above_avg = ranges[-1] > avg_range * 1.2

        return expanding or above_avg

    def _h4_context(self, h4, direction):
        """Check H4 trend context"""
        h4_close = h4['close'].values

        if len(h4_close) < 10:
            return 'unknown'

        ema_fast = pd.Series(h4_close).ewm(span=4).mean().iloc[-1]
        ema_slow = pd.Series(h4_close).ewm(span=12).mean().iloc[-1]

        if direction == 'buy':
            if h4_close[-1] > ema_fast > ema_slow:
                return 'aligned'
            elif h4_close[-1] > ema_slow:
                return 'moderate'
            else:
                return 'counter_trend'
        else:
            if h4_close[-1] < ema_fast < ema_slow:
                return 'aligned'
            elif h4_close[-1] < ema_slow:
                return 'moderate'
            else:
                return 'counter_trend'

    def _range_confluence(self, session_ranges, m15, direction):
        """Check if price at key range level with confluence"""
        current = m15['close'].iloc[-1]

        if direction == 'buy':
            # Price near session low with support
            distance_to_low = abs(current - session_ranges['current_low']) / session_ranges['current_range']
            near_low = distance_to_low < 0.2

            # Previous session low confluence
            near_prev_low = abs(current - session_ranges['prev_low']) / session_ranges['avg_range'] < 0.3

            return 1.0 if (near_low and near_prev_low) else 0.7 if near_low else 0.0
        else:
            distance_to_high = abs(current - session_ranges['current_high']) / session_ranges['current_range']
            near_high = distance_to_high < 0.2

            near_prev_high = abs(current - session_ranges['prev_high']) / session_ranges['avg_range'] < 0.3

            return 1.0 if (near_high and near_prev_high) else 0.7 if near_high else 0.0

    def _calculate_score(self, session_ranges, m15_structure, h1_expansion, h4_context, confluence):
        score = 0.0

        # Session range quality
        if session_ranges['current_range'] > session_ranges['avg_range'] * 0.8:
            score += 0.15

        # M15 structure
        if m15_structure == 'strong_directional':
            score += 0.25
        elif m15_structure == 'moderate':
            score += 0.15

        # H1 expansion
        if h1_expansion:
            score += 0.20

        # H4 context
        if h4_context == 'aligned':
            score += 0.20
        elif h4_context == 'moderate':
            score += 0.10

        # Confluence
        score += confluence * 0.20

        return min(1.0, score)

    def _calculate_levels(self, session_ranges, m15, direction, symbol):
        current = m15['close'].iloc[-1]

        if direction == 'buy':
            entry = current
            # Stop below session low or recent M15 low
            stop = min(session_ranges['current_low'] * 0.998, m15['low'].tail(3).min() * 0.998)

            # Target: session midpoint or previous session high
            risk = abs(entry - stop)
            tp1 = session_ranges['midpoint']
            tp2 = session_ranges['current_high']

            # If tp2 is closer than 2R, use 2R
            if abs(tp2 - entry) < risk * 2:
                tp2 = entry + risk * 2
        else:
            entry = current
            stop = max(session_ranges['current_high'] * 1.002, m15['high'].tail(3).max() * 1.002)

            risk = abs(entry - stop)
            tp1 = session_ranges['midpoint']
            tp2 = session_ranges['current_low']

            if abs(tp2 - entry) < risk * 2:
                tp2 = entry - risk * 2

        # Convert to pips
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        stop_pips = abs(entry - stop) / pip_size

        return entry, stop, tp1, tp2, stop_pips
