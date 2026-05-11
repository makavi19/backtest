# agents/feedback/trade_logger.py
# SQLite database logging for all trades

import sqlite3
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path


@dataclass
class TradeRecord:
    """Complete trade record for database"""
    # Identification
    id: Optional[int] = None
    ticket: Optional[int] = None
    timestamp_utc: Optional[str] = None
    timestamp_ist: Optional[str] = None
    
    # Trade details
    symbol: Optional[str] = None
    direction: Optional[str] = None  # 'buy' or 'sell'
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    
    # Position sizing
    lots: Optional[float] = None
    risk_usd: Optional[float] = None
    target_usd: Optional[float] = None
    
    # Levels
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None
    
    # Outcome
    profit_usd: Optional[float] = None
    pips: Optional[float] = None
    r_multiple: Optional[float] = None
    exit_reason: Optional[str] = None  # 'tp1', 'tp2', 'sl', 'manual', 'time'
    
    # Context
    session: Optional[str] = None
    strategy: Optional[str] = None
    grade: Optional[str] = None
    dxy_bias: Optional[str] = None
    setup_quality: Optional[int] = None
    
    # Screenshots and state
    screenshot_entry: Optional[str] = None
    screenshot_exit: Optional[str] = None
    mt5_state: Optional[str] = None  # JSON
    
    # Review
    reviewed: bool = False
    notes: Optional[str] = None
    tags: Optional[str] = None  # Comma-separated


class TradeLogger:
    """
    SQLite database for all trade records
    
    Enables post-trade analysis and strategy improvement
    """
    
    DB_PATH = "data/journal.db"
    
    def __init__(self):
        self._ensure_dir()
        self.conn = sqlite3.connect(self.DB_PATH)
        self._create_tables()
    
    def _ensure_dir(self):
        """Ensure data directory exists"""
        Path(self.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    def _create_tables(self):
        """Initialize database schema"""
        cursor = self.conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket INTEGER UNIQUE,
                timestamp_utc TEXT,
                timestamp_ist TEXT,
                symbol TEXT,
                direction TEXT,
                entry_price REAL,
                exit_price REAL,
                lots REAL,
                risk_usd REAL,
                target_usd REAL,
                stop_loss REAL,
                take_profit_1 REAL,
                take_profit_2 REAL,
                profit_usd REAL,
                pips REAL,
                r_multiple REAL,
                exit_reason TEXT,
                session TEXT,
                strategy TEXT,
                grade TEXT,
                dxy_bias TEXT,
                setup_quality INTEGER,
                screenshot_entry TEXT,
                screenshot_exit TEXT,
                mt5_state TEXT,
                reviewed BOOLEAN DEFAULT 0,
                notes TEXT,
                tags TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trade_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                event_time TEXT,
                event_type TEXT,
                details TEXT,
                FOREIGN KEY (trade_id) REFERENCES trades (id)
            )
        ''')
        
        self.conn.commit()
    
    def log_entry(self, record: TradeRecord) -> int:
        """Log new trade entry, return ID"""
        cursor = self.conn.cursor()
        
        # Set timestamps if empty
        if not record.timestamp_utc:
            record.timestamp_utc = datetime.utcnow().isoformat()
        if not record.timestamp_ist:
            from core.session_manager import format_ist_time
            record.timestamp_ist = format_ist_time()
        
        # Convert to dict, exclude None ID
        data = asdict(record)
        data.pop('id', None)
        
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?' for _ in data])
        
        cursor.execute(
            f"INSERT INTO trades ({columns}) VALUES ({placeholders})",
            list(data.values())
        )
        
        self.conn.commit()
        return cursor.lastrowid
    
    def log_exit(self, ticket: int, updates: Dict) -> bool:
        """Update trade with exit information"""
        cursor = self.conn.cursor()
        
        # Find trade
        cursor.execute("SELECT id FROM trades WHERE ticket = ?", (ticket,))
        row = cursor.fetchone()
        
        if not row:
            return False
        
        # Build update
        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        values = list(updates.values()) + [ticket]
        
        cursor.execute(
            f"UPDATE trades SET {set_clause} WHERE ticket = ?",
            values
        )
        
        self.conn.commit()
        return cursor.rowcount > 0
    
    def add_event(self, trade_id: int, event_type: str, details: Dict):
        """Add event to trade timeline"""
        cursor = self.conn.cursor()
        
        cursor.execute(
            "INSERT INTO trade_events (trade_id, event_time, event_type, details) VALUES (?, ?, ?, ?)",
            (
                trade_id,
                datetime.utcnow().isoformat(),
                event_type,
                json.dumps(details)
            )
        )
        
        self.conn.commit()
    
    def get_open_trades(self) -> List[TradeRecord]:
        """Get all trades without exit price"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT * FROM trades 
            WHERE exit_price IS NULL 
            ORDER BY timestamp_utc DESC
        """)
        
        columns = [desc[0] for desc in cursor.description]
        trades = []
        
        for row in cursor.fetchall():
            trade_dict = dict(zip(columns, row))
            trades.append(TradeRecord(**trade_dict))
        
        return trades
    
    def get_trade_by_ticket(self, ticket: int) -> Optional[TradeRecord]:
        """Get specific trade by MT5 ticket"""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT * FROM trades WHERE ticket = ?", (ticket,))
        row = cursor.fetchone()
        
        if not row:
            return None
        
        columns = [desc[0] for desc in cursor.description]
        return TradeRecord(**dict(zip(columns, row)))
    
    def get_daily_pnl(self, date_str: Optional[str] = None) -> float:
        """Calculate realized P&L for date"""
        if date_str is None:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT COALESCE(SUM(profit_usd), 0) 
            FROM trades 
            WHERE DATE(timestamp_utc) = ? AND exit_price IS NOT NULL
        """, (date_str,))
        
        return cursor.fetchone()[0] or 0.0
    
    def get_unrealized_pnl(self) -> float:
        """Sum of open position profits (from MT5)"""
        # This requires live MT5 data, placeholder
        return 0.0
    
    def get_trade_count(self, date_str: Optional[str] = None) -> int:
        """Count trades for date"""
        if date_str is None:
            date_str = datetime.utcnow().strftime('%Y-%m-%d')
        
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM trades WHERE DATE(timestamp_utc) = ?
        """, (date_str,))
        
        return cursor.fetchone()[0]
    
    def get_statistics(self, days: int = 30) -> Dict:
        """Calculate performance statistics"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN profit_usd > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN profit_usd < 0 THEN 1 ELSE 0 END) as losses,
                SUM(profit_usd) as net_pnl,
                AVG(profit_usd) as avg_pnl,
                AVG(CASE WHEN profit_usd > 0 THEN profit_usd END) as avg_win,
                AVG(CASE WHEN profit_usd < 0 THEN profit_usd END) as avg_loss,
                AVG(r_multiple) as avg_r
            FROM trades 
            WHERE timestamp_utc >= date('now', '-{} days')
            AND exit_price IS NOT NULL
        """.format(days))
        
        row = cursor.fetchone()
        if not row or row[0] == 0:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'net_pnl': 0,
                'profit_factor': 0,
            }
        
        total, wins, losses, net_pnl, avg_pnl, avg_win, avg_loss, avg_r = row
        
        win_rate = wins / total if total > 0 else 0
        profit_factor = abs(avg_win * wins) / abs(avg_loss * losses) if (losses or avg_loss) != 0 else 0
        
        return {
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate * 100, 2),
            'net_pnl': round(net_pnl, 2),
            'avg_pnl': round(avg_pnl or 0, 2),
            'avg_win': round(avg_win or 0, 2),
            'avg_loss': round(avg_loss or 0, 2),
            'profit_factor': round(profit_factor, 2),
            'avg_r': round(avg_r or 0, 2),
        }
    
    def close(self):
        """Clean shutdown"""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False