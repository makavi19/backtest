import os
import pandas as pd
import backtrader as bt
from typing import Dict, List, Optional
import pytz

class CustomCSVData(bt.feeds.PandasData):
    """
    Standardizes loading dataframe data into backtrader.
    We pre-process the CSV in Pandas to handle timezones and missing values,
    and then feed it directly via PandasData to Backtrader.
    """

    # Optional parameters for future spread/tick extensions
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 'open'),
        ('high', 'high'),
        ('low', 'low'),
        ('close', 'close'),
        ('volume', 'volume'),
        ('openinterest', -1),
        ('spread', -1), # Optional
    )


class DataLoader:
    """
    Institutional data loader for backtesting.
    Loads standard format: datetime, open, high, low, close, volume.
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.loaded_data: Dict[str, pd.DataFrame] = {}

    def load_pair_data(self, symbol: str, timeframe: str = 'M15',
                       start_date: Optional[str] = None,
                       end_date: Optional[str] = None) -> bt.feeds.PandasData:
        """
        Loads CSV file for a given symbol and timeframe.
        Default expects: {symbol}_{timeframe}.csv in the data directory.
        """
        filename = f"{symbol}_{timeframe}.csv"
        filepath = os.path.join(self.data_dir, filename)

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Data file not found: {filepath}")

        # Read CSV using pandas for fast & robust parsing
        df = pd.read_csv(filepath)

        # Standardize column names to lower case
        df.columns = [c.lower().strip() for c in df.columns]

        # Datetime handling
        if 'datetime' not in df.columns and 'date' in df.columns and 'time' in df.columns:
            df['datetime'] = df['date'] + " " + df['time']

        if 'datetime' not in df.columns:
            raise ValueError(f"CSV must contain 'datetime' column. Found: {df.columns}")

        # Parse datetime and sort
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime')

        # Filter by dates if specified
        if start_date:
            df = df[df['datetime'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['datetime'] <= pd.to_datetime(end_date)]

        # Set index for Backtrader PandasData feed
        df.set_index('datetime', inplace=True)

        self.loaded_data[symbol] = df

        # Create Backtrader feed
        data_feed = CustomCSVData(
            dataname=df,
            name=symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=15 if timeframe == 'M15' else 1
        )
        return data_feed

    def load_portfolio_data(self, symbols: List[str], timeframe: str = 'M15',
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> Dict[str, bt.feeds.PandasData]:
        """Loads data feeds for multiple pairs."""
        feeds = {}
        for symbol in symbols:
            try:
                feeds[symbol] = self.load_pair_data(symbol, timeframe, start_date, end_date)
            except FileNotFoundError as e:
                print(f"[Warning] Skipping {symbol}: {e}")
        return feeds

    def discover_available_pairs(self) -> List[str]:
        """Automatically discovers available pairs in the data directory."""
        if not os.path.exists(self.data_dir):
            return []

        pairs = []
        for filename in os.listdir(self.data_dir):
            if filename.endswith(".csv"):
                parts = filename.split('_')
                if len(parts) >= 1:
                    pairs.append(parts[0])
        return list(set(pairs))
