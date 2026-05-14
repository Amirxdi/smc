#!/usr/bin/env python3
"""
Trendline Analyzer module for detecting trendline breakouts on 15-minute charts.
Detects support/resistance trendlines and notifies when price breaks through.
"""

import asyncio
from market import Market


def _find_swing_highs(candles, left_bars=3, right_bars=3):
    """
    Find swing high points in a list of candles.

    A swing high is a candle where the high is greater than
    the highs of the N candles to its left and N candles to its right.

    Args:
        candles (list): List of candle data [timestamp, open, high, low, close, volume]
        left_bars (int): Number of candles to check on the left
        right_bars (int): Number of candles to check on the right

    Returns:
        list: List of (index, high_price) tuples for each swing high
    """
    swings = []
    for i in range(left_bars, len(candles) - right_bars):
        current_high = candles[i][2]
        is_swing = True

        for j in range(i - left_bars, i + right_bars + 1):
            if i == j:
                continue
            if candles[j][2] >= current_high:
                is_swing = False
                break

        if is_swing:
            swings.append((i, current_high))

    return swings


def _find_swing_lows(candles, left_bars=3, right_bars=3):
    """
    Find swing low points in a list of candles.

    A swing low is a candle where the low is lower than
    the lows of the N candles to its left and N candles to its right.

    Args:
        candles (list): List of candle data [timestamp, open, high, low, close, volume]
        left_bars (int): Number of candles to check on the left
        right_bars (int): Number of candles to check on the right

    Returns:
        list: List of (index, low_price) tuples for each swing low
    """
    swings = []
    for i in range(left_bars, len(candles) - right_bars):
        current_low = candles[i][3]
        is_swing = True

        for j in range(i - left_bars, i + right_bars + 1):
            if i == j:
                continue
            if candles[j][3] <= current_low:
                is_swing = False
                break

        if is_swing:
            swings.append((i, current_low))

    return swings


def _calculate_trendline(p1_idx, p1_price, p2_idx, p2_price):
    """
    Calculate the slope and equation of a line through two points.

    Args:
        p1_idx (int): Index of the first point (x-coordinate)
        p1_price (float): Price at the first point (y-coordinate)
        p2_idx (int): Index of the second point (x-coordinate)
        p2_price (float): Price at the second point (y-coordinate)

    Returns:
        tuple: (slope, intercept) where y = slope * x + intercept
    """
    dx = p2_idx - p1_idx
    if dx == 0:
        return 0, p1_price
    slope = (p2_price - p1_price) / dx
    intercept = p1_price - slope * p1_idx
    return slope, intercept


def _get_trendline_price_at_current(slope, intercept, current_idx):
    """
    Calculate the trendline price at the current candle index.

    Args:
        slope (float): Slope of the trendline
        intercept (float): Y-intercept of the trendline
        current_idx (int): Current candle index

    Returns:
        float: Price value of the trendline at current_idx
    """
    return slope * current_idx + intercept


def detect_trendline_breakouts(candles):
    """
    Detect trendline breakouts from a list of 15m candles.

    Analyzes both:
    - Downtrend resistance lines (connecting lower highs)
    - Uptrend support lines (connecting higher lows)

    Args:
        candles (list): List of candle data [timestamp, open, high, low, close, volume]

    Returns:
        list: List of breakout dicts with keys:
            - type: 'resistance_breakout' or 'support_breakout'
            - symbol: 'N/A' (caller fills this)
            - current_price: current close price
            - trendline_price: trendline value at current candle
            - description: human-readable description
    """
    if len(candles) < 20:
        return []

    breakouts = []
    current_close = candles[-1][4]
    current_high = candles[-1][2]
    current_low = candles[-1][3]
    current_idx = len(candles) - 1

    # ─── Uptrend Support Line (higher lows) ─────────────────
    swing_lows = _find_swing_lows(candles, left_bars=2, right_bars=2)

    # Take the most recent 2-3 swing lows to form a support trendline
    if len(swing_lows) >= 3:
        recent_lows = swing_lows[-3:]

        # Use the two most recent lows to draw the line
        low1_idx, low1_price = recent_lows[-2]
        low2_idx, low2_price = recent_lows[-1]

        # Ensure the lows are at different positions
        if low1_idx != low2_idx and low1_price <= low2_price:
            slope, intercept = _calculate_trendline(
                low1_idx, low1_price, low2_idx, low2_price
            )
            trendline_price = _get_trendline_price_at_current(
                slope, intercept, current_idx
            )

            # Check if price broke BELOW the support trendline
            # (current low is significantly below the trendline)
            if slope >= 0 and current_low < trendline_price * 0.998:
                breakouts.append({
                    "type": "support_breakout",
                    "current_price": current_close,
                    "trendline_price": trendline_price,
                    "description": (
                        f"📉 <b>Support Breakout (Uptrend)</b>\n"
                        f"   Price broke below the uptrend support line!\n"
                        f"   Support trendline: <code>{trendline_price:.8f}</code>\n"
                        f"   Current low: <code>{current_low:.8f}</code>\n"
                        f"   Bearish signal — potential reversal to downside."
                    ),
                })

    # ─── Downtrend Resistance Line (lower highs) ────────────
    swing_highs = _find_swing_highs(candles, left_bars=2, right_bars=2)

    if len(swing_highs) >= 3:
        recent_highs = swing_highs[-3:]

        high1_idx, high1_price = recent_highs[-2]
        high2_idx, high2_price = recent_highs[-1]

        if high1_idx != high2_idx and high1_price >= high2_price:
            slope, intercept = _calculate_trendline(
                high1_idx, high1_price, high2_idx, high2_price
            )
            trendline_price = _get_trendline_price_at_current(
                slope, intercept, current_idx
            )

            # Check if price broke ABOVE the resistance trendline
            # (current high is significantly above the trendline)
            if slope <= 0 and current_high > trendline_price * 1.002:
                breakouts.append({
                    "type": "resistance_breakout",
                    "current_price": current_close,
                    "trendline_price": trendline_price,
                    "description": (
                        f"📈 <b>Resistance Breakout (Downtrend)</b>\n"
                        f"   Price broke above the downtrend resistance line!\n"
                        f"   Resistance trendline: <code>{trendline_price:.8f}</code>\n"
                        f"   Current high: <code>{current_high:.8f}</code>\n"
                        f"   Bullish signal — potential trend reversal to upside."
                    ),
                })

    return breakouts


async def scan_trendline_breakouts(symbols, market):
    """
    Scan all symbols for trendline breakouts.

    Args:
        symbols (list): List of trading pair symbols
        market (Market): Market instance for fetching data

    Returns:
        list: List of breakout dicts with symbol info
    """
    results = []

    print(f"\nScanning {len(symbols)} symbols for trendline breakouts...")

    batch_size = 10
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        for symbol in batch:
            candles = await market.fetch_15m_candles(symbol, limit=100)
            if len(candles) < 20:
                continue

            breakouts = detect_trendline_breakouts(candles)
            for b in breakouts:
                b["symbol"] = symbol
                results.append(b)

        if i + batch_size < len(symbols):
            await asyncio.sleep(1)

    return results


def format_trendline_results(breakouts):
    """
    Format trendline breakout results into a Telegram message.

    Args:
        breakouts (list): List of breakout dicts

    Returns:
        str: Formatted message string
    """
    if not breakouts:
        return (
            "📊 <b>Trendline Breakout Scanner</b>\n\n"
            "No trendline breakouts detected on the 15-minute chart.\n"
            "Try again later when the market develops clearer trends."
        )

    lines = [
        "📊 <b>Trendline Breakout Scanner — Results</b>",
        f"<i>15-minute chart analysis</i>\n",
    ]

    for b in breakouts:
        lines.append(f"🔹 <b>{b['symbol']}</b>")
        lines.append(b["description"])
        lines.append("")

    lines.append("Use /trendline to run again.")
    return "\n".join(lines).strip()

