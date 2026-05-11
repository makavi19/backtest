# core/session_manager.py
# IST Timezone management and trading session phases

from datetime import datetime, time, timedelta
from typing import Literal, Tuple, Optional, List
import pytz

from core.config import config, SessionPhase, RiskTier


class SessionManager:
    """
    Manages trading sessions in Indian Standard Time (IST, UTC+5:30)
    Handles phase transitions and trading eligibility
    """
    
    def __init__(self):
        self.ist = pytz.timezone('Asia/Kolkata')
        self.utc = pytz.UTC
        self._current_phase: Optional[SessionPhase] = None
        self._last_check: Optional[datetime] = None
        
    def now(self) -> datetime:
        """Current time in IST"""
        return datetime.now(self.ist)
    
    def get_current_session(self) -> SessionPhase:
        """Determine current trading phase based on IST time"""
        now = self.now().time()
        
        # Check if within trading hours
        if now < config.TRADING_START or now > config.TRADING_END:
            return SessionPhase.CLOSED
        
        # Check sub-sessions
        if config.PRE_LONDON[0] <= now < config.PRE_LONDON[1]:
            return SessionPhase.PRE_LONDON
        elif config.LONDON[0] <= now < config.LONDON[1]:
            return SessionPhase.LONDON
        elif config.NY_OVERLAP[0] <= now < config.NY_OVERLAP[1]:
            return SessionPhase.NY_OVERLAP
        elif config.NY_SOLO[0] <= now <= config.TRADING_END:
            return SessionPhase.NY_SOLO
        
        return SessionPhase.CLOSED
    
    def is_trading_time(self) -> bool:
        """Check if currently within trading hours"""
        return self.get_current_session() != SessionPhase.CLOSED
    
    def is_prime_session(self) -> bool:
        """Check if in London prime window (best trading)"""
        return self.get_current_session() == SessionPhase.LONDON
    
    def time_to_session_start(self, target: SessionPhase) -> Optional[int]:
        """Minutes until target session starts"""
        now = self.now()
        now_time = now.time()
        
        session_times = {
            SessionPhase.PRE_LONDON: config.PRE_LONDON[0],
            SessionPhase.LONDON: config.LONDON[0],
            SessionPhase.NY_OVERLAP: config.NY_OVERLAP[0],
            SessionPhase.NY_SOLO: config.NY_SOLO[0],
        }
        
        target_time = session_times.get(target)
        if not target_time:
            return None
        
        # If already passed, wait for tomorrow
        if now_time >= target_time:
            return None  # Session already started or passed
        
        target_dt = datetime.combine(now.date(), target_time)
        target_dt = self.ist.localize(target_dt)
        
        return int((target_dt - now).total_seconds() / 60)
    
    def time_to_close(self) -> int:
        """Minutes until 11:50 PM IST hard stop"""
        now = self.now()
        close_time = datetime.combine(now.date(), config.TRADING_END)
        close_time = self.ist.localize(close_time)
        
        if now > close_time:
            return 0
        
        return int((close_time - now).total_seconds() / 60)
    
    def get_session_progress(self) -> Tuple[SessionPhase, float]:
        """Current phase and percentage complete"""
        phase = self.get_current_session()
        
        if phase == SessionPhase.CLOSED:
            return phase, 0.0
        
        now = self.now().time()
        session_times = {
            SessionPhase.PRE_LONDON: config.PRE_LONDON,
            SessionPhase.LONDON: config.LONDON,
            SessionPhase.NY_OVERLAP: config.NY_OVERLAP,
            SessionPhase.NY_SOLO: (config.NY_SOLO[0], config.TRADING_END),
        }
        
        start, end = session_times.get(phase, (now, now))
        
        # Calculate progress percentage
        start_min = start.hour * 60 + start.minute
        end_min = end.hour * 60 + end.minute
        now_min = now.hour * 60 + now.minute
        
        progress = (now_min - start_min) / max(1, (end_min - start_min))
        return phase, min(1.0, max(0.0, progress))
    
    def is_weekend(self) -> bool:
        """Check if Saturday or Sunday"""
        return self.now().weekday() >= 5  # 5=Sat, 6=Sun
    
    def get_active_pairs(self) -> List[str]:
        """Get pairs suitable for current session"""
        from core.config import get_active_pairs_for_session
        
        session = self.get_current_session()
        if session == SessionPhase.CLOSED:
            return []
        
        return get_active_pairs_for_session(session.value)
    
    def get_recommended_risk_tier(self, pair: str) -> RiskTier:
        """Get recommended risk tier based on session and pair"""
        from core.config import get_pair_config, get_default_risk_tier
        
        session = self.get_current_session()
        
        # London prime: can use tight stops
        if session == SessionPhase.LONDON:
            pair_config = get_pair_config(pair)
            if pair_config and pair_config.default_tier == RiskTier.TIGHT:
                return RiskTier.TIGHT
        
        # NY Overlap: normal, more volatility
        elif session == SessionPhase.NY_OVERLAP:
            return RiskTier.NORMAL
        
        # Pre-London or NY Solo: more conservative
        elif session in [SessionPhase.PRE_LONDON, SessionPhase.NY_SOLO]:
            return RiskTier.NORMAL
        
        # Default to pair's setting
        return get_default_risk_tier(pair)
    
    def can_open_new_trades(self) -> bool:
        """Check if new trades allowed in current phase"""
        session = self.get_current_session()
        
        # No new trades in NY Solo (exit management only)
        if session == SessionPhase.NY_SOLO:
            return False
        
        # No new trades when closed
        if session == SessionPhase.CLOSED:
            return False
        
        # Pre-London: only if exceptional setup (handled elsewhere)
        # London and NY Overlap: full trading
        
        return True
    
    def is_exit_management_only(self) -> bool:
        """Check if should only manage existing positions"""
        return self.get_current_session() == SessionPhase.NY_SOLO
    
    def next_session_info(self) -> Tuple[Optional[SessionPhase], int]:
        """Next trading session and minutes until start"""
        now = self.now()
        current = self.get_current_session()
        
        phases_order = [
            SessionPhase.PRE_LONDON,
            SessionPhase.LONDON,
            SessionPhase.NY_OVERLAP,
            SessionPhase.NY_SOLO,
        ]
        
        # Find current index
        try:
            current_idx = phases_order.index(current)
        except ValueError:
            current_idx = -1
        
        # Look for next phase today
        for phase in phases_order[current_idx + 1:]:
            minutes = self.time_to_session_start(phase)
            if minutes is not None:
                return phase, minutes
        
        # All phases passed, wait for tomorrow pre-london
        tomorrow = now.date() + timedelta(days=1)
        if tomorrow.weekday() >= 5:  # Weekend
            days_to_monday = 7 - tomorrow.weekday()
            tomorrow = tomorrow + timedelta(days=days_to_monday)
        
        target = datetime.combine(tomorrow, config.PRE_LONDON[0])
        target = self.ist.localize(target)
        minutes = int((target - now).total_seconds() / 60)
        
        return SessionPhase.PRE_LONDON, minutes
    
    def get_session_name(self, phase: Optional[SessionPhase] = None) -> str:
        """Human-readable session name"""
        if phase is None:
            phase = self.get_current_session()
        
        names = {
            SessionPhase.PRE_LONDON: "Pre-London (Analysis)",
            SessionPhase.LONDON: "London Prime (Active Trading)",
            SessionPhase.NY_OVERLAP: "NY Overlap (Volatile)",
            SessionPhase.NY_SOLO: "NY Solo (Exit Management)",
            SessionPhase.CLOSED: "Market Closed",
        }
        return names.get(phase, "Unknown")


# Singleton instance
session_mgr = SessionManager()


def get_current_ist_time() -> datetime:
    """Utility: current IST time"""
    return session_mgr.now()


def format_ist_time(dt: Optional[datetime] = None) -> str:
    """Utility: format time as IST string"""
    if dt is None:
        dt = session_mgr.now()
    return dt.strftime('%Y-%m-%d %H:%M:%S IST')
