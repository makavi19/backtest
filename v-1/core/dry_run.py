# core/dry_run.py
# Dry Run Simulator - Test the bot WITHOUT sending real orders to MT5

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path
import json
import random

from strategies.strategy_selector import StrategyRecommendation
from agents.safety_execution.dynamic_risk_manager import RiskAssignment


@dataclass
class SimulatedPosition:
    """A fake position for dry run testing"""
    ticket: int
    symbol: str
    direction: str
    entry_price: float
    volume: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_usd: float
    strategy: str
    open_time: str

    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    r_multiple: float = 0.0
    status: str = "open"
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    exit_time: Optional[str] = None

    def update_price(self, new_price: float):
        self.current_price = new_price
        if self.direction == 'BUY':
            self.unrealized_pnl = (new_price - self.entry_price) * self.volume * 100000
            risk = self.entry_price - self.stop_loss
            if risk != 0:
                self.r_multiple = (new_price - self.entry_price) / risk
        else:
            self.unrealized_pnl = (self.entry_price - new_price) * self.volume * 100000
            risk = self.stop_loss - self.entry_price
            if risk != 0:
                self.r_multiple = (self.entry_price - new_price) / risk


class DryRunSimulator:
    """
    Simulates MT5 trading WITHOUT sending real orders.

    What it does:
    - Logs every trade that WOULD be taken
    - Simulates price movement using random walk
    - Simulates position management (breakeven, trail, partial close)
    - Tracks simulated P&L
    - Exports results to JSON/Excel

    What it does NOT do:
    - Send real orders
    - Risk real money
    """

    DRY_RUN_LOG_DIR = "data/dry_run_logs"

    def __init__(self):
        Path(self.DRY_RUN_LOG_DIR).mkdir(parents=True, exist_ok=True)
        self.positions: List[SimulatedPosition] = []
        self.closed_positions: List[SimulatedPosition] = []
        self.daily_pnl = 0.0
        self.trades_today = 0
        self.ticket_counter = 900000
        self.log_file = Path(self.DRY_RUN_LOG_DIR) / f"dry_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self.trades_log: List[Dict] = []
        print("[DRY RUN] Simulator initialized - NO REAL ORDERS WILL BE SENT")

    def simulate_trade(self, recommendation, risk_assignment, position_size):
        self.ticket_counter += 1
        symbol = recommendation.symbol
        direction = recommendation.direction
        entry = recommendation.signal.entry_price

        slippage = random.uniform(-0.0001, 0.0001)
        fill_price = entry + slippage

        position = SimulatedPosition(
            ticket=self.ticket_counter,
            symbol=symbol,
            direction=direction,
            entry_price=fill_price,
            volume=position_size['lots'],
            stop_loss=recommendation.signal.stop_loss,
            take_profit_1=recommendation.signal.take_profit_1,
            take_profit_2=recommendation.signal.take_profit_2,
            risk_usd=risk_assignment.dollar_risk,
            strategy=recommendation.strategy_name,
            open_time=datetime.now().isoformat(),
            current_price=fill_price
        )

        self.positions.append(position)
        self.trades_today += 1

        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'ticket': position.ticket,
            'symbol': symbol,
            'direction': direction,
            'strategy': recommendation.strategy_name,
            'grade': recommendation.signal.grade,
            'confidence': recommendation.signal.confidence,
            'entry_price': round(fill_price, 5),
            'stop_loss': round(recommendation.signal.stop_loss, 5),
            'take_profit_1': round(recommendation.signal.take_profit_1, 5),
            'take_profit_2': round(recommendation.signal.take_profit_2, 5),
            'risk_usd': risk_assignment.dollar_risk,
            'volume': position_size['lots'],
            'slippage_pips': round(slippage / 0.0001, 2),
            'regime': recommendation.signal.detected_regime,
        }
        self.trades_log.append(trade_record)
        self._save_log()

        print("\n" + "="*60)
        print("[DRY RUN] SIMULATED TRADE EXECUTED")
        print("="*60)
        print(f"Ticket:     #{position.ticket}")
        print(f"Symbol:     {symbol}")
        print(f"Direction:  {direction}")
        print(f"Strategy:   {recommendation.strategy_name}")
        print(f"Grade:      {recommendation.signal.grade}")
        print(f"Confidence: {recommendation.signal.confidence:.0%}")
        print(f"Entry:      {fill_price:.5f}")
        print(f"Stop:       {recommendation.signal.stop_loss:.5f}")
        print(f"TP1 (1R):   {recommendation.signal.take_profit_1:.5f}")
        print(f"TP2 (2R):   {recommendation.signal.take_profit_2:.5f}")
        print(f"Risk:       ${risk_assignment.dollar_risk}")
        print(f"Volume:     {position_size['lots']:.2f} lots")
        print(f"R:R:        {recommendation.signal.risk_reward:.1f}")
        print("="*60 + "\n")

        return {'success': True, 'ticket': position.ticket, 'fill_price': fill_price}

    def simulate_price_movement(self, symbol: str) -> float:
        volatility = {
            'EURUSD': 0.0002, 'GBPUSD': 0.0003, 'AUDUSD': 0.0002,
            'NZDUSD': 0.0002, 'USDJPY': 0.02, 'USDCAD': 0.0002,
            'USDCHF': 0.0002, 'EURJPY': 0.03, 'GBPJPY': 0.04,
            'XAUUSD': 0.5, 'XAGUSD': 0.03
        }
        vol = volatility.get(symbol, 0.0002)
        return random.gauss(0, vol)

    def update_positions(self):
        for pos in list(self.positions):
            if pos.status != "open":
                continue
            price_move = self.simulate_price_movement(pos.symbol)
            new_price = pos.current_price + price_move
            pos.update_price(new_price)

            if pos.direction == 'BUY' and new_price <= pos.stop_loss:
                self._close_simulated_position(pos, new_price, 'stop_loss')
            elif pos.direction == 'SELL' and new_price >= pos.stop_loss:
                self._close_simulated_position(pos, new_price, 'stop_loss')
            elif pos.direction == 'BUY' and new_price >= pos.take_profit_2:
                self._close_simulated_position(pos, new_price, 'take_profit_2')
            elif pos.direction == 'SELL' and new_price <= pos.take_profit_2:
                self._close_simulated_position(pos, new_price, 'take_profit_2')

    def _close_simulated_position(self, pos, exit_price, reason):
        pos.status = "closed"
        pos.exit_price = exit_price
        pos.exit_reason = reason
        pos.exit_time = datetime.now().isoformat()
        pos.update_price(exit_price)
        self.daily_pnl += pos.unrealized_pnl
        self.closed_positions.append(pos)
        self.positions = [p for p in self.positions if p.ticket != pos.ticket]

        result = {
            'timestamp': datetime.now().isoformat(),
            'ticket': pos.ticket,
            'symbol': pos.symbol,
            'exit_price': round(exit_price, 5),
            'exit_reason': reason,
            'pnl': round(pos.unrealized_pnl, 2),
            'r_multiple': round(pos.r_multiple, 2),
        }
        self.trades_log.append(result)
        self._save_log()

        print(f"[DRY RUN] Position #{pos.ticket} {pos.symbol} CLOSED via {reason}")
        print(f"          P&L: ${pos.unrealized_pnl:+.2f} ({pos.r_multiple:+.1f}R)")

    def get_summary(self):
        total = len(self.closed_positions)
        wins = sum(1 for p in self.closed_positions if p.unrealized_pnl > 0)
        losses = sum(1 for p in self.closed_positions if p.unrealized_pnl < 0)
        return {
            'open_positions': len(self.positions),
            'closed_trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate': (wins / total * 100) if total > 0 else 0,
            'daily_pnl': round(self.daily_pnl, 2),
            'trades_today': self.trades_today,
            'avg_r': round(sum(p.r_multiple for p in self.closed_positions) / total, 2) if total > 0 else 0,
        }

    def print_summary(self):
        s = self.get_summary()
        print("\n" + "="*60)
        print("[DRY RUN] SESSION SUMMARY")
        print("="*60)
        print(f"Trades taken:    {s['trades_today']}")
        print(f"Closed trades:   {s['closed_trades']}")
        print(f"Wins:            {s['wins']}")
        print(f"Losses:          {s['losses']}")
        print(f"Win rate:        {s['win_rate']:.1f}%")
        print(f"Daily P&L:       ${s['daily_pnl']:+.2f}")
        print(f"Avg R:           {s['avg_r']:.2f}R")
        print(f"Open positions:  {s['open_positions']}")
        print("="*60 + "\n")

    def _save_log(self):
        with open(self.log_file, 'w') as f:
            json.dump(self.trades_log, f, indent=2)

    def emergency_close_all(self, reason: str):
        for pos in list(self.positions):
            self._close_simulated_position(pos, pos.current_price, f"emergency: {reason}")
        print(f"[DRY RUN] Emergency closed all: {reason}")