# core/dynamic_risk.py
# Dynamic risk tier assignment: $4 / $7 / $10 per trade

from dataclasses import dataclass
from typing import Tuple, Optional, Dict, List
from enum import Enum

from core.config import RiskTier, RiskTierConfig, PairConfig, config, get_pair_config


class RiskAssessment:
    """Result of risk tier evaluation"""
    def __init__(
        self,
        tier: RiskTier,
        risk_usd: float,
        stop_pips: int,
        lot_size: Optional[float] = None,
        max_sl_pct: Optional[float] = None
    ):
        self.tier = tier
        self.risk_usd = risk_usd
        self.stop_pips = stop_pips
        self.lot_size = lot_size
        self.max_sl_pct = max_sl_pct  # Stop as % of price
        
    def __repr__(self):
        return f"RiskAssessment({self.tier.value}, ${self.risk_usd}, {self.stop_pips}pips)"
    
    def to_dict(self) -> Dict:
        return {
            'tier': self.tier.value,
            'risk_usd': self.risk_usd,
            'stop_pips': self.stop_pips,
            'lot_size': self.lot_size,
            'max_sl_pct': self.max_sl_pct,
        }


class DynamicRiskCalculator:
    """
    Assigns risk tier based on:
    - Pair characteristics (volatility, spread)
    - Market conditions (ATR, session)
    - Setup quality (grade A/B)
    """
    
    def __init__(self):
        self.tier_configs = config.RISK_TIERS
        
    def assess_risk_tier(
        self,
        symbol: str,
        setup_grade: str,  # 'A', 'B', 'C'
        current_atr_pips: Optional[float] = None,
        session: Optional[str] = None,
        spread_pips: Optional[float] = None
    ) -> RiskAssessment:
        """
        Determine appropriate risk tier for a setup
        """
        pair_config = get_pair_config(symbol)
        if not pair_config:
            # Fallback to normal tier
            return self._create_assessment(RiskTier.NORMAL, symbol)
        
        # Start with pair's default
        proposed_tier = pair_config.default_tier
        proposed_config = self.tier_configs[proposed_tier]
        
        # Grade check: wide stops need A grade
        if proposed_tier == RiskTier.WIDE and setup_grade != 'A':
            # Downgrade to normal
            proposed_tier = RiskTier.NORMAL
            proposed_config = self.tier_configs[proposed_tier]
        
        # Tight stops need A grade
        if proposed_tier == RiskTier.TIGHT and setup_grade not in ['A', 'A+']:
            proposed_tier = RiskTier.NORMAL
            proposed_config = self.tier_configs[proposed_tier]
        
        # ATR check: adjust stop size
        adjusted_stop = self._adjust_stop_for_atr(
            proposed_config, current_atr_pips, pair_config
        )
        
        # Spread check: widen stop if spread is high
        adjusted_stop = self._adjust_for_spread(
            adjusted_stop, spread_pips, pair_config
        )
        
        # Validate stop is within tier bounds
        adjusted_stop = max(
            proposed_config.min_stop_pips,
            min(proposed_config.max_stop_pips, adjusted_stop)
        )
        
        return self._create_assessment(proposed_tier, symbol, adjusted_stop)
    
    def _adjust_stop_for_atr(
        self,
        tier_config: RiskTierConfig,
        atr_pips: Optional[float],
        pair_config: PairConfig
    ) -> int:
        """Adjust stop based on current market volatility"""
        if atr_pips is None:
            # Use tier default
            return (tier_config.min_stop_pips + tier_config.max_stop_pips) // 2
        
        # For tight tier: 0.8x ATR
        # For normal tier: 1.0x ATR
        # For wide tier: 1.2x ATR
        
        multipliers = {
            RiskTier.TIGHT: 0.8,
            RiskTier.NORMAL: 1.0,
            RiskTier.WIDE: 1.2,
        }
        
        # Get base tier (we need to know which one we're adjusting)
        # This is a simplification - in practice, pass tier explicitly
        multiplier = 1.0
        
        adjusted = atr_pips * multiplier
        
        # Ensure within bounds
        return int(max(
            tier_config.min_stop_pips,
            min(tier_config.max_stop_pips, adjusted)
        ))
    
    def _adjust_for_spread(
        self,
        stop_pips: int,
        spread_pips: Optional[float],
        pair_config: PairConfig
    ) -> int:
        """Ensure stop is at least 2x spread"""
        if spread_pips is None:
            spread_pips = pair_config.spread_typical
        
        min_stop_for_spread = int(spread_pips * 2.5)
        
        return max(stop_pips, min_stop_for_spread)
    
    def _create_assessment(
        self,
        tier: RiskTier,
        symbol: str,
        stop_pips: Optional[int] = None
    ) -> RiskAssessment:
        """Create risk assessment for tier"""
        tier_config = self.tier_configs[tier]
        
        if stop_pips is None:
            stop_pips = (tier_config.min_stop_pips + tier_config.max_stop_pips) // 2
        
        # Calculate lot size would need account balance from MT5
        # Return without lot_size for now, calculate later
        
        return RiskAssessment(
            tier=tier,
            risk_usd=tier_config.max_risk_usd,
            stop_pips=stop_pips,
            lot_size=None,
            max_sl_pct=None
        )
    
    def calculate_position_size(
        self,
        risk_assessment: RiskAssessment,
        entry_price: float,
        account_balance: float,
        account_currency: str = 'USD'
    ) -> RiskAssessment:
        """
        Calculate actual lot size based on account balance
        
        Formula: Risk Amount / (Stop Pips * Pip Value * Point)
        """
        if account_currency != 'USD':
            # Would need conversion
            pass
        
        tier_config = self.tier_configs[risk_assessment.tier]
        risk_amount = min(
            tier_config.max_risk_usd,
            account_balance * 0.01  # Max 1% of account per trade
        )
        
        # Get pair config for pip calculation
        pair_config = None
        for sym, cfg in config.PAIRS.items():
            if sym == entry_price:  # This logic needs fixing
                pass
        
        # Simplified lot calculation
        # Standard: 1 lot = $10 per pip on EURUSD
        # Risk $4, 10 pip stop = need $4 / $100 per lot = 0.04 lots
        # But this varies by pair
        
        # Placeholder - actual calculation in MT5 bridge
        risk_assessment.lot_size = 0.0  # To be calculated with live prices
        risk_assessment.risk_usd = risk_amount
        
        return risk_assessment
    
    def get_daily_risk_budget(
        self,
        current_pnl: float,
        trades_today: int,
        daily_loss: float = -15.0
    ) -> Dict:
        """
        Calculate remaining risk budget for the day
        
        Returns how many trades and what risk per trade
        """
        remaining_loss_allowance = daily_loss - current_pnl
        
        if remaining_loss_allowance <= 0:
            # Already at or past loss limit
            return {
                'can_trade': False,
                'reason': 'Daily loss limit reached',
                'trades_remaining': 0,
                'risk_per_trade': 0,
            }
        
        # Always allow at least one small attempt if budget permits
        if remaining_loss_allowance >= 10:
            # Full 3-trade structure possible
            return {
                'can_trade': True,
                'trades_remaining': 3 - trades_today,
                'risk_options': [4.0, 4.0, remaining_loss_allowance - 8],
                'suggested': 'Start with $4 tight, scale up if winning',
            }
        elif remaining_loss_allowance >= 7:
            # Two normal trades
            return {
                'can_trade': True,
                'trades_remaining': 2 - trades_today,
                'risk_options': [4.0, remaining_loss_allowance - 4],
                'suggested': 'Conservative, tight entries only',
            }
        elif remaining_loss_allowance >= 4:
            # One last shot
            return {
                'can_trade': True,
                'trades_remaining': 1,
                'risk_options': [4.0],
                'suggested': 'Final trade, A+ setup only',
            }
        else:
            # Too little left for meaningful trade
            return {
                'can_trade': False,
                'reason': f'Only ${remaining_loss_allowance:.2f} risk remaining',
                'trades_remaining': 0,
                'risk_per_trade': 0,
            }
    
    def recommend_tier_sequence(
        self,
        won_first: Optional[bool] = None,
        won_second: Optional[bool] = None
    ) -> List[RiskTier]:
        """
        Recommend sequence of tiers based on early results
        
        Example: Win $4 tight, then $7 normal, then $4 tight again
        """
        if won_first is None:
            # No trades yet: start conservative
            return [RiskTier.TIGHT, RiskTier.NORMAL, RiskTier.TIGHT]
        
        if won_first:
            # First trade won: can afford normal risk
            if won_second is None:
                # Second trade: normal risk
                return [RiskTier.NORMAL, RiskTier.TIGHT]
            elif won_second:
                # Two wins: lock in profit, small risk
                return [RiskTier.TIGHT]
            else:
                # Win then loss: back to tight
                return [RiskTier.TIGHT]
        else:
            # First trade lost: must be tighter
            if won_second is None:
                return [RiskTier.TIGHT, RiskTier.TIGHT]
            elif won_second:
                # Loss then win: normal risk for third
                return [RiskTier.NORMAL]
            else:
                # Two losses: last chance, minimum risk
                return [RiskTier.TIGHT]


# Singleton
risk_calc = DynamicRiskCalculator()


def get_risk_for_setup(
    symbol: str,
    grade: str,
    atr: Optional[float] = None
) -> RiskAssessment:
    """Quick utility function"""
    return risk_calc.assess_risk_tier(symbol, grade, atr)


def check_daily_budget(current_pnl: float, trades: int) -> Dict:
    """Quick utility function"""
    return risk_calc.get_daily_risk_budget(current_pnl, trades)