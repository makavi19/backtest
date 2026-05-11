
import pytest
from agents.safety_execution.the_sheriff import Sheriff, SheriffDecision


class TestSheriff:
    """Test The Sheriff - correlation and trade approval"""

    def setup_method(self):
        self.sheriff = Sheriff()

    def test_max_trades_limit(self):
        """Test: Reject when max trades reached"""
        # Simulate 4 trades already taken
        decision = self.sheriff.review_trade(
            proposed_symbol='EURUSD',
            proposed_direction='buy',
            proposed_risk=4.0,
            current_pnl=0.0,
            daily_trades_count=4,
        )

        assert not decision.approved
        assert 'maximum reached' in decision.conflicts[0]

    def test_daily_loss_limit(self):
        """Test: Reject when daily loss limit reached"""
        decision = self.sheriff.review_trade(
            proposed_symbol='EURUSD',
            proposed_direction='buy',
            proposed_risk=10.0,
            current_pnl=-16.0,
            daily_trades_count=1,
        )

        assert not decision.approved

    def test_correlation_conflict(self):
        """Test: Reject correlated pair duplicate"""
        # Simulate existing EURUSD trade
        existing = [{'symbol': 'EURUSD', 'direction': 'buy', 'open_time': __import__('datetime').datetime.now()}]

        decision = self.sheriff.review_trade(
            proposed_symbol='GBPUSD',  # Correlated with EURUSD
            proposed_direction='buy',
            proposed_risk=4.0,
            current_pnl=0.0,
            daily_trades_count=1,
            existing_positions=existing
        )

        # Should detect correlation conflict
        assert len(decision.conflicts) > 0 or not decision.approved

    def test_valid_trade_approval(self):
        """Test: Approve valid trade"""
        decision = self.sheriff.review_trade(
            proposed_symbol='XAUUSD',
            proposed_direction='buy',
            proposed_risk=4.0,
            current_pnl=0.0,
            daily_trades_count=0,
        )

        assert decision.approved
        assert decision.action == 'execute'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
'''

with open('/mnt/agents/output/tests/test_correlation.py', 'w') as f:
    f.write(test_correlation)

# Test 2: Risk tiers
test_risk = '''# tests/test_risk_tiers.py
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

        assert available == 15.0  # Full $15 budget

    def test_available_risk_after_loss(self):
        """Test: Reduced budget after loss"""
        available = self.risk_mgr.get_available_risk(
            current_pnl=-5.0,
            trades_today=1
        )

        assert available == 10.0  # $15 - $5 used

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
            grade='B',  # B grade should downgrade to normal
            atr_pips=30,
            spread_pips=0.2,
            session='london',
            volatility_percentile=70,
            available_budget=15.0
        )

        assert assignment is not None
        assert assignment.tier != RiskTier.WIDE  # Should be downgraded

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
'''

with open('/mnt/agents/output/tests/test_risk_tiers.py', 'w') as f:
    f.write(test_risk)

# Test 3: Session phases
test_session = '''# tests/test_session_phases.py
# Test session management and timing

import pytest
from datetime import time
from core.session_manager import SessionManager, SessionPhase
from core.config import config


class TestSessionPhases:
    """Test Session Manager - IST timezone and phases"""

    def setup_method(self):
        self.mgr = SessionManager()

    def test_london_prime_detection(self):
        """Test: Correctly identify London prime time"""
        # Mock time to 14:00 IST (London prime)
        from unittest.mock import patch

        with patch.object(self.mgr, 'now', return_value=self.mgr.ist.localize(
            __import__('datetime').datetime(2024, 1, 15, 14, 0)
        )):
            phase = self.mgr.get_current_session()
            assert phase == SessionPhase.LONDON

    def test_ny_solo_no_new_trades(self):
        """Test: NY solo phase blocks new trades"""
        from unittest.mock import patch

        with patch.object(self.mgr, 'now', return_value=self.mgr.ist.localize(
            __import__('datetime').datetime(2024, 1, 15, 22, 0)
        )):
            can_trade = self.mgr.can_open_new_trades()
            assert not can_trade

    def test_time_to_close(self):
        """Test: Calculate minutes until hard stop"""
        from unittest.mock import patch

        with patch.object(self.mgr, 'now', return_value=self.mgr.ist.localize(
            __import__('datetime').datetime(2024, 1, 15, 23, 0)
        )):
            minutes = self.mgr.time_to_close()
            assert minutes == 50  # 23:50 - 23:00

    def test_pre_london_selective(self):
        """Test: Pre-London only allows A grade"""
        from unittest.mock import patch

        with patch.object(self.mgr, 'now', return_value=self.mgr.ist.localize(
            __import__('datetime').datetime(2024, 1, 15, 11, 0)
        )):
            phase = self.mgr.get_current_session()
            assert phase == SessionPhase.PRE_LONDON

            # Should allow trades but very selective
            assert self.mgr.can_open_new_trades()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
