# agents/safety_execution/session_allocator.py
# Allocates trading parameters based on session phase

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from core.config import RiskTier, SessionPhase, config, get_pair_config
from core.session_manager import session_mgr


@dataclass
class SessionParameters:
    """Trading parameters for current session"""
    phase: str
    can_trade_new: bool
    can_manage_exits: bool
    max_trades_allowed: int
    risk_tier_bias: RiskTier  # Prefer tighter/more conservative
    min_grade_required: str  # 'A', 'B', etc.
    focus_pairs: List[str]  # Which pairs to prioritize
    strategy_weights: Dict[str, float]
    notes: str


class SessionAllocator:
    """
    Determines trading behavior based on session phase:
    - Pre-London: Analysis, rare A+ trades
    - London Prime: Full deployment, best opportunities
    - NY Overlap: Selective, manage volatility
    - NY Solo: Exit management only
    """
    
    def __init__(self):
        self.current_phase: Optional[SessionPhase] = None
        self.parameters: Optional[SessionParameters] = None
        
    def update(self) -> SessionParameters:
        """Get current session parameters"""
        phase = session_mgr.get_current_session()
        self.current_phase = phase
        
        # Delegate to phase-specific allocator
        if phase == SessionPhase.PRE_LONDON:
            self.parameters = self._pre_london_params()
        elif phase == SessionPhase.LONDON:
            self.parameters = self._london_params()
        elif phase == SessionPhase.NY_OVERLAP:
            self.parameters = self._ny_overlap_params()
        elif phase == SessionPhase.NY_SOLO:
            self.parameters = self._ny_solo_params()
        else:  # Closed
            self.parameters = self._closed_params()
        
        return self.parameters
    
    def _pre_london_params(self) -> SessionParameters:
        """10:30 AM - 12:30 PM IST: Building, selective"""
        return SessionParameters(
            phase='pre_london',
            can_trade_new=True,  # But very selective
            can_manage_exits=True,
            max_trades_allowed=1,  # Max 1 trade
            risk_tier_bias=RiskTier.TIGHT,  # Tight stops only
            min_grade_required='A',  # A grade only
            focus_pairs=['EURUSD', 'XAUUSD', 'GBPUSD'],  # Prime only
            strategy_weights={
                'ict_ob_fvg': 0.40,
                'crt_multitimeframe': 0.35,
                'supply_demand_zones': 0.25,
            },
            notes='Analysis phase. Only A+ setups. Wait for London if unsure.'
        )
    
    def _london_params(self) -> SessionParameters:
        """12:30 PM - 5:30 PM IST: Prime trading window"""
        return SessionParameters(
            phase='london',
            can_trade_new=True,
            can_manage_exits=True,
            max_trades_allowed=3,  # Up to 3 trades
            risk_tier_bias=RiskTier.NORMAL,  # Default to pair setting
            min_grade_required='B',  # B grade acceptable
            focus_pairs=[
                'EURUSD', 'XAUUSD', 'GBPUSD',  # Prime
                'EURJPY', 'USDJPY', 'GBPJPY',  # Crosses
                'AUDUSD', 'USDCAD'             # Selected
            ],
            strategy_weights={
                'ict_ob_fvg': 0.30,
                'smc_structure': 0.25,
                'london_breakout': 0.25,
                'wyckoff_amd': 0.10,
                'supply_demand_zones': 0.10,
            },
            notes='PRIMARY TRADING WINDOW. Deploy fully. Best R:R opportunities.'
        )
    
    def _ny_overlap_params(self) -> SessionParameters:
        """5:30 PM - 9:30 PM IST: Volatile, conditional"""
        return SessionParameters(
            phase='ny_overlap',
            can_trade_new=True,  # But reduced
            can_manage_exits=True,
            max_trades_allowed=2,  # Max 2 new trades
            risk_tier_bias=RiskTier.NORMAL,  # Conservative
            min_grade_required='B',  # B grade, strict scrutiny
            focus_pairs=[
                'EURUSD', 'XAUUSD',  # Stable
                'USDJPY', 'EURJPY'   # NY active
            ],
            strategy_weights={
                'ict_ob_fvg': 0.25,
                'smc_structure': 0.20,
                'breakout_momentum': 0.25,  # News-driven
                'trend_following_ema': 0.15,
                'mean_reversion_bollinger': 0.15,  # Volatility plays
            },
            notes='High volatility. Manage London trades. New trades: Prime/Core only, A/B grade.'
        )
    
    def _ny_solo_params(self) -> SessionParameters:
        """9:30 PM - 11:50 PM IST: Exit management only"""
        return SessionParameters(
            phase='ny_solo',
            can_trade_new=False,  # NO NEW TRADES
            can_manage_exits=True,
            max_trades_allowed=0,
            risk_tier_bias=RiskTier.TIGHT,  # Irrelevant, no new trades
            min_grade_required='A',  # Irrelevant
            focus_pairs=[],  # None
            strategy_weights={},  # Not trading
            notes='EXIT MANAGEMENT ONLY. Trail stops, take profits, cut losses. No new entries.'
        )
    
    def _closed_params(self) -> SessionParameters:
        """Before 10:30 AM or after 11:50 PM IST"""
        return SessionParameters(
            phase='closed',
            can_trade_new=False,
            can_manage_exits=False,  # Should be flat
            max_trades_allowed=0,
            risk_tier_bias=RiskTier.TIGHT,
            min_grade_required='A',
            focus_pairs=[],
            strategy_weights={},
            notes='Market closed. Rest and prepare for next session.'
        )
    
    def should_allow_new_trade(
        self,
        current_trades: int,
        current_grade: str
    ) -> Tuple[bool, str]:
        """Check if new trade allowed"""
        if not self.parameters:
            self.update()
        
        params = self.parameters
        
        # Basic permission
        if not params.can_trade_new:
            return False, f"Phase {params.phase}: No new trades allowed"
        
        # Count check
        if current_trades >= params.max_trades_allowed:
            return False, f"Max {params.max_trades_allowed} trades for {params.phase}"
        
        # Grade check
        grade_order = {'A+': 5, 'A': 4, 'B+': 3, 'B': 2, 'C': 1, 'D': 0}
        current_val = grade_order.get(current_grade, 0)
        required_val = grade_order.get(params.min_grade_required, 0)
        
        if current_val < required_val:
            return False, f"Grade {current_grade} below required {params.min_grade_required} for {params.phase}"
        
        return True, "Trade approved for session parameters"
    
    def get_recommended_pairs(self) -> List[str]:
        """Get prioritized pairs for current session"""
        if not self.parameters:
            self.update()
        
        return self.parameters.focus_pairs
    
    def get_strategy_weights(self) -> Dict[str, float]:
        """Get strategy probability weights for current session"""
        if not self.parameters:
            self.update()
        
        return self.parameters.strategy_weights
    
    def get_risk_recommendation(self, pair: str) -> RiskTier:
        """Get recommended risk tier considering session bias"""
        if not self.parameters:
            self.update()
        
        pair_config = get_pair_config(pair)
        default = pair_config.default_tier if pair_config else RiskTier.NORMAL
        
        # Session may bias more conservative
        bias = self.parameters.risk_tier_bias
        
        if bias == RiskTier.TIGHT and default == RiskTier.WIDE:
            return RiskTier.NORMAL  # Step down
        
        if bias == RiskTier.TIGHT and default == RiskTier.NORMAL:
            return RiskTier.TIGHT  # Step down
        
        return default
    
    def is_exit_only(self) -> bool:
        """Check if in exit-management-only phase"""
        if not self.parameters:
            self.update()
        
        return not self.parameters.can_trade_new
    
    def time_in_phase(self) -> Tuple[str, float]:
        """Current phase and progress percentage"""
        phase, progress = session_mgr.get_session_progress()
        return phase.value, progress
    
    def alert_if_transition_soon(self, minutes_before: int = 15) -> Optional[str]:
        """Alert if session phase ending soon"""
        # Check time to next phase or close
        time_left = session_mgr.time_to_close()
        
        if time_left <= minutes_before:
            return f"Session ends in {time_left} minutes - prepare exits"
        
        # Could add more granular phase transitions
        
        return None