# Strategy 2: Smart Money Concepts - Liquidity sweeps and order flow

from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge


class SMCStructure(BaseStrategy):
    """
    Smart Money Concepts Strategy

    Core concepts:
    - Liquidity sweeps (stop hunts above/below key levels)
    - Order blocks with institutional order flow
    - Breaker blocks and mitigation blocks

    Best pairs: EURUSD, GBPUSD
    Best sessions: London, NY overlap
    """

    NAME = "smc_structure"
    PREFERRED_SESSIONS = ['london', 'ny_overlap']
    PREFERRED_PAIRS = ['EURUSD', 'GBPUSD', 'XAUUSD']
    BEST_REGIMES = ['trending', 'accumulating']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol, direction, m15, h1, h4):
        """Detect SMC liquidity sweep + order block setup"""

        # 1. Find liquidity sweep
        sweep = self._find_liquidity_sweep(m15, direction)

        # 2. Find order block after sweep
        ob = self._find_order_block_after_sweep(m15, direction, sweep)

        # 3. Check for breaker/mitigation
        breaker = self._check_breaker_block(m15, direction)

        # 4. HTF alignment
        htf = self._htf_structure(h1, h4, direction)

        # Score
        score = self._calculate_score(sweep, ob, breaker, htf)
        grade = self._grade_from_score(score)

        if grade in ['C', 'D']:
            return self._empty_signal(symbol, f"SMC score too low: {score:.2f}")

        # Calculate levels
        entry, stop, tp1, tp2, stop_pips = self._calculate_levels(ob, m15, direction, symbol)

        risk_tier, risk_usd = self._assign_risk_tier(stop_pips, symbol)

        return StrategySignal(
            valid=True,
            strategy_name=self.NAME,
            symbol=symbol,
            direction='BUY' if direction == 'buy' else 'SELL',
            grade=grade,
            confidence=round(score, 2),
            entry_price=entry,
            entry_zone=(entry * 0.998, entry * 1.002) if 'JPY' not in symbol else (entry * 0.9998, entry * 1.0002),
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            stop_pips=stop_pips,
            risk_tier=risk_tier,
            recommended_risk_usd=risk_usd,
            reasons=[
                f"Liquidity sweep: {sweep.get('type', 'none')}",
                f"Order block: {'found' if ob['found'] else 'none'}",
                f"HTF structure: {htf}"
            ],
            warnings=["Watch for false sweep - confirm with close"] if not breaker['confirmed'] else [],
            detected_regime='accumulating' if sweep.get('type') == 'spring' else 'trending',
            htf_aligned=htf == 'aligned',
        )

    def _find_liquidity_sweep(self, df, direction):
        """Find liquidity sweep above/below key level"""
        recent = df.tail(20)

        if direction == 'buy':
            # Look for sell-side liquidity sweep (drop below recent low)
            recent_lows = recent['low'].values
            prev_low = np.min(recent_lows[:-5]) if len(recent_lows) > 5 else recent_lows[0]

            # Check if price swept below then recovered
            for i in range(-5, 0):
                if df['low'].iloc[i] < prev_low * 0.998 and df['close'].iloc[i] > prev_low:
                    return {
                        'found': True,
                        'type': 'sellside_sweep',
                        'level': prev_low,
                        'sweep_low': df['low'].iloc[i],
                        'recovery': df['close'].iloc[i] > prev_low
                    }
        else:
            # Buy-side liquidity sweep
            recent_highs = recent['high'].values
            prev_high = np.max(recent_highs[:-5]) if len(recent_highs) > 5 else recent_highs[0]

            for i in range(-5, 0):
                if df['high'].iloc[i] > prev_high * 1.002 and df['close'].iloc[i] < prev_high:
                    return {
                        'found': True,
                        'type': 'buyside_sweep',
                        'level': prev_high,
                        'sweep_high': df['high'].iloc[i],
                        'recovery': df['close'].iloc[i] < prev_high
                    }

        return {'found': False}

    def _find_order_block_after_sweep(self, df, direction, sweep):
        """Find order block formed after liquidity sweep"""
        if not sweep['found']:
            return {'found': False}

        # Look for opposing candle after sweep
        for i in range(-8, -1):
            if direction == 'buy':
                # Bullish candle after sweep
                if df['close'].iloc[i] > df['open'].iloc[i]:
                    return {
                        'found': True,
                        'type': 'bullish_ob',
                        'zone': (df['low'].iloc[i], df['high'].iloc[i]),
                        'strength': abs(df['close'].iloc[i] - df['open'].iloc[i]) / df['open'].iloc[i] * 100
                    }
            else:
                if df['close'].iloc[i] < df['open'].iloc[i]:
                    return {
                        'found': True,
                        'type': 'bearish_ob',
                        'zone': (df['low'].iloc[i], df['high'].iloc[i]),
                        'strength': abs(df['close'].iloc[i] - df['open'].iloc[i]) / df['open'].iloc[i] * 100
                    }

        return {'found': False}

    def _check_breaker_block(self, df, direction):
        """Check for breaker block (failed order block that becomes support/resistance)"""
        # Simplified: check if recent structure broke and reversed
        recent = df.tail(15)

        if direction == 'buy':
            # Price broke below then reclaimed
            lows = recent['low'].values
            if lows[-1] > np.min(lows[:-3]):
                return {'confirmed': True, 'type': 'reclaimed_support'}
        else:
            highs = recent['high'].values
            if highs[-1] < np.max(highs[:-3]):
                return {'confirmed': True, 'type': 'reclaimed_resistance'}

        return {'confirmed': False}

    def _htf_structure(self, h1, h4, direction):
        """Check higher timeframe market structure"""
        h4_close = h4['close'].values
        h1_close = h1['close'].values

        # Higher highs / lower lows check
        if direction == 'buy':
            h4_hh = h4_close[-1] > np.max(h4_close[-10:-1]) if len(h4_close) >= 10 else False
            h1_hh = h1_close[-1] > np.max(h1_close[-5:-1]) if len(h1_close) >= 5 else False
            return 'aligned' if h4_hh or h1_hh else 'mixed'
        else:
            h4_ll = h4_close[-1] < np.min(h4_close[-10:-1]) if len(h4_close) >= 10 else False
            h1_ll = h1_close[-1] < np.min(h1_close[-5:-1]) if len(h1_close) >= 5 else False
            return 'aligned' if h4_ll or h1_ll else 'mixed'

    def _calculate_score(self, sweep, ob, breaker, htf):
        score = 0.0
        if sweep['found']:
            score += 0.35
            if sweep.get('recovery'):
                score += 0.15
        if ob['found']:
            score += 0.25
        if breaker['confirmed']:
            score += 0.15
        if htf == 'aligned':
            score += 0.10
        return min(1.0, score)

    def _calculate_levels(self, ob, df, direction, symbol):
        current = df['close'].iloc[-1]

        if ob['found']:
            entry = ob['zone'][1] if direction == 'buy' else ob['zone'][0]
            stop = ob['zone'][0] * 0.998 if direction == 'buy' else ob['zone'][1] * 1.002
        else:
            entry = current
            atr = self._calculate_atr(df)
            stop = current - atr * 1.5 if direction == 'buy' else current + atr * 1.5

        risk = abs(entry - stop)

        # Convert to pips
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        stop_pips = risk / pip_size

        tp1 = entry + risk * 1.5 if direction == 'buy' else entry - risk * 1.5
        tp2 = entry + risk * 2.5 if direction == 'buy' else entry - risk * 2.5

        return entry, stop, tp1, tp2, stop_pips

    def _calculate_atr(self, df, period=14):
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean().iloc[-1]
