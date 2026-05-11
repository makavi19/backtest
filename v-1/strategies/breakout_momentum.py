
# strategies/breakout_momentum.py
# Strategy 8: Momentum Breakout

from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge


class BreakoutMomentum(BaseStrategy):
    """
    Momentum Breakout Strategy

    Core concepts:
    - Volatility expansion after consolidation
    - Break of key level with momentum
    - Volume spike confirmation
    - News/event driven moves

    Best pairs: All (works on anything volatile)
    Best session: News/events, London/NY overlap
    """

    NAME = "breakout_momentum"
    PREFERRED_SESSIONS = ['london', 'ny_overlap']
    PREFERRED_PAIRS = ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY']
    BEST_REGIMES = ['volatile', 'trending']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol, direction, m15, h1, h4):
        """Detect momentum breakout setup"""

        # 1. Check for consolidation (tight range)
        consolidation = self._check_consolidation(h1)

        # 2. Check for breakout
        breakout = self._check_breakout(m15, h1, direction)

        # 3. Volume confirmation
        volume = self._volume_spike(m15)

        # 4. Momentum strength
        momentum = self._momentum_strength(m15, direction)

        # 5. Volatility expansion
        vol_expansion = self._volatility_expansion(m15)

        # Score
        score = self._calculate_score(consolidation, breakout, volume, momentum, vol_expansion)
        grade = self._grade_from_score(score)

        if grade in ['C', 'D']:
            return self._empty_signal(symbol, f"Momentum score too low: {score:.2f}")

        # Calculate levels
        entry, stop, tp1, tp2, stop_pips = self._calculate_levels(breakout, m15, direction, symbol)

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
                f"Consolidation: {consolidation:.0f}%",
                f"Breakout: {breakout['type']}",
                f"Volume: {'spike' if volume else 'normal'}",
                f"Momentum: {momentum:.0f}%",
                f"Vol expansion: {vol_expansion:.0f}%"
            ],
            warnings=["Momentum: fast move, manage aggressively"] if momentum > 0.8 else [],
            detected_regime='volatile',
            htf_aligned=True,
        )

    def _check_consolidation(self, h1):
        """Check if market was in consolidation (0-100%)"""
        recent = h1.tail(20)
        highs = recent['high'].values
        lows = recent['low'].values

        range_pct = (np.max(highs) - np.min(lows)) / np.mean(recent['close'].values) * 100

        # Tighter range = higher consolidation score
        if range_pct < 1.0:
            return 1.0
        elif range_pct < 2.0:
            return 0.7
        elif range_pct < 3.0:
            return 0.4
        else:
            return 0.0

    def _check_breakout(self, m15, h1, direction):
        """Check for breakout of consolidation range"""
        recent_h1 = h1.tail(20)
        range_high = recent_h1['high'].max()
        range_low = recent_h1['low'].min()

        current = m15['close'].iloc[-1]

        if direction == 'buy':
            if current > range_high * 1.001:
                return {
                    'found': True,
                    'type': 'bullish_breakout',
                    'level': range_high,
                    'strength': (current - range_high) / (range_high - range_low)
                }
        else:
            if current < range_low * 0.999:
                return {
                    'found': True,
                    'type': 'bearish_breakout',
                    'level': range_low,
                    'strength': (range_low - current) / (range_high - range_low)
                }

        return {'found': False}

    def _volume_spike(self, m15):
        """Check for volume spike"""
        if 'tick_volume' not in m15.columns:
            return False

        recent_vol = m15['tick_volume'].tail(3).mean()
        avg_vol = m15['tick_volume'].tail(30).head(27).mean()

        if avg_vol == 0:
            return False

        return recent_vol > avg_vol * 1.5

    def _momentum_strength(self, m15, direction):
        """Calculate momentum strength (0-1)"""
        closes = m15['close'].tail(6).values

        if direction == 'buy':
            change = (closes[-1] - closes[0]) / closes[0] * 100
        else:
            change = (closes[0] - closes[-1]) / closes[0] * 100

        return min(1.0, max(0.0, change / 0.3))  # 0.3% move = full score

    def _volatility_expansion(self, m15):
        """Check for volatility expansion"""
        recent_atr = self._calculate_atr(m15.tail(20))
        prev_atr = self._calculate_atr(m15.tail(40).head(20))

        if prev_atr == 0:
            return 0.0

        expansion = recent_atr / prev_atr
        return min(1.0, max(0.0, (expansion - 1.0) * 2))

    def _calculate_atr(self, df, period=14):
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean().iloc[-1]

    def _calculate_score(self, consolidation, breakout, volume, momentum, vol_expansion):
        score = 0.0
        score += consolidation * 0.20

        if breakout['found']:
            score += 0.25
            score += min(0.10, breakout.get('strength', 0))

        if volume:
            score += 0.20

        score += momentum * 0.15
        score += vol_expansion * 0.10

        return min(1.0, score)

    def _calculate_levels(self, breakout, m15, direction, symbol):
        current = m15['close'].iloc[-1]

        if breakout['found']:
            entry = current
            # Stop at opposite side of consolidation or recent pullback
            if direction == 'buy':
                stop = m15['low'].tail(5).min() * 0.998
            else:
                stop = m15['high'].tail(5).max() * 1.002
        else:
            entry = current
            atr = self._calculate_atr(m15)
            stop = current - atr * 1.5 if direction == 'buy' else current + atr * 1.5

        risk = abs(entry - stop)

        # Convert to pips
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        stop_pips = risk / pip_size

        # Targets: 1.5R and 2.5R (momentum moves fast)
        tp1 = entry + risk * 1.5 if direction == 'buy' else entry - risk * 1.5
        tp2 = entry + risk * 2.5 if direction == 'buy' else entry - risk * 2.5

        return entry, stop, tp1, tp2, stop_pips
