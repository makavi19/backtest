# core/__init__.py
# Core module exports

from .config import (
    config,
    SessionConfig,
    RiskTier,
    RiskTierConfig,
    PairConfig,
    SessionPhase,
    get_pair_config,
    get_active_pairs_for_session,
    is_correlated,
    get_correlation_group,
)
from .session_manager import (
    session_mgr,
    SessionManager,
    get_current_ist_time,
    format_ist_time,
)
from .dynamic_risk import (
    risk_calc,
    DynamicRiskCalculator,
    RiskAssessment,
    get_risk_for_setup,
    check_daily_budget,
)
from .mt5_bridge import (
    MT5Bridge,
    get_bridge,
    OrderResult,
    PositionInfo,
    DataError,
)

__all__ = [
    # Config
    'config',
    'SessionConfig',
    'RiskTier',
    'RiskTierConfig',
    'PairConfig',
    'SessionPhase',
    'get_pair_config',
    'get_active_pairs_for_session',
    'is_correlated',
    'get_correlation_group',
    # Session
    'session_mgr',
    'SessionManager',
    'get_current_ist_time',
    'format_ist_time',
    # Risk
    'risk_calc',
    'DynamicRiskCalculator',
    'RiskAssessment',
    'get_risk_for_setup',
    'check_daily_budget',
    # MT5
    'MT5Bridge',
    'get_bridge',
    'OrderResult',
    'PositionInfo',
    'DataError',
]