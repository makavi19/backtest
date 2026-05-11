# agents/feedback/performance_tracker.py
# Daily and session performance tracking

import json
from dataclasses import dataclass, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class DailyPerformance:
    """Performance summary for a trading day"""
    date: str
    starting_balance: float
    ending_balance: float

    trades_taken: int = 0
    trades_win: int = 0
    trades_loss: int = 0
    trades_breakeven: int = 0

    total_pnl: float = 0.0
    max_profit: float = 0.0
    max_loss: float = 0.0

    largest_winner: float = 0.0
    largest_loser: float = 0.0

    avg_winner: float = 0.0
    avg_loser: float = 0.0

    win_rate: float = 0.0
    profit_factor: float = 0.0

    r_sum: float = 0.0  # Sum of R multiples

    # Session breakdown
    pre_london_pnl: float = 0.0
    london_pnl: float = 0.0
    ny_overlap_pnl: float = 0.0
    ny_solo_pnl: float = 0.0

    strategy_breakdown: Dict[str, Dict] = None
    pair_breakdown: Dict[str, Dict] = None

    notes: str = ""

    def __post_init__(self):
        if self.strategy_breakdown is None:
            self.strategy_breakdown = {}
        if self.pair_breakdown is None:
            self.pair_breakdown = {}


class PerformanceTracker:
    """
    Tracks and analyzes trading performance

    Daily summaries, streaks, patterns
    """

    LOG_DIR = "data/daily_logs"

    def __init__(self):
        Path(self.LOG_DIR).mkdir(parents=True, exist_ok=True)
        self.today: Optional[DailyPerformance] = None
        self._load_today()

    def _get_today_path(self) -> Path:
        """Get file path for today's log"""
        today_str = date.today().isoformat()
        return Path(self.LOG_DIR) / f"{today_str}.json"

    def _load_today(self):
        """Load or create today's performance"""
        path = self._get_today_path()

        if path.exists():
            with open(path, 'r') as f:
                data = json.load(f)
                self.today = DailyPerformance(**data)
        else:
            self.today = DailyPerformance(
                date=date.today().isoformat(),
                starting_balance=0.0,  # Will be updated
                ending_balance=0.0
            )

    def update_balance(self, starting: Optional[float] = None, ending: Optional[float] = None):
        """Update account balance"""
        if starting is not None:
            self.today.starting_balance = starting
        if ending is not None:
            self.today.ending_balance = ending

        self._save()

    def record_trade(self, pnl: float, r_multiple: float, session: str,
                    strategy: str, pair: str):
        """Record completed trade"""
        self.today.trades_taken += 1
        self.today.total_pnl += pnl
        self.today.r_sum += r_multiple

        # Win/loss tracking
        if pnl > 0:
            self.today.trades_win += 1
            self.today.largest_winner = max(self.today.largest_winner, pnl)
        elif pnl < 0:
            self.today.trades_loss += 1
            self.today.largest_loser = min(self.today.largest_loser, pnl)
        else:
            self.today.trades_breakeven += 1

        # Extremes
        self.today.max_profit = max(self.today.max_profit, self.today.total_pnl)
        self.today.max_loss = min(self.today.max_loss, self.today.total_pnl)

        # Session breakdown
        if session == 'pre_london':
            self.today.pre_london_pnl += pnl
        elif session == 'london':
            self.today.london_pnl += pnl
        elif session == 'ny_overlap':
            self.today.ny_overlap_pnl += pnl
        elif session == 'ny_solo':
            self.today.ny_solo_pnl += pnl

        # Strategy breakdown
        if strategy not in self.today.strategy_breakdown:
            self.today.strategy_breakdown[strategy] = {
                'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0
            }
        self.today.strategy_breakdown[strategy]['trades'] += 1
        self.today.strategy_breakdown[strategy]['pnl'] += pnl
        if pnl > 0:
            self.today.strategy_breakdown[strategy]['wins'] += 1
        elif pnl < 0:
            self.today.strategy_breakdown[strategy]['losses'] += 1

        # Pair breakdown
        if pair not in self.today.pair_breakdown:
            self.today.pair_breakdown[pair] = {
                'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0
            }
        self.today.pair_breakdown[pair]['trades'] += 1
        self.today.pair_breakdown[pair]['pnl'] += pnl
        if pnl > 0:
            self.today.pair_breakdown[pair]['wins'] += 1
        elif pnl < 0:
            self.today.pair_breakdown[pair]['losses'] += 1

        # Recalculate averages
        self._recalculate_stats()
        self._save()

    def _recalculate_stats(self):
        """Recalculate derived statistics"""
        t = self.today

        # Win rate
        closed = t.trades_win + t.trades_loss
        t.win_rate = (t.trades_win / closed * 100) if closed > 0 else 0

        # Averages
        if t.trades_win > 0:
            t.avg_winner = sum([
                s['pnl'] for s in t.strategy_breakdown.values()
                if s['pnl'] > 0
            ]) / t.trades_win
        if t.trades_loss > 0:
            t.avg_loser = sum([
                s['pnl'] for s in t.strategy_breakdown.values()
                if s['pnl'] < 0
            ]) / t.trades_loss

        # Profit factor
        gross_profit = sum([s['pnl'] for s in t.strategy_breakdown.values() if s['pnl'] > 0])
        gross_loss = abs(sum([s['pnl'] for s in t.strategy_breakdown.values() if s['pnl'] < 0]))
        t.profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    def _save(self):
        """Save to JSON"""
        path = self._get_today_path()
        with open(path, 'w') as f:
            json.dump(asdict(self.today), f, indent=2, default=str)

    def get_current_stats(self) -> Dict:
        """Get live statistics"""
        return {
            'trades': self.today.trades_taken,
            'pnl': round(self.today.total_pnl, 2),
            'win_rate': round(self.today.win_rate, 1),
            'r_sum': round(self.today.r_sum, 2),
            'max_drawdown': round(self.today.max_loss, 2),
            'max_profit': round(self.today.max_profit, 2),
        }

    def should_stop_trading(self) -> Tuple[bool, str]:
        """Check if should stop based on daily limits"""
        # Loss limit
        if self.today.total_pnl <= -15:
            return True, "Daily loss limit (-$15) reached"

        # Profit target (soft stop)
        if self.today.total_pnl >= 60:
            return True, "Daily profit target ($60) reached - consider stopping"

        # Max trades
        if self.today.trades_taken >= 4:
            return True, "Maximum trades (4) reached"

        return False, "Continue trading"

    def add_note(self, note: str):
        """Add daily note"""
        self.today.notes += f"[{datetime.now().strftime('%H:%M')}] {note}\n"
        self._save()