# Eleven Pairs Institutional Backtesting Framework

## Overview
This is a production-grade, modular backtesting framework designed for the Eleven Pairs architecture. It simulates realistic market conditions including spread, slippage, and capital limits, while running multiple pairs simultaneously in a portfolio configuration.

Importantly, it **reuses the exact same strategy logic** (`base_strategy.py`, `strategy_selector.py`) as the live bot. There is no isolated indicator-based test environment — if a setup is detected in backtesting, it is exactly how the live bot would detect it.

## Folder Structure
```
backtesting/
│
├── config/              # YAML or JSON config files for backtests
├── data/                # Place your CSV data files here
├── reports/             # Generated HTML tearsheets and trade logs go here
├── charts/              # Saved equity curves and analysis charts
├── logs/                # Backtesting execution logs
│
├── backtest_runner.py   # Primary Entry Point
├── data_loader.py       # Handles robust CSV loading into Pandas & Backtrader
├── portfolio_engine.py  # Configures Backtrader environment (leverage, commission)
├── strategy_adapter.py  # Bridges Backtrader bar feeds into the Eleven Pairs Pandas logic
├── metrics.py           # Calculates institutional metrics (Sharpe, Sortino, etc)
├── report_generator.py  # Generates quantstats tear sheets
├── optimizer.py         # Grid search optimization for parameters
└── walk_forward.py      # Rolling out-of-sample validation to prevent curve-fitting
```

## How to Place Historical Data

The system expects CSV files in `backtesting/data/` with the format:
`{SYMBOL}_{TIMEFRAME}.csv`
Example: `EURUSD_M15.csv`

**Required CSV Format:**
```csv
datetime,open,high,low,close,volume
2015-01-01 09:15:00,1.2045,1.2050,1.2038,1.2048,1200
```
*Note: Ensure `datetime` parses properly and timezone logic aligns with your live trading session definitions.*

## How to Run Backtests

You can run backtests either through the main bot entry point or directly via the runner:

### Single/Specific Pairs
```bash
# Via backtest runner
python backtesting/backtest_runner.py --pairs EURUSD,XAUUSD --start-date 2020-01-01 --end-date 2023-01-01 --report

# Via main.py
python main.py --mode backtest --pairs EURUSD,XAUUSD --report
```

### Portfolio Testing (All Available Data)
```bash
python backtesting/backtest_runner.py --all-pairs --years 10 --report
```

## Optimization & Walk-Forward Testing

**Optimization (Grid Search):**
Find optimal parameters for your specific strategies across different pairs.
```bash
python backtesting/backtest_runner.py --pairs EURUSD --optimize
```
*Warning: Over-optimizing parameters can lead to curve-fitting. Always validate.*

**Walk-Forward Testing (Rolling Out-of-Sample):**
The gold standard for ensuring strategies generalize beyond the training data.
```bash
python backtesting/backtest_runner.py --pairs EURUSD --walk-forward
```

## How to Interpret Metrics

When you run with `--report`, an HTML tearsheet is generated in `backtesting/reports/`.
Key institutional metrics to watch:
- **Net Profit**: Total dollar profit (after simulated commissions).
- **Sharpe Ratio**: Risk-adjusted return. Institutional grade is typically > 1.0.
- **Sortino Ratio**: Similar to Sharpe, but only penalizes downside volatility.
- **Max Drawdown**: The largest peak-to-trough drop in equity. A critical metric for retail risk.
- **Win Rate**: Percentage of trades that were profitable.
- **CAGR**: Compound Annual Growth Rate.

## Future Extensibility
This framework is built as a foundation for future AI layers:
- **Liquidity Intelligence**: Hooks are ready in `StrategyAdapter` to inject liquidity metrics.
- **AI Scoring**: `StrategySignal` supports continuous confidence scoring, making it trivial to swap rule-based grading with an XGBoost or LightGBM model.
- **Reinforcement Learning**: The portfolio engine can be easily wrapped into a Gym environment for RL agents.
