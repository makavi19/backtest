import os
import pandas as pd
import quantstats as qs
import logging
from backtesting.metrics import Metrics

class ReportGenerator:
    """
    Generates institutional tear sheets, charts, and logs.
    """

    def __init__(self, output_dir: str = "v-1/backtesting/reports"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def generate_tearsheet(self, returns: pd.Series, filename: str = "tearsheet.html", title: str = "Backtest Report"):
        """
        Generates an HTML tearsheet using quantstats.
        """
        filepath = os.path.join(self.output_dir, filename)

        # QuantStats requires daily returns for some of its advanced metrics
        if returns.empty:
            logging.warning("No returns data to generate tearsheet.")
            return

        # Resample to daily if it's not already
        # Assuming index is datetime
        daily_returns = returns.resample('D').sum() # Simplified aggregation

        qs.reports.html(
            daily_returns,
            output=filepath,
            title=title,
            download_filename=filepath
        )
        logging.info(f"Tearsheet generated at {filepath}")

    def generate_trade_log(self, trades_analyzer, filename: str = "trade_log.csv"):
        """
        Extracts trade details from backtrader's TradeAnalyzer and saves to CSV.
        """
        analysis = trades_analyzer.get_analysis()
        # Basic parsing, Backtrader trade analyzer output is complex

        # A full implementation would parse analysis['closed'] list or listen via notify_trade
        # Here we provide a stub for saving the summary

        filepath = os.path.join(self.output_dir, filename)

        # Simplified placeholder for logging trade summary
        summary = {
            "Total Trades": analysis.get('total', {}).get('total', 0),
            "Closed Trades": analysis.get('total', {}).get('closed', 0),
            "Won": analysis.get('won', {}).get('total', 0),
            "Lost": analysis.get('lost', {}).get('total', 0),
            "Net PnL": analysis.get('pnl', {}).get('net', {}).get('total', 0),
            "Win Rate": Metrics.calculate_win_rate(pd.Series([1]*analysis.get('won',{}).get('total',0) + [-1]*analysis.get('lost',{}).get('total',0))) if analysis.get('total',{}).get('closed',0) > 0 else 0
        }

        df = pd.DataFrame([summary])
        df.to_csv(filepath, index=False)
        logging.info(f"Trade log summary generated at {filepath}")

    def print_console_summary(self, returns: pd.Series, trades_analyzer):
        """Prints high-level institutional metrics to console."""
        metrics = Metrics.compute_all(returns)
        analysis = trades_analyzer.get_analysis()

        print("\n" + "="*50)
        print("INSTITUTIONAL BACKTEST REPORT")
        print("="*50)
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"{k}: {v:.4f}")
            else:
                print(f"{k}: {v}")

        print("\nTRADE SUMMARY")
        print(f"Total Trades: {analysis.get('total', {}).get('closed', 0)}")
        print(f"Won: {analysis.get('won', {}).get('total', 0)}")
        print(f"Lost: {analysis.get('lost', {}).get('total', 0)}")
        print("="*50)
