# tests/test_session_phases.py
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
            assert minutes == 50
    
    def test_pre_london_selective(self):
        """Test: Pre-London only allows A grade"""
        from unittest.mock import patch
        
        with patch.object(self.mgr, 'now', return_value=self.mgr.ist.localize(
            __import__('datetime').datetime(2024, 1, 15, 11, 0)
        )):
            phase = self.mgr.get_current_session()
            assert phase == SessionPhase.PRE_LONDON
            assert self.mgr.can_open_new_trades()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])