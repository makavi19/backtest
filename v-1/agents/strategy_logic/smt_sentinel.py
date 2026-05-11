# agents/strategy_logic/smt_sentinel.py
# Smart Money Tool: Gold-Silver divergence analysis

from dataclasses import dataclass
from typing import Optional, Dict, Literal
from datetime import datetime
import pandas as pd
import numpy as np

from core.mt5_bridge import MT5Bridge, get_bridge


@dataclass
class SMTSignal:
    """Smart Money Tool divergence signal"""
    valid: bool
    smt_type: Optional[Literal['bullish', 'bearish']] = None
    strength: float = 0.0  # 0-100
    gold_direction: Optional[str] = None
    silver_direction: Optional[str] = None
    divergence_pips: float = 0.0
    expected_move: Optional[str] = None  # which metal leads
    confidence_boost: float = 0.0  # Add to setup score
    reason: str = ""


class SMTSentinel:
    """
    Detects SMT (Smart Money Tool) divergence between XAUUSD and XAGUSD
    
    Bullish SMT: Gold higher low, Silver lower low (Gold leading strength)
    Bearish SMT: Gold lower high, Silver higher high (Gold showing weakness)
    """
    
    def __init__(self, bridge: Optional[MT5Bridge] = None):
        self.bridge = bridge or get_bridge()
        self.gold_symbol = 'XAUUSD'
        self.silver_symbol = 'XAGUSD'
        self.correlation_threshold = 0.70
        
    def analyze(self, lookback: int = 20) -> SMTSignal:
        """
        Full SMT analysis on current market
        """
        try:
            # Fetch both metals
            gold = self._get_swings(self.gold_symbol, lookback)
            silver = self._get_swings(self.silver_symbol, lookback)
            
        except Exception as e:
            return SMTSignal(valid=False, reason=f"Data error: {e}")
        
        # Check correlation first
        correlation = self._calculate_correlation(gold['closes'], silver['closes'])
        
        if correlation < self.correlation_threshold:
            return SMTSignal(
                valid=False,
                reason=f"Correlation too low: {correlation:.2f}",
                correlation=correlation
            )
        
        # Detect divergence
        smt_type = self._detect_divergence(gold, silver)
        
        if not smt_type:
            return SMTSignal(valid=False, reason="No divergence detected")
        
        # Calculate strength
        strength = self._calculate_strength(gold, silver, smt_type)
        
        # Expected move
        expected = 'gold' if smt_type == 'bullish' else 'silver' if smt_type == 'bearish' else None
        
        # Confidence boost for gold setups
        confidence_boost = strength / 100 * 0.15  # Max +0.15 to score
        
        return SMTSignal(
            valid=True,
            smt_type=smt_type,
            strength=strength,
            gold_direction=gold['direction'],
            silver_direction=silver['direction'],
            divergence_pips=abs(gold['last_low'] - silver['last_low']),
            expected_move=expected,
            confidence_boost=confidence_boost,
            reason=f"SMT {smt_type}: {strength:.0f}% strength"
        )
    
    def _get_swings(self, symbol: str, lookback: int) -> Dict:
        """Get recent swing highs and lows"""
        df = self.bridge.get_historical_data(symbol, 'M15', lookback + 10)
        
        highs = df['high'].values
        lows = df['low'].values
        closes = df['close'].values
        
        # Find last two significant swings
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        
        return {
            'last_high': np.max(recent_highs[-10:]),
            'last_low': np.min(recent_lows[-10:]),
            'prev_high': np.max(highs[-lookback:-10]) if lookback > 10 else highs[-lookback],
            'prev_low': np.min(lows[-lookback:-10]) if lookback > 10 else lows[-lookback],
            'closes': closes,
            'direction': 'up' if closes[-1] > closes[-lookback//2] else 'down'
        }
    
    def _calculate_correlation(self, gold_closes: np.ndarray, silver_closes: np.ndarray) -> float:
        """Rolling correlation of price movements"""
        if len(gold_closes) != len(silver_closes):
            min_len = min(len(gold_closes), len(silver_closes))
            gold_closes = gold_closes[-min_len:]
            silver_closes = silver_closes[-min_len:]
        
        # Use returns for correlation
        gold_returns = np.diff(gold_closes) / gold_closes[:-1]
        silver_returns = np.diff(silver_closes) / silver_closes[:-1]
        
        if len(gold_returns) < 5:
            return 0.0
        
        correlation = np.corrcoef(gold_returns, silver_returns)[0, 1]
        return correlation if not np.isnan(correlation) else 0.0
    
    def _detect_divergence(
        self,
        gold: Dict,
        silver: Dict
    ) -> Optional[Literal['bullish', 'bearish']]:
        """
        Detect SMT divergence pattern
        """
        # Bullish: Gold HL, Silver LL
        gold_hl = gold['last_low'] > gold['prev_low']
        silver_ll = silver['last_low'] < silver['prev_low']
        
        if gold_hl and silver_ll:
            return 'bullish'
        
        # Bearish: Gold LH, Silver HH
        gold_lh = gold['last_high'] < gold['prev_high']
        silver_hh = silver['last_high'] > silver['prev_high']
        
        if gold_lh and silver_hh:
            return 'bearish'
        
        return None
    
    def _calculate_strength(
        self,
        gold: Dict,
        silver: Dict,
        smt_type: str
    ) -> float:
        """Calculate signal strength 0-100"""
        strength = 50.0  # Base
        
        # Size of divergence
        if smt_type == 'bullish':
            divergence = (gold['last_low'] - gold['prev_low']) / gold['prev_low'] * 100
            divergence_silver = abs(silver['last_low'] - silver['prev_low']) / silver['prev_low'] * 100
        else:
            divergence = abs(gold['last_high'] - gold['prev_high']) / gold['prev_high'] * 100
            divergence_silver = (silver['last_high'] - silver['prev_high']) / silver['prev_high'] * 100
        
        # Larger divergence = stronger signal
        strength += min(30, divergence * 10)
        strength += min(20, divergence_silver * 10)
        
        return min(100, strength)
    
    def confirm_gold_setup(self, gold_scan_direction: str) -> bool:
        """
        Quick check: Does SMT confirm a gold trade direction?
        """
        smt = self.analyze()
        
        if not smt.valid:
            return False  # No SMT, proceed with caution
        
        # SMT bullish + Gold buy setup = strong confirmation
        if smt.smt_type == 'bullish' and gold_scan_direction == 'buy':
            return True
        
        # SMT bearish + Gold sell setup = strong confirmation
        if smt.smt_type == 'bearish' and gold_scan_direction == 'sell':
            return True
        
        # Conflicting: SMT bullish but Gold sell = warning
        return False