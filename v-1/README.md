# Eleven Pairs Trading Bot

## Overview
Intelligent multi-strategy trading bot for MetaTrader 5 (XM broker).

**Core Philosophy: Option B+**
- 1-4 trades/day max
- Dynamic risk: $4 tight / $7 normal / $10 wide
- A/B grade only
- Session focus: 10:30 AM - 11:50 PM IST
- Hard stops: $60 profit / $15 loss

## The 9 Strategies
| # | Strategy | Best Regime | Best Pairs | Best Session |
|---|----------|-------------|------------|--------------|
| 1 | ICT OB + FVG | All | EURUSD, XAUUSD | London |
| 2 | SMC Structure | Trending/Accum | EURUSD, GBPUSD | London/NY |
| 3 | London Breakout | Volatile | GBP pairs, EURJPY | London Open |
| 4 | Wyckoff AMD | Accumulating | XAUUSD, XAGUSD | All |
| 5 | Supply/Demand | Ranging | All | Any |
| 6 | Bollinger Reversion | Ranging | JPY pairs | Tokyo/London |
| 7 | EMA Trend | Trending | EURUSD, GBPUSD | NY |
| 8 | Momentum Breakout | Volatile | All | News/Events |
| 9 | CRT Multi-TF | All | EURUSD, GBPUSD, XAUUSD | Session Opens |

## How It Works
1. Regime Detector analyzes market (ADX, Bollinger, ATR, Volume)
2. All 9 strategies scan their preferred pairs
3. Strategy Selector scores each signal (Regime 40% + Quality 25% + Session 20% + Pair 15%)
4. Sheriff validates (correlation, risk budget, trade count)
5. Executioner sends order to MT5

## Daily Flow
- 10:30 AM: Boot, analyze, wait
- 12:30 PM: London Prime — full deployment
- 17:30 PM: NY Overlap — selective
- 21:30 PM: NY Solo — exit only
- 23:50 PM: Hard close, Excel export

## Risk Tiers
| Tier | Risk | Stop | Pairs | Grade |
|------|------|------|-------|-------|
| Tight | $4 | 8-12 pips | Gold, EURUSD, GBPUSD | A |
| Normal | $7 | 15-20 pips | EURJPY, AUDUSD, USDCAD | A/B |
| Wide | $10 | 25-35 pips | JPY pairs, NZDUSD, XAGUSD | A only |

## Run
```cmd
cd "E:\trading dashboard\Eleven_Pairs_Project\v-1"
python main.py