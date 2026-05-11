import pandas as pd
import numpy as np
import quantstats as qs
import empyrical
from typing import Dict, Any, List

class Metrics:
    """
    Computes institutional-grade metrics for backtest results.
    """

    @staticmethod
    def compute_all(returns: pd.Series, risk_free_rate: float = 0.0) -> Dict[str, Any]:
        """
        Computes all core performance metrics.
        Returns expects a daily or higher frequency pandas Series of percentage returns.
        """
        if returns.empty:
            return {}

        metrics = {
            "Total Return": empyrical.cum_returns_final(returns),
            "CAGR": empyrical.cagr(returns),
            "Sharpe Ratio": empyrical.sharpe_ratio(returns, risk_free=risk_free_rate),
            "Sortino Ratio": empyrical.sortino_ratio(returns, required_return=risk_free_rate),
            "Max Drawdown": empyrical.max_drawdown(returns),
            "Calmar Ratio": empyrical.calmar_ratio(returns),
            "Annual Volatility": empyrical.annual_volatility(returns),
            "Omega Ratio": empyrical.omega_ratio(returns, risk_free=risk_free_rate),
            "Tail Ratio": empyrical.tail_ratio(returns),
            "Win Rate": Metrics.calculate_win_rate(returns)
        }
        return metrics

    @staticmethod
    def calculate_win_rate(returns: pd.Series) -> float:
        wins = len(returns[returns > 0])
        losses = len(returns[returns < 0])
        total = wins + losses
        if total == 0:
            return 0.0
        return wins / total

    @staticmethod
    def extract_returns_from_analyzer(analyzer_returns) -> pd.Series:
        """Converts backtrader TimeReturn analyzer dict to pandas Series."""
        returns_dict = analyzer_returns.get_analysis()
        s = pd.Series(returns_dict)
        s.index = pd.to_datetime(s.index)
        return s
