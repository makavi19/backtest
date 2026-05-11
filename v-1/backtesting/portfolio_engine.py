import backtrader as bt
from typing import List, Dict, Type, Optional
from backtesting.data_loader import DataLoader
import logging

class PortfolioEngine:
    """
    Manages the setup and execution of the Backtrader multi-pair backtest.
    Sets up realistic institutional conditions: capital, leverage, spread, slippage, commissions.
    """

    def __init__(self, data_dir: str, initial_cash: float = 10000.0,
                 leverage: float = 100.0,
                 commission_per_lot: float = 3.5, # $3.50 per lot round trip
                 slippage_pips: float = 0.5):

        self.cerebro = bt.Cerebro(stdstats=False) # We will handle stats manually for realism
        self.data_loader = DataLoader(data_dir)

        # Setup Broker settings
        self.cerebro.broker.setcash(initial_cash)
        # Note: Backtrader handles margin natively but we will manage real capital allocation in strategy.
        # But we still set commission here if we want simple modeling
        self.cerebro.broker.setcommission(
            commission=commission_per_lot,
            margin=0,
            mult=1.0,
            leverage=leverage
        )

        # Adding slippage simulation
        # Fixed slippage in points. For a pip (0.0001), 0.5 pips = 0.00005
        # This will be configured more accurately per pair inside the StrategyAdapter
        # self.cerebro.broker.set_slippage_fixed(0.00005)

        self.symbols_loaded: List[str] = []

    def add_data(self, symbols: List[str], timeframe: str = 'M15',
                 start_date: Optional[str] = None, end_date: Optional[str] = None):
        """Loads data into cerebro for the given portfolio."""
        feeds = self.data_loader.load_portfolio_data(symbols, timeframe, start_date, end_date)

        for symbol, feed in feeds.items():
            self.cerebro.adddata(feed, name=symbol)
            self.symbols_loaded.append(symbol)
            logging.info(f"Loaded {symbol} into portfolio engine.")

    def set_strategy(self, strategy_class: Type[bt.Strategy], **kwargs):
        """Injects the StrategyAdapter."""
        self.cerebro.addstrategy(strategy_class, **kwargs)

    def run(self) -> List[bt.Strategy]:
        """Runs the backtest."""
        logging.info("Starting portfolio backtest...")
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.0)
        self.cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='returns')

        results = self.cerebro.run()
        logging.info("Backtest complete.")
        return results
