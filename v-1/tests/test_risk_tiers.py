# tests/test_risk_tiers.py
# Test dynamic risk assignment

import pytest
from agents.safety_execution.dynamic_risk_manager import DynamicRiskManager, RiskAssignment
from core.config import RiskTier


class TestDynamicRisk:
    """Test Dynamic Risk Manager - $4/$7/$10 tiers"""
    
    def setup_method(self):
        self.risk_mgr = DynamicRiskManager()
    
    def test_available_risk_at_start(self):
        """Test: Full budget available at day start"""
        available = self.risk_mgr.get_available_risk(
            current_pnl=0.0,
            trades_today=0
        )
        assert available == 15.0
    
    def test_available_risk_after_loss(self):
        """Test: Reduced budget after loss"""
        available = self.risk_mgr.get_available_risk(
            current_pnl=-5.0,
            trades_today=1
        )
        assert available == 10.0
    
    def test_available_risk_at_limit(self):
        """Test: Zero budget at loss limit"""
        available = self.risk_mgr.get_available_risk(
            current_pnl=-15.0,
            trades_today=3
        )
        assert available == 0.0
    
    def test_tight_risk_assignment(self):
        """Test: Assign $4 tight risk for A grade + low volatility"""
        assignment = self.risk_mgr.assign_risk_for_setup(
            symbol='EURUSD',
            grade='A',
            atr_pips=10,
            spread_pips=0.1,
            session='london',
            volatility_percentile=30,
            available_budget=15.0
        )
        assert assignment is not None
        assert assignment.tier == RiskTier.TIGHT
        assert assignment.dollar_risk == 4.0
    
    def test_wide_risk_needs_a_grade(self):
        """Test: Wide risk ($10) requires A grade"""
        assignment = self.risk_mgr.assign_risk_for_setup(
            symbol='GBPJPY',
            grade='B',
            atr_pips=30,
            spread_pips=0.2,
            session='london',
            volatility_percentile=70,
            available_budget=15.0
        )
        assert assignment is not None
        assert assignment.tier != RiskTier.WIDE
    
    def test_sequence_building(self):
        """Test: Build risk sequence for remaining trades"""
        sequence = self.risk_mgr._build_sequence(
            first_tier=RiskTier.TIGHT,
            first_risk=4.0,
            remaining_budget=11.0
        )
        assert sequence[0] == 4.0
        assert len(sequence) >= 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])