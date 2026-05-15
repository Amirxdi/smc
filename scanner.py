#!/usr/bin/env python3
"""
Scanner module for detecting untouched level touches and liquidity sweeps
across Daily and 4H timeframes.

Uses LevelTracker to remember levels between scan cycles.
"""

import asyncio
import logging
from ai_analyzer import AIAnalyzer
from level_tracker import LevelTracker, format_level_touch_events, format_sweep_events


logger = logging.getLogger(__name__)


# Global level tracker — persists across scan cycles
GLOBAL_TRACKER = LevelTracker()


async def scan_symbol_levels(symbol, market, tracker=None, exchange=""):
    """
    Scan a single symbol for untouched levels on 1d and 4h timeframes,
    then check if the latest candle has touched/swept any tracked levels.

    Args:
        symbol (str): Trading pair (e.g. 'BTC/USDT')
        market (Market): Market instance
        tracker (LevelTracker): Level tracker to use (defaults to global)
        exchange (str): Exchange label

    Returns:
        dict: {
            'touches': list of touch events,
            'sweeps': list of LiquiditySweep objects,
            'new_levels_1d': count of new 1d levels added,
            'new_levels_4h': count of new 4h levels added,
            'total_tracked': total levels being tracked
        }
    """
    if tracker is None:
        tracker = GLOBAL_TRACKER

    result = {
        "touches": [],
        "sweeps": [],
        "new_levels_1d": 0,
        "new_levels_4h": 0,
        "total_tracked": 0,
    }

    # ─── Fetch Daily candles ───────────────────────────
    daily_candles = await market.fetch_1d_candles(symbol, limit=50)
    current_1d = daily_candles[-1] if daily_candles and len(daily_candles) >= 1 else None
    if len(daily_candles) >= 10:
        # Find and add new 1d swing levels
        new_1d = tracker.find_untouched_swing_levels(
            daily_candles[:-1],  # exclude latest (may be forming)
            symbol=symbol,
            timeframe="1d",
            exchange=exchange,
        )
        result["new_levels_1d"] = len(new_1d)

        # Check for touches on 1d levels using the latest candle
        if current_1d:
            touches_1d = tracker.check_touches(current_1d, symbol=symbol)
            result["touches"].extend(touches_1d)

            sweeps_1d = tracker.check_liquidity_sweeps(current_1d, symbol=symbol)
            result["sweeps"].extend(sweeps_1d)

    # ─── Fetch 4H candles ─────────────────────────────
    fourh_candles = await market.fetch_4h_candles(symbol, limit=50)
    current_4h = fourh_candles[-1] if fourh_candles and len(fourh_candles) >= 1 else None
    if len(fourh_candles) >= 10:
        # Find and add new 4h swing levels
        new_4h = tracker.find_untouched_swing_levels(
            fourh_candles[:-1],  # exclude latest
            symbol=symbol,
            timeframe="4h",
            exchange=exchange,
        )
        result["new_levels_4h"] = len(new_4h)

        # Check for touches on 4h levels
        if current_4h:
            touches_4h = tracker.check_touches(current_4h, symbol=symbol)
            result["touches"].extend(touches_4h)

            sweeps_4h = tracker.check_liquidity_sweeps(current_4h, symbol=symbol)
            result["sweeps"].extend(sweeps_4h)

    # ─── Clean old levels ──────────────────────────────
    tracker.clear_old_levels(max_age_hours=72)

    result["total_tracked"] = tracker.total_levels
    return result


async def scan_all_symbols(symbols, market, tracker=None, exchange=""):
    """
    Scan all symbols for untouched level touches and sweeps.

    Args:
        symbols (list): List of trading pairs
        market (Market): Market instance
        tracker (LevelTracker): Tracker instance
        exchange (str): Exchange label

    Returns:
        dict: Aggregated results across all symbols
    """
    if tracker is None:
        tracker = GLOBAL_TRACKER

    all_touches = []
    all_sweeps = []
    total_new_1d = 0
    total_new_4h = 0
    symbols_scanned = 0

    print(f"\n🔍 Scanning {len(symbols)} symbols for untouched levels...")
    print(f"   📊 Currently tracking {tracker.total_levels} levels")

    batch_size = 10
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        tasks = [
            scan_symbol_levels(symbol, market, tracker, exchange)
            for symbol in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, Exception):
                logger.error("Symbol scan error: %s", r)
                continue
            all_touches.extend(r["touches"])
            all_sweeps.extend(r["sweeps"])
            total_new_1d += r["new_levels_1d"]
            total_new_4h += r["new_levels_4h"]
            symbols_scanned += 1

        if i + batch_size < len(symbols):
            await asyncio.sleep(1)

    print(f"   ✅ Scanned {symbols_scanned} symbols")
    print(f"   🆕 New 1D levels: {total_new_1d} | New 4H levels: {total_new_4h}")
    print(f"   👆 Touches: {len(all_touches)} | Sweeps: {len(all_sweeps)}")
    print(f"   📊 Total tracked: {tracker.total_levels} levels")

    return {
        "touches": all_touches,
        "sweeps": all_sweeps,
        "new_levels_1d": total_new_1d,
        "new_levels_4h": total_new_4h,
        "total_tracked": tracker.total_levels,
    }