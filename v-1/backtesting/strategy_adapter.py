import backtrader as bt
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Import live system core
from core.config import config, get_pair_config
from core.session_manager import session_mgr
from agents.market_intelligence.dxy_sentinel import DXYSentinel
from agents.market_dynamics.regime_detector import RegimeDetector
from strategies.strategy_selector import StrategySelector
from strategies.base_strategy import StrategySignal

class StrategyAdapter(bt.Strategy):
    """
    Bridges Backtrader with the existing Eleven Pairs infrastructure.
    Maintains a rolling Pandas window, interfaces with existing modules,
    and executes orders seamlessly within the Backtrader ecosystem.
    """

    params = (
        ('lookback_bars', 100),  # Number of bars to keep in rolling df
        ('dry_run_log', False),
    )

    def __init__(self):
        # Rolling DataFrames per symbol
        self.rolling_data: Dict[str, pd.DataFrame] = {}

        # We also need H1 and H4 equivalents for the strategies.
        # For simplicity, we will dynamically resample the M15 rolling buffer,
        # but in a perfect world, we'd maintain separate feeds.
        # We need a longer lookback to generate sufficient H1/H4 bars.
        self.max_lookback = self.params.lookback_bars * 16 # roughly 100 H4 bars worth

        # Instantiate core modules WITHOUT MT5 bridge
        # We pass None for bridge and will mock data internally
        self.regime_detector = RegimeDetector(bridge=None)
        self.strategy_selector = StrategySelector(bridge=None)

        # We need to hack the StrategySelector and BaseStrategies slightly since they usually call bridge.get_historical_data
        # We will inject our rolling data directly when calling detect_setup.

        # Keep track of active positions to manage stops/TPs realistically
        self.active_orders: Dict[str, bt.Order] = {}
        self.order_meta: Dict[str, dict] = {} # Store TP/SL levels

    def start(self):
        logging.info("StrategyAdapter initialized.")
        for data in self.datas:
            # Initialize empty buffers
            self.rolling_data[data._name] = pd.DataFrame(columns=['open', 'high', 'low', 'close', 'volume', 'datetime'])
            self.rolling_data[data._name].set_index('datetime', inplace=True)

    def prenext(self):
        # Called before next() if minimum lookback isn't reached yet
        self.update_rolling_data()

    def update_rolling_data(self):
        """Maintains the rolling Pandas DataFrame for each data feed."""
        for data in self.datas:
            symbol = data._name
            dt = data.datetime.datetime()

            # Append current bar
            new_row = pd.DataFrame({
                'open': [data.open[0]],
                'high': [data.high[0]],
                'low': [data.low[0]],
                'close': [data.close[0]],
                'volume': [data.volume[0]]
            }, index=[dt])

            # Concat and prune
            self.rolling_data[symbol] = pd.concat([self.rolling_data[symbol], new_row])
            if len(self.rolling_data[symbol]) > self.max_lookback:
                self.rolling_data[symbol] = self.rolling_data[symbol].iloc[-self.max_lookback:]

    def next(self):
        """Called bar-by-bar."""
        self.update_rolling_data()

        # Manage existing orders (trailing stops, etc. could go here)
        # Real MT5 brackets are managed by the broker, Backtrader brackets are managed by its broker.

        # Run Eleven Pairs Analysis loop (simulate a scan step)
        # In reality, the bot scans periodically (e.g., every 15m)
        # We assume the data feed is M15, so this triggers on bar close.

        # Mock DXY Directions for now (would need actual DXY correlation logic via DXY proxy feed if available)
        mock_dxy_directions = {d._name: 'buy' for d in self.datas} # Simplified mock

        # Get current session string
        current_time_ist = self.datas[0].datetime.datetime() # Simplified timezone handling for backtest
        # We should map dt to IST phase. For now, assuming always "london" for backtest mock if simple
        current_session = "london"

        recommendations = self.evaluate_strategies(mock_dxy_directions, current_session)

        if not recommendations:
            return

        for rec in recommendations:
            if rec.selected and rec.signal.grade in ['A', 'A+', 'B+', 'B']:
                self.execute_signal(rec.signal)

    def evaluate_strategies(self, dxy_directions, session) -> list:
        """
        Mimics strategy_selector.select_best_trade but injects local rolling data
        instead of fetching from MT5 bridge.
        """
        all_signals = []

        for data in self.datas:
            symbol = data._name
            df_m15 = self.rolling_data[symbol]

            if len(df_m15) < 100: # Need minimum bars
                continue

            # Create higher timeframes dynamically
            df_h1 = self._resample_df(df_m15, '1H')
            df_h4 = self._resample_df(df_m15, '4H')

            # We would normally loop over strategies in StrategySelector.
            # To preserve architecture, we must instantiate them here and call detect_setup directly,
            # bypassing the mt5 bridge dependency inside base_strategy.fetch_data.
            for strat_name, strat_instance in self.strategy_selector.strategies.items():
                if not strat_instance.is_preferred_for_session(session):
                    continue
                if not strat_instance.is_preferred_for_pair(symbol):
                    continue

                direction = dxy_directions.get(symbol, 'buy')

                try:
                    # Pass the rolling dataframes directly!
                    signal = strat_instance.detect_setup(
                        symbol=symbol,
                        direction=direction,
                        m15=df_m15.iloc[-100:], # Pass exact required slice
                        h1=df_h1.iloc[-25:] if len(df_h1) >= 25 else df_h1,
                        h4=df_h4.iloc[-10:] if len(df_h4) >= 10 else df_h4
                    )

                    if signal and signal.is_tradeable:
                        all_signals.append(signal)

                except Exception as e:
                    logging.debug(f"Strategy {strat_name} failed on {symbol}: {e}")

        # Score and rank signals (mimicking strategy_selector logic)
        # For version 1 backtesting, we just take the first valid signal.
        # Future enhancement: proper scoring & ranking.
        ranked = []
        for sig in all_signals:
            from core.strategy_selector import StrategyRecommendation
            rec = StrategyRecommendation(
                strategy_name=sig.strategy_name,
                symbol=sig.symbol,
                direction=sig.direction,
                signal=sig,
                score=sig.confidence,
                selected=True
            )
            ranked.append(rec)

        return ranked

    def _resample_df(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        """Helper to resample M15 pandas df to H1/H4"""
        if df.empty:
            return df
        resampled = df.resample(timeframe).agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()
        return resampled

    def execute_signal(self, signal: StrategySignal):
        """Translates StrategySignal into Backtrader bracket orders."""
        symbol = signal.symbol
        data_feed = self.getdatabyname(symbol)

        # Don't trade if already in position
        if self.getposition(data_feed).size != 0:
            return

        # Realistic position sizing
        risk_usd = signal.recommended_risk_usd
        # Approximate lot size based on fixed pip value
        # e.g., 0.1 pip value, $7 risk over 10 pips = $0.7 per pip -> 0.07 lots (standardized)
        # Backtrader uses raw size. We'll simulate generic size for now.
        lot_size = risk_usd / (signal.stop_pips * 10) if signal.stop_pips > 0 else 0.01

        is_buy = signal.direction.upper() == 'BUY'

        # Send Bracket Order
        if is_buy:
            order = self.buy(
                data=data_feed,
                size=lot_size,
                exectype=bt.Order.Market,
                transmit=False # For brackets
            )
            sl_order = self.sell(
                data=data_feed, size=lot_size, exectype=bt.Order.Stop, price=signal.stop_loss, parent=order, transmit=False
            )
            tp_order = self.sell(
                data=data_feed, size=lot_size, exectype=bt.Order.Limit, price=signal.take_profit_1, parent=order, transmit=True
            )
        else:
            order = self.sell(
                data=data_feed,
                size=lot_size,
                exectype=bt.Order.Market,
                transmit=False
            )
            sl_order = self.buy(
                data=data_feed, size=lot_size, exectype=bt.Order.Stop, price=signal.stop_loss, parent=order, transmit=False
            )
            tp_order = self.buy(
                data=data_feed, size=lot_size, exectype=bt.Order.Limit, price=signal.take_profit_1, parent=order, transmit=True
            )

        logging.info(f"Executed {signal.direction} on {symbol} @ {signal.entry_price} [Risk: ${risk_usd}] (Strat: {signal.strategy_name})")

    def notify_order(self, order):
        """Log order execution details."""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            action = 'BUY' if order.isbuy() else 'SELL'
            logging.info(f"[ORDER EXECUTED] {action} {order.data._name} at {order.executed.price:.5f}, Cost: {order.executed.value:.2f}, Comm: {order.executed.comm:.2f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            logging.warning(f"[ORDER FAILED] {order.data._name} status: {order.status}")

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        logging.info(f"[TRADE CLOSED] {trade.data._name} Gross PnL: {trade.pnl:.2f}, Net PnL: {trade.pnlcomm:.2f}")
