# agents/market_intelligence/dxy_sentinel.py
# DXY strength analysis and directional bias

from dataclasses import dataclass
from typing import Dict, Optional, Literal, List
from datetime import datetime
import pandas as pd
import numpy as np

from core.config import config, get_pair_config
from core.mt5_bridge import get_bridge, MT5Bridge


@dataclass
class DXYBias:
    direction: Literal['bullish', 'bearish', 'neutral']
    strength: int  # 0-100
    key_level: float
    trend_4h: str
    trend_1h: str
    pair_directions: Dict[str, str]  # 'buy' or 'sell' for each pair
    trade_recommended: bool
    valid_until: datetime


class DXYSentinel:
    """
    Analyzes USD strength via DXY or EURUSD proxy
    Generates directional bias for all eleven pairs
    """
    
    def __init__(self, bridge: Optional[MT5Bridge] = None):
        self.bridge = bridge or get_bridge()
        self.dxy_proxy = 'DXY_PROXY'  # Configured as EURUSD inverse
        
    def analyze(self, bars_4h: int = 50, bars_1h: int = 50) -> DXYBias:
        """
        Full DXY analysis using multi-timeframe structure
        """
        try:
            # Fetch data
            df_4h = self._fetch_data('4H', bars_4h)
            df_1h = self._fetch_data('1H', bars_1h)
            
        except Exception as e:
            # Fallback to neutral if data fails
            return self._neutral_bias(f"Data fetch failed: {e}")
        
        # Analyze trends
        trend_4h = self._analyze_trend(df_4h)
        trend_1h = self._analyze_trend(df_1h)
        
        # Determine direction and strength
        direction, strength = self._calculate_bias(trend_4h, trend_1h)
        
        # Find key level (nearest order block or swing)
        key_level = self._find_key_level(df_4h, direction)
        
        # Generate pair directions
        pair_directions = self._map_to_pairs(direction)
        
        # Trading recommendation
        trade_recommended = strength >= 60 and direction != 'neutral'
        
        return DXYBias(
            direction=direction,
            strength=strength,
            key_level=key_level,
            trend_4h=trend_4h['description'],
            trend_1h=trend_1h['description'],
            pair_directions=pair_directions,
            trade_recommended=trade_recommended,
            valid_until=pd.Timestamp.now() + pd.Timedelta(hours=4)
        )
    
    def _fetch_data(self, timeframe: str, bars: int) -> pd.DataFrame:
        """Fetch DXY proxy data"""
        return self.bridge.get_historical_data(self.dxy_proxy, timeframe, bars)
    
    def _analyze_trend(self, df: pd.DataFrame) -> Dict:
        """
        ICT-style trend analysis: Market Structure Shift detection
        """
        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        
        # Calculate EMAs
        ema_fast = pd.Series(closes).ewm(span=8).mean().iloc[-1]
        ema_slow = pd.Series(closes).ewm(span=21).mean().iloc[-1]
        
        # Swing analysis (simplified)
        recent_highs = highs[-20:]
        recent_lows = lows[-20:]
        
        higher_highs = recent_highs[-1] > np.percentile(recent_highs, 75)
        lower_lows = recent_lows[-1] < np.percentile(recent_lows, 25)
        
        # Determine trend
        if ema_fast > ema_slow and higher_highs:
            trend = 'bullish'
            quality = 80
        elif ema_fast < ema_slow and lower_lows:
            trend = 'bearish'
            quality = 80
        elif ema_fast > ema_slow:
            trend = 'weak_bullish'
            quality = 60
        elif ema_fast < ema_slow:
            trend = 'weak_bearish'
            quality = 60
        else:
            trend = 'neutral'
            quality = 50
        
        return {
            'trend': trend,
            'quality': quality,
            'ema_fast': ema_fast,
            'ema_slow': ema_slow,
            'description': f"{trend} (q:{quality})"
        }
    
    def _calculate_bias(
        self,
        trend_4h: Dict,
        trend_1h: Dict
    ) -> tuple:
        """
        Combine 4H and 1H for final bias
        """
        t4 = trend_4h['trend']
        t1 = trend_1h['trend']
        q4 = trend_4h['quality']
        q1 = trend_1h['quality']
        
        # Align trends = stronger signal
        if 'bullish' in t4 and 'bullish' in t1:
            # DXY bullish = USD strong
            return 'bullish', min(95, (q4 + q1) // 2 + 10)
        
        if 'bearish' in t4 and 'bearish' in t1:
            # DXY bearish = USD weak  
            return 'bearish', min(95, (q4 + q1) // 2 + 10)
        
        # Conflicting or weak = neutral
        if q4 > 70 or q1 > 70:
            # One strong timeframe wins
            dominant = t4 if q4 > q1 else t1
            strength = max(q4, q1) - 15
            if 'bullish' in dominant:
                return 'bullish', strength
            if 'bearish' in dominant:
                return 'bearish', strength
        
        return 'neutral', 50
    
    def _find_key_level(self, df: pd.DataFrame, direction: str) -> float:
        """Find nearest support/resistance level"""
        recent = df.tail(20)
        
        if direction == 'bullish':
            # Recent lows as support
            return recent['low'].min()
        elif direction == 'bearish':
            # Recent highs as resistance
            return recent['high'].max()
        
        # Neutral: middle of range
        return (recent['high'].max() + recent['low'].min()) / 2
    
    def _map_to_pairs(self, dxy_direction: str) -> Dict[str, str]:
        """
        Map DXY direction to trade directions for each pair
        
        DXY bullish = USD strong = sell EURUSD, buy USDJPY, etc.
        """
        from core.config import config
        
        directions = {}
        
        for symbol, pair_config in config.PAIRS.items():
            if symbol == 'DXY_PROXY':
                continue
            
            correlation = pair_config.dxy_correlation
            
            if dxy_direction == 'bullish':  # USD strong
                if correlation < -0.5:
                    # Inverse correlation: DXY up = pair down
                    directions[symbol] = 'sell'
                elif correlation > 0.5:
                    # Positive correlation: DXY up = pair up
                    directions[symbol] = 'buy'
                else:
                    directions[symbol] = 'neutral'
                    
            elif dxy_direction == 'bearish':  # USD weak
                if correlation < -0.5:
                    directions[symbol] = 'buy'
                elif correlation > 0.5:
                    directions[symbol] = 'sell'
                else:
                    directions[symbol] = 'neutral'
            else:
                directions[symbol] = 'neutral'
        
        return directions
    
    def _neutral_bias(self, reason: str) -> DXYBias:
        """Return neutral bias with all pairs neutral"""
        return DXYBias(
            direction='neutral',
            strength=50,
            key_level=0.0,
            trend_4h=f'error: {reason}',
            trend_1h='error',
            pair_directions={},
            trade_recommended=False,
            valid_until=pd.Timestamp.now()
        )
    
    def get_best_pairs(self, bias: DXYBias, min_strength: int = 60) -> List[str]:
        """Return pairs aligned with strong DXY bias"""
        if bias.strength < min_strength:
            return []
        
        # Filter to clear directional pairs
        aligned = [
            symbol for symbol, direction in bias.pair_directions.items()
            if direction in ['buy', 'sell']
        ]
        
        # Sort by correlation strength (absolute value)
        sorted_pairs = sorted(
            aligned,
            key=lambda s: abs(get_pair_config(s).dxy_correlation),
            reverse=True
        )
        
        return sorted_pairs[:5]  # Top 5