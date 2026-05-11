
# strategies/london_breakout.py
# Strategy 3: London Opening Range Breakout

from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge
from core.session_manager import session_mgr


class LondonBreakout(BaseStrategy):
    """
    London Breakout Strategy

    Core concept:
    - Capture the opening range expansion at London open (12:30 PM IST)
    - Trade the breakout of Asian session range
    - High volatility, directional momentum

    Best pairs: GBP pairs, EURJPY
    Best session: London open ONLY (12:30-13:30 IST)
    """

    NAME = "london_breakout"
    PREFERRED_SESSIONS = ['london']
    PREFERRED_PAIRS = ['GBPUSD', 'GBPJPY', 'EURJPY', 'EURUSD']
    BEST_REGIMES = ['volatile', 'trending']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol, direction, m15, h1, h4):
        """Detect London opening range breakout"""

        # Check if we're in London open window (first 60 min)
        now = session_mgr.now()
        london_start = now.replace(hour=12, minute=30, second=0)
        london_end = now.replace(hour=13, minute=30, second=0)

        if not (london_start <= now <= london_end):
            return self._empty_signal(symbol, "Outside London open window (12:30-13:30 IST)")

        # 1. Calculate Asian session range (02:00-12:30 IST = 21:00-07:00 UTC)
        asian_range = self._calculate_asian_range(h1)

        # 2. Check if price broke out
        breakout = self._check_breakout(m15, asian_range, direction)

        # 3. Volume confirmation
        volume_ok = self._volume_confirmation(m15)

        # 4. Momentum check
        momentum = self._momentum_check(m15, direction)

        # Score
        score = self._calculate_score(breakout, volume_ok, momentum)
        grade = self._grade_from_score(score)

        if grade in ['C', 'D']:
            return self._empty_signal(symbol, f"Breakout score too low: {score:.2f}")

        # Calculate levels
        entry, stop, tp1, tp2, stop_pips = self._calculate_levels(breakout, asian_range, m15, direction, symbol)

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
                f"Asian range: {asian_range['high']:.5f} - {asian_range['low']:.5f}",
                f"Breakout: {breakout['type']}",
                f"Volume: {'confirmed' if volume_ok else 'weak'}",
                f"Momentum: {'strong' if momentum > 0.7 else 'moderate'}"
            ],
            warnings=["London breakout: fast move, manage aggressively"] if momentum > 0.8 else [],
            detected_regime='volatile',
            htf_aligned=True,
        )

    def _calculate_asian_range(self, h1):
        """Calculate Asian session high/low (last 10 hours before London)"""
        asian = h1.tail(10)
        return {
            'high': asian['high'].max(),
            'low': asian['low'].min(),
            'mid': (asian['high'].max() + asian['low'].min()) / 2,
            'range': asian['high'].max() - asian['low'].min()
        }

    def _check_breakout(self, m15, asian_range, direction):
        """Check if price broke Asian range"""
        recent = m15.tail(6)  # Last 90 minutes

        if direction == 'buy':
            breakout_candles = recent[recent['close'] > asian_range['high']]
            if len(breakout_candles) > 0:
                return {
                    'found': True,
                    'type': 'bullish_breakout',
                    'break_level': asian_range['high'],
                    'strength': (recent['close'].iloc[-1] - asian_range['high']) / asian_range['range']
                }
        else:
            breakout_candles = recent[recent['close'] < asian_range['low']]
            if len(breakout_candles) > 0:
                return {
                    'found': True,
                    'type': 'bearish_breakout',
                    'break_level': asian_range['low'],
                    'strength': (asian_range['low'] - recent['close'].iloc[-1]) / asian_range['range']
                }

        return {'found': False}

    def _volume_confirmation(self, m15):
        """Check if volume supports breakout"""
        recent_vol = m15['tick_volume'].tail(4).mean() if 'tick_volume' in m15.columns else 0
        avg_vol = m15['tick_volume'].tail(20).head(16).mean() if 'tick_volume' in m15.columns else 1

        if avg_vol == 0:
            return False

        return recent_vol > avg_vol * 1.3  # 30% above average

    def _momentum_check(self, m15, direction):
        """Check momentum strength"""
        closes = m15['close'].tail(6).values

        if direction == 'buy':
            momentum = (closes[-1] - closes[0]) / closes[0] * 100
        else:
            momentum = (closes[0] - closes[-1]) / closes[0] * 100

        # Normalize to 0-1
        return min(1.0, max(0.0, momentum / 0.5))  # 0.5% move = full score

    def _calculate_score(self, breakout, volume_ok, momentum):
        score = 0.0
        if breakout['found']:
            score += 0.40
            score += min(0.15, breakout.get('strength', 0) * 0.5)
        if volume_ok:
            score += 0.25
        score += momentum * 0.20
        return min(1.0, score)

    def _calculate_levels(self, breakout, asian_range, m15, direction, symbol):
        current = m15['close'].iloc[-1]

        if direction == 'buy':
            entry = max(current, asian_range['high'])
            stop = asian_range['mid']  # Stop at Asian mid-point
        else:
            entry = min(current, asian_range['low'])
            stop = asian_range['mid']

        risk = abs(entry - stop)

        # Convert to pips
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        stop_pips = risk / pip_size

        # Targets: 1.5R and 2.5R (breakouts run further)
        tp1 = entry + risk * 1.5 if direction == 'buy' else entry - risk * 1.5
        tp2 = entry + risk * 2.5 if direction == 'buy' else entry - risk * 2.5

        return entry, stop, tp1, tp2, stop_pips
