
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd

from strategies.base_strategy import BaseStrategy, StrategySignal
from agents.market_dynamics.regime_detector import RegimeDetector, MarketRegime
from core.config import config, get_pair_config, RiskTier
from core.session_manager import session_mgr
from core.mt5_bridge import MT5Bridge, get_bridge

# Import all 9 strategies
from strategies.ict_ob_fvg import ICTOBFVG
from strategies.smc_structure import SMCStructure
from strategies.london_breakout import LondonBreakout
from strategies.wyckoff_amd import WyckoffAMD
from strategies.supply_demand_zones import SupplyDemandZones
from strategies.mean_reversion_bollinger import MeanReversionBollinger
from strategies.trend_following_ema import TrendFollowingEMA
from strategies.breakout_momentum import BreakoutMomentum
from strategies.crt_multitimeframe import CRTMultitimeframe


@dataclass
class StrategyRecommendation:
    """Final recommendation: which strategy, which pair, full signal details"""
    selected: bool                     # True if we should take this trade
    strategy_name: str
    symbol: str
    direction: str

    # The actual trade signal
    signal: StrategySignal

    # Selection reasoning
    regime_match_score: float          # How well strategy fits regime
    session_match_score: float         # How well strategy fits session
    pair_match_score: float            # How well strategy fits pair
    overall_score: float               # Combined score

    # Risk
    risk_tier: str
    risk_usd: float

    # Alternative options (if this one rejected)
    alternatives: List[Tuple[str, str, float]] = field(default_factory=list)  # [(strategy, pair, score), ...]

    # Rejection reason (if not selected)
    rejection_reason: Optional[str] = None


class StrategySelector:
    """
    The "Brain" of the trading bot.

    Workflow:
    1. Detect market regime for each pair (RegimeDetector)
    2. Ask ALL 9 strategies to analyze their preferred pairs
    3. Score each strategy-signal combination:
       - Regime fit (40%): Does strategy match current market?
       - Session fit (25%): Is this the right time for this strategy?
       - Pair fit (20%): Is this pair optimal for this strategy?
       - Signal quality (15%): Grade, confidence, R:R
    4. Pick the HIGHEST scored signal that passes Sheriff/Risk checks
    5. Return StrategyRecommendation with full details

    NOT random - purely data-driven selection.
    """

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        self.bridge = bridge or get_bridge()
        self.regime_detector = RegimeDetector(bridge)

        # Instantiate all 9 strategies
        self.strategies = {
            'ict_ob_fvg': ICTOBFVG(bridge),
            'smc_structure': SMCStructure(bridge),
            'london_breakout': LondonBreakout(bridge),
            'wyckoff_amd': WyckoffAMD(bridge),
            'supply_demand_zones': SupplyDemandZones(bridge),
            'mean_reversion_bollinger': MeanReversionBollinger(bridge),
            'trend_following_ema': TrendFollowingEMA(bridge),
            'breakout_momentum': BreakoutMomentum(bridge),
            'crt_multitimeframe': CRTMultitimeframe(bridge),
        }

        # Strategy metadata for scoring
        self.strategy_meta = {
            'ict_ob_fvg': {
                'regimes': ['trending', 'ranging', 'accumulating'],
                'sessions': ['london', 'ny_overlap', 'pre_london'],
                'pairs': ['EURUSD', 'XAUUSD', 'GBPUSD', 'EURJPY', 'USDJPY', 'AUDUSD', 'USDCAD', 'GBPJPY'],
            },
            'smc_structure': {
                'regimes': ['trending', 'accumulating'],
                'sessions': ['london', 'ny_overlap'],
                'pairs': ['EURUSD', 'GBPUSD'],
            },
            'london_breakout': {
                'regimes': ['volatile', 'trending'],
                'sessions': ['london'],
                'pairs': ['GBPUSD', 'GBPJPY', 'EURJPY'],
            },
            'wyckoff_amd': {
                'regimes': ['accumulating', 'ranging'],
                'sessions': ['london', 'ny_overlap', 'pre_london'],
                'pairs': ['XAUUSD', 'XAGUSD'],
            },
            'supply_demand_zones': {
                'regimes': ['ranging', 'accumulating'],
                'sessions': ['all'],
                'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY'],
            },
            'mean_reversion_bollinger': {
                'regimes': ['ranging'],
                'sessions': ['tokyo', 'london', 'pre_london'],
                'pairs': ['USDJPY', 'EURJPY', 'GBPJPY'],
            },
            'trend_following_ema': {
                'regimes': ['trending'],
                'sessions': ['ny_overlap', 'london'],
                'pairs': ['EURUSD', 'GBPUSD', 'AUDUSD', 'USDCAD'],
            },
            'breakout_momentum': {
                'regimes': ['volatile', 'trending'],
                'sessions': ['london', 'ny_overlap'],
                'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY'],
            },
            'crt_multitimeframe': {
                'regimes': ['trending', 'volatile', 'ranging'],
                'sessions': ['london', 'ny_overlap', 'pre_london'],
                'pairs': ['EURUSD', 'GBPUSD', 'XAUUSD'],
            },
        }

    def select_best_trade(
        self,
        dxy_directions: Dict[str, str],
        current_session: Optional[str] = None,
        max_candidates: int = 3
    ) -> List[StrategyRecommendation]:
        """
        Main entry point: Find the BEST trade opportunity across all 9 strategies and 11 pairs.

        Returns ranked list of StrategyRecommendation (top 3 candidates).
        """
        if current_session is None:
            current_session = session_mgr.get_current_session().value

        # Get active pairs for this session
        active_pairs = session_mgr.get_active_pairs()

        all_signals = []

        # === PHASE 1: Detect regime for each pair ===
        regime_readings = {}
        for symbol in active_pairs:
            regime_readings[symbol] = self.regime_detector.analyze_pair(symbol)

        # === PHASE 2: Run ALL strategies on ALL pairs ===
        for symbol in active_pairs:
            dxy_dir = dxy_directions.get(symbol, 'neutral')
            if dxy_dir == 'neutral':
                continue

            regime = regime_readings[symbol]

            # Fetch data once per pair
            try:
                m15 = self.bridge.get_historical_data(symbol, 'M15', 100)
                h1 = self.bridge.get_historical_data(symbol, 'H1', 50)
                h4 = self.bridge.get_historical_data(symbol, 'H4', 30)
            except Exception as e:
                continue

            # Ask each strategy to analyze
            for strat_name, strategy in self.strategies.items():
                try:
                    signal = strategy.detect_setup(symbol, dxy_dir, m15, h1, h4)

                    if signal.valid and signal.is_tradeable:
                        # Score this signal
                        score = self._score_signal(
                            signal=signal,
                            strat_name=strat_name,
                            symbol=symbol,
                            regime=regime,
                            current_session=current_session
                        )

                        all_signals.append((score, strat_name, symbol, signal))

                except Exception as e:
                    # Strategy failed on this pair, continue
                    continue

        # === PHASE 3: Rank and select top candidates ===
        if not all_signals:
            return []

        # Sort by score descending
        all_signals.sort(key=lambda x: x[0], reverse=True)

        # Build recommendations
        recommendations = []
        for i, (score, strat_name, symbol, signal) in enumerate(all_signals[:max_candidates]):

            # Get alternatives (next best options)
            alternatives = [
                (s[1], s[2], s[0]) for s in all_signals[max_candidates:max_candidates+3]
            ]

            # Risk assignment
            risk_tier, risk_usd = self._assign_risk(signal)

            rec = StrategyRecommendation(
                selected=(i == 0),  # Top candidate is "selected"
                strategy_name=strat_name,
                symbol=symbol,
                direction=signal.direction,
                signal=signal,
                regime_match_score=round(self._regime_score(strat_name, regime.regime.value), 2),
                session_match_score=round(self._session_score(strat_name, current_session), 2),
                pair_match_score=round(self._pair_score(strat_name, symbol), 2),
                overall_score=round(score, 3),
                risk_tier=risk_tier,
                risk_usd=risk_usd,
                alternatives=alternatives,
                rejection_reason=None if i == 0 else f"Lower score ({score:.3f}) vs top ({all_signals[0][0]:.3f})"
            )

            recommendations.append(rec)

        return recommendations

    def _score_signal(
        self,
        signal: StrategySignal,
        strat_name: str,
        symbol: str,
        regime,
        current_session: str
    ) -> float:
        """
        Calculate composite score for a strategy-signal combination.

        Weights:
        - Regime fit: 40% (most important - strategy must match market)
        - Signal quality: 25% (grade, confidence, R:R)
        - Session fit: 20% (right time for this strategy)
        - Pair fit: 15% (right pair for this strategy)
        """
        # 1. Regime match (40%)
        regime_score = self._regime_score(strat_name, regime.regime.value)

        # 2. Signal quality (25%)
        quality_score = (
            signal.confidence * 0.4 +           # Confidence weight
            (1.0 if signal.grade in ['A+', 'A'] else 0.7 if signal.grade in ['B+', 'B'] else 0.3) * 0.35 +
            min(1.0, signal.risk_reward / 3.0) * 0.25  # R:R capped at 3.0
        )

        # 3. Session fit (20%)
        session_score = self._session_score(strat_name, current_session)

        # 4. Pair fit (15%)
        pair_score = self._pair_score(strat_name, symbol)

        # Weighted total
        total = (
            regime_score * 0.40 +
            quality_score * 0.25 +
            session_score * 0.20 +
            pair_score * 0.15
        )

        return total

    def _regime_score(self, strat_name: str, regime: str) -> float:
        """Score how well strategy fits current market regime (0-1)"""
        meta = self.strategy_meta.get(strat_name, {})
        best_regimes = meta.get('regimes', [])

        if regime in best_regimes:
            return 1.0

        # Partial match: strategy works in some conditions
        return 0.4

    def _session_score(self, strat_name: str, session: str) -> float:
        """Score how well strategy fits current session (0-1)"""
        meta = self.strategy_meta.get(strat_name, {})
        sessions = meta.get('sessions', [])

        if 'all' in sessions or session in sessions:
            return 1.0

        # Partial: strategy works in some sessions
        return 0.5

    def _pair_score(self, strat_name: str, symbol: str) -> float:
        """Score how well pair fits strategy (0-1)"""
        meta = self.strategy_meta.get(strat_name, {})
        pairs = meta.get('pairs', [])

        if symbol in pairs:
            return 1.0

        # Check pair category
        pair_config = get_pair_config(symbol)
        if pair_config:
            # Prime pairs get slight bonus
            if symbol in ['XAUUSD', 'EURUSD']:
                return 0.8
            # Core pairs
            if symbol in ['GBPUSD', 'EURJPY', 'USDJPY']:
                return 0.7

        return 0.5

    def _assign_risk(self, signal: StrategySignal) -> Tuple[str, float]:
        """Assign risk tier based on signal characteristics"""
        # Use signal's own recommendation if valid
        if signal.risk_tier in ['tight', 'normal', 'wide']:
            return signal.risk_tier, signal.recommended_risk_usd

        # Fallback: calculate from stop pips
        if signal.stop_pips <= 12:
            return 'tight', 4.0
        elif signal.stop_pips <= 20:
            return 'normal', 7.0
        else:
            return 'wide', 10.0

    def get_strategy_for_regime(self, regime: str) -> List[str]:
        """Get strategies ranked for a specific regime"""
        regime_enum = MarketRegime(regime)
        strategies = self.regime_detector.REGIME_STRATEGY_MAP.get(regime_enum, [])
        return [s[0] for s in strategies]

    def quick_check(
        self,
        symbol: str,
        direction: str,
        strategy_hint: Optional[str] = None
    ) -> Optional[StrategySignal]:
        """
        Quick check: Run ONE strategy on ONE pair (for manual override or testing).

        If strategy_hint provided, use that strategy.
        Otherwise, detect regime and pick best strategy.
        """
        # Fetch data
        try:
            m15 = self.bridge.get_historical_data(symbol, 'M15', 100)
            h1 = self.bridge.get_historical_data(symbol, 'H1', 50)
            h4 = self.bridge.get_historical_data(symbol, 'H4', 30)
        except Exception:
            return None

        # Determine strategy
        if strategy_hint and strategy_hint in self.strategies:
            strategy = self.strategies[strategy_hint]
        else:
            # Detect regime and pick best strategy
            regime = self.regime_detector.analyze_pair(symbol)
            if regime.recommended_strategies:
                best_strat = regime.recommended_strategies[0][0]
                strategy = self.strategies.get(best_strat, self.strategies['ict_ob_fvg'])
            else:
                strategy = self.strategies['ict_ob_fvg']

        # Run analysis
        return strategy.detect_setup(symbol, direction, m15, h1, h4)
