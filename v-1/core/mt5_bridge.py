# core/mt5_bridge.py -: Imports and Data Classes

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None
    print("Warning: MetaTrader5 not available. Ensure DRY_RUN=TRUE.")
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Literal, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
import logging
import time
import threading

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('MT5Bridge')


@dataclass
class OrderResult:
    success: bool
    ticket: Optional[int] = None
    price: Optional[float] = None
    slippage_pips: Optional[float] = None
    error: Optional[str] = None
    retcode: Optional[int] = None
    volume_executed: Optional[float] = None
    time_executed: Optional[datetime] = None
    comment: Optional[str] = None


@dataclass
class PositionInfo:
    ticket: int
    symbol: str
    direction: Literal['BUY', 'SELL']
    volume: float
    open_price: float
    current_price: float
    sl: float
    tp: float
    profit: float
    swap: float
    commission: float
    open_time: datetime
    magic: int
    comment: str = ""

    @property
    def pnl_total(self) -> float:
        return self.profit + self.swap + self.commission


class MT5Bridge:
    """
    Production-grade MT5 connection with:
    - Auto-reconnect
    - Symbol normalization (your names to XM's names)
    - Dynamic position sizing
    - Thread-safe operations
    """

    # Map your standard symbol names to XM's exact symbols
    # MODIFY THESE TO MATCH YOUR XM TERMINAL
    SYMBOL_MAP: Dict[str, str] = {
        'EURUSD': 'EURUSD',
        'GBPUSD': 'GBPUSD',
        'AUDUSD': 'AUDUSD',
        'NZDUSD': 'NZDUSD',
        'USDJPY': 'USDJPY',
        'USDCAD': 'USDCAD',
        'USDCHF': 'USDCHF',
        'EURJPY': 'EURJPY',
        'GBPJPY': 'GBPJPY',
        'XAUUSD': 'GOLD',    # ← CHANGE IF XM USES 'GOLD'
        'XAGUSD': 'SILVER',    # ← CHANGE IF XM USES 'SILVER'
        'DXY_PROXY': 'USDX-JUN26', # ← CHANGE IF XM HAS 'DXY' or 'USDX'
    }

    def __init__(
        self,
        account: Optional[int] = None,
        password: Optional[str] = None,
        server: Optional[str] = None,
        path: Optional[str] = None,
        magic_number: int = 987654
    ):
        self.account = account
        self.password = password
        self.server = server
        self.path = path
        self.magic_number = magic_number

        self.connected: bool = False
        self.last_heartbeat: Optional[datetime] = None
        self.connection_retries: int = 0
        self.max_retries: int = 3
        self.lock = threading.Lock()

        self.symbol_specs: Dict[str, Dict] = {}
        self._initialize_symbol_specs_template()

    def _initialize_symbol_specs_template(self):
        """Initialize with safe defaults - will be updated on connect"""
        for std_symbol, broker_symbol in self.SYMBOL_MAP.items():
            self.symbol_specs[std_symbol] = {
                'broker_symbol': broker_symbol,
                'digits': 5,
                'point': 0.00001,
                'volume_min': 0.01,
                'volume_max': 100.0,
                'volume_step': 0.01,
                'spread': 10,
            }
 # === CONNECTION MANAGEMENT ===

    def connect(self) -> bool:
        """Initialize MT5 connection with retry logic"""
        with self.lock:
            if self.connected and self._heartbeat_check():
                return True

            # Shutdown any existing connection
            try:
                mt5.shutdown()
            except:
                pass

            # Initialize MT5
            init_kwargs = {}
            if self.path:
                init_kwargs['path'] = self.path

            if not mt5.initialize(**init_kwargs):
                error = mt5.last_error()
                logger.error(f"MT5 initialize failed: {error}")
                self.connected = False
                return False

            # Login if credentials provided
            if self.account and self.password and self.server:
                authorized = mt5.login(
                    self.account,
                    password=self.password,
                    server=self.server
                )
                if not authorized:
                    logger.error(f"MT5 login failed: {mt5.last_error()}")
                    mt5.shutdown()
                    self.connected = False
                    return False

            self.connected = True
            self.last_heartbeat = datetime.now()
            self.connection_retries = 0

            # Cache symbol specifications
            self._cache_symbol_specs()

            # Log success
            try:
                account_info = mt5.account_info()
                logger.info(f"MT5 connected: {account_info.name}, Balance: ${account_info.balance:,.2f}")
            except Exception as e:
                logger.warning(f"Connected but couldn't get account info: {e}")

            return True

    def disconnect(self):
        """Clean shutdown"""
        with self.lock:
            try:
                mt5.shutdown()
            except:
                pass
            self.connected = False
            self.last_heartbeat = None
            logger.info("MT5 disconnected")

    def _heartbeat_check(self) -> bool:
        """Verify connection is alive"""
        if not self.last_heartbeat:
            return False

        # Consider stale if >30 seconds
        if datetime.now() - self.last_heartbeat > timedelta(seconds=30):
            try:
                # Lightweight check
                info = mt5.symbol_info("EURUSD")
                if info is None:
                    return False
                self.last_heartbeat = datetime.now()
                return True
            except:
                return False

        # Recent enough heartbeat
        return True

    def _ensure_connected(self):
        """Ensure connection before operations"""
        if not self._heartbeat_check():
            self._reconnect()

    def _reconnect(self) -> bool:
        """Attempt reconnection with exponential backoff"""
        self.connection_retries += 1

        if self.connection_retries > self.max_retries:
            logger.critical(f"Failed to reconnect after {self.max_retries} attempts")
            raise ConnectionError("MT5 connection permanently lost")

        wait = min(2 ** self.connection_retries, 30)  # Cap at 30 seconds
        logger.warning(f"Reconnecting in {wait}s (attempt {self.connection_retries})")
        time.sleep(wait)

        return self.connect()

    def _normalize_symbol(self, symbol: str) -> str:
        """Convert standard symbol name to XM's symbol"""
        return self.SYMBOL_MAP.get(symbol, symbol)

    def _cache_symbol_specs(self):
        """Pre-load contract specifications from MT5"""
        for std_symbol, broker_symbol in self.SYMBOL_MAP.items():
            try:
                # Ensure symbol is in Market Watch
                selected = mt5.symbol_select(broker_symbol, True)
                if not selected:
                    logger.warning(f"Could not select {broker_symbol} in Market Watch")
                    continue

                info = mt5.symbol_info(broker_symbol)
                if info is None:
                    logger.warning(f"No info for {broker_symbol}")
                    continue

                # Use getattr with defaults for compatibility across MT5 versions
                self.symbol_specs[std_symbol] = {
                    'broker_symbol': broker_symbol,
                    'digits': info.digits,
                    'point': info.point,
                    'volume_min': getattr(info, 'volume_min', 0.01),
                    'volume_max': getattr(info, 'volume_max', 100.0),
                    'volume_step': getattr(info, 'volume_step', 0.01),
                    'contract_size': getattr(info, 'trade_contract_size', 100000),
                    'margin_initial': getattr(info, 'margin_initial', 0),
                    'spread': info.spread,
                    'swap_long': getattr(info, 'swap_long', 0),
                    'swap_short': getattr(info, 'swap_short', 0),
                }

                logger.info(f"Cached {std_symbol}: digits={info.digits}, point={info.point}")

            except Exception as e:
                logger.error(f"Failed to cache {std_symbol}: {e}")

    def _get_spec(self, symbol: str) -> Dict:
        """Get cached symbol specification"""
        if symbol not in self.symbol_specs:
            raise ValueError(f"Unknown symbol: {symbol}")
        return self.symbol_specs[symbol]
        # === MARKET DATA ===

    def get_account_info(self) -> Dict:
        """Get current account information"""
        self._ensure_connected()

        info = mt5.account_info()
        if info is None:
            raise ConnectionError("Failed to get account info")

        self.last_heartbeat = datetime.now()

        return {
            'balance': info.balance,
            'equity': info.equity,
            'margin': info.margin,
            'free_margin': info.margin_free,
            'margin_level': info.margin_level,
            'profit': info.profit,
            'currency': info.currency,
            'name': info.name,
            'server': info.server,
            'login': info.login,
        }

    def get_positions(self, symbol: Optional[str] = None) -> List[PositionInfo]:
        """Get open positions, optionally filtered by symbol"""
        self._ensure_connected()

        kwargs = {}
        if symbol:
            kwargs['symbol'] = self._normalize_symbol(symbol)

        positions = mt5.positions_get(**kwargs)
        if positions is None:
            return []

        # Filter to our magic number only
        our_positions = [p for p in positions if p.magic == self.magic_number]

        result = []
        for pos in our_positions:
            # Map back to standard symbol
            std_symbol = None
            for std, broker in self.SYMBOL_MAP.items():
                if broker == pos.symbol:
                    std_symbol = std
                    break
            if std_symbol is None:
                std_symbol = pos.symbol

            result.append(PositionInfo(
                ticket=pos.ticket,
                symbol=std_symbol,
                direction='BUY' if pos.type == mt5.ORDER_TYPE_BUY else 'SELL',
                volume=pos.volume,
                open_price=pos.price_open,
                current_price=pos.price_current,
                sl=pos.sl,
                tp=pos.tp,
                profit=pos.profit,
                swap=pos.swap,
                commission=pos.commission,
                open_time=datetime.fromtimestamp(pos.time),
                magic=pos.magic,
                comment=pos.comment,
            ))

        return result

    def get_historical_data(
        self,
        symbol: str,
        timeframe: Literal['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'],
        bars: int = 100
    ) -> pd.DataFrame:
        """Fetch OHLCV data for symbol"""
        self._ensure_connected()

        tf_map = {
            'M1': mt5.TIMEFRAME_M1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
            'M30': mt5.TIMEFRAME_M30,
            'H1': mt5.TIMEFRAME_H1,
            'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1,
        }

        broker_symbol = self._normalize_symbol(symbol)
        mt5_tf = tf_map.get(timeframe, mt5.TIMEFRAME_M15)

        # Ensure symbol is selected
        mt5.symbol_select(broker_symbol, True)

        rates = mt5.copy_rates_from_pos(broker_symbol, mt5_tf, 0, bars)

        if rates is None or len(rates) == 0:
            raise DataError(f"No data for {symbol} {timeframe}: {mt5.last_error()}")

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)

        # Standardize column names
        df = df.rename(columns={
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'tick_volume': 'tick_volume',
            'real_volume': 'real_volume',
            'spread': 'spread',
        })

        self.last_heartbeat = datetime.now()
        return df

    def calculate_position_size(
        self,
        symbol: str,
        risk_usd: float,
        stop_pips: float,
        entry_price: Optional[float] = None
    ) -> Dict:
        """
        Calculate lot size based on risk amount and stop distance
        """
        self._ensure_connected()

        spec = self._get_spec(symbol)
        broker_symbol = spec['broker_symbol']

        # Get current price if entry not specified
        if entry_price is None:
            tick = mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                raise ValueError(f"Cannot get price for {symbol}")
            entry_price = (tick.ask + tick.bid) / 2

        # Determine pip value for this symbol
        from core.config import get_pair_config
        pair_config = get_pair_config(symbol)

        if pair_config:
            pip_value = pair_config.pip_value
            contract_size = spec.get('contract_size', 100000)
        else:
            # Fallback calculation
            if 'JPY' in symbol:
                pip_value = 0.01
            elif 'XAU' in symbol or 'GOLD' in symbol:
                pip_value = 0.1
            else:
                pip_value = 0.0001
            contract_size = 100000

        # Calculate value per pip per lot
        # For forex: 1 standard lot = $10 per pip on XXXUSD pairs
        # Varies by pair type

        if symbol in ['EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD']:
            value_per_pip_per_lot = 10.0  # $10 per pip for 1.0 lot
        elif symbol in ['USDJPY', 'USDCAD', 'USDCHF']:
            # Inverse pairs, approximate
            value_per_pip_per_lot = 10.0 / entry_price * entry_price  # Simplified
            value_per_pip_per_lot = 10.0  # Approximation
        elif 'XAU' in symbol or 'GOLD' in symbol:
            value_per_pip_per_lot = 1.0  # $1 per $0.01 move for 1.0 lot (varies by broker)
        elif 'XAG' in symbol or 'SILVER' in symbol:
            value_per_pip_per_lot = 0.5  # Approximate
        else:
            # General formula
            value_per_pip_per_lot = (spec['point'] * contract_size) / pip_value

        # Calculate lots: Risk / (Stop Pips * Value Per Pip)
        risk_per_pip = risk_usd / stop_pips
        lots = risk_per_pip / value_per_pip_per_lot

        # Round to volume step
        step = spec['volume_step']
        lots = round(lots / step) * step

        # Enforce min/max
        lots = max(spec['volume_min'], min(spec['volume_max'], lots))

        # Calculate actual risk with rounded lots
        actual_risk = lots * stop_pips * value_per_pip_per_lot

        return {
            'lots': round(lots, 2),
            'risk_usd': round(actual_risk, 2),
            'value_per_pip': round(lots * value_per_pip_per_lot, 4),
            'stop_pips': stop_pips,
            'entry_price': entry_price,
        }

    # === ORDER EXECUTION ===

    def send_market_order(
        self,
        symbol: str,
        direction: Literal['BUY', 'SELL'],
        volume: float,
        sl: float,
        tp: float,
        deviation: int = 10,
        comment: str = "ElevenPairs"
    ) -> OrderResult:
        """Execute market order with full validation"""
        self._ensure_connected()

        spec = self._get_spec(symbol)
        broker_symbol = spec['broker_symbol']

        # Ensure symbol is selected
        if not mt5.symbol_select(broker_symbol, True):
            return OrderResult(
                success=False,
                error=f"Symbol {broker_symbol} not available"
            )

        # Normalize volume
        step = spec['volume_step']
        volume = round(volume / step) * step
        volume = max(spec['volume_min'], min(spec['volume_max'], volume))

        # Get current price
        tick = mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            return OrderResult(success=False, error="No tick data")

        price = tick.ask if direction == 'BUY' else tick.bid

        # Build order
        order_type = mt5.ORDER_TYPE_BUY if direction == 'BUY' else mt5.ORDER_TYPE_SELL

        request = {
            'action': mt5.TRADE_ACTION_DEAL,
            'symbol': broker_symbol,
            'volume': volume,
            'type': order_type,
            'price': price,
            'sl': sl,
            'tp': tp,
            'deviation': deviation,
            'magic': self.magic_number,
            'comment': comment[:31],
            'type_time': mt5.ORDER_TIME_GTC,
            'type_filling': mt5.ORDER_FILLING_IOC,
        }

        logger.info(f"Order: {direction} {volume} {symbol} @ {price:.5f}, SL={sl:.5f}, TP={tp:.5f}")

        # Send
        result = mt5.order_send(request)

        if result is None:
            return OrderResult(
                success=False,
                error=f"Send failed: {mt5.last_error()}"
            )

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            error_msg = self._decode_retcode(result.retcode)
            logger.error(f"Order failed: {error_msg} (code: {result.retcode})")
            return OrderResult(
                success=False,
                error=error_msg,
                retcode=result.retcode
            )

        # Success
        slippage = abs(result.price - price) / spec['point'] if spec['point'] > 0 else 0

        logger.info(f"Order success: #{result.order} at {result.price}")

        return OrderResult(
            success=True,
            ticket=result.order,
            price=result.price,
            slippage_pips=slippage,
            volume_executed=result.volume,
            time_executed=datetime.now(),
            comment=comment,
        )

    def modify_position(
        self,
        ticket: int,
        new_sl: Optional[float] = None,
        new_tp: Optional[float] = None
    ) -> OrderResult:
        """Modify SL/TP of open position"""
        self._ensure_connected()

        position = mt5.positions_get(ticket=ticket)
        if not position or len(position) == 0:
            return OrderResult(success=False, error="Position not found")

        pos = position[0]

        request = {
            'action': mt5.TRADE_ACTION_SLTP,
            'position': ticket,
            'symbol': pos.symbol,
            'sl': new_sl if new_sl is not None else pos.sl,
            'tp': new_tp if new_tp is not None else pos.tp,
        }

        result = mt5.order_send(request)

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return OrderResult(success=True, ticket=ticket)

        return OrderResult(
            success=False,
            error=self._decode_retcode(result.retcode) if result else "Unknown"
        )

    def close_position(self, ticket: int, percent: float = 100.0) -> OrderResult:
        """Close position fully or partially"""
        self._ensure_connected()

        position = mt5.positions_get(ticket=ticket)
        if not position or len(position) == 0:
            return OrderResult(success=False, error="Position not found")

        pos = position[0]
        close_volume = round(pos.volume * percent / 100, 2)

        # Offsetting order
        order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY

        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            return OrderResult(success=False, error="No tick data")

        price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask

        request = {
            'action': mt5.TRADE_ACTION_DEAL,
            'symbol': pos.symbol,
            'volume': close_volume,
            'type': order_type,
            'position': ticket,
            'price': price,
            'deviation': 10,
            'magic': self.magic_number,
            'comment': "Close",
        }

        result = mt5.order_send(request)

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            return OrderResult(
                success=True,
                ticket=result.order,
                price=result.price,
                volume_executed=result.volume
            )

        return OrderResult(
            success=False,
            error=self._decode_retcode(result.retcode) if result else "Close failed"
        )

    def close_all_positions(self) -> List[OrderResult]:
        """Emergency close all our positions"""
        results = []
        positions = self.get_positions()

        for pos in positions:
            result = self.close_position(pos.ticket, 100)
            results.append(result)

        return results

    def _decode_retcode(self, code: int) -> str:
        """Convert MT5 error code to message"""
        errors = {
            10004: "Requote",
            10006: "Request rejected",
            10007: "Order canceled by trader",
            10008: "Order placed",
            10009: "Request completed",
            10010: "Only part completed",
            10011: "Processing error",
            10012: "Timeout",
            10013: "Invalid request",
            10014: "Invalid volume",
            10015: "Invalid price",
            10016: "Invalid stops",
            10017: "Trade disabled",
            10018: "Market closed",
            10019: "No money",
            10020: "Price changed",
            10021: "No quotes",
            10022: "Too many requests",
            10024: "Autotrading disabled",
            10025: "Position not found",
            10026: "Symbol not found",
        }
        return errors.get(code, f"Error {code}")

    # === Context Manager ===

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False


class DataError(Exception):
    pass


# Singleton instance
_bridge_instance: Optional[MT5Bridge] = None

def get_bridge(**kwargs) -> MT5Bridge:
    """Get or create singleton bridge"""
    global _bridge_instance
    if mt5 is None:
        class DummyBridge:
            connected = False
            def connect(self): return False
            def disconnect(self): pass

            def get_account_info(self):
                return {'balance': 1000.0, 'equity': 1000.0, 'margin': 0.0, 'free_margin': 1000.0, 'margin_level': 100.0, 'profit': 0.0, 'currency': 'USD', 'name': 'Dummy', 'server': 'Dummy', 'login': '123'}

            def get_positions(self, symbol=None):
                return []

            def get_historical_data(self, symbol, timeframe, bars=100):
                import numpy as np
                import pandas as pd
                now = pd.Timestamp.now()
                dates = pd.date_range(end=now, periods=bars, freq='15min')
                df = pd.DataFrame(index=dates)
                df['open'] = np.random.normal(1.1000, 0.0010, bars)
                df['high'] = df['open'] + abs(np.random.normal(0, 0.0005, bars))
                df['low'] = df['open'] - abs(np.random.normal(0, 0.0005, bars))
                df['close'] = np.random.normal(1.1000, 0.0010, bars)
                df['tick_volume'] = np.random.randint(100, 1000, bars)
                df['real_volume'] = np.random.randint(100, 1000, bars)
                df['spread'] = np.random.randint(1, 10, bars)
                return df

            def calculate_position_size(self, symbol, risk_usd, stop_pips, entry_price=None):
                return {'lots': 0.1, 'risk_usd': risk_usd, 'value_per_pip': 1.0, 'stop_pips': stop_pips, 'entry_price': entry_price or 1.1}

            def send_market_order(self, symbol, direction, volume, sl, tp, deviation=10, comment=""):
                from core.mt5_bridge import OrderResult
                from datetime import datetime
                return OrderResult(success=True, ticket=123, price=1.1, slippage_pips=0.0, volume_executed=volume, time_executed=datetime.now(), comment=comment)

            def modify_position(self, ticket, new_sl=None, new_tp=None):
                from core.mt5_bridge import OrderResult
                return OrderResult(success=True, ticket=ticket)

            def close_position(self, ticket, percent=100.0):
                from core.mt5_bridge import OrderResult
                return OrderResult(success=True, ticket=ticket, price=1.1, volume_executed=0.1)

            def close_all_positions(self):
                return []
        return DummyBridge()

    if _bridge_instance is None or not _bridge_instance.connected:
        _bridge_instance = MT5Bridge(**kwargs)
        _bridge_instance.connect()
    return _bridge_instance
