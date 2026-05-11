
# strategies/trend_following_ema.py
# Strategy 7: EMA Trend Following

from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge


class TrendFollowingEMA(BaseStrategy):
    """
    EMA Trend Following Strategy

    Core concepts:
    - EMA 8/21/50 alignment for trend direction
    - Pullback to EMA 21 = entry
    - Stop below EMA 50 or recent swing
    - Ride the trend with trailing stop

    Best pairs: Trending pairs (EURUSD, GBPUSD, AUDUSD)
    Best session: NY session (strong trends)
    """

    NAME = "trend_following_ema"
    PREFERRED_SESSIONS = ['ny_overlap', 'london']
    PREFERRED_PAIRS = ['EURUSD', 'GBPUSD', 'AUDUSD', 'USDCAD']
    BEST_REGIMES = ['trending']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol, direction, m15, h1, h4):
        """Detect EMA trend following setup"""

        # 1. Calculate EMAs on H1
        emas = self._calculate_emas(h1)

        # 2. Check trend alignment
        trend_aligned = self._trend_alignment(emas, direction)

        # 3. Check pullback to EMA 21
        pullback = self._check_pullback(m15, emas, direction)

        # 4. Check momentum
        momentum = self._momentum_check(h1, direction)

        # 5. ADX confirmation
        adx_ok = self._adx_confirmation(h1)

        # Score
        score = self._calculate_score(trend_aligned, pullback, momentum, adx_ok)
        grade = self._grade_from_score(score)

        if grade in ['C', 'D']:
            return self._empty_signal(symbol, f"EMA score too low: {score:.2f}")

        # Calculate levels
        entry, stop, tp1, tp2, stop_pips = self._calculate_levels(emas, m15, direction, symbol)

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
                f"EMA alignment: {trend_aligned}",
                f"Pullback: {pullback:.0f}%",
                f"Momentum: {momentum:.0f}%",
                f"ADX: {'strong' if adx_ok else 'weak'}"
            ],
            warnings=["Trend following: use trailing stop"] if momentum > 0.8 else [],
            detected_regime='trending',
            htf_aligned=trend_aligned == 'strong',
        )

    def _calculate_emas(self, df):
        """Calculate EMA 8, 21, 50"""
        close = df['close']
        return {
            'ema8': close.ewm(span=8, adjust=False).mean(),
            'ema21': close.ewm(span=21, adjust=False).mean(),
            'ema50': close.ewm(span=50, adjust=False).mean(),
            'current_8': close.ewm(span=8, adjust=False).mean().iloc[-1],
            'current_21': close.ewm(span=21, adjust=False).mean().iloc[-1],
            'current_50': close.ewm(span=50, adjust=False).mean().iloc[-1],
        }

    def _trend_alignment(self, emas, direction):
        """Check EMA alignment for trend"""
        e8 = emas['current_8']
        e21 = emas['current_21']
        e50 = emas['current_50']

        if direction == 'buy':
            if e8 > e21 > e50:
                return 'strong'
            elif e8 > e21:
                return 'moderate'
            else:
                return 'weak'
        else:
            if e8 < e21 < e50:
                return 'strong'
            elif e8 < e21:
                return 'moderate'
            else:
                return 'weak'

    def _check_pullback(self, m15, emas, direction):
        """Check if price pulled back to EMA 21"""
        current = m15['close'].iloc[-1]
        ema21 = emas['current_21']

        distance = abs(current - ema21) / ema21 * 100

        if direction == 'buy':
            # Price near or below EMA 21 = pullback
            if current <= ema21 * 1.001:
                return 1.0
            return max(0.0, 1.0 - distance * 10)
        else:
            if current >= ema21 * 0.999:
                return 1.0
            return max(0.0, 1.0 - distance * 10)

    def _momentum_check(self, h1, direction):
        """Check price momentum"""
        closes = h1['close'].tail(10).values

        if direction == 'buy':
            momentum = (closes[-1] - closes[0]) / closes[0] * 100
        else:
            momentum = (closes[0] - closes[-1]) / closes[0] * 100

        return min(1.0, max(0.0, momentum / 1.0))

    def _adx_confirmation(self, h1, period=14):
        """Check ADX for trend strength"""
        high = h1['high']
        low = h1['low']
        close = h1['close']

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0
        plus_dm[plus_dm <= minus_dm] = 0
        minus_dm[minus_dm <= plus_dm] = 0

        atr = tr.ewm(span=period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.ewm(span=period, adjust=False).mean().iloc[-1]

        return adx > 25

    def _calculate_score(self, trend_aligned, pullback, momentum, adx_ok):
        score = 0.0

        if trend_aligned == 'strong':
            score += 0.35
        elif trend_aligned == 'moderate':
            score += 0.20

        score += pullback * 0.25
        score += momentum * 0.20

        if adx_ok:
            score += 0.20

        return min(1.0, score)

    def _calculate_levels(self, emas, m15, direction, symbol):
        current = m15['close'].iloc[-1]

        if direction == 'buy':
            entry = current
            # Stop below EMA 50 or recent low
            stop = min(emas['current_50'] * 0.998, m15['low'].tail(5).min() * 0.998)
            # Target: 2R and 3R
            risk = abs(entry - stop)
            tp1 = entry + risk * 2
            tp2 = entry + risk * 3
        else:
            entry = current
            stop = max(emas['current_50'] * 1.002, m15['high'].tail(5).max() * 1.002)
            risk = abs(entry - stop)
            tp1 = entry - risk * 2
            tp2 = entry - risk * 3

        # Convert to pips
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        stop_pips = abs(entry - stop) / pip_size

        return entry, stop, tp1, tp2, stop_pips
