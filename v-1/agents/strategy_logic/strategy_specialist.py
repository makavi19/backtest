# agents/strategy_logic/strategy_specialist.py
# Final strategy validation and selection

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime

from agents.market_intelligence.market_scanner import ScanResult
from agents.market_intelligence.volatility_monitor import VolatilityReading
from core.config import RiskTier, get_pair_config


@dataclass
class StrategyResult:
    """Final validated strategy output"""
    symbol: str
    direction: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_amount: float  # $4, $7, or $10
    risk_tier: RiskTier
    position_size: float  # lots
    strategy_type: str  # which of the 9 strategies
    grade: str  # 'A', 'B', 'C'
    confidence: float  # 0.0 to 1.0
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class StrategySpecialist:
    """
    Final validation gate before execution
    Confirms all criteria met, assigns dynamic risk
    """
    
    # Minimum requirements by session phase
    MIN_GRADE = {
        'pre_london': 'A',      # Only best setups
        'london': 'B',          # Standard quality
        'ny_overlap': 'B',      # But tighter scrutiny
        'ny_solo': 'A',         # High conviction only
    }
    
    def __init__(self, session: str = 'london'):
        self.session = session
        self.min_required = self.MIN_GRADE.get(session, 'B')
        
    def validate_setup(
        self,
        scan_result: ScanResult,
        volatility: VolatilityReading,
        dxy_strength: int,
        daily_pnl: float = 0.0,
        open_trades: int = 0
    ) -> Optional[StrategyResult]:
        """
        Full validation pipeline for a single setup
        """
        reasons = []
        warnings = []
        
        # 1. Grade check
        if scan_result.grade == 'C':
            return None  # Never trade C grade
        
        if scan_result.grade < self.min_required:
            return None  # Session too strict for this grade
        
        reasons.append(f"Grade {scan_result.grade} meets session minimum {self.min_required}")
        
        # 2. Volatility check
        if not volatility.is_tradeable():
            warnings.append(f"Volatility caution: {volatility.volatility_rating}")
            # Allow but warn
        
        if volatility.recommended_tier == 'none':
            return None  # Volatility says avoid
        
        # 3. DXY strength check
        if dxy_strength < 60:
            if scan_result.grade != 'A':
                return None  # Weak DXY needs A grade confirmation
        
        reasons.append(f"DXY strength {dxy_strength} sufficient")
        
        # 4. Determine risk tier
        risk_tier = self._assign_risk_tier(
            scan_result, volatility, scan_result.grade
        )
        
        # 5. Get risk amount
        from core.dynamic_risk import risk_calc
        tier_config = risk_calc.tier_configs.get(risk_tier)
        risk_amount = tier_config.max_risk_usd if tier_config else 7.0
        
        # 6. Calculate position size (placeholder, actual in execution)
        position_size = 0.0  # Will be calculated with live MT5
        
        # 7. Final validation
        result = StrategyResult(
            symbol=scan_result.symbol,
            direction=scan_result.direction,
            entry_price=scan_result.entry_zone[0],
            stop_loss=scan_result.stop_loss,
            take_profit_1=scan_result.take_profit_1,
            take_profit_2=scan_result.take_profit_2,
            risk_amount=risk_amount,
            risk_tier=risk_tier,
            position_size=position_size,
            strategy_type=scan_result.setup_type,
            grade=scan_result.grade,
            confidence=scan_result.confidence,
            reasons=reasons,
            warnings=warnings
        )
        
        return result
    
    def _assign_risk_tier(
        self,
        scan: ScanResult,
        vol: VolatilityReading,
        grade: str
    ) -> RiskTier:
        """
        Assign appropriate risk tier based on conditions
        """
        from core.config import RiskTier
        
        pair_config = get_pair_config(scan.symbol)
        default = pair_config.default_tier if pair_config else RiskTier.NORMAL
        
        # Volatility recommendation
        if vol.recommended_tier == 'tight':
            return RiskTier.TIGHT
        elif vol.recommended_tier == 'wide':
            # Only if not tight by default and grade A
            if default != RiskTier.TIGHT and grade == 'A':
                return RiskTier.WIDE
        
        # Grade adjustment
        if grade == 'A' and default == RiskTier.NORMAL:
            # Can try tight on A grade
            return RiskTier.TIGHT
        elif grade == 'B' and default == RiskTier.WIDE:
            # Step down B grade on wide
            return RiskTier.NORMAL
        
        return default