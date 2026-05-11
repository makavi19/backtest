# agents/safety_execution/dynamic_risk_manager.py
# Assigns $4 / $7 / $10 risk per trade with full tracking

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum

from core.config import RiskTier, RiskTierConfig, config, get_pair_config


@dataclass
class RiskAssignment:
    """Complete risk allocation for a trade"""
    tier: RiskTier
    dollar_risk: float
    stop_pips: int
    max_attempts: int
    sequence: List[float]  # e.g., [4.0, 4.0, 7.0] for three trades
    
    # Calculated
    lot_size: Optional[float] = None
    actual_stop_price: Optional[float] = None


class DynamicRiskManager:
    """
    Manages $15 daily loss budget across 3 attempts
    Assigns $4 tight, $7 normal, $10 wide based on conditions
    """
    
    DAILY_LOSS_LIMIT = 15.0
    DAILY_PROFIT_TARGET = 60.0
    
    def __init__(self):
        self.tier_configs = config.RISK_TIERS
        self.daily_used = 0.0
        self.trade_history: List[Dict] = []
        
    def get_available_risk(self, current_pnl: float, trades_today: int) -> float:
        """
        Calculate remaining risk budget
        """
        # Check daily limits
        if current_pnl >= self.DAILY_PROFIT_TARGET:
            return 0.0  # Target hit
        
        if current_pnl <= -self.DAILY_LOSS_LIMIT:
            return 0.0  # Loss limit hit
        
        # Remaining loss allowance
        remaining = self.DAILY_LOSS_LIMIT + current_pnl
        
        # Max 3 trades
        remaining_trades = max(0, 3 - trades_today)
        
        if remaining_trades == 0:
            return 0.0
        
        return min(remaining, self.DAILY_LOSS_LIMIT)
    
    def assign_risk_for_setup(
        self,
        symbol: str,
        grade: str,
        atr_pips: Optional[float],
        spread_pips: float,
        session: str,
        volatility_percentile: float,
        available_budget: float
    ) -> Optional[RiskAssignment]:
        """
        Determine appropriate risk tier and amount
        """
        pair_config = get_pair_config(symbol)
        default_tier = pair_config.default_tier if pair_config else RiskTier.NORMAL
        
        # Start with default
        proposed_tier = default_tier
        
        # Adjust based on conditions
        proposed_tier = self._adjust_for_grade(proposed_tier, grade)
        proposed_tier = self._adjust_for_volatility(proposed_tier, volatility_percentile)
        proposed_tier = self._adjust_for_session(proposed_tier, session)
        
        # Get dollar amount
        tier_config = self.tier_configs[proposed_tier]
        dollar_risk = tier_config.max_risk_usd
        
        # Check budget
        if dollar_risk > available_budget:
            # Try smaller tier
            if proposed_tier == RiskTier.WIDE:
                proposed_tier = RiskTier.NORMAL
            elif proposed_tier == RiskTier.NORMAL:
                proposed_tier = RiskTier.TIGHT
            
            tier_config = self.tier_configs[proposed_tier]
            dollar_risk = tier_config.max_risk_usd
            
            if dollar_risk > available_budget:
                return None  # Can't afford any trade
        
        # Determine stop pips
        stop_pips = self._calculate_stop_pips(
            proposed_tier, atr_pips, spread_pips, pair_config
        )
        
        # Build sequence for remaining trades
        sequence = self._build_sequence(
            proposed_tier, dollar_risk, available_budget - dollar_risk
        )
        
        return RiskAssignment(
            tier=proposed_tier,
            dollar_risk=dollar_risk,
            stop_pips=stop_pips,
            max_attempts=len(sequence),
            sequence=sequence
        )
    
    def _adjust_for_grade(self, tier: RiskTier, grade: str) -> RiskTier:
        """Grade-based adjustment"""
        # Wide stops need A grade
        if tier == RiskTier.WIDE and grade not in ['A', 'A+']:
            return RiskTier.NORMAL
        
        # Tight stops need A/B grade
        if tier == RiskTier.TIGHT and grade not in ['A', 'A+', 'B', 'B+']:
            return RiskTier.NORMAL
        
        # A grade can improve tier
        if grade in ['A', 'A+'] and tier == RiskTier.NORMAL:
            # Only if pair supports tight
            pass  # Keep normal, tight has strict requirements
        
        return tier
    
    def _adjust_for_volatility(self, tier: RiskTier, percentile: float) -> RiskTier:
        """Volatility-based adjustment"""
        if percentile > 85:  # High volatility
            if tier == RiskTier.TIGHT:
                return RiskTier.NORMAL  # Tight stops too risky
        
        if percentile < 25:  # Low volatility
            if tier == RiskTier.WIDE:
                return RiskTier.NORMAL  # Wide stops unnecessary
        
        return tier
    
    def _adjust_for_session(self, tier: RiskTier, session: str) -> RiskTier:
        """Session-based adjustment"""
        if session == 'pre_london':
            # Conservative
            if tier == RiskTier.WIDE:
                return RiskTier.NORMAL
        
        if session == 'ny_overlap':
            # Wider acceptable
            if tier == RiskTier.NORMAL:
                # Check if can go wide
                pass  # Keep normal unless other factors
        
        if session == 'ny_solo':
            # No wide stops
            if tier == RiskTier.WIDE:
                return RiskTier.NORMAL
        
        return tier
    
    def _calculate_stop_pips(
        self,
        tier: RiskTier,
        atr_pips: Optional[float],
        spread_pips: float,
        pair_config
    ) -> int:
        """Calculate stop distance in pips"""
        tier_config = self.tier_configs[tier]
        
        # Base from tier
        min_pips = tier_config.min_stop_pips
        max_pips = tier_config.max_stop_pips
        
        # ATR adjustment
        if atr_pips:
            if tier == RiskTier.TIGHT:
                target = int(atr_pips * 0.8)
            elif tier == RiskTier.NORMAL:
                target = int(atr_pips * 1.0)
            else:  # Wide
                target = int(atr_pips * 1.2)
            
            target = max(min_pips, min(max_pips, target))
        else:
            target = (min_pips + max_pips) // 2
        
        # Spread buffer
        min_for_spread = int(spread_pips * 2.5)
        target = max(target, min_for_spread)
        
        return target
    
    def _build_sequence(
        self,
        first_tier: RiskTier,
        first_risk: float,
        remaining_budget: float
    ) -> List[float]:
        """
        Build risk sequence for remaining trades
        
        Example: First $4, then $4, then remaining $7
        """
        sequence = [first_risk]
        
        if remaining_budget >= 4.0:
            sequence.append(4.0)  # Second trade tight
            remaining = remaining_budget - 4.0
            
            if remaining >= 4.0:
                sequence.append(min(7.0, remaining))  # Third trade
        
        elif remaining_budget > 0:
            sequence.append(remaining_budget)
        
        return sequence
    
    def record_trade(self, risk_used: float, result: str, pnl: float):
        """Record trade for tracking"""
        self.daily_used += risk_used
        self.trade_history.append({
            'risk': risk_used,
            'result': result,  # 'win' or 'loss'
            'pnl': pnl
        })
    
    def suggest_next_risk(self) -> Optional[float]:
        """Suggest risk for next trade based on history"""
        if not self.trade_history:
            return 4.0  # Start conservative
        
        recent = self.trade_history[-2:]  # Look at last 2
        
        wins = sum(1 for t in recent if t['result'] == 'win')
        
        if wins == 2:
            # Two wins: can increase
            return 7.0
        elif wins == 1:
            # One win: maintain
            return 4.0
        else:
            # No wins: minimum
            return 4.0
    
    def reset_daily(self):
        """Call at end of day"""
        self.daily_used = 0.0
        self.trade_history = []