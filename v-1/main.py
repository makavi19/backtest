# main.py
# Eleven Pairs Trading Bot - Main Orchestration
# WITH DRY RUN MODE - Safe testing without real orders

import sys
import time
import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════
# CREATE DIRECTORIES FIRST (before logging tries to write to them)
# Handle case where files with same name exist
# ═══════════════════════════════════════════════════════════════════

def ensure_dir(path: str):
    """Create directory, removing file if one exists with same name"""
    p = Path(path)
    if p.exists() and not p.is_dir():
        # It's a file, remove it first
        p.unlink()
        print(f"[SETUP] Removed file '{path}' to create directory")
    p.mkdir(parents=True, exist_ok=True)

ensure_dir("data/logs")
ensure_dir("data/screenshots")
ensure_dir("data/journal")
ensure_dir("data/dry_run_logs")
ensure_dir("config")

# ═══════════════════════════════════════════════════════════════════
# SETUP LOGGING (now directories exist)
# ═══════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('data/logs/trading_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('Main')

# ═══════════════════════════════════════════════════════════════════
# DRY RUN CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

DRY_RUN = False

def load_dry_run_config():
    global DRY_RUN
    try:
        config_path = Path("config/dry_run.txt")
        if config_path.exists():
            with open(config_path, 'r') as f:
                for line in f:
                    if 'DRY_RUN' in line and '=' in line:
                        value = line.split('=')[1].strip().upper()
                        DRY_RUN = (value == 'TRUE')
                        break
        else:
            with open(config_path, 'w') as f:
                f.write("# DRY RUN MODE\n")
                f.write("# Set to TRUE to simulate trades without sending real orders\n")
                f.write("# Set to FALSE for live trading\n\n")
                f.write("DRY_RUN = TRUE\n")
            DRY_RUN = True
            print("[CONFIG] Created default config/dry_run.txt (DRY_RUN = TRUE)")
    except Exception as e:
        print(f"Could not load dry run config: {e}")
        DRY_RUN = False
    return DRY_RUN

load_dry_run_config()

# ═══════════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════════

from core.config import config, get_pair_config
from core.session_manager import session_mgr, SessionPhase
from core.dynamic_risk import risk_calc, check_daily_budget

from agents.market_intelligence.dxy_sentinel import DXYSentinel
from agents.market_intelligence.market_scanner import MarketScanner
from agents.market_intelligence.volatility_monitor import VolatilityMonitor

from agents.market_dynamics.regime_detector import RegimeDetector
from agents.market_dynamics.session_clock import SessionClock
from agents.market_dynamics.news_filter import NewsFilter

from agents.strategy_logic.setup_grader import SetupGrader
from agents.strategy_logic.smt_sentinel import SMTSentinel
from agents.strategy_logic.strategy_specialist import StrategySpecialist

from agents.safety_execution.dynamic_risk_manager import DynamicRiskManager
from agents.safety_execution.the_sheriff import Sheriff
from agents.safety_execution.session_allocator import SessionAllocator

from agents.feedback.trade_logger import TradeLogger
from agents.feedback.performance_tracker import PerformanceTracker
from agents.feedback.reporter import Reporter

from strategies.strategy_selector import StrategySelector, StrategyRecommendation

if DRY_RUN:
    from core.dry_run import DryRunSimulator
    print("=" * 60)
    print("DRY RUN MODE ACTIVE")
    print("NO REAL ORDERS WILL BE SENT TO MT5")
    print("=" * 60)
else:
    from core.mt5_bridge import get_bridge, MT5Bridge
    print("=" * 60)
    print("LIVE TRADING MODE")
    print("REAL ORDERS WILL BE SENT TO MT5")
    print("=" * 60)


class TradingBot:
    def __init__(self):
        print("\n" + "=" * 60)
        print("ELEVEN PAIRS TRADING BOT - INITIALIZING")
        if DRY_RUN:
            print("MODE: DRY RUN (Simulation Only)")
        else:
            print("MODE: LIVE TRADING")
        print("=" * 60)

        self.dry_run = DRY_RUN
        self.bridge = None
        self.connected = False
        self.dry_run_sim = None

        self.dxy_sentinel = None
        self.market_scanner = None
        self.volatility_monitor = None
        self.regime_detector = None
        self.session_clock = None
        self.news_filter = None

        self.strategy_selector = None
        self.setup_grader = None
        self.smt_sentinel = None
        self.strategy_specialist = None

        self.risk_manager = None
        self.sheriff = None
        self.executioner = None
        self.session_allocator = None

        self.trade_logger = None
        self.performance_tracker = None
        self.reporter = None

        self.daily_pnl = 0.0
        self.trades_today = 0
        self.open_positions = []
        self.last_scan_time = None

    def boot(self):
        print("\n[PHASE 0] SYSTEM BOOT")
        print("-" * 40)

        if self.dry_run:
            print("[DRY RUN] Initializing simulator (no MT5 connection)")
            self.dry_run_sim = DryRunSimulator()
            self.connected = True
            print("✓ Dry Run Simulator ready")
            print("✓ Simulated Account: Balance $500.00")
        else:
            try:
                self.bridge = get_bridge()
                self.connected = self.bridge.connected
                print(f"✓ MT5 Connected: {self.connected}")
                account = self.bridge.get_account_info()
                print(f"✓ Account: {account['name']}, Balance: ${account['balance']:,.2f}")
            except Exception as e:
                print(f"✗ MT5 Connection failed: {e}")
                print("Set DRY_RUN = TRUE in config/dry_run.txt to test without MT5")
                return False

        self._initialize_agents()
        self.news_filter.fetch_calendar()
        print("✓ Economic calendar loaded")
        self._initial_market_analysis()

        self.session_clock.setup_daily_alerts()
        self.session_clock.register_callback(self._on_session_alert)
        self.session_clock.start_monitoring()
        print("✓ Session alerts active")

        print("\n[BOOT COMPLETE] Waiting for London open...")
        return True

    def _initialize_agents(self):
        print("Initializing agents...")
        bridge = self.bridge if not self.dry_run else None

        self.dxy_sentinel = DXYSentinel(bridge)
        self.market_scanner = MarketScanner(bridge)
        self.volatility_monitor = VolatilityMonitor(bridge)
        self.regime_detector = RegimeDetector(bridge)
        self.session_clock = SessionClock()
        self.news_filter = NewsFilter()

        self.strategy_selector = StrategySelector(bridge)
        self.setup_grader = SetupGrader()
        self.smt_sentinel = SMTSentinel(bridge)
        self.strategy_specialist = StrategySpecialist()

        self.risk_manager = DynamicRiskManager()
        self.sheriff = Sheriff()

        if not self.dry_run:
            from agents.safety_execution.executioner import Executioner
            self.executioner = Executioner(self.bridge)

        self.session_allocator = SessionAllocator()

        self.trade_logger = TradeLogger()
        self.performance_tracker = PerformanceTracker()
        self.reporter = Reporter(self.trade_logger)

        print("✓ All agents initialized")

    def _initial_market_analysis(self):
        print("\n[MARKET ANALYSIS] Pre-London Scan")
        dxy_bias = self.dxy_sentinel.analyze()
        print(f"DXY: {dxy_bias.direction.upper()} (strength: {dxy_bias.strength}/100)")

        vol_summary = self.volatility_monitor.get_market_summary()
        print(f"Volatility: {vol_summary['market_volatility']}, Tradeable: {vol_summary['tradeable_pairs']}/{vol_summary['total_pairs']}")

        self.dxy_directions = dxy_bias.pair_directions
        self.dxy_strength = dxy_bias.strength
        print("✓ Market analysis complete")

    def _on_session_alert(self, alert):
        print(f"[ALERT] {alert.message}")
        if alert.action_required == 'emergency_close_all':
            if self.dry_run:
                self.dry_run_sim.emergency_close_all("Hard stop time reached")
            else:
                self.emergency_close_all("Hard stop time reached")

    def run_trading_loop(self):
        print("\n[TRADING LOOP] Starting...")

        while session_mgr.is_trading_time():
            try:
                current_session = session_mgr.get_current_session()
                session_name = session_mgr.get_session_name(current_session)

                print(f"\n{'='*50}")
                print(f"SESSION: {session_name}")
                print(f"Time: {session_mgr.now().strftime('%H:%M')} IST")

                if self.dry_run:
                    sim_summary = self.dry_run_sim.get_summary()
                    print(f"Simulated P&L: ${sim_summary['daily_pnl']:+.2f} | Trades: {sim_summary['trades_today']}")
                else:
                    print(f"Daily P&L: ${self.daily_pnl:+.2f} | Trades: {self.trades_today}")
                print(f"{'='*50}")

                should_stop, reason = self.performance_tracker.should_stop_trading()
                if should_stop:
                    print(f"[STOP] {reason}")
                    self._manage_exits_only()
                    break

                news_status = self.news_filter.check_current_status()
                if not news_status['safe_to_trade']:
                    print(f"[NEWS HALT] {news_status['reason']}")
                    time.sleep(60)
                    continue

                if current_session == SessionPhase.PRE_LONDON:
                    self._handle_pre_london()
                elif current_session == SessionPhase.LONDON:
                    self._handle_london_prime()
                elif current_session == SessionPhase.NY_OVERLAP:
                    self._handle_ny_overlap()
                elif current_session == SessionPhase.NY_SOLO:
                    self._handle_ny_solo()

                if self.dry_run:
                    self.dry_run_sim.update_positions()

                time.sleep(30)

            except Exception as e:
                print(f"[ERROR] Trading loop: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(60)

        self._hard_close()

    def _handle_pre_london(self):
        print("[PRE-LONDON] Analysis phase - selective only")
        dxy_bias = self.dxy_sentinel.analyze()
        self.dxy_directions = dxy_bias.pair_directions
        if dxy_bias.strength >= 70:
            self._scan_and_trade(max_trades=1, min_grade='A')

    def _handle_london_prime(self):
        print("[LONDON PRIME] Full deployment")
        params = self.session_allocator.update()
        self._scan_and_trade(max_trades=params.max_trades_allowed, min_grade=params.min_grade_required)
        self._manage_open_positions()

    def _handle_ny_overlap(self):
        print("[NY OVERLAP] Selective trading")
        params = self.session_allocator.update()
        self._manage_open_positions()
        if params.can_trade_new and self.trades_today < params.max_trades_allowed:
            self._scan_and_trade(max_trades=params.max_trades_allowed - self.trades_today, min_grade='A', focus_pairs=params.focus_pairs)

    def _handle_ny_solo(self):
        print("[NY SOLO] Exit management only - NO NEW TRADES")
        self._manage_open_positions(aggressive_trail=True)
        if self.dry_run:
            for pos in list(self.dry_run_sim.positions):
                if pos.unrealized_pnl < -5:
                    print(f"[CUT] {pos.symbol} showing -${abs(pos.unrealized_pnl):.2f}")
                    self.dry_run_sim._close_simulated_position(pos, pos.current_price, "Preserve mental capital")
        else:
            for pos in self.open_positions:
                if pos.get('unrealized_pnl', 0) < -5:
                    self._close_position(pos, reason="Preserve mental capital")

    def _scan_and_trade(self, max_trades: int = 3, min_grade: str = 'B', focus_pairs: List[str] = None):
        if self.dry_run:
            if self.dry_run_sim.trades_today >= max_trades:
                return
        else:
            if self.trades_today >= max_trades:
                return

        print(f"[SCAN] Looking for setups (max {max_trades} trades, min grade {min_grade})")
        current_session = session_mgr.get_current_session().value

        recommendations = self.strategy_selector.select_best_trade(
            dxy_directions=self.dxy_directions,
            current_session=current_session,
            max_candidates=3
        )

        if not recommendations:
            print("[SCAN] No valid setups found")
            return

        top_rec = recommendations[0]
        if not top_rec.selected:
            print(f"[SCAN] Top candidate rejected: {top_rec.rejection_reason}")
            return

        if top_rec.signal.grade < min_grade:
            print(f"[SCAN] Grade {top_rec.signal.grade} below minimum {min_grade}")
            return

        print(f"[SETUP FOUND] {top_rec.strategy_name} on {top_rec.symbol} {top_rec.direction}")
        print(f"  Grade: {top_rec.signal.grade} | Confidence: {top_rec.signal.confidence:.0%}")
        print(f"  Entry: {top_rec.signal.entry_price:.5f} | Stop: {top_rec.signal.stop_loss:.5f}")
        print(f"  R:R: {top_rec.signal.risk_reward:.1f}")

        current_pnl = self.dry_run_sim.daily_pnl if self.dry_run else self.daily_pnl
        current_trades = self.dry_run_sim.trades_today if self.dry_run else self.trades_today

        sheriff_decision = self.sheriff.review_trade(
            proposed_symbol=top_rec.symbol,
            proposed_direction=top_rec.direction,
            proposed_risk=top_rec.risk_usd,
            current_pnl=current_pnl,
            daily_trades_count=current_trades,
            existing_positions=self.open_positions
        )

        if not sheriff_decision.approved:
            print(f"[SHERIFF] Rejected: {sheriff_decision.recommendation}")
            return

        print(f"[SHERIFF] Approved: {sheriff_decision.recommendation}")

        risk_assignment = self.risk_manager.assign_risk_for_setup(
            symbol=top_rec.symbol,
            grade=top_rec.signal.grade,
            atr_pips=top_rec.signal.stop_pips,
            spread_pips=0.1,
            session=current_session,
            volatility_percentile=50,
            available_budget=self.risk_manager.get_available_risk(current_pnl, current_trades)
        )

        if not risk_assignment:
            print("[RISK] Cannot assign risk - budget exhausted")
            return

        if self.dry_run:
            position_size = {
                'lots': round(risk_assignment.dollar_risk / (top_rec.signal.stop_pips * 10), 2),
                'risk_usd': risk_assignment.dollar_risk,
            }
        else:
            position_size = self.bridge.calculate_position_size(
                symbol=top_rec.symbol,
                risk_usd=risk_assignment.dollar_risk,
                stop_pips=top_rec.signal.stop_pips,
                entry_price=top_rec.signal.entry_price
            )

        print(f"[RISK] Tier: {risk_assignment.tier.value} | Risk: ${risk_assignment.dollar_risk} | Lots: {position_size['lots']}")
        self._execute_trade(top_rec, risk_assignment, position_size)

    def _execute_trade(self, recommendation, risk_assignment, position_size):
        symbol = recommendation.symbol
        direction = recommendation.direction

        if self.dry_run:
            print(f"[DRY RUN] Simulating {direction} {symbol}")
            result = self.dry_run_sim.simulate_trade(recommendation, risk_assignment, position_size)
            if result['success']:
                self.trades_today += 1
        else:
            print(f"[EXECUTE] {direction} {symbol} @ {recommendation.signal.entry_price:.5f}")
            result = self.executioner.execute_with_confirmation(
                symbol=symbol,
                direction=direction,
                volume=position_size['lots'],
                stop_loss=recommendation.signal.stop_loss,
                take_profit=recommendation.signal.take_profit_1,
                confirmation_timeout=5
            )
            if result.success:
                print(f"[FILLED] Ticket #{result.order_ticket} at {result.fill_price}")
                self.trades_today += 1
            else:
                print(f"[EXECUTE FAILED] {result.error}")

    def _manage_open_positions(self, aggressive_trail: bool = False):
        if self.dry_run:
            if self.dry_run_sim.positions:
                print(f"[MANAGE] {len(self.dry_run_sim.positions)} simulated positions")
            return
        if not self.open_positions:
            return
        print(f"[MANAGE] Managing {len(self.open_positions)} open positions")

    def _manage_exits_only(self):
        print("[EXIT ONLY] Managing existing positions")
        while session_mgr.is_trading_time():
            if self.dry_run:
                self.dry_run_sim.update_positions()
                if not self.dry_run_sim.positions:
                    break
            else:
                self._manage_open_positions(aggressive_trail=True)
                if not self.open_positions:
                    break
            time.sleep(30)

    def _hard_close(self):
        print("\n[HARD CLOSE] End of trading day")

        if self.dry_run:
            self.dry_run_sim.emergency_close_all("End of day")
            self.dry_run_sim.print_summary()
            try:
                import pandas as pd
                today = datetime.now().strftime('%Y-%m-%d')
                df = pd.DataFrame(self.dry_run_sim.trades_log)
                excel_path = f"data/dry_run_logs/dry_run_{today}.xlsx"
                df.to_excel(excel_path, index=False)
                print(f"[DRY RUN] Excel exported: {excel_path}")
            except Exception as e:
                print(f"[DRY RUN] Excel export failed: {e}")
        else:
            if self.open_positions:
                self.emergency_close_all("End of day")
            report = self.reporter.generate_daily_report()
            self.reporter.print_console_summary(self.performance_tracker)
            self.performance_tracker._save()
            self._export_to_excel()

        self.risk_manager.reset_daily()
        self.trades_today = 0
        self.daily_pnl = 0.0
        print("\n[DAILY COMPLETE] System ready for tomorrow")

    def emergency_close_all(self, reason: str):
        print(f"[EMERGENCY] Closing all: {reason}")
        if not self.dry_run:
            results = self.executioner.emergency_close_all()
            print(f"[EMERGENCY] Closed {len(results)} positions")

    def _export_to_excel(self):
        try:
            import pandas as pd
            today = datetime.utcnow().strftime('%Y-%m-%d')
            cursor = self.trade_logger.conn.cursor()
            cursor.execute("SELECT * FROM trades WHERE DATE(timestamp_utc) = ?", (today,))
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=columns)
                df.to_excel(f"data/journal/daily_{today}.xlsx", index=False)
                print(f"[EXCEL] Exported: data/journal/daily_{today}.xlsx")
        except Exception as e:
            print(f"[EXCEL] Export failed: {e}")

    def shutdown(self):
        print("\n[SHUTDOWN] Cleaning up...")
        if self.session_clock:
            self.session_clock.stop_monitoring()
        if self.trade_logger:
            self.trade_logger.close()
        if not self.dry_run and self.bridge:
            self.bridge.disconnect()
        print("[SHUTDOWN COMPLETE] Goodbye")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Eleven Pairs Trading Bot")
    parser.add_argument('--mode', type=str, choices=['live', 'backtest'], default='live',
                        help="Run mode: 'live' (default) or 'backtest'")
    parser.add_argument('--backtest', action='store_true', help="Shortcut for --mode backtest")

    # Allow passing unknown args to the backtest runner
    args, unknown = parser.parse_known_args()

    if args.mode == 'backtest' or args.backtest:
        print("=" * 60)
        print("REDIRECTING TO BACKTESTING FRAMEWORK")
        print("=" * 60)
        import subprocess
        import sys

        # Build the command to run the backtest runner
        cmd = [sys.executable, "backtesting/backtest_runner.py"] + unknown
        subprocess.run(cmd)
        return

    bot = TradingBot()
    try:
        if bot.boot():
            bot.run_trading_loop()
        else:
            print("Boot failed")
    except KeyboardInterrupt:
        print("\n[INTERRUPT] User stopped")
    except Exception as e:
        print(f"\n[FATAL] {e}")
        import traceback
        traceback.print_exc()
    finally:
        bot.shutdown()


if __name__ == "__main__":
    main()