import argparse
import sys
import logging
import os
from datetime import datetime

# Setup basic logging for the runner
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

from backtesting.portfolio_engine import PortfolioEngine
from backtesting.strategy_adapter import StrategyAdapter
from backtesting.metrics import Metrics
from backtesting.report_generator import ReportGenerator
from backtesting.optimizer import Optimizer
from backtesting.walk_forward import WalkForwardTester

def main():
    parser = argparse.ArgumentParser(description="Eleven Pairs Institutional Backtesting Framework")

    # Target Selection
    parser.add_argument('--all-pairs', action='store_true', help="Run backtest on all available pairs in data directory")
    parser.add_argument('--pairs', type=str, help="Comma-separated list of pairs (e.g., EURUSD,XAUUSD)")

    # Timeframe & Duration
    parser.add_argument('--years', type=int, default=10, help="Number of years of historical data to load")
    parser.add_argument('--start-date', type=str, help="Start date YYYY-MM-DD")
    parser.add_argument('--end-date', type=str, help="End date YYYY-MM-DD")

    # Modes
    parser.add_argument('--optimize', action='store_true', help="Run grid search optimization")
    parser.add_argument('--walk-forward', action='store_true', help="Run rolling walk-forward validation")

    # Output
    parser.add_argument('--report', action='store_true', help="Generate HTML tearsheet report")

    args = parser.parse_args()

    data_dir = os.path.join(os.path.dirname(__file__), "data")

    if args.all_pairs:
        from backtesting.data_loader import DataLoader
        loader = DataLoader(data_dir)
        symbols = loader.discover_available_pairs()
        if not symbols:
            logging.error("No pairs found in data directory. Please add CSV files.")
            sys.exit(1)
    elif args.pairs:
        symbols = [s.strip() for s in args.pairs.split(",")]
    else:
        logging.error("You must specify either --all-pairs or --pairs <list>")
        sys.exit(1)

    logging.info(f"Target Pairs: {symbols}")

    if args.optimize:
        opt = Optimizer(data_dir)
        # Example grid: vary the lookback bars for the rolling window
        param_grid = {'lookback_bars': [50, 100, 200]}
        opt.optimize(StrategyAdapter, symbols, param_grid, start_date=args.start_date, end_date=args.end_date)
        sys.exit(0)

    if args.walk_forward:
        wfa = WalkForwardTester(data_dir)
        wfa.run_walk_forward(StrategyAdapter, symbols, start_date=args.start_date, end_date=args.end_date)
        sys.exit(0)

    # Standard Portfolio Backtest
    engine = PortfolioEngine(data_dir)
    engine.add_data(symbols, start_date=args.start_date, end_date=args.end_date)
    engine.set_strategy(StrategyAdapter)

    results = engine.run()
    strategy_instance = results[0]

    # Reporting
    if args.report:
        generator = ReportGenerator()
        returns_s = Metrics.extract_returns_from_analyzer(strategy_instance.analyzers.returns)
        generator.generate_tearsheet(returns_s, filename=f"tearsheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
        generator.generate_trade_log(strategy_instance.analyzers.trades)
        generator.print_console_summary(returns_s, strategy_instance.analyzers.trades)

if __name__ == "__main__":
    main()
