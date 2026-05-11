# core/config.py
# Eleven Pairs Project - Master Configuration

from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List, Tuple, Optional
from enum import Enum
import pytz


class RiskTier(Enum):
    TIGHT = "tight"      # $4 risk, 8-12 pip stop
    NORMAL = "normal"    # $7 risk, 15-20 pip stop
    WIDE = "wide"        # $10 risk, 25-35 pip stop


class SessionPhase(Enum):
    PRE_LONDON = "pre_london"
    LONDON = "london"
    NY_OVERLAP = "ny_overlap"
    NY_SOLO = "ny_solo"
    CLOSED = "closed"


@dataclass
class PairConfig:
    """Configuration for each trading pair"""
    symbol: str                       # Your code name (e.g., 'XAUUSD')
    mt5_symbol: str                   # XM's exact symbol (e.g., 'XAUUSD' or 'GOLD')
    category: str                     # 'major', 'cross', 'commodity'
    dxy_correlation: float           # -1.0 to 1.0
    default_tier: RiskTier           # Default risk tier
    pip_value: float                 # 0.0001 for forex, 0.1 or 0.01 for gold/silver
    pip_location: int                # MT5 digits (2 for XAUUSD, 5 for EURUSD)
    spread_typical: float            # Typical spread in pips
    session_preference: List[str]    # Best sessions for this pair
    smt_pair: Optional[str] = None   # For gold/silver divergence


@dataclass
class RiskTierConfig:
    """Risk parameters for each tier"""
    max_risk_usd: float
    min_stop_pips: int
    max_stop_pips: int
    min_grade_required: str  # 'A', 'B', etc.
    size_multiplier: float   # 1.0 = full, 0.75 = reduced


@dataclass
class SessionConfig:
    """Master configuration for Eleven Pairs trading system"""
    
    # Timezone: IST (Indian Standard Time, UTC+5:30)
    TIMEZONE = pytz.timezone('Asia/Kolkata')
    
    # Trading hours (IST)
    TRADING_START: time = time(10, 30)   # 10:30 AM IST = 05:00 UTC
    TRADING_END: time = time(23, 50)     # 11:50 PM IST = 18:20 UTC
    
    # Session definitions (IST)
    PRE_LONDON: Tuple[time, time] = (time(10, 30), time(12, 30))
    LONDON: Tuple[time, time] = (time(12, 30), time(17, 30))
    NY_OVERLAP: Tuple[time, time] = (time(17, 30), time(21, 30))
    NY_SOLO: Tuple[time, time] = (time(21, 30), time(23, 50))
    
    # Daily limits
    DAILY_PROFIT_TARGET: float = 60.0    # $60 profit = stop new trades
    DAILY_LOSS_LIMIT: float = -15.0      # $15 loss = hard stop
    MAX_TRADES_PER_DAY: int = 4
    
    # Risk tiers
    RISK_TIERS: Dict[RiskTier, RiskTierConfig] = field(default_factory=lambda: {
        RiskTier.TIGHT: RiskTierConfig(
            max_risk_usd=4.0,
            min_stop_pips=8,
            max_stop_pips=12,
            min_grade_required='A',
            size_multiplier=1.0
        ),
        RiskTier.NORMAL: RiskTierConfig(
            max_risk_usd=7.0,
            min_stop_pips=15,
            max_stop_pips=20,
            min_grade_required='B',
            size_multiplier=1.0
        ),
        RiskTier.WIDE: RiskTierConfig(
            max_risk_usd=10.0,
            min_stop_pips=25,
            max_stop_pips=35,
            min_grade_required='A',  # Wide stops need A grade only
            size_multiplier=0.75     # Reduced size for wide stops
        )
    })
    
    # ELEVEN PAIRS CONFIGURATION
    # VERIFY THESE MATCH YOUR XM MT5 SYMBOLS
    PAIRS: Dict[str, PairConfig] = field(default_factory=lambda: {
        
        # PRIME TIER - Best setups, tight stops
        'GOLD': PairConfig(
            symbol='GOLD',
            mt5_symbol='GOLD',      # ← CHANGE IF XM USES 'GOLD' OR 'XAUUSDm'
            category='commodity',
            dxy_correlation=-0.80,
            default_tier=RiskTier.TIGHT,
            pip_value=0.01,           # ← VERIFY: XM uses 0.01 or 0.1?
            pip_location=2,           # ← VERIFY: 2 digits (1950.50) or 3?
            spread_typical=0.35,
            session_preference=['london', 'ny_overlap'],
            smt_pair='SILVER'
        ),
        
        'EURUSD': PairConfig(
            symbol='EURUSD',
            mt5_symbol='EURUSD',
            category='major',
            dxy_correlation=-0.92,
            default_tier=RiskTier.TIGHT,
            pip_value=0.0001,
            pip_location=5,
            spread_typical=0.1,
            session_preference=['london', 'ny_overlap', 'pre_london']
        ),
        
        # CORE TIER - Quality setups, normal stops
        'GBPUSD': PairConfig(
            symbol='GBPUSD',
            mt5_symbol='GBPUSD',
            category='major',
            dxy_correlation=-0.89,
            default_tier=RiskTier.TIGHT,  # Can use tight due to volatility
            pip_value=0.0001,
            pip_location=5,
            spread_typical=0.15,
            session_preference=['london', 'ny_overlap']
        ),
        
        'EURJPY': PairConfig(
            symbol='EURJPY',
            mt5_symbol='EURJPY',
            category='cross',
            dxy_correlation=0.15,  # Mixed, euro vs yen
            default_tier=RiskTier.NORMAL,
            pip_value=0.01,
            pip_location=3,
            spread_typical=0.18,
            session_preference=['london', 'ny_overlap']
        ),
        
        'USDJPY': PairConfig(
            symbol='USDJPY',
            mt5_symbol='USDJPY',
            category='major',
            dxy_correlation=0.78,
            default_tier=RiskTier.NORMAL,
            pip_value=0.01,
            pip_location=3,
            spread_typical=0.12,
            session_preference=['tokyo', 'london', 'ny_overlap']
        ),
        
        # SELECTED TIER - Conditional quality
        'AUDUSD': PairConfig(
            symbol='AUDUSD',
            mt5_symbol='AUDUSD',
            category='major',
            dxy_correlation=-0.85,
            default_tier=RiskTier.NORMAL,
            pip_value=0.0001,
            pip_location=5,
            spread_typical=0.16,
            session_preference=['ny_overlap', 'london']
        ),
        
        'USDCAD': PairConfig(
            symbol='USDCAD',
            mt5_symbol='USDCAD',
            category='major',
            dxy_correlation=0.75,
            default_tier=RiskTier.NORMAL,
            pip_value=0.0001,
            pip_location=5,
            spread_typical=0.18,
            session_preference=['ny_overlap']
        ),
        
        'GBPJPY': PairConfig(
            symbol='GBPJPY',
            mt5_symbol='GBPJPY',
            category='cross',
            dxy_correlation=0.25,
            default_tier=RiskTier.WIDE,  # Volatile
            pip_value=0.01,
            pip_location=3,
            spread_typical=0.25,
            session_preference=['london', 'ny_overlap']
        ),
        
        # RARE TIER - Exceptional setups only
        'NZDUSD': PairConfig(
            symbol='NZDUSD',
            mt5_symbol='NZDUSD',
            category='major',
            dxy_correlation=-0.82,
            default_tier=RiskTier.NORMAL,
            pip_value=0.0001,
            pip_location=5,
            spread_typical=0.20,
            session_preference=['ny_overlap']
        ),
        
        'USDCHF': PairConfig(
            symbol='USDCHF',
            mt5_symbol='USDCHF',
            category='major',
            dxy_correlation=0.88,
            default_tier=RiskTier.WIDE,  # Often choppy, need wide stop
            pip_value=0.0001,
            pip_location=5,
            spread_typical=0.15,
            session_preference=['london']
        ),
        
        'SILVER': PairConfig(
            symbol='SILVER',
            mt5_symbol='SILVER',      # ← CHANGE IF XM USES 'SILVER'
            category='commodity',
            dxy_correlation=-0.75,
            default_tier=RiskTier.WIDE,
            pip_value=0.001,          # ← VERIFY
            pip_location=3,
            spread_typical=0.03,
            session_preference=['london', 'ny_overlap'],
            smt_pair='GOLD'
        ),
        # DXY PROXY (for USD strength analysis)
        # Most brokers don't offer DXY directly, use EURUSD inverse
        'DXY_PROXY': PairConfig(
            symbol='DXY_PROXY',
            mt5_symbol='USDX-JUN26',      # ← CHANGE IF XM HAS ACTUAL 'DXY' or 'USDX'
            category='index',
            dxy_correlation=-1.0,     # Perfect inverse
            default_tier=RiskTier.NORMAL,
            pip_value=0.0001,
            pip_location=5,
            spread_typical=0.1,
            session_preference=['all'],
            smt_pair=None
        ),
    })
    
    # Strategy weights for selection
    STRATEGY_PREFERENCES: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        'london': {
            'ict_ob_fvg': 0.30,
            'smc_structure': 0.25,
            'london_breakout': 0.25,
            'wyckoff_amd': 0.10,
            'supply_demand_zones': 0.10,
        },
        'ny_overlap': {
            'ict_ob_fvg': 0.25,
            'smc_structure': 0.20,
            'breakout_momentum': 0.20,
            'trend_following_ema': 0.15,
            'wyckoff_amd': 0.10,
            'mean_reversion_bollinger': 0.10,
        },
        'pre_london': {
            'ict_ob_fvg': 0.40,
            'crt_multitimeframe': 0.30,
            'supply_demand_zones': 0.30,
        }
    })
    
    # Correlation groups (pairs that move together)
    CORRELATION_GROUPS: Dict[str, List[str]] = field(default_factory=lambda: {
        'euro_dollar_block': ['EURUSD', 'GBPUSD', 'USDCHF', 'AUDUSD', 'NZDUSD', 'XAUUSD', 'XAGUSD'],
        'dollar_yen_block': ['USDJPY', 'EURJPY', 'GBPJPY'],
        'comodity_dollar': ['USDCAD', 'XAUUSD', 'XAGUSD'],
        'euro_crosses': ['EURUSD', 'EURJPY'],
        'gbp_crosses': ['GBPUSD', 'GBPJPY'],
    })


# Global instance
config = SessionConfig()


def get_pair_config(symbol: str) -> Optional[PairConfig]:
    """Get configuration for a specific pair"""
    return config.PAIRS.get(symbol)


def get_active_pairs_for_session(session: str) -> List[str]:
    """Return pairs suitable for current session"""
    active = []
    for symbol, pair in config.PAIRS.items():
        if session in pair.session_preference or 'all' in pair.session_preference:
            active.append(symbol)
    return active


def get_default_risk_tier(symbol: str) -> RiskTier:
    """Get default risk tier for a pair"""
    pair = get_pair_config(symbol)
    if pair:
        return pair.default_tier
    return RiskTier.NORMAL  # Fallback


def calculate_stop_distance(symbol: str, tier: RiskTier) -> Tuple[int, int]:
    """Calculate min/max stop pips for pair and tier"""
    pair = get_pair_config(symbol)
    tier_config = config.RISK_TIERS.get(tier)
    
    if not pair or not tier_config:
        return (15, 20)  # Safe fallback
    
    return (tier_config.min_stop_pips, tier_config.max_stop_pips)


def is_correlated(pair1: str, pair2: str) -> bool:
    """Check if two pairs are in same correlation group"""
    for group, members in config.CORRELATION_GROUPS.items():
        if pair1 in members and pair2 in members:
            return True
    return False


def get_correlation_group(pair: str) -> Optional[str]:
    """Get which correlation group a pair belongs to"""
    for group, members in config.CORRELATION_GROUPS.items():
        if pair in members:
            return group
    return None