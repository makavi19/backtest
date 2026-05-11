
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum, auto
from datetime import datetime
import pandas as pd
import numpy as np

from core.mt5_bridge import MT5Bridge, get_bridge
from core.config import config, get_pair_config


class MarketRegime(Enum):
    """Four primary market states that determine strategy selection"""
    TRENDING = "trending"           # Strong directional move → EMA, Momentum
    RANGING = "ranging"             # Sideways, mean-reverting → Bollinger, S/D
    VOLATILE = "volatile"           # High volatility, expansion → Breakout, CRT
    ACCUMULATING = "accumulating"   # Wyckoff phase, consolidation → Wyckoff-AMD
    UNKNOWN = "unknown"           # Cannot determine


@dataclass
class RegimeReading:
    """Complete regime assessment for a single pair"""
    symbol: str
    regime: MarketRegime
    confidence: float              # 0-1, how sure we are

    # Trend metrics
    adx: float                     # 0-100, trend strength
    trend_direction: str           # 'up', 'down', 'neutral'

    # Range metrics
    bollinger_width: float         # Band width percentile
    range_bound: bool              # Price oscillating between levels

    # Volatility metrics
    atr_percentile: float          # Where current ATR sits historically
    volatility_spike: bool         # Sudden volatility increase

    # Accumulation metrics
    volume_profile: str            # 'accumulating', 'distributing', 'neutral'
    wyckoff_phase: Optional[str]   # 'spring', 'test', 'markup', etc.

    # Recommended strategies (ranked)
    recommended_strategies: List[Tuple[str, float]]  # [(strategy_name, score), ...]

    # Timestamp
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


class RegimeDetector:
    """
    Detects current market regime using multi-factor analysis:
    - ADX for trend strength
    - Bollinger Bands for range detection
    - ATR percentile for volatility
    - Volume/price patterns for accumulation phases

    This feeds strategy_selector.py to pick the RIGHT strategy for current conditions.
    """

    # Regime → Strategy mapping (which strategies work best in which regime)
    REGIME_STRATEGY_MAP = {
        MarketRegime.TRENDING: [
            ('trend_following_ema', 1.0),
            ('ema_trend', 0.95),
            ('ict_ob_fvg', 0.70),      # Can work in trends
            ('breakout_momentum', 0.65),
            ('smc_structure', 0.60),
        ],
        MarketRegime.RANGING: [
            ('mean_reversion_bollinger', 1.0),
            ('bollinger_reversion', 0.95),
            ('supply_demand_zones', 0.85),
            ('ict_ob_fvg', 0.70),
            ('smc_structure', 0.60),
        ],
        MarketRegime.VOLATILE: [
            ('breakout_momentum', 1.0),
            ('momentum_breakout', 0.95),
            ('london_breakout', 0.80),
            ('crt_multitimeframe', 0.75),
            ('ict_ob_fvg', 0.50),      # Risky in high vol
        ],
        MarketRegime.ACCUMULATING: [
            ('wyckoff_amd', 1.0),
            ('supply_demand_zones', 0.80),
            ('smc_structure', 0.70),
            ('ict_ob_fvg', 0.60),
        ],
        MarketRegime.UNKNOWN: [
            ('ict_ob_fvg', 0.60),      # Default fallback
            ('supply_demand_zones', 0.50),
        ],
    }

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        self.bridge = bridge or get_bridge()
        self._cache: Dict[str, RegimeReading] = {}
        self._last_update: Optional[datetime] = None

    def analyze_pair(self, symbol: str, refresh: bool = False) -> RegimeReading:
        """
        Full regime analysis for a single pair

        Returns RegimeReading with:
        - Detected regime (trending/ranging/volatile/accumulating)
        - Confidence score
        - Ranked list of recommended strategies
        """
        # Check cache
        if not refresh and symbol in self._cache:
            cache_time = datetime.fromisoformat(self._cache[symbol].timestamp)
            if (datetime.utcnow() - cache_time).total_seconds() < 300:  # 5 min cache
                return self._cache[symbol]

        try:
            # Fetch multi-timeframe data
            m15 = self.bridge.get_historical_data(symbol, 'M15', 100)
            h1 = self.bridge.get_historical_data(symbol, 'H1', 50)
            h4 = self.bridge.get_historical_data(symbol, 'H4', 30)

        except Exception as e:
            return self._error_reading(symbol, f"Data fetch failed: {e}")

        # === REGIME DETECTION ===

        # 1. Trend Analysis (ADX)
        adx, trend_dir = self._calculate_adx(h1, period=14)

        # 2. Range Detection (Bollinger)
        bb_width, is_ranging = self._detect_ranging(m15, h1)

        # 3. Volatility Analysis (ATR)
        atr_pct, vol_spike = self._analyze_volatility(m15, h1)

        # 4. Accumulation Detection (Volume/Price)
        vol_profile, wyckoff = self._detect_accumulation(m15, h4)

        # === CLASSIFICATION ===
        regime, confidence = self._classify_regime(
            adx=adx,
            bb_width=bb_width,
            is_ranging=is_ranging,
            atr_pct=atr_pct,
            vol_spike=vol_spike,
            vol_profile=vol_profile,
            wyckoff=wyckoff,
        )

        # Get recommended strategies for this regime
        strategies = self.REGIME_STRATEGY_MAP.get(regime, [])

        reading = RegimeReading(
            symbol=symbol,
            regime=regime,
            confidence=confidence,
            adx=round(adx, 1),
            trend_direction=trend_dir,
            bollinger_width=round(bb_width, 2),
            range_bound=is_ranging,
            atr_percentile=round(atr_pct, 1),
            volatility_spike=vol_spike,
            volume_profile=vol_profile,
            wyckoff_phase=wyckoff,
            recommended_strategies=strategies,
        )

        # Cache result
        self._cache[symbol] = reading
        self._last_update = datetime.utcnow()

        return reading

    def analyze_all_pairs(self, symbols: Optional[List[str]] = None) -> Dict[str, RegimeReading]:
        """Analyze regime for all active pairs"""
        if symbols is None:
            from core.session_manager import session_mgr
            symbols = session_mgr.get_active_pairs()

        results = {}
        for symbol in symbols:
            results[symbol] = self.analyze_pair(symbol)

        return results

    def get_market_regime_summary(self) -> Dict:
        """Overall market regime summary across all pairs"""
        all_readings = self.analyze_all_pairs()

        regime_counts = {}
        for r in all_readings.values():
            regime_counts[r.regime.value] = regime_counts.get(r.regime.value, 0) + 1

        # Dominant regime
        dominant = max(regime_counts, key=regime_counts.get) if regime_counts else 'unknown'

        # Average confidence
        avg_conf = np.mean([r.confidence for r in all_readings.values()]) if all_readings else 0

        # Best strategy across market
        strategy_scores = {}
        for r in all_readings.values():
            for strat, score in r.recommended_strategies:
                strategy_scores[strat] = strategy_scores.get(strat, 0) + score

        top_strategies = sorted(strategy_scores.items(), key=lambda x: x[1], reverse=True)[:3]

        return {
            'dominant_regime': dominant,
            'regime_distribution': regime_counts,
            'average_confidence': round(avg_conf, 2),
            'top_strategies': top_strategies,
            'pairs_analyzed': len(all_readings),
        }

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> Tuple[float, str]:
        """Calculate ADX (Average Directional Index) for trend strength"""
        high = df['high']
        low = df['low']
        close = df['close']

        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # +DM and -DM
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        plus_dm[plus_dm <= minus_dm] = 0
        minus_dm[minus_dm <= plus_dm] = 0

        # Smoothed
        atr = tr.ewm(span=period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / atr)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.ewm(span=period, adjust=False).mean()

        current_adx = adx.iloc[-1]

        # Determine trend direction
        if plus_di.iloc[-1] > minus_di.iloc[-1]:
            trend_dir = 'up'
        elif minus_di.iloc[-1] > plus_di.iloc[-1]:
            trend_dir = 'down'
        else:
            trend_dir = 'neutral'

        return current_adx, trend_dir

    def _detect_ranging(self, m15: pd.DataFrame, h1: pd.DataFrame) -> Tuple[float, bool]:
        """Detect if market is range-bound using Bollinger Bands"""
        # Bollinger on H1
        close = h1['close']
        sma = close.rolling(20).mean()
        std = close.rolling(20).std()
        upper = sma + 2 * std
        lower = sma - 2 * std

        # Band width as % of price
        width = (upper - lower) / sma * 100
        current_width = width.iloc[-1]

        # Historical width for percentile
        width_history = width.dropna()
        if len(width_history) > 20:
            width_pct = sum(width_history < current_width) / len(width_history) * 100
        else:
            width_pct = 50

        # Range detection: price oscillating between bands
        recent = h1.tail(20)
        touches_upper = sum(recent['high'] >= upper.tail(20)) >= 2
        touches_lower = sum(recent['low'] <= lower.tail(20)) >= 2

        is_ranging = touches_upper and touches_lower and width_pct < 60

        return width_pct, is_ranging

    def _analyze_volatility(self, m15: pd.DataFrame, h1: pd.DataFrame) -> Tuple[float, bool]:
        """Analyze volatility using ATR percentile"""
        # Calculate ATR on M15
        high_low = m15['high'] - m15['low']
        high_close = abs(m15['high'] - m15['close'].shift())
        low_close = abs(m15['low'] - m15['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.ewm(span=14, adjust=False).mean()

        current_atr = atr.iloc[-1]
        atr_history = atr.dropna()

        if len(atr_history) > 20:
            percentile = sum(atr_history < current_atr) / len(atr_history) * 100
        else:
            percentile = 50

        # Volatility spike: ATR > 80th percentile and increasing
        vol_spike = percentile > 80 and atr.iloc[-1] > atr.iloc[-5]

        return percentile, vol_spike

    def _detect_accumulation(self, m15: pd.DataFrame, h4: pd.DataFrame) -> Tuple[str, Optional[str]]:
        """Detect Wyckoff accumulation/distribution phases"""
        # Simplified: look for volume patterns and spring/test structures
        volume = m15['tick_volume'] if 'tick_volume' in m15.columns else m15['volume']

        if volume is None or len(volume) < 30:
            return 'neutral', None

        recent_vol = volume.tail(20).mean()
        historical_vol = volume.tail(60).head(40).mean()

        if historical_vol == 0:
            return 'neutral', None

        vol_ratio = recent_vol / historical_vol

        # Volume profile
        if vol_ratio < 0.7:
            vol_profile = 'accumulating'  # Low volume = potential accumulation
        elif vol_ratio > 1.5:
            vol_profile = 'distributing'  # High volume = potential distribution
        else:
            vol_profile = 'neutral'

        # Wyckoff phase detection (simplified)
        h4_close = h4['close'].values
        h4_low = h4['low'].values
        h4_high = h4['high'].values

        # Spring: sharp drop below support then recovery
        recent_lows = h4_low[-10:]
        prev_low = np.min(h4_low[-20:-10]) if len(h4_low) >= 20 else h4_low[0]

        spring = recent_lows.min() < prev_low * 0.995 and h4_close[-1] > prev_low

        # Test: drop to support and bounce
        test = abs(recent_lows.min() - prev_low) / prev_low < 0.002 and h4_close[-1] > h4_close[-5]

        if spring:
            wyckoff = 'spring'
        elif test:
            wyckoff = 'test'
        else:
            wyckoff = None

        return vol_profile, wyckoff

    def _classify_regime(
        self,
        adx: float,
        bb_width: float,
        is_ranging: bool,
        atr_pct: float,
        vol_spike: bool,
        vol_profile: str,
        wyckoff: Optional[str],
    ) -> Tuple[MarketRegime, float]:
        """
        Classify market regime using weighted scoring

        Returns: (regime, confidence)
        """
        scores = {
            MarketRegime.TRENDING: 0,
            MarketRegime.RANGING: 0,
            MarketRegime.VOLATILE: 0,
            MarketRegime.ACCUMULATING: 0,
        }

        # Trend scoring
        if adx > 25:
            scores[MarketRegime.TRENDING] += min(50, adx - 25)

        # Range scoring
        if is_ranging:
            scores[MarketRegime.RANGING] += 40
        if bb_width < 40:
            scores[MarketRegime.RANGING] += 20

        # Volatility scoring
        if vol_spike:
            scores[MarketRegime.VOLATILE] += 50
        if atr_pct > 80:
            scores[MarketRegime.VOLATILE] += 30

        # Accumulation scoring
        if wyckoff in ['spring', 'test']:
            scores[MarketRegime.ACCUMULATING] += 50
        if vol_profile == 'accumulating' and adx < 20:
            scores[MarketRegime.ACCUMULATING] += 30

        # Determine winner
        max_score = max(scores.values())

        if max_score == 0:
            return MarketRegime.UNKNOWN, 0.3

        winner = max(scores, key=scores.get)

        # Confidence based on margin over second place
        sorted_scores = sorted(scores.values(), reverse=True)
        margin = sorted_scores[0] - sorted_scores[1]
        confidence = min(0.95, 0.5 + margin / 100)

        return winner, round(confidence, 2)

    def _error_reading(self, symbol: str, error: str) -> RegimeReading:
        """Return error state"""
        return RegimeReading(
            symbol=symbol,
            regime=MarketRegime.UNKNOWN,
            confidence=0.0,
            adx=0,
            trend_direction='neutral',
            bollinger_width=0,
            range_bound=False,
            atr_percentile=50,
            volatility_spike=False,
            volume_profile='unknown',
            wyckoff_phase=None,
            recommended_strategies=[],
        )
