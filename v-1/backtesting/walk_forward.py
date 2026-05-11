import logging
import pandas as pd
from datetime import timedelta
from typing import Type, List, Dict
import backtrader as bt

from backtesting.portfolio_engine import PortfolioEngine
from backtesting.metrics import Metrics
from backtesting.report_generator import ReportGenerator

class WalkForwardTester:
    """
    Implements rolling-window walk-forward testing to combat curve fitting.
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def run_walk_forward(self, strategy_class: Type[bt.Strategy], symbols: List[str],
                         start_date: str, end_date: str,
                         train_years: int = 2, test_months: int = 6):
        """
        Executes rolling walk-forward slices.
        """
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)

        train_delta = timedelta(days=train_years * 365)
        test_delta = timedelta(days=test_months * 30)

        current_train_start = start_dt

        results = []

        logging.info("\n" + "="*50)
        logging.info("STARTING WALK-FORWARD ANALYSIS")
        logging.info("="*50)

        step = 1
        while current_train_start + train_delta + test_delta <= end_dt:
            train_end = current_train_start + train_delta
            test_start = train_end
            test_end = test_start + test_delta

            logging.info(f"\n--- WFA Step {step} ---")
            logging.info(f"In-Sample (Train): {current_train_start.date()} to {train_end.date()}")
            logging.info(f"Out-of-Sample (Test): {test_start.date()} to {test_end.date()}")

            # Step 1: Optimize In-Sample (Mocked for now, just running standard backtest to prove concept)
            # In a full implementation, you would call the Optimizer here to find the best params
            # for the in-sample period, and then pass those params to the Out-Of-Sample run.

            # Step 2: Run Out-of-Sample validation
            engine = PortfolioEngine(self.data_dir)
            engine.add_data(symbols, start_date=str(test_start.date()), end_date=str(test_end.date()))
            engine.set_strategy(strategy_class)

            run_results = engine.run()
            strat = run_results[0]

            # Extract Metrics for Out-Of-Sample
            returns_s = strat.analyzers.returns.get_analysis()
            s = pd.Series(returns_s)
            s.index = pd.to_datetime(s.index)
            metrics = Metrics.compute_all(s)

            pnl = strat.analyzers.trades.get_analysis().get('pnl', {}).get('net', {}).get('total', 0)

            logging.info(f"OOS Net Profit: ${pnl:.2f}")
            logging.info(f"OOS Sharpe: {metrics.get('Sharpe Ratio', 0):.2f}")

            results.append({
                'step': step,
                'train_period': f"{current_train_start.date()} -> {train_end.date()}",
                'test_period': f"{test_start.date()} -> {test_end.date()}",
                'oos_pnl': pnl,
                'oos_sharpe': metrics.get('Sharpe Ratio', 0)
            })

            # Shift window forward by the test delta
            current_train_start += test_delta
            step += 1

        self._print_wfa_summary(results)

    def _print_wfa_summary(self, results: List[Dict]):
        print("\n" + "="*50)
        print("WALK-FORWARD OOS SUMMARY")
        print("="*50)
        total_pnl = 0
        for r in results:
            print(f"Step {r['step']} ({r['test_period']}) | PnL: ${r['oos_pnl']:.2f} | Sharpe: {r['oos_sharpe']:.2f}")
            total_pnl += r['oos_pnl']
        print("-" * 50)
        print(f"TOTAL OOS PnL: ${total_pnl:.2f}")
        print("="*50)
