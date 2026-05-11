
# strategies/wyckoff_amd.py
# Strategy 4: Wyckoff Accumulation/Manipulation/Distribution

from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge


class WyckoffAMD(BaseStrategy):
    """
    Wyckoff Accumulation/Manipulation/Distribution Strategy

    Core concepts:
    - Phase detection: Accumulation → Markup → Distribution → Markdown
    - Spring: False breakdown below support (buy signal)
    - Test: Return to support after spring (confirmation)
    - LPS (Last Point of Support): Entry after markup begins

    Best pairs: XAUUSD, XAGUSD (commodities show Wyckoff well)
    Best session: All (phase-dependent)
    """

    NAME = "wyckoff_amd"
    PREFERRED_SESSIONS = ['london', 'ny_overlap', 'pre_london']
    PREFERRED_PAIRS = ['XAUUSD', 'XAGUSD', 'EURUSD']
    BEST_REGIMES = ['accumulating', 'ranging']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol, direction, m15, h1, h4):
        """Detect Wyckoff phase and trading opportunity"""

        # 1. Detect current phase
        phase = self._detect_phase(h4, h1)

        # 2. Look for spring or test
        spring = self._detect_spring(m15, h4, direction)
        test = self._detect_test(m15, h4, direction)

        # 3. Volume analysis
        vol = self._volume_analysis(m15, phase)

        # 4. Check if in markup phase (best for entries)
        markup_ready = self._markup_ready(h1, direction)

        # Score based on phase and signals
        score = self._calculate_score(phase, spring, test, vol, markup_ready)
        grade = self._grade_from_score(score)

        if grade in ['C', 'D']:
            return self._empty_signal(symbol, f"Wyckoff score too low: {score:.2f}")

        # Calculate levels
        entry, stop, tp1, tp2, stop_pips = self._calculate_levels(spring, test, m15, direction, symbol)

        risk_tier, risk_usd = self._assign_risk_tier(stop_pips, symbol)

        return StrategySignal(
            valid=True,
            strategy_name=self.NAME,
            symbol=symbol,
            direction='BUY' if direction == 'buy' else 'SELL',
            grade=grade,
            confidence=round(score, 2),
            entry_price=entry,
            entry_zone=(entry * 0.998, entry * 1.002),
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            stop_pips=stop_pips,
            risk_tier=risk_tier,
            recommended_risk_usd=risk_usd,
            reasons=[
                f"Phase: {phase}",
                f"Spring: {'found' if spring['found'] else 'none'}",
                f"Test: {'found' if test['found'] else 'none'}",
                f"Volume: {vol['profile']}",
                f"Markup ready: {markup_ready}"
            ],
            warnings=["Wyckoff: patience required, phases take time"] if phase != 'markup' else [],
            detected_regime='accumulating',
            htf_aligned=markup_ready,
        )

    def _detect_phase(self, h4, h1):
        """Detect Wyckoff phase using volume and price structure"""
        h4_close = h4['close'].values
        h4_vol = h4['tick_volume'].values if 'tick_volume' in h4.columns else np.ones(len(h4_close))

        # Check for accumulation characteristics
        recent = h4.tail(20)

        # Range-bound with decreasing volume = accumulation
        highs = recent['high'].values
        lows = recent['low'].values
        range_pct = (np.max(highs) - np.min(lows)) / np.mean(h4_close) * 100

        vol_trend = np.polyfit(range(len(h4_vol[-20:])), h4_vol[-20:], 1)[0]

        if range_pct < 3 and vol_trend < 0:
            return 'accumulation'
        elif range_pct < 3 and vol_trend > 0:
            return 'markup'
        elif range_pct > 5 and vol_trend > 0:
            return 'distribution'
        else:
            return 'unknown'

    def _detect_spring(self, m15, h4, direction):
        """Detect spring: false breakdown below support"""
        if direction != 'buy':
            return {'found': False}  # Spring is bullish only

        # Find support level on H4
        h4_lows = h4['low'].tail(10).values
        support = np.min(h4_lows)

        # Check M15 for false breakdown
        recent = m15.tail(20)
        for i in range(-10, -1):
            if m15['low'].iloc[i] < support * 0.998 and m15['close'].iloc[i] > support:
                return {
                    'found': True,
                    'support': support,
                    'spring_low': m15['low'].iloc[i],
                    'recovery_close': m15['close'].iloc[i],
                    'strength': (support - m15['low'].iloc[i]) / support * 100
                }

        return {'found': False}

    def _detect_test(self, m15, h4, direction):
        """Detect test: return to support after spring"""
        if direction != 'buy':
            return {'found': False}

        h4_lows = h4['low'].tail(10).values
        support = np.min(h4_lows)

        # Price near support with rejection
        recent = m15.tail(10)
        for i in range(-5, -1):
            low = m15['low'].iloc[i]
            close = m15['close'].iloc[i]

            if abs(low - support) / support < 0.002 and close > low:
                return {
                    'found': True,
                    'support': support,
                    'test_low': low,
                    'rejection': close > low
                }

        return {'found': False}

    def _volume_analysis(self, m15, phase):
        """Analyze volume for phase confirmation"""
        if 'tick_volume' not in m15.columns:
            return {'profile': 'unknown', 'confirmed': False}

        recent_vol = m15['tick_volume'].tail(20).mean()
        prev_vol = m15['tick_volume'].tail(60).head(40).mean()

        if prev_vol == 0:
            return {'profile': 'unknown', 'confirmed': False}

        ratio = recent_vol / prev_vol

        if phase == 'accumulation' and ratio < 0.8:
            return {'profile': 'decreasing', 'confirmed': True}
        elif phase == 'markup' and ratio > 1.2:
            return {'profile': 'increasing', 'confirmed': True}
        else:
            return {'profile': 'neutral', 'confirmed': False}

    def _markup_ready(self, h1, direction):
        """Check if markup phase has begun"""
        if direction != 'buy':
            return False

        h1_close = h1['close'].values
        ema_fast = pd.Series(h1_close).ewm(span=8).mean().iloc[-1]
        ema_slow = pd.Series(h1_close).ewm(span=21).mean().iloc[-1]

        return ema_fast > ema_slow and h1_close[-1] > ema_fast

    def _calculate_score(self, phase, spring, test, vol, markup_ready):
        score = 0.0

        if phase == 'accumulation':
            score += 0.20
        elif phase == 'markup':
            score += 0.30

        if spring['found']:
            score += 0.25
            score += min(0.10, spring.get('strength', 0) / 10)

        if test['found']:
            score += 0.20

        if vol['confirmed']:
            score += 0.15

        if markup_ready:
            score += 0.10

        return min(1.0, score)

    def _calculate_levels(self, spring, test, m15, direction, symbol):
        current = m15['close'].iloc[-1]

        if spring['found']:
            entry = spring['support']
            stop = spring['spring_low'] * 0.998
        elif test['found']:
            entry = test['support']
            stop = test['test_low'] * 0.998
        else:
            entry = current
            atr = self._calculate_atr(m15)
            stop = current - atr * 2 if direction == 'buy' else current + atr * 2

        risk = abs(entry - stop)

        # Convert to pips
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        stop_pips = risk / pip_size

        # Targets: 2R and 3R (Wyckoff moves are larger)
        tp1 = entry + risk * 2 if direction == 'buy' else entry - risk * 2
        tp2 = entry + risk * 3 if direction == 'buy' else entry - risk * 3

        return entry, stop, tp1, tp2, stop_pips

    def _calculate_atr(self, df, period=14):
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean().iloc[-1]
