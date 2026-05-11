# strategies/supply_demand_zones.py
# Strategy 5: Supply and Demand Zones - Institutional levels

from typing import Dict, Optional
import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, StrategySignal
from core.mt5_bridge import MT5Bridge, get_bridge


class SupplyDemandZones(BaseStrategy):
    """
    Supply and Demand Zones Strategy

    Core concepts:
    - Supply zone: Aggressive selling, price drops fast (sell)
    - Demand zone: Aggressive buying, price rises fast (buy)
    - Fresh zones: Untested, high probability
    - Tested zones: Lower probability but still valid

    Best pairs: All
    Best session: Any
    """

    NAME = "supply_demand_zones"
    PREFERRED_SESSIONS = ['all', 'london', 'ny_overlap', 'pre_london']
    PREFERRED_PAIRS = ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY']
    BEST_REGIMES = ['ranging', 'accumulating']

    def __init__(self, bridge: Optional[MT5Bridge] = None):
        super().__init__(bridge)

    def detect_setup(self, symbol, direction, m15, h1, h4):
        """Detect supply/demand zone setup"""

        # 1. Find zones on H1
        zones = self._find_zones(h1, direction)

        # 2. Check if price near zone
        near_zone = self._price_near_zone(m15, zones, direction)

        # 3. Check zone freshness
        fresh = self._check_freshness(m15, zones, direction)

        # 4. Reaction confirmation
        reaction = self._check_reaction(m15, zones, direction)

        # Score
        score = self._calculate_score(zones, near_zone, fresh, reaction)
        grade = self._grade_from_score(score)

        if grade in ['C', 'D']:
            return self._empty_signal(symbol, f"S/D score too low: {score:.2f}")

        # Calculate levels
        entry, stop, tp1, tp2, stop_pips = self._calculate_levels(zones, m15, direction, symbol)

        risk_tier, risk_usd = self._assign_risk_tier(stop_pips, symbol)

        return StrategySignal(
            valid=True,
            strategy_name=self.NAME,
            symbol=symbol,
            direction='BUY' if direction == 'buy' else 'SELL',
            grade=grade,
            confidence=round(score, 2),
            entry_price=entry,
            entry_zone=(entry * 0.998, entry * 1.002),
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            stop_pips=stop_pips,
            risk_tier=risk_tier,
            recommended_risk_usd=risk_usd,
            reasons=[
                f"Zone: {'demand' if direction == 'buy' else 'supply'}",
                f"Fresh: {fresh}",
                f"Reaction: {reaction}",
                f"Proximity: {near_zone:.1f}%"
            ],
            warnings=["Zone tested before - lower probability"] if not fresh else [],
            detected_regime='ranging',
            htf_aligned=True,
        )

    def _find_zones(self, h1, direction):
        """Find supply/demand zones on H1"""
        zones = []

        # Look for strong candles that created imbalance
        for i in range(-20, -2):
            candle = h1.iloc[i]
            body = abs(candle['close'] - candle['open'])
            range_size = candle['high'] - candle['low']

            if range_size == 0:
                continue

            body_pct = body / range_size

            # Strong candle = body > 60% of range
            if body_pct > 0.6:
                if direction == 'buy' and candle['close'] > candle['open']:
                    # Demand zone: base of strong bullish candle
                    zone = {
                        'type': 'demand',
                        'base': candle['open'],
                        'top': candle['high'],
                        'bottom': candle['low'],
                        'strength': body_pct,
                        'index': i
                    }
                    zones.append(zone)

                elif direction == 'sell' and candle['close'] < candle['open']:
                    # Supply zone: top of strong bearish candle
                    zone = {
                        'type': 'supply',
                        'base': candle['open'],
                        'top': candle['high'],
                        'bottom': candle['low'],
                        'strength': body_pct,
                        'index': i
                    }
                    zones.append(zone)

        # Return strongest zone
        if zones:
            return max(zones, key=lambda z: z['strength'])

        return None

    def _price_near_zone(self, m15, zone, direction):
        """Check if current price is near the zone"""
        if zone is None:
            return 0.0

        current = m15['close'].iloc[-1]

        if direction == 'buy':
            # Price should be near or inside demand zone
            zone_top = zone['top']
            zone_bottom = zone['bottom']

            if zone_bottom <= current <= zone_top:
                return 1.0  # Inside zone
            elif current < zone_bottom:
                return max(0.0, 1.0 - abs(current - zone_bottom) / zone_bottom * 100)
            else:
                return 0.0
        else:
            # Price should be near or inside supply zone
            zone_top = zone['top']
            zone_bottom = zone['bottom']

            if zone_bottom <= current <= zone_top:
                return 1.0
            elif current > zone_top:
                return max(0.0, 1.0 - abs(current - zone_top) / zone_top * 100)
            else:
                return 0.0

    def _check_freshness(self, m15, zone, direction):
        """Check if zone has been tested since formation"""
        if zone is None:
            return False

        zone_index = zone['index']

        # Check candles after zone formation
        for i in range(zone_index + 1, 0):
            candle = m15.iloc[i]

            if direction == 'buy':
                # If price went below zone bottom, it's tested
                if candle['low'] < zone['bottom']:
                    return False
            else:
                # If price went above zone top, it's tested
                if candle['high'] > zone['top']:
                    return False

        return True

    def _check_reaction(self, m15, zone, direction):
        """Check for price reaction at zone (rejection candles)"""
        if zone is None:
            return 'none'

        recent = m15.tail(5)

        for i in range(len(recent)):
            candle = recent.iloc[i]

            if direction == 'buy':
                # Bullish reaction at demand
                if candle['low'] <= zone['top'] and candle['close'] > candle['open']:
                    return 'strong' if candle['close'] > zone['top'] else 'weak'
            else:
                # Bearish reaction at supply
                if candle['high'] >= zone['bottom'] and candle['close'] < candle['open']:
                    return 'strong' if candle['close'] < zone['bottom'] else 'weak'

        return 'none'

    def _calculate_score(self, zone, near_zone, fresh, reaction):
        score = 0.0

        if zone:
            score += 0.30
            score += zone['strength'] * 0.15

        score += near_zone * 0.25

        if fresh:
            score += 0.20

        if reaction == 'strong':
            score += 0.15
        elif reaction == 'weak':
            score += 0.08

        return min(1.0, score)

    def _calculate_levels(self, zone, m15, direction, symbol):
        current = m15['close'].iloc[-1]

        if zone:
            if direction == 'buy':
                entry = zone['base']
                stop = zone['bottom'] * 0.998
            else:
                entry = zone['base']
                stop = zone['top'] * 1.002
        else:
            entry = current
            atr = self._calculate_atr(m15)
            stop = current - atr * 1.5 if direction == 'buy' else current + atr * 1.5

        risk = abs(entry - stop)

        # Convert to pips
        if 'JPY' in symbol or 'XAU' in symbol or 'GOLD' in symbol:
            pip_size = 0.01 if 'JPY' in symbol else 0.1
        else:
            pip_size = 0.0001

        stop_pips = risk / pip_size

        # Targets: 1.5R and 2.5R
        tp1 = entry + risk * 1.5 if direction == 'buy' else entry - risk * 1.5
        tp2 = entry + risk * 2.5 if direction == 'buy' else entry - risk * 2.5

        return entry, stop, tp1, tp2, stop_pips

    def _calculate_atr(self, df, period=14):
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean().iloc[-1]
