#!/usr/bin/env python3
"""
trendline_analyzer.py — Detects trendline breakouts on 15m charts.

Updated to include the `exchange` key in breakout dicts for consistent
Telegram formatting.  Signature otherwise unchanged.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


def _find_swing_highs(candles, left_bars=3, right_bars=3):
    """Find swing high points."""
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
    """Find swing low points."""
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
    dx = p2_idx - p1_idx
    if dx == 0:
        return 0, p1_price
    slope = (p2_price - p1_price) / dx
    intercept = p1_price - slope * p1_idx
    return slope, intercept


def _get_trendline_price_at_current(slope, intercept, current_idx):
    return slope * current_idx + intercept


def detect_trendline_breakouts(candles, exchange=""):
    """
    Detect trendline breakouts from a list of 15m candles.

    Returns list of breakout dicts with keys:
        type, symbol, current_price, trendline_price, description, exchange
    """
    if len(candles) < 20:
        return []

    breakouts = []
    current_close = candles[-1][4]
    current_high = candles[-1][2]
    current_low = candles[-1][3]
    current_idx = len(candles) - 1

    # Uptrend support line (higher lows)
    swing_lows = _find_swing_lows(candles, left_bars=2, right_bars=2)
    if len(swing_lows) >= 3:
        recent_lows = swing_lows[-3:]
        low1_idx, low1_price = recent_lows[-2]
        low2_idx, low2_price = recent_lows[-1]
        if low1_idx != low2_idx and low1_price <= low2_price:
            slope, intercept = _calculate_trendline(low1_idx, low1_price, low2_idx, low2_price)
            trendline_price = _get_trendline_price_at_current(slope, intercept, current_idx)
            if slope >= 0 and current_low < trendline_price * 0.998:
                breakouts.append({
                    "type": "support_breakout",
                    "current_price": current_close,
                    "trendline_price": trendline_price,
                    "exchange": exchange,
                    "description": (
                        f"📉 <b>Support Breakout (Uptrend)</b>\n"
                        f"   Price broke below the uptrend support line!\n"
                        f"   Trendline: <code>{trendline_price:.8f}</code>\n"
                        f"   Current low: <code>{current_low:.8f}</code>\n"
                        f"   Bearish signal — potential downside reversal."
                    ),
                })

    # Downtrend resistance line (lower highs)
    swing_highs = _find_swing_highs(candles, left_bars=2, right_bars=2)
    if len(swing_highs) >= 3:
        recent_highs = swing_highs[-3:]
        high1_idx, high1_price = recent_highs[-2]
        high2_idx, high2_price = recent_highs[-1]
        if high1_idx != high2_idx and high1_price >= high2_price:
            slope, intercept = _calculate_trendline(high1_idx, high1_price, high2_idx, high2_price)
            trendline_price = _get_trendline_price_at_current(slope, intercept, current_idx)
            if slope <= 0 and current_high > trendline_price * 1.002:
                breakouts.append({
                    "type": "resistance_breakout",
                    "current_price": current_close,
                    "trendline_price": trendline_price,
                    "exchange": exchange,
                    "description": (
                        f"📈 <b>Resistance Breakout (Downtrend)</b>\n"
                        f"   Price broke above the downtrend resistance line!\n"
                        f"   Trendline: <code>{trendline_price:.8f}</code>\n"
                        f"   Current high: <code>{current_high:.8f}</code>\n"
                        f"   Bullish signal — potential upside reversal."
                    ),
                })

    return breakouts


async def scan_trendline_breakouts(symbols, market):
    """Scan all symbols for trendline breakouts."""
    results = []
    logger.info("Scanning %d symbols for trendline breakouts…", len(symbols))

    BATCH = 10
    for i in range(0, len(symbols), BATCH):
        batch = symbols[i:i + BATCH]
        for symbol in batch:
            try:
                candles = await market.fetch_15m_candles(symbol, limit=100)
                if len(candles) < 20:
                    continue
                breakouts = detect_trendline_breakouts(candles, exchange=market.label)
                for b in breakouts:
                    b["symbol"] = symbol
                    results.append(b)
            except Exception as e:
                logger.error("Trendline error %s: %s", symbol, e)
        if i + BATCH < len(symbols):
            await asyncio.sleep(1)

    return results


def format_trendline_results(breakouts):
    """Format trendline breakouts into a Telegram message."""
    if not breakouts:
        return (
            "📊 <b>Trendline Breakout Scanner</b>\n\n"
            "No trendline breakouts detected on the 15-minute chart."
        )

    lines = [
        "📊 <b>Trendline Breakout Scanner — Results</b>",
        "<i>15-minute chart analysis</i>\n",
    ]

    for b in breakouts:
        ex = b.get("exchange", "")
        ex_tag = f"[{ex}] " if ex else ""
        lines.append(f"🔹 <b>{ex_tag}{b['symbol']}</b>")
        lines.append(b["description"])
        lines.append("")

    lines.append("Use /trendline to run again.")
    return "\n".join(lines).strip()