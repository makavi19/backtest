
# strategies/mean_reversion_bollinger.py
# Strategy 6: Bollinger Bands Mean Reversion

from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge


class MeanReversionBollinger(BaseStrategy):
    """
    Bollinger Bands Mean Reversion Strategy

    Core concepts:
    - Price reaches upper/lower Bollinger Band = overbought/oversold
    - Reversion to mean (middle band)
    - Confirmation: candlestick rejection patterns
    - Best in ranging markets, NOT trending

    Best pairs: JPY pairs (range-bound behavior)
    Best sessions: Tokyo, London (lower volatility)
    """

    NAME = "mean_reversion_bollinger"
    PREFERRED_SESSIONS = ['tokyo', 'london', 'pre_london']
    PREFERRED_PAIRS = ['USDJPY', 'EURJPY', 'GBPJPY']
    BEST_REGIMES = ['ranging']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol, direction, m15, h1, h4):
        """Detect Bollinger Band mean reversion setup"""

        # 1. Calculate Bollinger Bands on H1
        bb = self._calculate_bollinger(h1, period=20, std_dev=2)

        # 2. Check if price at extreme
        at_extreme = self._price_at_extreme(m15, bb, direction)

        # 3. Check for reversal candlestick
        reversal = self._reversal_candle(m15, direction)

        # 4. Check RSI for confirmation
        rsi = self._calculate_rsi(h1, period=14)
        rsi_ok = self._rsi_confirmation(rsi, direction)

        # 5. Check if ranging (not trending)
        is_ranging = self._is_ranging(h1)

        # Score
        score = self._calculate_score(at_extreme, reversal, rsi_ok, is_ranging)
        grade = self._grade_from_score(score)

        if grade in ['C', 'D']:
            return self._empty_signal(symbol, f"Bollinger score too low: {score:.2f}")

        # Calculate levels
        entry, stop, tp1, tp2, stop_pips = self._calculate_levels(bb, m15, direction, symbol)

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
                f"Bollinger extreme: {at_extreme:.0f}%",
                f"Reversal candle: {reversal}",
                f"RSI: {rsi:.1f}",
                f"Ranging: {is_ranging}"
            ],
            warnings=["Mean reversion: avoid if trend forming"] if not is_ranging else [],
            detected_regime='ranging',
            htf_aligned=is_ranging,
        )

    def _calculate_bollinger(self, df, period=20, std_dev=2):
        """Calculate Bollinger Bands"""
        close = df['close']
        sma = close.rolling(period).mean()
        std = close.rolling(period).std()

        return {
            'upper': sma + std_dev * std,
            'middle': sma,
            'lower': sma - std_dev * std,
            'bandwidth': (std_dev * std / sma) * 100,
            'current_upper': (sma + std_dev * std).iloc[-1],
            'current_middle': sma.iloc[-1],
            'current_lower': (sma - std_dev * std).iloc[-1],
        }

    def _price_at_extreme(self, m15, bb, direction):
        """Check if price is at Bollinger extreme (0-100%)"""
        current = m15['close'].iloc[-1]

        if direction == 'buy':
            # Price at or below lower band
            if current <= bb['current_lower']:
                return 1.0
            # How close to lower band?
            range_size = bb['current_middle'] - bb['current_lower']
            if range_size == 0:
                return 0.0
            distance = bb['current_middle'] - current
            return min(1.0, distance / range_size)
        else:
            # Price at or above upper band
            if current >= bb['current_upper']:
                return 1.0
            range_size = bb['current_upper'] - bb['current_middle']
            if range_size == 0:
                return 0.0
            distance = current - bb['current_middle']
            return min(1.0, distance / range_size)

    def _reversal_candle(self, m15, direction):
        """Detect reversal candlestick pattern"""
        recent = m15.tail(3)

        for i in range(len(recent)):
            candle = recent.iloc[i]
            body = abs(candle['close'] - candle['open'])
            upper_wick = candle['high'] - max(candle['open'], candle['close'])
            lower_wick = min(candle['open'], candle['close']) - candle['low']
            total_range = candle['high'] - candle['low']

            if total_range == 0:
                continue

            if direction == 'buy':
                # Hammer or bullish engulfing at lower band
                if lower_wick > body * 2 and candle['close'] > candle['open']:
                    return 'hammer'
                if i > 0:
                    prev = recent.iloc[i-1]
                    if candle['close'] > prev['open'] and candle['open'] < prev['close'] and candle['close'] > candle['open']:
                        return 'engulfing'
            else:
                # Shooting star or bearish engulfing at upper band
                if upper_wick > body * 2 and candle['close'] < candle['open']:
                    return 'shooting_star'
                if i > 0:
                    prev = recent.iloc[i-1]
                    if candle['close'] < prev['open'] and candle['open'] > prev['close'] and candle['close'] < candle['open']:
                        return 'engulfing'

        return 'none'

    def _calculate_rsi(self, df, period=14):
        """Calculate RSI"""
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi.iloc[-1]

    def _rsi_confirmation(self, rsi, direction):
        """Check RSI confirmation for reversal"""
        if direction == 'buy':
            return rsi < 35  # Oversold
        else:
            return rsi > 65  # Overbought

    def _is_ranging(self, h1):
        """Check if market is ranging (Bollinger bandwidth contraction)"""
        bb = self._calculate_bollinger(h1)
        bandwidth = bb['bandwidth'].iloc[-10:].mean() if hasattr(bb['bandwidth'], 'iloc') else 2.0
        return bandwidth < 5.0  # Narrow bands = ranging

    def _calculate_score(self, at_extreme, reversal, rsi_ok, is_ranging):
        score = 0.0
        score += at_extreme * 0.35

        if reversal != 'none':
            score += 0.25

        if rsi_ok:
            score += 0.20

        if is_ranging:
            score += 0.20

        return min(1.0, score)

    def _calculate_levels(self, bb, m15, direction, symbol):
        current = m15['close'].iloc[-1]

        if direction == 'buy':
            entry = current
            stop = bb['current_lower'] * 0.998
            tp1 = bb['current_middle']
            tp2 = bb['current_middle'] + (bb['current_middle'] - bb['current_lower']) * 0.5
        else:
            entry = current
            stop = bb['current_upper'] * 1.002
            tp1 = bb['current_middle']
            tp2 = bb['current_middle'] - (bb['current_upper'] - bb['current_middle']) * 0.5

        risk = abs(entry - stop)

        # Convert to pips
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        stop_pips = risk / pip_size

        return entry, stop, tp1, tp2, stop_pips
