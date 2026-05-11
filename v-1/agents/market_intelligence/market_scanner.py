# agents/market_intelligence/market_scanner.py
# Scans all 11 pairs for ICT setups

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
import pandas as pd
import numpy as np

from core.config import config, PairConfig, get_pair_config, SessionPhase
from core.session_manager import session_mgr
from core.mt5_bridge import MT5Bridge, get_bridge


@dataclass
class ScanResult:
    """Raw setup detection result for a pair"""
    symbol: str
    direction: str  # 'buy' or 'sell'
    confidence: float  # 0.0 to 1.0
    setup_type: str  # 'ob_fvg', 'break_structure', etc.
    grade: str  # 'A', 'B', 'C' preliminary
    entry_zone: Tuple[float, float]  # (min, max)
    stop_loss: float
    take_profit_1: float  # 1R
    take_profit_2: float  # 2R
    m15_data: Optional[pd.DataFrame] = None
    h1_data: Optional[pd.DataFrame] = None
    h4_data: Optional[pd.DataFrame] = None
    notes: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'direction': self.direction,
            'confidence': self.confidence,
            'setup_type': self.setup_type,
            'grade': self.grade,
            'entry_zone': self.entry_zone,
            'stop_loss': self.stop_loss,
            'risk_reward': round(abs(self.take_profit_2 - self.entry_zone[0]) / 
                               abs(self.stop_loss - self.entry_zone[0]), 2),
        }


class MarketScanner:
    """
    Scans all 11 pairs for potential ICT setups
    Uses multi-timeframe analysis (M15 primary, H1/H4 context)
    """
    
    def __init__(self, bridge: Optional[MT5Bridge] = None):
        self.bridge = bridge or get_bridge()
        self.session = session_mgr.get_current_session()
        
    def scan_all_pairs(
        self,
        dxy_directions: Dict[str, str],
        min_confidence: float = 0.6
    ) -> List[ScanResult]:
        """
        Full scan of active pairs for session
        
        Returns list of potential setups, sorted by quality
        """
        # Get pairs suitable for current session
        active_symbols = session_mgr.get_active_pairs()
        
        results = []
        
        for symbol in active_symbols:
            # Skip if DXY direction unclear for this pair
            if dxy_directions.get(symbol) == 'neutral':
                continue
            
            try:
                result = self.scan_pair(symbol, dxy_directions.get(symbol))
                if result and result.confidence >= min_confidence:
                    results.append(result)
                    
            except Exception as e:
                # Log error but continue scanning other pairs
                print(f"Scan failed for {symbol}: {e}")
                continue
        
        # Sort by confidence (grade quality)
        results.sort(key=lambda r: r.confidence, reverse=True)
        
        return results
    
    def scan_pair(
        self,
        symbol: str,
        dxy_direction: Optional[str]
    ) -> Optional[ScanResult]:
        """
        Deep scan single pair for ICT setup
        
        Looks for: Order Blocks, Fair Value Gaps, Market Structure Shift
        """
        pair_config = get_pair_config(symbol)
        if not pair_config:
            return None
        
        # Fetch multi-timeframe data
        try:
            m15 = self.bridge.get_historical_data(symbol, 'M15', 100)
            h1 = self.bridge.get_historical_data(symbol, 'H1', 50)
            h4 = self.bridge.get_historical_data(symbol, 'H4', 30)
        except Exception as e:
            return None  # Data unavailable
        
        # Determine expected direction from DXY
        expected_direction = dxy_direction  # 'buy' or 'sell'
        
        # === ICT STRUCTURE DETECTION ===
        
        # 1. Find Order Blocks
        ob_result = self._find_order_block(m15, expected_direction)
        
        # 2. Find Fair Value Gaps
        fvg_result = self._find_fvg(m15, expected_direction)
        
        # 3. Check HTF alignment
        htf_aligned = self._check_htf_trend(h1, h4, expected_direction)
        
        # Score the setup
        score, grade, notes = self._calculate_score(
            ob=ob_result,
            fvg=fvg_result,
            htf=htf_aligned,
            direction=expected_direction
        )
        
        if grade not in ['A', 'B']:
            return None  # Skip low quality
        
        # Calculate trade parameters
        entry, stop, tp1, tp2 = self._calculate_levels(
            ob_result, fvg_result, m15, expected_direction
        )
        
        # Validate R:R
        risk = abs(entry[0] - stop)
        reward = abs(tp2 - entry[0])
        
        if risk == 0 or (reward / risk) < 1.5:
            return None  # Poor R:R
        
        return ScanResult(
            symbol=symbol,
            direction=expected_direction,
            confidence=score,
            setup_type=self._classify_setup(ob_result, fvg_result),
            grade=grade,
            entry_zone=entry,
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            m15_data=m15,
            h1_data=h1,
            h4_data=h4,
            notes=notes
        )
    
    def _find_order_block(
        self,
        df: pd.DataFrame,
        direction: str
    ) -> Dict:
        """
        Detect ICT Order Block: last opposing candle before MSS
        """
        if len(df) < 25:
            return {'found': False}
        
        # Look for Market Structure Shift in recent candles
        recent = df.tail(20)
        
        if direction == 'buy':
            # Bullish MSS: price breaks above previous high
            highs = recent['high'].values
            lows = recent['low'].values
            
            # Find where price made higher high
            for i in range(-5, -15, -1):
                idx = len(df) + i
                
                if df['close'].iloc[idx] > df['high'].iloc[idx-3:idx].max():
                    # Look back for bearish OB (last bearish candle before break)
                    for j in range(idx-1, max(idx-10, 0), -1):
                        if df['close'].iloc[j] < df['open'].iloc[j]:
                            return {
                                'found': True,
                                'type': 'bullish_ob',
                                'index': j,
                                'zone': (df['low'].iloc[j], df['high'].iloc[j]),
                                'mitigation': df['low'].iloc[j],
                                'fresh': df['low'].iloc[idx:].min() > df['low'].iloc[j],
                                'strength': 1.0 - (idx - j) / 10  # Closer = stronger
                            }
        
        else:  # sell
            for i in range(-5, -15, -1):
                idx = len(df) + i
                
                if df['close'].iloc[idx] < df['low'].iloc[idx-3:idx].min():
                    for j in range(idx-1, max(idx-10, 0), -1):
                        if df['close'].iloc[j] > df['open'].iloc[j]:
                            return {
                                'found': True,
                                'type': 'bearish_ob',
                                'index': j,
                                'zone': (df['low'].iloc[j], df['high'].iloc[j]),
                                'mitigation': df['high'].iloc[j],
                                'fresh': df['high'].iloc[idx:].max() < df['high'].iloc[j],
                                'strength': 1.0 - (idx - j) / 10
                            }
        
        return {'found': False}
    
    def _find_fvg(
        self,
        df: pd.DataFrame,
        direction: str
    ) -> Dict:
        """
        Detect Fair Value Gap: 3-candle imbalance
        """
        if len(df) < 10:
            return {'found': False}
        
        for i in range(-3, -8, -1):
            if i + 2 >= 0:
                continue
            
            c1, c2, c3 = df.iloc[i], df.iloc[i+1], df.iloc[i+2]
            
            if direction == 'buy':
                # Bullish FVG: c2.low > c1.high
                if c2['low'] > c1['high']:
                    fill_ratio = min(1.0, max(0.0, 
                        (c3['low'] - c1['high']) / (c2['low'] - c1['high'])))
                    
                    return {
                        'found': True,
                        'type': 'bullish_fvg',
                        'gap': (c1['high'], c2['low']),
                        'filled': c3['low'] <= c2['low'],
                        'fill_ratio': fill_ratio,
                        'freshness': 1.0 - fill_ratio
                    }
            
            else:  # sell
                # Bearish FVG: c2.high < c1.low
                if c2['high'] < c1['low']:
                    fill_ratio = min(1.0, max(0.0,
                        (c1['low'] - c3['high']) / (c1['low'] - c2['high'])))
                    
                    return {
                        'found': True,
                        'type': 'bearish_fvg',
                        'gap': (c2['high'], c1['low']),
                        'filled': c3['high'] >= c2['high'],
                        'fill_ratio': fill_ratio,
                        'freshness': 1.0 - fill_ratio
                    }
        
        return {'found': False}
    
    def _check_htf_trend(
        self,
        h1: pd.DataFrame,
        h4: pd.DataFrame,
        direction: str
    ) -> Dict:
        """Check higher timeframe alignment"""
        # H4 trend
        h4_close = h4['close'].values
        h4_ema_fast = pd.Series(h4_close).ewm(span=8).mean().iloc[-1]
        h4_ema_slow = pd.Series(h4_close).ewm(span=21).mean().iloc[-1]
        
        # H1 trend
        h1_close = h1['close'].values
        h1_ema_fast = pd.Series(h1_close).ewm(span=8).mean().iloc[-1]
        h1_ema_slow = pd.Series(h1_close).ewm(span=21).mean().iloc[-1]
        
        if direction == 'buy':
            h4_aligned = h4_ema_fast > h4_ema_slow and h4_close[-1] > h4_ema_fast
            h1_aligned = h1_ema_fast > h1_ema_slow and h1_close[-1] > h1_ema_fast
        else:
            h4_aligned = h4_ema_fast < h4_ema_slow and h4_close[-1] < h4_ema_fast
            h1_aligned = h1_ema_fast < h1_ema_slow and h1_close[-1] < h1_ema_fast
        
        return {
            'h4_aligned': h4_aligned,
            'h1_aligned': h1_aligned,
            'both_aligned': h4_aligned and h1_aligned
        }
    
    def _calculate_score(
        self,
        ob: Dict,
        fvg: Dict,
        htf: Dict,
        direction: str
    ) -> Tuple[float, str, List[str]]:
        """
        Calculate setup confidence score and grade
        """
        score = 0.0
        notes = []
        
        # OB contribution (max 0.4)
        if ob.get('found'):
            score += 0.3 * ob.get('strength', 0.5)
            if ob.get('fresh'):
                score += 0.1
                notes.append('Fresh OB')
            else:
                notes.append('Tested OB')
        
        # FVG contribution (max 0.3)
        if fvg.get('found'):
            score += 0.2 * fvg.get('freshness', 0.5)
            if not fvg.get('filled'):
                score += 0.1
                notes.append('Unfilled FVG')
        
        # HTF alignment (max 0.3)
        if htf.get('both_aligned'):
            score += 0.3
            notes.append('HTF aligned')
        elif htf.get('h1_aligned'):
            score += 0.15
            notes.append('H1 aligned only')
        
        # Determine grade
        if score >= 0.75:
            grade = 'A'
        elif score >= 0.60:
            grade = 'B'
        elif score >= 0.45:
            grade = 'C'
        else:
            grade = 'D'
        
        return round(score, 2), grade, notes
    
    def _calculate_levels(
        self,
        ob: Dict,
        fvg: Dict,
        df: pd.DataFrame,
        direction: str
    ) -> Tuple[Tuple[float, float], float, float, float]:
        """
        Calculate entry zone, stop loss, and targets
        """
        current = df['close'].iloc[-1]
        
        # Entry zone: confluence of OB and FVG
        if ob.get('found'):
            ob_low, ob_high = ob['zone']
        else:
            ob_low, ob_high = current * 0.99, current * 1.01
        
        if fvg.get('found'):
            fvg_low, fvg_high = fvg['gap']
        else:
            fvg_low, fvg_high = ob_low, ob_high
        
        # Confluence zone
        entry_min = max(ob_low, fvg_low)
        entry_max = min(ob_high, fvg_high)
        
        # Ensure valid zone
        if entry_min >= entry_max:
            entry_min, entry_max = ob_low, ob_high
        
        if direction == 'buy':
            entry = (entry_min, entry_min + (entry_max - entry_min) * 0.3)
            ideal_entry = entry[0]
            stop = ob_low * 0.999  # Below OB
        else:
            entry = (entry_max - (entry_max - entry_min) * 0.3, entry_max)
            ideal_entry = entry[1]
            stop = ob_high * 1.001  # Above OB
        
        # Targets: 1R and 2R
        risk = abs(ideal_entry - stop)
        if direction == 'buy':
            tp1 = ideal_entry + risk
            tp2 = ideal_entry + risk * 2
        else:
            tp1 = ideal_entry - risk
            tp2 = ideal_entry - risk * 2
        
        return entry, stop, tp1, tp2
    
    def _classify_setup(self, ob: Dict, fvg: Dict) -> str:
        """Classify setup type for logging"""
        has_ob = ob.get('found', False)
        has_fvg = fvg.get('found', False)
        
        if has_ob and has_fvg:
            return 'ob_fvg_confluence'
        elif has_ob:
            return 'order_block'
        elif has_fvg:
            return 'fair_value_gap'
        else:
            return 'structure_based'