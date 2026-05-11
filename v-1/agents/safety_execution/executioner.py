# agents/safety_execution/executioner.py
# Order execution with retry logic and fill validation

from dataclasses import dataclass
from typing import Optional, Dict, List, Literal
from datetime import datetime
import time
import logging

from core.mt5_bridge import MT5Bridge, get_bridge, OrderResult

logger = logging.getLogger('Executioner')


@dataclass
class ExecutionReport:
    """Complete execution result"""
    success: bool
    order_ticket: Optional[int]
    fill_price: Optional[float]
    slippage_pips: Optional[float]
    lots_filled: Optional[float]
    execution_time_ms: Optional[int]
    error: Optional[str]
    retry_count: int
    alternative_action: Optional[str] = None  # 'market', 'limit', 'cancel'


class Executioner:
    """
    Executes orders to MT5 with:
    - Retry on temporary failures
    - Slippage monitoring
    - Fill validation
    - Partial fill handling
    """
    
    MAX_RETRIES = 3
    SLIPPAGE_TOLERANCE = {
        'XAUUSD': 5.0,      # 5 pips for gold
        'XAGUSD': 10.0,     # 10 pips for silver
        'GBPJPY': 3.0,      # 3 pips for volatile crosses
        'default': 2.0      # 2 pips for majors
    }
    RETRY_DELAY_MS = 250
    
    def __init__(self, bridge: Optional[MT5Bridge] = None):
        self.bridge = bridge or get_bridge()
        
    def execute_market_order(
        self,
        symbol: str,
        direction: Literal['BUY', 'SELL'],
        volume: float,
        stop_loss: float,
        take_profit: float,
        max_slippage: Optional[float] = None
    ) -> ExecutionReport:
        """
        Execute market order with full error handling
        """
        start_time = datetime.now()
        last_error = None
        retry_count = 0
        
        # Determine max slippage
        if max_slippage is None:
            max_slippage = self.SLIPPAGE_TOLERANCE.get(symbol, self.SLIPPAGE_TOLERANCE['default'])
        
        for attempt in range(1, self.MAX_RETRIES + 1):
            retry_count = attempt - 1
            
            try:
                # Pre-execution price check
                expected_price = self._get_current_price(symbol, direction)
                
                # Send order
                result = self.bridge.send_market_order(
                    symbol=symbol,
                    direction=direction,
                    volume=volume,
                    sl=stop_loss,
                    tp=take_profit,
                    deviation=int(max_slippage * 10),  # Convert to points
                    comment=f"EP_{attempt}"
                )
                
                execution_time = int((datetime.now() - start_time).total_seconds() * 1000)
                
                if result.success:
                    # Validate fill quality
                    slippage = self._calculate_slippage(
                        expected_price, result.price, symbol, direction
                    )
                    
                    if slippage > max_slippage:
                        # Excessive slippage - log but keep position
                        logger.warning(
                            f"High slippage on {symbol}: {slippage:.1f}p > {max_slippage}p"
                        )
                    
                    return ExecutionReport(
                        success=True,
                        order_ticket=result.ticket,
                        fill_price=result.price,
                        slippage_pips=slippage,
                        lots_filled=result.volume_executed,
                        execution_time_ms=execution_time,
                        error=None,
                        retry_count=retry_count
                    )
                
                # Failed - analyze error
                last_error = result.error
                error_type = self._classify_error(result.error, result.retcode)
                
                if error_type == 'fatal':
                    # Don't retry
                    return ExecutionReport(
                        success=False,
                        order_ticket=None,
                        error=f"Fatal: {result.error}",
                        retry_count=retry_count,
                        alternative_action='cancel'
                    )
                
                if error_type == 'price_changed':
                    # Market moved significantly - re-evaluate
                    new_price = self._get_current_price(symbol, direction)
                    price_drift = abs(new_price - expected_price)
                    
                    if price_drift > max_slippage * 2:
                        # Structure broken, abort
                        return ExecutionReport(
                            success=False,
                            error=f"Structure broken: price moved {price_drift:.1f}p",
                            retry_count=retry_count,
                            alternative_action='re_analyze'
                        )
                
                # Temporary error - retry
                if attempt < self.MAX_RETRIES:
                    sleep_sec = (self.RETRY_DELAY_MS * attempt) / 1000
                    logger.info(f"Retry {attempt}/{self.MAX_RETRIES} in {sleep_sec}s")
                    time.sleep(sleep_sec)
                    
            except Exception as e:
                last_error = str(e)
                logger.error(f"Execution exception: {e}")
                
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY_MS / 1000)
        
        # All retries exhausted
        return ExecutionReport(
            success=False,
            error=f"Failed after {self.MAX_RETRIES} attempts: {last_error}",
            retry_count=retry_count,
            alternative_action='limit_order'
        )
    
    def execute_with_confirmation(
        self,
        symbol: str,
        direction: Literal['BUY', 'SELL'],
        volume: float,
        stop_loss: float,
        take_profit: float,
        confirmation_timeout: int = 5
    ) -> ExecutionReport:
        """
        Execute and wait for position to appear in MT5
        Handles case where order sends but position not created
        """
        # Initial execution
        result = self.execute_market_order(
            symbol, direction, volume, stop_loss, take_profit
        )
        
        if not result.success:
            return result
        
        # Wait for position confirmation
        start_wait = datetime.now()
        
        while (datetime.now() - start_wait).total_seconds() < confirmation_timeout:
            positions = self.bridge.get_positions(symbol)
            
            match = next(
                (p for p in positions if p.ticket == result.order_ticket),
                None
            )
            
            if match:
                # Validate parameters
                params_ok = (
                    abs(match.sl - stop_loss) < 0.0001 and
                    abs(match.tp - take_profit) < 0.0001 and
                    abs(match.volume - volume) < 0.001
                )
                
                if not params_ok:
                    # Attempt correction
                    self._correct_position(result.order_ticket, stop_loss, take_profit)
                
                return result  # Confirmed
            
            time.sleep(0.1)  # 100ms check interval
        
        # Position not found - investigation needed
        logger.error(f"Order {result.order_ticket} sent but position not found!")
        
        return ExecutionReport(
            success=True,  # Order did send
            order_ticket=result.order_ticket,
            fill_price=result.fill_price,
            error="Position confirmation timeout - verify manually",
            retry_count=result.retry_count,
            alternative_action='manual_check'
        )
    
    def modify_trade(
        self,
        ticket: int,
        new_stop: Optional[float] = None,
        new_target: Optional[float] = None
    ) -> bool:
        """
        Modify SL/TP of open trade
        """
        try:
            result = self.bridge.modify_position(ticket, new_stop, new_target)
            return result.success
        except Exception as e:
            logger.error(f"Modify failed: {e}")
            return False
    
    def partial_close(
        self,
        ticket: int,
        percent: float = 50.0
    ) -> ExecutionReport:
        """
        Close percentage of position
        """
        try:
            result = self.bridge.close_position(ticket, percent)
            
            return ExecutionReport(
                success=result.success,
                order_ticket=result.ticket if result.success else None,
                fill_price=result.price,
                lots_filled=result.volume_executed,
                error=result.error,
                retry_count=0
            )
            
        except Exception as e:
            return ExecutionReport(
                success=False,
                error=str(e),
                retry_count=0
            )
    
    def emergency_close_all(self) -> List[ExecutionReport]:
        """
        Close all positions immediately
        """
        results = []
        positions = self.bridge.get_positions()
        
        for pos in positions:
            result = self.bridge.close_position(pos.ticket, 100.0)
            
            results.append(ExecutionReport(
                success=result.success,
                order_ticket=result.ticket,
                fill_price=result.price,
                error=result.error,
                retry_count=0
            ))
            
            logger.info(f"Emergency close {pos.symbol}: {'OK' if result.success else 'FAIL'}")
        
        return results
    
    def _get_current_price(self, symbol: str, direction: str) -> float:
        """Get current relevant price"""
        try:
            # Fetch from MT5
            import MetaTrader5 as mt5
            broker_symbol = self.bridge._normalize_symbol(symbol)
            tick = mt5.symbol_info_tick(broker_symbol)
            
            if direction == 'BUY':
                return tick.ask
            else:
                return tick.bid
                
        except:
            # Fallback
            return 0.0
    
    def _calculate_slippage(
        self,
        expected: float,
        filled: float,
        symbol: str,
        direction: str
    ) -> float:
        """Calculate slippage in pips"""
        diff = abs(filled - expected)
        
        # Convert to pips based on symbol
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001
        
        slippage_pips = diff / pip_size
        
        # Direction matters: adverse only
        if direction == 'BUY' and filled > expected:
            return slippage_pips  # Worse
        elif direction == 'SELL' and filled < expected:
            return slippage_pips  # Worse
        
        return 0.0  # Favorable or zero
    
    def _classify_error(self, error: str, retcode: Optional[int]) -> str:
        """Classify MT5 error for retry decision"""
        if not error:
            return 'unknown'
        
        error_lower = error.lower()
        
        fatal_keywords = [
            'no money', 'disabled', 'closed', 'invalid stops',
            'invalid volume', 'autotrading disabled', 'not found'
        ]
        
        price_keywords = ['price changed', 'requote', 'off quotes']
        
        if any(k in error_lower for k in fatal_keywords):
            return 'fatal'
        
        if any(k in error_lower for k in price_keywords):
            return 'price_changed'
        
        # Temporary errors
        return 'temporary'
    
    def _correct_position(self, ticket: int, correct_sl: float, correct_tp: float):
        """Attempt to fix SL/TP mismatch"""
        try:
            self.bridge.modify_position(ticket, correct_sl, correct_tp)
            logger.info(f"Corrected position #{ticket} parameters")
        except Exception as e:
            logger.error(f"Failed to correct position: {e}")
    
    def get_execution_stats(self) -> Dict:
        """Statistics for review"""
        return {
            'total_executions': 0,  # Track in persistence
            'successful_fills': 0,
            'avg_slippage': 0.0,
            'retry_rate': 0.0,        }
