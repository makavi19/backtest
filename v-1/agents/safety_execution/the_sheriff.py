# agents/safety_execution/the_sheriff.py
# Correlation enforcer and trade approver

from dataclasses import dataclass
from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime

from core.config import config, get_pair_config, is_correlated, get_correlation_group


@dataclass
class SheriffDecision:
    """Final approval decision from Sheriff"""
    approved: bool
    action: str  # 'execute', 'modify', 'reject', 'close_existing'
    priority_rank: int  # 1 = highest
    conflicts: List[str]  # Conflicting pairs/situations
    recommendation: str  # Human-readable advice
    modified_params: Optional[Dict] = None  # If modification required


class Sheriff:
    """
    The Sheriff enforces trading rules:
    - Max 2 simultaneous trades
    - No correlated pair conflicts
    - Daily risk budget respect
    - Quality over quantity

    Correlation groups prevent doubling risk on same move
    """

    MAX_SIMULTANEOUS_TRADES = 2
    MAX_CORRELATED_EXPOSURE = 1  # Only 1 from each correlation group

    def __init__(self):
        self.open_trades: List[Dict] = []  # Currently open positions
        self.pending_trades: List[Dict] = []  # Queue if at max

    def review_trade(
        self,
        proposed_symbol: str,
        proposed_direction: str,
        proposed_risk: float,
        current_pnl: float,
        daily_trades_count: int,
        existing_positions: List[Dict] = None
    ) -> SheriffDecision:
        """
        Full review of proposed trade

        Returns: approve, reject, or modify with specifics
        """
        if existing_positions:
            self.open_trades = existing_positions

        conflicts = []

        # 1. Daily trade count check
        if current_pnl <= -15.0:
            return SheriffDecision(
                approved=False,
                action='reject',
                priority_rank=0,
                conflicts=['Daily loss limit reached'],
                recommendation='Stop trading for today'
            )
        if daily_trades_count >= 4:  # Hard max
            return SheriffDecision(
                approved=False,
                action='reject',
                priority_rank=0,
                conflicts=['Daily trade maximum reached'],
                recommendation='Stop trading for today'
            )

        # 2. Simultaneous trade limit
        if len(self.open_trades) >= self.MAX_SIMULTANEOUS_TRADES:
            # Check if we should close an existing trade
            oldest = min(self.open_trades, key=lambda x: x.get('open_time', datetime.min))

            return SheriffDecision(
                approved=False,
                action='close_existing',
                priority_rank=0,
                conflicts=[f'Max {self.MAX_SIMULTANEOUS_TRADES} trades open'],
                recommendation=f'Consider closing {oldest["symbol"]} if profitable',
                modified_params={'close_candidate': oldest}
            )

        # 3. Correlation check
        corr_conflicts = self._check_correlation_conflicts(proposed_symbol)
        if corr_conflicts:
            conflicts.extend(corr_conflicts)

            # Reject if there are correlation conflicts, or suggest closing if profitable
            for conflict_symbol in corr_conflicts:
                conflict_trade = next(
                    (t for t in self.open_trades if t['symbol'] == conflict_symbol),
                    None
                )
                if conflict_trade and conflict_trade.get('profit', 0) > 0:
                    return SheriffDecision(
                        approved=False,
                        action='close_existing',
                        priority_rank=1,
                        conflicts=conflicts,
                        recommendation=f'Close profitable {conflict_symbol} first',
                        modified_params={'close_candidate': conflict_trade}
                    )

            return SheriffDecision(
                approved=False,
                action='reject',
                priority_rank=0,
                conflicts=conflicts,
                recommendation='Correlated pair already trading'
            )

        # 4. Directional check in same group
        direction_conflict = self._check_directional_conflict(
            proposed_symbol, proposed_direction
        )
        if direction_conflict:
            conflicts.append(direction_conflict)
            return SheriffDecision(
                approved=False,
                action='reject',
                priority_rank=0,
                conflicts=conflicts,
                recommendation='Opposite direction in correlated pair'
            )

        # 5. Risk concentration check
        total_risk = sum(t.get('risk', 0) for t in self.open_trades)
        if total_risk + proposed_risk > 15:  # Daily limit
            conflicts.append(f'Risk ${total_risk + proposed_risk} exceeds $15 daily')
            return SheriffDecision(
                approved=False,
                action='modify',
                priority_rank=2,
                conflicts=conflicts,
                recommendation='Reduce position size or wait',
                modified_params={'max_risk': 15 - total_risk}
            )

        # Approved
        priority = self._calculate_priority(proposed_symbol, proposed_direction)

        return SheriffDecision(
            approved=True,
            action='execute',
            priority_rank=priority,
            conflicts=[],
            recommendation='Trade approved - proceed to execution'
        )

    def _check_correlation_conflicts(self, symbol: str) -> List[str]:
        """Check for same-group pair already trading"""
        conflicts = []

        group = get_correlation_group(symbol)
        if not group:
            return []

        for trade in self.open_trades:
            trade_group = get_correlation_group(trade['symbol'])
            if trade_group == group and trade['symbol'] != symbol:
                conflicts.append(trade['symbol'])

        if len(conflicts) > 0:
            return conflicts

        return []

    def _check_directional_conflict(
        self,
        symbol: str,
        direction: str
    ) -> Optional[str]:
        """Check if same pair opposite direction (rare but possible)"""
        for trade in self.open_trades:
            if trade['symbol'] == symbol and trade['direction'] != direction:
                return f'Opposite direction in {symbol}'
        return None

    def _calculate_priority(self, symbol: str, direction: str) -> int:
        """Calculate execution priority (lower = higher priority)"""
        priority = 5  # Base

        # Prime pairs get priority
        if symbol in ['XAUUSD', 'EURUSD']:
            priority = 1
        elif symbol in ['GBPUSD', 'USDJPY', 'EURJPY']:
            priority = 2
        else:
            priority = 3

        # Direction with DXY alignment gets bonus
        # (Handled in strategy, but reflected here)

        return priority

    def can_add_to_queue(self, symbol: str) -> bool:
        """Check if can queue when at max trades"""
        # Check if queued trade would be valid later
        pending_symbols = [t['symbol'] for t in self.pending_trades]

        if symbol in pending_symbols:
            return False  # Already queued

        if len(self.pending_trades) >= 2:
            return False  # Queue full

        return True

    def add_to_queue(self, trade_details: Dict):
        """Queue trade for when slot opens"""
        if self.can_add_to_queue(trade_details['symbol']):
            self.pending_trades.append(trade_details)
            return True
        return False

    def get_next_from_queue(self) -> Optional[Dict]:
        """Get highest priority queued trade"""
        if not self.pending_trades:
            return None

        # Sort by priority
        sorted_queue = sorted(
            self.pending_trades,
            key=lambda t: t.get('priority', 5)
        )

        return sorted_queue[0]

    def remove_from_queue(self, symbol: str):
        """Remove specific symbol from queue"""
        self.pending_trades = [
            t for t in self.pending_trades
            if t['symbol'] != symbol
        ]

    def update_position(self, symbol: str, updates: Dict):
        """Update tracked position"""
        for trade in self.open_trades:
            if trade['symbol'] == symbol:
                trade.update(updates)
                break

    def close_position(self, symbol: str, pnl: float):
        """Remove from tracking, archive"""
        self.open_trades = [
            t for t in self.open_trades
            if t['symbol'] != symbol
        ]

        # Check queue
        next_trade = self.get_next_from_queue()
        if next_trade:
            return next_trade  # Suggest next trade

        return None

    def get_exposure_summary(self) -> Dict:
        """Current risk exposure breakdown"""
        summary = {
            'open_count': len(self.open_trades),
            'pending_count': len(self.pending_trades),
            'total_risk': sum(t.get('risk', 0) for t in self.open_trades),
            'total_pnl': sum(t.get('pnl', 0) for t in self.open_trades),
            'correlation_groups': {}
        }

        # Group by correlation
        for trade in self.open_trades:
            group = get_correlation_group(trade['symbol']) or 'other'
            if group not in summary['correlation_groups']:
                summary['correlation_groups'][group] = []
            summary['correlation_groups'][group].append(trade['symbol'])

        return summary