import logging
import backtrader as bt
from typing import Dict, Any, Type, List
from backtesting.portfolio_engine import PortfolioEngine

class Optimizer:
    """
    Handles parameter grid search using Backtrader's optimization capabilities.
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir

    def optimize(self, strategy_class: Type[bt.Strategy], symbols: List[str],
                 param_grid: Dict[str, Any], timeframe: str = 'M15',
                 start_date: str = None, end_date: str = None):
        """
        Runs a grid search over the specified parameters.
        """
        logging.info("Initializing Optimization...")

        # We need a new cerebro instance configured for optimization
        cerebro = bt.Cerebro(optreturn=False)

        # Setup Broker settings
        cerebro.broker.setcash(10000.0)
        cerebro.broker.setcommission(commission=3.5, margin=0, mult=1.0, leverage=100.0)

        # Load Data
        from backtesting.data_loader import DataLoader
        loader = DataLoader(self.data_dir)
        feeds = loader.load_portfolio_data(symbols, timeframe, start_date, end_date)
        for symbol, feed in feeds.items():
            cerebro.adddata(feed, name=symbol)

        # Add Analyzers
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)

        # Add Strategy with Param Grid
        cerebro.optstrategy(strategy_class, **param_grid)

        # Run
        logging.info(f"Running Optimization with grid: {param_grid}")
        results = cerebro.run()

        self._parse_results(results)
        return results

    def _parse_results(self, opt_results):
        """Extracts and sorts results to find the best parameter set."""
        print("\n" + "="*50)
        print("OPTIMIZATION RESULTS (Ranked by Net Profit)")
        print("="*50)

        ranked_results = []
        for run in opt_results:
            for strategy in run:
                params = strategy.params._getkwargs()

                # Fetch analyzers
                trades = strategy.analyzers.trades.get_analysis()
                net_pnl = trades.get('pnl', {}).get('net', {}).get('total', 0)

                sharpe = strategy.analyzers.sharpe.get_analysis().get('sharperatio', 0)
                drawdown = strategy.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)

                ranked_results.append({
                    'params': params,
                    'net_profit': net_pnl,
                    'sharpe': sharpe,
                    'max_drawdown': drawdown
                })

        # Sort by Net Profit (descending)
        ranked_results.sort(key=lambda x: x['net_profit'], reverse=True)

        for idx, res in enumerate(ranked_results[:10]): # Top 10
            print(f"#{idx+1} | PnL: ${res['net_profit']:.2f} | MaxDD: {res['max_drawdown']:.2f}% | Params: {res['params']}")

        print("="*50)
        print("WARNING: Beware of curve-fitting! Always validate optimized parameters with Out-of-Sample/Walk-Forward testing.")
