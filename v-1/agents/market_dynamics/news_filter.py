# agents/market_dynamics/news_filter.py
# Economic calendar and high-impact news filtering

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import requests
import json


class ImpactLevel(Enum):
    HIGH = 3    # Red folder - halt trading
    MEDIUM = 2  # Orange - reduce size
    LOW = 1     # Yellow - monitor
    NONE = 0


@dataclass
class NewsEvent:
    """Single economic news event"""
    time_utc: datetime
    currency: str  # 'USD', 'EUR', 'GBP', etc.
    impact: ImpactLevel
    event_name: str
    forecast: Optional[str] = None
    actual: Optional[str] = None
    previous: Optional[str] = None
    
    def affects_pair(self, pair: str) -> bool:
        """Check if event affects given pair"""
        # Extract currencies from pair
        if len(pair) == 6:  # Standard forex
            base = pair[:3]
            quote = pair[3:]
        elif 'XAU' in pair or 'GOLD' in pair:
            base, quote = 'XAU', 'USD'
        elif 'XAG' in pair or 'SILVER' in pair:
            base, quote = 'XAG', 'USD'
        else:
            return False
        
        return self.currency in [base, quote]
    
    def minutes_until(self, now: Optional[datetime] = None) -> int:
        """Minutes until event (negative if passed)"""
        if now is None:
            now = datetime.utcnow()
        return int((self.time_utc - now).total_seconds() / 60)


class NewsFilter:
    """
    Filters trades based on economic calendar
    
    Halt periods: 15 min before to 15 min after HIGH impact
    Reduce size: MEDIUM impact events
    """
    
    HALT_WINDOW_MINUTES = 15  # Before and after
    HIGH_IMPACT_HALT = True   # Completely stop for red events
    RED_EVENTS = [
        'Non-Farm Payrolls',
        'FOMC Statement',
        'Interest Rate Decision',
        'CPI',
        'GDP',
        'Fed Chairman Speech',
        'ECB President Speech',
        'Brexit-related',
        'War/Conflict news',
    ]
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.events: List[NewsEvent] = []
        self.last_fetch: Optional[datetime] = None
        self.cache_duration = timedelta(minutes=30)
        
    def fetch_calendar(self, days_ahead: int = 2) -> List[NewsEvent]:
        """
        Fetch economic calendar from source
        
        Uses Forex Factory or backup mock data
        """
        try:
            if self.api_key:
                return self._fetch_forexfactory(days_ahead)
            else:
                return self._generate_mock_calendar(days_ahead)
                
        except Exception as e:
            # Fallback to static high-impact events
            return self._static_high_impact()
    
    def _fetch_forexfactory(self, days: int) -> List[NewsEvent]:
        """Fetch from Forex Factory API (if key available)"""
        # Placeholder - implement with actual API
        # url = f"https://api.forexfactory.com/calendar?key={self.api_key}"
        # response = requests.get(url)
        # Parse and return
        return self._generate_mock_calendar(days)
    
    def _generate_mock_calendar(self, days: int) -> List[NewsEvent]:
        """Generate known recurring events"""
        events = []
        base = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        import calendar
        
        # Find upcoming Friday (NFP)
        days_to_friday = (4 - base.weekday()) % 7
        if days_to_friday == 0 and base.hour > 14:
            days_to_friday = 7
        
        friday = base + timedelta(days=days_to_friday)
        
        # NFP (first Friday of month roughly)
        if friday.day <= 7:
            events.append(NewsEvent(
                time_utc=friday.replace(hour=12, minute=30),
                currency='USD',
                impact=ImpactLevel.HIGH,
                event_name='Non-Farm Payrolls'
            ))
        
        # Weekly ECB (Thursday)
        thursday = friday - timedelta(days=1)
        events.append(NewsEvent(
            time_utc=thursday.replace(hour=11, minute=15),
            currency='EUR',
            impact=ImpactLevel.HIGH,
            event_name='ECB Press Conference'
        ))
        
        # Add weekly jobless claims (Thursday)
        events.append(NewsEvent(
            time_utc=thursday.replace(hour=12, minute=30),
            currency='USD',
            impact=ImpactLevel.MEDIUM,
            event_name='Initial Jobless Claims'
        ))
        
        self.events = events
        self.last_fetch = datetime.utcnow()
        
        return events
    
    def _static_high_impact(self) -> List[NewsEvent]:
        """Minimal static events if all else fails"""
        return [
            NewsEvent(
                time_utc=datetime.utcnow().replace(hour=12, minute=30) + timedelta(days=1),
                currency='USD',
                impact=ImpactLevel.HIGH,
                event_name='High Impact Economic Data (Unknown)'
            )
        ]
    
    def check_current_status(self, now: Optional[datetime] = None) -> Dict:
        """
        Check if safe to trade right now
        
        Returns status and next event info
        """
        if now is None:
            now = datetime.utcnow()
        
        # Refresh if stale
        if not self.events or not self.last_fetch or \
           (now - self.last_fetch) > self.cache_duration:
            self.fetch_calendar()
        
        # Find active and upcoming events
        window_start = now - timedelta(minutes=self.HALT_WINDOW_MINUTES)
        window_end = now + timedelta(minutes=self.HALT_WINDOW_MINUTES * 4)
        
        active_events = []
        upcoming_high = None
        
        for event in self.events:
            # Check if in halt window
            event_start = event.time_utc - timedelta(minutes=self.HALT_WINDOW_MINUTES)
            event_end = event.time_utc + timedelta(minutes=self.HALT_WINDOW_MINUTES)
            
            if event_start <= now <= event_end and event.impact == ImpactLevel.HIGH:
                active_events.append(event)
            
            # Find next high impact
            if event.time_utc > now and event.impact == ImpactLevel.HIGH:
                if upcoming_high is None or event.time_utc < upcoming_high.time_utc:
                    upcoming_high = event
        
        # Determine status
        if active_events and self.HIGH_IMPACT_HALT:
            return {
                'safe_to_trade': False,
                'status': 'HALT',
                'reason': f"High impact event active: {active_events[0].event_name}",
                'until': (active_events[0].time_utc + timedelta(minutes=self.HALT_WINDOW_MINUTES)).isoformat(),
                'next_event': None
            }
        
        # Check upcoming
        if upcoming_high:
            minutes_until = upcoming_high.minutes_until(now)
            
            if minutes_until <= self.HALT_WINDOW_MINUTES:
                return {
                    'safe_to_trade': False,
                    'status': 'APPROACHING_HALT',
                    'reason': f"{upcoming_high.event_name} in {minutes_until} min",
                    'until': (upcoming_high.time_utc + timedelta(minutes=self.HALT_WINDOW_MINUTES)).isoformat(),
                    'next_event': upcoming_high.event_name
                }
            elif minutes_until <= 60:
                return {
                    'safe_to_trade': True,  # But cautious
                    'status': 'CAUTION',
                    'reason': f"High impact in {minutes_until} min - reduce size",
                    'until': None,
                    'next_event': upcoming_high.event_name
                }
        
        # Clear
        return {
            'safe_to_trade': True,
            'status': 'CLEAR',
            'reason': 'No high impact events in window',
            'until': None,
            'next_event': upcoming_high.event_name if upcoming_high else None
        }
    
    def should_close_position(
        self,
        position,
        minutes_ahead: int = 10
    ) -> Tuple[bool, str]:
        """
        Recommend if position should be closed before news
        """
        status = self.check_current_status()
        
        if status['status'] in ['HALT', 'APPROACHING_HALT']:
            # High impact imminent
            
            if position.profit > position.risk * 0.5:  # More than 50% of risk in profit
                return True, f"Take {position.profit:.2f} profit before {status.get('next_event', 'news')}"
            
            if position.profit < -position.risk * 0.3:  # Losing
                return True, f"Cut loss before volatility"
        
        return False, "Hold through news window"
    
    def get_affected_pairs(self, event: NewsEvent) -> List[str]:
        """Get all pairs affected by an event"""
        from core.config import config
        
        affected = []
        for symbol in config.PAIRS.keys():
            if symbol == 'DXY_PROXY':
                continue
            if event.affects_pair(symbol):
                affected.append(symbol)
        
        return affected