# agents/market_intelligence/volatility_monitor.py
# Real-time volatility tracking and assessment

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from core.config import config, get_pair_config, PairConfig
from core.mt5_bridge import MT5Bridge, get_bridge


@dataclass
class VolatilityReading:
    """Current volatility state for a pair"""
    symbol: str
    atr_current: float
    atr_percentile: float  # 0-100, where current sits in 20-day range
    volatility_rating: str  # 'low', 'normal', 'high', 'extreme'
    spread_pips: float
    spread_rating: str  # 'tight', 'normal', 'wide', 'extreme'
    volume_health: str  # 'low', 'normal', 'high'
    overall_assessment: str  # 'tradeable', 'caution', 'avoid'
    recommended_tier: str  # 'tight', 'normal', 'wide', 'none'
    notes: List[str]
    
    def is_tradeable(self, min_percentile: int = 20, max_percentile: int = 90) -> bool:
        """Check if conditions suitable for trading"""
        if self.volatility_rating in ['extreme']:
            return False
        if self.spread_rating in ['extreme']:
            return False
        if not (min_percentile <= self.atr_percentile <= max_percentile):
            return False
        return True


class VolatilityMonitor:
    """
    Monitors volatility conditions across all pairs
    Determines if market environment suitable for trading
    """
    
    def __init__(self, bridge: Optional[MT5Bridge] = None, lookback_days: int = 20):
        self.bridge = bridge or get_bridge()
        self.lookback_days = lookback_days
        self._cache: Dict[str, pd.DataFrame] = {}  # ATR history cache
        self._last_update: Optional[datetime] = None
        
    def assess_pair(self, symbol: str, refresh: bool = False) -> VolatilityReading:
        """
        Full volatility assessment for single pair
        """
        pair_config = get_pair_config(symbol)
        if not pair_config:
            return self._error_reading(symbol, "Unknown pair")
        
        try:
            # Fetch recent data
            df = self._get_data(symbol, refresh)
            
            # Calculate ATR
            atr_current = self._calculate_atr(df, 14)
            
            # Calculate percentile vs history
            atr_history = self._get_historical_atr(symbol, refresh)
            percentile = self._calculate_percentile(atr_current, atr_history)
            
            # Classify
            vol_rating = self._classify_volatility(percentile)
            
            # Get spread
            spread_pips = self._get_current_spread(symbol, pair_config)
            spread_rating = self._classify_spread(spread_pips, pair_config)
            
            # Volume health
            volume_health = self._assess_volume(df)
            
            # Overall assessment
            assessment, recommended_tier, notes = self._final_assessment(
                vol_rating, spread_rating, volume_health, percentile, pair_config
            )
            
            return VolatilityReading(
                symbol=symbol,
                atr_current=round(atr_current, 6),
                atr_percentile=round(percentile, 1),
                volatility_rating=vol_rating,
                spread_pips=round(spread_pips, 2),
                spread_rating=spread_rating,
                volume_health=volume_health,
                overall_assessment=assessment,
                recommended_tier=recommended_tier,
                notes=notes
            )
            
        except Exception as e:
            return self._error_reading(symbol, str(e))
    
    def assess_all_pairs(self, symbols: Optional[List[str]] = None) -> Dict[str, VolatilityReading]:
        """Assess all configured pairs"""
        if symbols is None:
            symbols = list(config.PAIRS.keys())
            symbols = [s for s in symbols if s != 'DXY_PROXY']
        
        results = {}
        for symbol in symbols:
            results[symbol] = self.assess_pair(symbol)
        
        return results
    
    def get_market_summary(self) -> Dict:
        """Overall market volatility summary"""
        all_readings = self.assess_all_pairs()
        
        tradeable_count = sum(1 for r in all_readings.values() if r.is_tradeable())
        total_count = len(all_readings)
        
        avg_percentile = np.mean([r.atr_percentile for r in all_readings.values()])
        
        extreme_vol = [s for s, r in all_readings.items() if r.volatility_rating == 'extreme']
        wide_spread = [s for s, r in all_readings.items() if r.spread_rating == 'wide']
        
        return {
            'tradeable_pairs': tradeable_count,
            'total_pairs': total_count,
            'market_volatility': 'high' if avg_percentile > 70 else 'normal' if avg_percentile > 30 else 'low',
            'extreme_volatility_pairs': extreme_vol,
            'wide_spread_pairs': wide_spread,
            'recommendation': 'proceed' if tradeable_count >= 5 else 'caution' if tradeable_count >= 3 else 'wait'
        }
    
    def _get_data(self, symbol: str, refresh: bool = False) -> pd.DataFrame:
        """Fetch M15 data for pair"""
        cache_key = symbol
        
        if not refresh and cache_key in self._cache:
            cache_time = self._last_update or datetime.min
            if datetime.now() - cache_time < timedelta(minutes=5):
                return self._cache[cache_key]
        
        df = self.bridge.get_historical_data(symbol, 'M15', 100)
        
        self._cache[cache_key] = df
        self._last_update = datetime.now()
        
        return df
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Wilder's ATR"""
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        
        return atr.iloc[-1]
    
    def _get_historical_atr(self, symbol: str, refresh: bool = False) -> pd.Series:
        """Get 20-day ATR history for percentile calculation"""
        try:
            # Fetch daily data for longer history
            df_daily = self.bridge.get_historical_data(symbol, 'D1', 25)
            return df_daily.apply(
                lambda x: max(
                    x['high'] - x['low'],
                    abs(x['high'] - df_daily['close'].shift().loc[x.name]) if not pd.isna(df_daily['close'].shift().loc[x.name]) else 0,
                    abs(x['low'] - df_daily['close'].shift().loc[x.name]) if not pd.isna(df_daily['close'].shift().loc[x.name]) else 0
                ),
                axis=1
            ).ewm(span=14).mean()
        except:
            # Fallback: use M15 data, less accurate
            df = self._get_data(symbol, refresh)
            atr_series = df.apply(
                lambda x: max(
                    x['high'] - x['low'],
                    abs(x['high'] - df['close'].shift().loc[x.name]) if not pd.isna(df['close'].shift().loc[x.name]) else 0,
                    abs(x['low'] - df['close'].shift().loc[x.name]) if not pd.isna(df['close'].shift().loc[x.name]) else 0
                ),
                axis=1
            ).ewm(span=14).mean()
            return atr_series.tail(100)
    
    def _calculate_percentile(self, current: float, history: pd.Series) -> float:
        """Where current value sits in historical distribution"""
        history_clean = history.dropna()
        if len(history_clean) < 10:
            return 50.0  # Neutral if insufficient data
        
        count_below = sum(history_clean < current)
        percentile = (count_below / len(history_clean)) * 100
        
        return max(0, min(100, percentile))
    
    def _classify_volatility(self, percentile: float) -> str:
        """Classify volatility level"""
        if percentile < 15:
            return 'very_low'
        elif percentile < 30:
            return 'low'
        elif percentile < 70:
            return 'normal'
        elif percentile < 90:
            return 'high'
        else:
            return 'extreme'
    
    def _get_current_spread(self, symbol: str, pair_config: PairConfig) -> float:
        """Get current spread in pips"""
        try:
            broker_symbol = pair_config.mt5_symbol
            tick = self.bridge.get_historical_data(symbol, 'M1', 1)
            
            # Approximate spread from last candle
            if 'spread' in tick.columns:
                spread_points = tick['spread'].iloc[-1]
            else:
                # Estimate from high-low of M1
                spread_points = (tick['high'].iloc[-1] - tick['low'].iloc[-1]) / 2
            
            # Convert to pips
            if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
                pip_size = pair_config.pip_value
            else:
                pip_size = 0.0001
            
            spread_pips = spread_points / pip_size
            
            return spread_pips
            
        except:
            return pair_config.spread_typical
    
    def _classify_spread(self, spread_pips: float, pair_config: PairConfig) -> str:
        """Classify spread as tight/normal/wide/extreme"""
        typical = pair_config.spread_typical
        
        if spread_pips <= typical * 1.5:
            return 'tight'
        elif spread_pips <= typical * 2.5:
            return 'normal'
        elif spread_pips <= typical * 4:
            return 'wide'
        else:
            return 'extreme'
    
    def _assess_volume(self, df: pd.DataFrame) -> str:
        """Assess tick volume health"""
        recent_vol = df['tick_volume'].tail(20).mean()
        historical_vol = df['tick_volume'].tail(100).head(80).mean()
        
        if historical_vol == 0:
            return 'normal'
        
        ratio = recent_vol / historical_vol
        
        if ratio < 0.6:
            return 'low'
        elif ratio < 1.3:
            return 'normal'
        else:
            return 'high'
    
    def _final_assessment(
        self,
        vol_rating: str,
        spread_rating: str,
        volume_health: str,
        percentile: float,
        pair_config: PairConfig
    ) -> Tuple[str, str, List[str]]:
        """Determine final tradeability and recommended tier"""
        notes = []
        
        # Default tier based on pair
        default_tier = pair_config.default_tier.value
        
        # Volatility checks
        if vol_rating == 'extreme':
            return 'avoid', 'none', ['ATR extreme — avoid trading']
        
        if vol_rating == 'very_low':
            notes.append('Low volatility — tight stops only')
            recommended = 'tight'
        elif vol_rating == 'high':
            notes.append('High volatility — widen stops')
            recommended = 'wide' if default_tier != 'tight' else 'normal'
        else:
            recommended = default_tier
        
        # Spread checks
        if spread_rating == 'extreme':
            return 'avoid', 'none', ['Spread extreme — avoid trading']
        
        if spread_rating == 'wide':
            notes.append('Wide spread — reduce size or wait')
            if recommended != 'wide':
                recommended = 'normal'  # Step down
        
        # Volume checks
        if volume_health == 'low':
            notes.append('Low volume — cautious')
        
        # Final assessment
        if vol_rating in ['normal', 'high'] and spread_rating in ['tight', 'normal']:
            assessment = 'tradeable'
        elif vol_rating in ['low', 'normal'] and spread_rating == 'wide':
            assessment = 'caution'
        else:
            assessment = 'caution'
        
        return assessment, recommended, notes
    
    def _error_reading(self, symbol: str, error: str) -> VolatilityReading:
        """Return error state"""
        return VolatilityReading(
            symbol=symbol,
            atr_current=0.0,
            atr_percentile=50.0,
            volatility_rating='unknown',
            spread_pips=0.0,
            spread_rating='unknown',
            volume_health='unknown',
            overall_assessment='error',
            recommended_tier='none',
            notes=[f'Error: {error}']
        )