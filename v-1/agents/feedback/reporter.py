# agents/feedback/reporter.py
# End-of-day and periodic reports

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

from agents.feedback.trade_logger import TradeLogger


class Reporter:
    """
    Generates trading reports
    
    - Daily summary
    - Weekly review
    - Monthly analysis
    """
    
    def __init__(self, logger: Optional[TradeLogger] = None):
        self.logger = logger or TradeLogger()
        self.report_dir = Path("data/reports")
        self.report_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_daily_report(self, date_str: Optional[str] = None) -> str:
        """Generate and save daily report"""
        if date_str is None:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')
        
        stats = self.logger.get_statistics(days=1)
        
        report = f"""
========================================
DAILY TRADING REPORT - {date_str}
========================================

OVERALL PERFORMANCE
------------------
Total Trades: {stats.get('total_trades', 0)}
Win Rate: {stats.get('win_rate', 0)}%
Net P&L: ${stats.get('net_pnl', 0):.2f}
Profit Factor: {stats.get('profit_factor', 0)}

TRADE BREAKDOWN
--------------
Winners: {stats.get('wins', 0)}
Losers: {stats.get('losses', 0)}
Avg Winner: ${stats.get('avg_win', 0):.2f}
Avg Loser: ${stats.get('avg_loss', 0):.2f}
Avg R: {stats.get('avg_r', 0):.2f}

SESSION NOTES
-------------
Add your observations here.

========================================
"""
        
        # Save to file
        report_path = self.report_dir / f"daily_{date_str}.txt"
        with open(report_path, 'w') as f:
            f.write(report)
        
        return report
    
    def print_console_summary(self, performance_tracker):
        """Print live summary to console"""
        stats = performance_tracker.get_current_stats()
        
        print("\n" + "="*50)
        print("TODAY'S TRADING SUMMARY")
        print("="*50)
        print(f"Trades: {stats['trades']} | P&L: ${stats['pnl']:.2f}")
        print(f"Win Rate: {stats['win_rate']}% | Total R: {stats['r_sum']}")
        print(f"Max DD: ${stats['max_drawdown']} | Best: ${stats['max_profit']}")
        print("="*50 + "\n")
    
    def generate_weekly_report(self) -> str:
        """Generate weekly summary"""
        stats = self.logger.get_statistics(days=7)
        
        # Build week range
        end = datetime.utcnow()
        start = end - timedelta(days=7)
        
        return f"""
WEEKLY REPORT: {start.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}

Performance: ${stats.get('net_pnl', 0):.2f} | Win Rate: {stats.get('win_rate', 0)}%
Trades: {stats.get('total_trades', 0)} | Profit Factor: {stats.get('profit_factor', 0)}

Review and adjust strategies as needed.
"""