from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge


class ICTOBFVG(BaseStrategy):
    """
    ICT Order Block + Fair Value Gap Strategy

    Core concepts:
    - Order Block: Last opposing candle before Market Structure Shift
    - Fair Value Gap: 3-candle imbalance
    - Confluence: OB + FVG overlap = highest probability

    Best pairs: All (especially EURUSD, XAUUSD, GBPUSD)
    Best session: London
    """

    NAME = "ict_ob_fvg"
    PREFERRED_SESSIONS = ['london', 'ny_overlap', 'pre_london']
    PREFERRED_PAIRS = ['EURUSD', 'XAUUSD', 'GBPUSD', 'EURJPY']
    BEST_REGIMES = ['trending', 'ranging', 'accumulating']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol: str, direction: str,
                     m15: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> StrategySignal:
        """
        THE CONTRACT: Must return StrategySignal (not a dict)

        This is the ONLY method strategy_selector.py calls.
        Everything else is internal helper methods.
        """

        # === YOUR EXISTING LOGIC (unchanged) ===

        # 1. Find Order Block
        ob = self._find_order_block(m15, direction)

        # 2. Find Fair Value Gap
        fvg = self._find_fvg(m15, direction)

        # 3. Check confluence
        confluence = self._check_confluence(ob, fvg)

        # 4. HTF alignment
        htf_score = self._htf_alignment(h1, h4, direction)

        # 5. Calculate final score
        score = self._calculate_score(ob, fvg, confluence, htf_score)

        # === GRADE CHECK ===
        grade = self._grade_from_score(score['total'])

        # If score too low, return INVALID signal (not None!)
        if score['total'] < 0.6 or grade in ['C', 'D']:
            return self._empty_signal(symbol, f"ICT score too low: {score['total']:.2f}")

        # === CALCULATE LEVELS ===
        entry, stop, tp1, tp2 = self._calculate_levels(ob, fvg, m15, direction)

        # === CALCULATE STOP PIPS ===
        stop_pips = self._calculate_stop_pips(entry, stop, symbol)

        # === RISK TIER ===
        risk_tier, risk_usd = self._assign_risk_tier(stop_pips, symbol)

        # === BUILD REASONS ===
        reasons = []
        if ob['found']:
            reasons.append(f"Order Block: {ob['type']} (strength: {ob['strength']:.0%})")
        if fvg['found']:
            reasons.append(f"FVG: {fvg['type']} (freshness: {fvg.get('freshness', 0):.0%})")
        if confluence['valid']:
            reasons.append("OB+FVG confluence")
        reasons.append(f"HTF alignment: {htf_score:.0%}")

        warnings = []
        if ob['found'] and not ob.get('fresh', False):
            warnings.append("Order Block tested - lower probability")
        if fvg['found'] and fvg.get('filled', False):
            warnings.append("FVG partially filled")

        # === RETURN StrategySignal (THE CONTRACT) ===
        return StrategySignal(
            valid=True,                          # Setup found
            strategy_name=self.NAME,             # "ict_ob_fvg"
            symbol=symbol,                       # e.g., "EURUSD"
            direction='BUY' if direction == 'buy' else 'SELL',
            grade=grade,                         # 'A', 'B', etc.
            confidence=round(score['total'], 2), # 0.0 to 1.0
            entry_price=entry[0] if isinstance(entry, tuple) else entry,
            entry_zone=entry if isinstance(entry, tuple) else (entry * 0.998, entry * 1.002),
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            stop_pips=stop_pips,
            risk_tier=risk_tier,                 # 'tight', 'normal', 'wide'
            recommended_risk_usd=risk_usd,       # $4, $7, or $10
            reasons=reasons,
            warnings=warnings,
            detected_regime='trending' if htf_score > 0.7 else 'ranging',
            htf_aligned=htf_score > 0.7,
        )

    # === ALL YOUR EXISTING HELPER METHODS (unchanged) ===

    def _find_order_block(self, df: pd.DataFrame, direction: str) -> Dict:
        """Find ICT Order Block"""
        if len(df) < 25:
            return {'found': False}

        for i in range(-5, -20, -1):
            idx = len(df) + i

            if direction == 'buy':
                if df['close'].iloc[idx] > df['high'].iloc[idx-3:idx].max():
                    for j in range(idx-1, max(idx-10, 0), -1):
                        if df['close'].iloc[j] < df['open'].iloc[j]:
                            return {
                                'found': True,
                                'type': 'bullish_ob',
                                'zone': (df['low'].iloc[j], df['high'].iloc[j]),
                                'strength': 1.0 - (idx-j)/10,
                                'fresh': df['low'].iloc[idx:].min() > df['low'].iloc[j]
                            }
            else:
                if df['close'].iloc[idx] < df['low'].iloc[idx-3:idx].min():
                    for j in range(idx-1, max(idx-10, 0), -1):
                        if df['close'].iloc[j] > df['open'].iloc[j]:
                            return {
                                'found': True,
                                'type': 'bearish_ob',
                                'zone': (df['low'].iloc[j], df['high'].iloc[j]),
                                'strength': 1.0 - (idx-j)/10,
                                'fresh': df['high'].iloc[idx:].max() < df['high'].iloc[j]
                            }

        return {'found': False}

    def _find_fvg(self, df: pd.DataFrame, direction: str) -> Dict:
        """Find Fair Value Gap"""
        for i in range(-3, -10, -1):
            if i+2 >= 0:
                continue

            c1, c2, c3 = df.iloc[i], df.iloc[i+1], df.iloc[i+2]

            if direction == 'buy' and c2['low'] > c1['high']:
                fill = (c3['low'] - c1['high']) / (c2['low'] - c1['high'])
                return {
                    'found': True,
                    'type': 'bullish_fvg',
                    'gap': (c1['high'], c2['low']),
                    'filled': c3['low'] <= c2['low'],
                    'freshness': 1.0 - max(0, min(1, fill))
                }

            elif direction == 'sell' and c2['high'] < c1['low']:
                fill = (c1['low'] - c3['high']) / (c1['low'] - c2['high'])
                return {
                    'found': True,
                    'type': 'bearish_fvg',
                    'gap': (c2['high'], c1['low']),
                    'filled': c3['high'] >= c2['high'],
                    'freshness': 1.0 - max(0, min(1, fill))
                }

        return {'found': False}

    def _check_confluence(self, ob: Dict, fvg: Dict) -> Dict:
        """Check if OB and FVG overlap"""
        if not ob['found'] or not fvg['found']:
            return {'valid': False}

        ob_low, ob_high = ob['zone']
        fvg_low, fvg_high = fvg['gap']

        overlap_low = max(ob_low, fvg_low)
        overlap_high = min(ob_high, fvg_high)

        return {
            'valid': overlap_low < overlap_high,
            'overlap': (overlap_low, overlap_high) if overlap_low < overlap_high else None
        }

    def _htf_alignment(self, h1: pd.DataFrame, h4: pd.DataFrame, direction: str) -> float:
        """Check higher timeframe trend alignment"""
        h1_close = h1['close'].values
        h4_close = h4['close'].values

        h1_ema_fast = pd.Series(h1_close).ewm(span=8).mean().iloc[-1]
        h1_ema_slow = pd.Series(h1_close).ewm(span=21).mean().iloc[-1]
        h4_ema_fast = pd.Series(h4_close).ewm(span=8).mean().iloc[-1]

        if direction == 'buy':
            aligned = h1_ema_fast > h1_ema_slow and h4_ema_fast > h1_ema_slow
        else:
            aligned = h1_ema_fast < h1_ema_slow and h4_ema_fast < h1_ema_slow

        return 1.0 if aligned else 0.5

    def _calculate_score(self, ob: Dict, fvg: Dict, confluence: Dict, htf: float) -> Dict:
        """Calculate component scores"""
        ob_score = 0.3 * ob['strength'] if ob['found'] else 0
        fvg_score = 0.2 * fvg.get('freshness', 0) if fvg['found'] else 0
        conf_score = 0.2 if confluence['valid'] else 0
        htf_score = 0.2 * htf
        setup_score = 0.1 if (ob['found'] and fvg['found']) else 0

        return {
            'ob': ob_score,
            'fvg': fvg_score,
            'confluence': conf_score,
            'htf': htf_score,
            'setup': setup_score,
            'total': ob_score + fvg_score + conf_score + htf_score + setup_score
        }

    def _calculate_levels(self, ob: Dict, fvg: Dict, df: pd.DataFrame, direction: str):
        """Calculate entry, stop, and targets"""
        current = df['close'].iloc[-1]

        if ob['found']:
            entry_zone = ob['zone']
        else:
            entry_zone = (current * 0.995, current * 1.005)

        confluence = self._check_confluence(ob, fvg)
        if confluence['valid']:
            entry_zone = confluence['overlap']

        if direction == 'buy':
            ideal_entry = entry_zone[0]
            stop = ob['zone'][0] * 0.999 if ob['found'] else current * 0.985
        else:
            ideal_entry = entry_zone[1]
            stop = ob['zone'][1] * 1.001 if ob['found'] else current * 1.015

        risk = abs(ideal_entry - stop)
        tp1 = ideal_entry + risk * (1 if direction == 'buy' else -1)
        tp2 = ideal_entry + risk * 2 * (1 if direction == 'buy' else -1)

        return entry_zone, stop, tp1, tp2

    def _calculate_stop_pips(self, entry, stop, symbol: str) -> float:
        """Convert price distance to pips"""
        risk = abs(entry - stop) if not isinstance(entry, tuple) else abs(entry[0] - stop)

        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        return risk / pip_size
