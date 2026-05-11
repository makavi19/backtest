#base_strategy_code = '''# strategies/base_strategy.py
# Abstract base class - contract that ALL 9 strategies must implement

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Literal
from datetime import datetime
import pandas as pd

from core.mt5_bridge import MT5Bridge, get_bridge


@dataclass
class StrategySignal:
    """
    STANDARDIZED output that EVERY strategy must return.
    This is the "contract" - uniform format so strategy_selector can compare apples to apples.
    """
    # Core trade details
    valid: bool                          # True if setup found, False if nothing
    strategy_name: str                   # e.g., "ict_ob_fvg", "london_breakout"
    symbol: str                          # e.g., "EURUSD", "XAUUSD"
    direction: Literal['BUY', 'SELL']  # Standardized

    # Grade & Quality
    grade: str                           # 'A+', 'A', 'B+', 'B', 'C', 'D'
    confidence: float                    # 0.0 to 1.0 (numeric score)

    # Price Levels
    entry_price: float                   # Ideal entry
    entry_zone: Tuple[float, float]      # (min, max) acceptable entry range
    stop_loss: float                     # Stop loss price
    take_profit_1: float                 # 1R target
    take_profit_2: float                 # 2R target (runner)
    stop_pips: float                     # Distance in pips

    # Risk
    risk_tier: str                       # 'tight', 'normal', 'wide'
    recommended_risk_usd: float          # $4, $7, or $10

    # Context
    reasons: List[str] = field(default_factory=list)      # Why this trade is good
    warnings: List[str] = field(default_factory=list)     # What to watch

    # Market Context (for regime detection)
    detected_regime: Optional[str] = None  # 'trending', 'ranging', 'volatile', 'accumulating'
    htf_aligned: bool = False             # Higher timeframe alignment

    # Data (for debugging/review)
    m15_data: Optional[pd.DataFrame] = None
    h1_data: Optional[pd.DataFrame] = None
    h4_data: Optional[pd.DataFrame] = None

    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    session_phase: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON/logging"""
        return {
            'valid': self.valid,
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'direction': self.direction,
            'grade': self.grade,
            'confidence': round(self.confidence, 3),
            'entry_price': self.entry_price,
            'entry_zone': self.entry_zone,
            'stop_loss': self.stop_loss,
            'take_profit_1': self.take_profit_1,
            'take_profit_2': self.take_profit_2,
            'stop_pips': self.stop_pips,
            'risk_tier': self.risk_tier,
            'recommended_risk_usd': self.recommended_risk_usd,
            'reasons': self.reasons,
            'warnings': self.warnings,
            'detected_regime': self.detected_regime,
            'htf_aligned': self.htf_aligned,
            'timestamp': self.timestamp,
        }

    @property
    def risk_reward(self) -> float:
        """Calculate R:R ratio"""
        if self.stop_pips == 0:
            return 0.0
        reward_pips = abs(self.take_profit_2 - self.entry_price)
        return round(reward_pips / self.stop_pips, 2)

    @property
    def is_tradeable(self) -> bool:
        """Quick check if this signal meets minimum standards"""
        if not self.valid:
            return False
        if self.grade in ['C', 'D']:
            return False
        if self.confidence < 0.55:
            return False
        if self.risk_reward < 1.5:
            return False
        return True


class BaseStrategy(ABC):
    """
    Abstract base class that ALL 9 strategies MUST inherit from.

    This enforces the contract:
    - Every strategy must implement detect_setup()
    - Every strategy must return a StrategySignal in the SAME format
    - strategy_selector.py can then compare all 9 signals easily
    """

    # Class-level metadata - each strategy defines these
    NAME: str = "base"                    # Override in subclass
    PREFERRED_SESSIONS: List[str] = []    # ['london', 'ny_overlap']
    PREFERRED_PAIRS: List[str] = []       # ['EURUSD', 'XAUUSD']
    BEST_REGIMES: List[str] = []          # ['trending', 'ranging']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        self.bridge = bridge or get_bridge()

    @abstractmethod
    def detect_setup(
        self,
        symbol: str,
        direction: str,
        m15: pd.DataFrame,
        h1: pd.DataFrame,
        h4: pd.DataFrame
    ) -> StrategySignal:
        """
        THE CONTRACT: Every strategy MUST implement this.

        Parameters:
            symbol: Pair being analyzed (e.g., 'EURUSD')
            direction: Expected direction from DXY ('buy' or 'sell')
            m15: M15 OHLCV DataFrame
            h1: H1 OHLCV DataFrame
            h4: H4 OHLCV DataFrame

        Returns:
            StrategySignal with ALL fields populated (or valid=False if no setup)
        """
        pass

    def fetch_data(self, symbol: str, bars: int = 100) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Helper: Fetch M15, H1, H4 data for a pair"""
        m15 = self.bridge.get_historical_data(symbol, 'M15', bars)
        h1 = self.bridge.get_historical_data(symbol, 'H1', bars // 4)
        h4 = self.bridge.get_historical_data(symbol, 'H4', bars // 16)
        return m15, h1, h4

    def is_preferred_for_session(self, session: str) -> bool:
        """Check if this strategy works well in current session"""
        return session in self.PREFERRED_SESSIONS or 'all' in self.PREFERRED_SESSIONS

    def is_preferred_for_pair(self, symbol: str) -> bool:
        """Check if this strategy works well for this pair"""
        return symbol in self.PREFERRED_PAIRS or not self.PREFERRED_PAIRS

    def score_for_regime(self, regime: str) -> float:
        """How well this strategy fits current market regime (0-1)"""
        if regime in self.BEST_REGIMES:
            return 1.0
        if not self.BEST_REGIMES:  # Strategy works in all regimes
            return 0.7
        return 0.3  # Not ideal for this regime

    def _grade_from_score(self, score: float) -> str:
        """Convert 0-1 score to letter grade"""
        if score >= 0.90: return 'A+'
        elif score >= 0.80: return 'A'
        elif score >= 0.70: return 'B+'
        elif score >= 0.60: return 'B'
        elif score >= 0.45: return 'C'
        else: return 'D'

    def _assign_risk_tier(self, stop_pips: float, symbol: str) -> Tuple[str, float]:
        """Map stop pips to risk tier and dollar amount"""
        from core.config import get_pair_config

        pair_config = get_pair_config(symbol)

        # Tight: 8-12 pips -> $4
        if stop_pips <= 12:
            return 'tight', 4.0
        # Normal: 15-20 pips -> $7
        elif stop_pips <= 20:
            return 'normal', 7.0
        # Wide: 25-35 pips -> $10
        else:
            return 'wide', 10.0

    def _empty_signal(self, symbol: str, reason: str) -> StrategySignal:
        """Return invalid signal with explanation"""
        return StrategySignal(
            valid=False,
            strategy_name=self.NAME,
            symbol=symbol,
            direction='BUY',
            grade='D',
            confidence=0.0,
            entry_price=0.0,
            entry_zone=(0.0, 0.0),
            stop_loss=0.0,
            take_profit_1=0.0,
            take_profit_2=0.0,
            stop_pips=0.0,
            risk_tier='none',
            recommended_risk_usd=0.0,
            reasons=[],
            warnings=[reason],
        )
