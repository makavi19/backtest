# agents/market_dynamics/session_clock.py
# Session timing alerts and phase management

from dataclasses import dataclass
from typing import Optional, Callable, List
import datetime as dt
from datetime import timedelta
import threading
import time


@dataclass
class SessionAlert:
    """Scheduled alert for session events"""
    alert_time: dt.datetime
    message: str
    priority: str  # 'high', 'medium', 'low'
    action_required: Optional[str] = None
    triggered: bool = False


class SessionClock:
    """
    Manages session timing and alerts

    Alerts for:
    - Session starts/ends
    - Phase transitions
    - Wind-down warnings
    """

    ALERT_TIMES_IST = {
        'pre_london_open': (10, 30),
        'london_open': (12, 30),
        'london_mid': (15, 00),  # Middle, reassess
        'ny_overlap_start': (17, 30),
        'ny_solo_start': (21, 30),
        'wind_down_warning': (23, 30),
        'hard_stop': (23, 50),
    }

    def __init__(self):
        self.alerts: List[SessionAlert] = []
        self.callbacks: List[Callable] = []
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def setup_daily_alerts(self):
        """Create alerts for trading day"""
        from core.session_manager import session_mgr

        today = session_mgr.now().date()

        self.alerts = []

        # London open - prime trading
        self.add_alert(
            session_mgr.ist.localize(dt.datetime.combine(today, dt.time(self.ALERT_TIMES_IST['london_open'][0], self.ALERT_TIMES_IST['london_open'][1]))),
            "London Open - BEGIN TRADING",
            'high'
        )

        # London mid - reassess
        self.add_alert(
            session_mgr.ist.localize(dt.datetime.combine(today, dt.time(self.ALERT_TIMES_IST['london_mid'][0], self.ALERT_TIMES_IST['london_mid'][1]))),
            "London Mid - Check progress, reassess targets",
            'medium'
        )

        # NY overlap - volatility warning
        self.add_alert(
            session_mgr.ist.localize(dt.datetime.combine(today, dt.time(self.ALERT_TIMES_IST['ny_overlap_start'][0], self.ALERT_TIMES_IST['ny_overlap_start'][1]))),
            "NY Overlap - High volatility, selective entries",
            'medium'
        )

        # NY solo - exit only
        self.add_alert(
            session_mgr.ist.localize(dt.datetime.combine(today, dt.time(self.ALERT_TIMES_IST['ny_solo_start'][0], self.ALERT_TIMES_IST['ny_solo_start'][1]))),
            "NY Solo - NO NEW TRADES, manage exits only",
            'high',
            action_required='exit_only'
        )

        # Wind down
        self.add_alert(
            session_mgr.ist.localize(dt.datetime.combine(today, dt.time(self.ALERT_TIMES_IST['wind_down_warning'][0], self.ALERT_TIMES_IST['wind_down_warning'][1]))),
            "20 minutes to close - Prepare final exits",
            'high'
        )

        # Hard stop
        self.add_alert(
            session_mgr.ist.localize(dt.datetime.combine(today, dt.time(self.ALERT_TIMES_IST['hard_stop'][0], self.ALERT_TIMES_IST['hard_stop'][1]))),
            "HARD STOP - Close all positions NOW",
            'high',
            action_required='emergency_close_all'
        )

        # Sort by time
        self.alerts.sort(key=lambda a: a.alert_time)

    def add_alert(self, alert_time: dt.datetime, message: str, priority: str = 'medium',
                  action_required: Optional[str] = None):
        """Add custom alert"""
        self.alerts.append(SessionAlert(
            alert_time=alert_time,
            message=message,
            priority=priority,
            action_required=action_required
        ))

    def register_callback(self, callback: Callable):
        """Register function to call on alert"""
        self.callbacks.append(callback)

    def start_monitoring(self):
        """Start background alert thread"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop_monitoring(self):
        """Stop alert thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

    def _monitor_loop(self):
        """Background loop checking for alerts"""
        from core.session_manager import session_mgr

        while self.running:
            now = session_mgr.now()

            for alert in self.alerts:
                if not alert.triggered and now >= alert.alert_time:
                    alert.triggered = True
                    self._trigger_alert(alert)

            # Sleep until next minute
            time.sleep(30)  # Check every 30 seconds

    def _trigger_alert(self, alert: SessionAlert):
        """Execute alert"""
        print(f"\n*** ALERT [{alert.priority.upper()}]: {alert.message} ***\n")

        # Call registered callbacks
        for callback in self.callbacks:
            try:
                callback(alert)
            except:
                pass

    def get_next_alert(self) -> Optional[SessionAlert]:
        """Get next pending alert"""
        from core.session_manager import session_mgr

        now = session_mgr.now()

        for alert in self.alerts:
            if not alert.triggered and alert.alert_time > now:
                return alert

        return None

    def get_time_until_next(self) -> Optional[int]:
        """Minutes until next alert"""
        next_alert = self.get_next_alert()
        if not next_alert:
            return None

        from core.session_manager import session_mgr
        now = session_mgr.now()

        delta = next_alert.alert_time - now
        return int(delta.total_seconds() / 60)

    def is_last_hour(self) -> bool:
        """Check if in final hour of trading"""
        from core.session_manager import session_mgr

        time_to_close = session_mgr.time_to_close()
        return time_to_close is not None and time_to_close <= 60

    def format_time_remaining(self) -> str:
        """Human-readable time until close"""
        from core.session_manager import session_mgr

        minutes = session_mgr.time_to_close()
        if minutes is None or minutes <= 0:
            return "CLOSED"

        hours = minutes // 60
        mins = minutes % 60

        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"