#!/usr/bin/env python3
"""
Level Tracker — remembers untouched swing highs/lows across scan cycles.

Each Level represents an important price level that price has NOT touched yet.
Levels are stored in memory and removed once touched or swept.

Also detects liquidity sweeps (false breakouts).
"""

from datetime import datetime


class Level:
    """
    A single price level (swing high or swing low) that has NOT been touched yet.

    Attributes:
        symbol (str): Trading pair (e.g. 'BTC/USDT')
        timeframe (str): '1d' or '4h'
        level_type (str): 'high' or 'low'
        price (float): The price of the level
        candle_time (int): Timestamp when the candle that formed this level closed
        created_at (float): When this level was added to the tracker
        exchange (str): Exchange label (e.g. 'Bybit')
        is_live (bool): True = formed by current forming candle, False = completed candle
    """

    def __init__(self, symbol, timeframe, level_type, price, candle_time, exchange="", is_live=False):
        self.symbol = symbol
        self.timeframe = timeframe
        self.level_type = level_type  # 'high' or 'low'
        self.price = price
        self.candle_time = candle_time
        self.created_at = datetime.now().timestamp()
        self.exchange = exchange
        self.is_live = is_live

    def key(self):
        """Unique key for deduplication."""
        return f"{self.symbol}|{self.timeframe}|{self.level_type}|{self.price:.8f}"

    def __repr__(self):
        return (
            f"<Level {self.symbol} {self.timeframe} "
            f"{'🔺' if self.level_type == 'high' else '🔻'}{self.price:.8f}>"
        )


class LiquiditySweep:
    """
    Represents a detected liquidity sweep event.

    - Bearish sweep: price wicks above a high, then closes below it
    - Bullish sweep: price wicks below a low, then closes above it
    """

    def __init__(self, symbol, timeframe, sweep_type, level_price, wick_price, close_price, exchange=""):
        self.symbol = symbol
        self.timeframe = timeframe
        self.sweep_type = sweep_type  # 'bearish' or 'bullish'
        self.level_price = level_price
        self.wick_price = wick_price
        self.close_price = close_price
        self.exchange = exchange
        self.timestamp = datetime.now().timestamp()

    def __repr__(self):
        direction = "🔻 Bearish" if self.sweep_type == "bearish" else "🔺 Bullish"
        return (
            f"<{direction} Sweep {self.symbol} {self.timeframe} "
            f"level={self.level_price:.8f} wick={self.wick_price:.8f}>"
        )


class LevelTracker:
    """
    In-memory store of untouched price levels and logic to detect touches/sweeps.

    How it works:
    1. On each scan, we fetch candles for a symbol.
    2. We extract swing highs and swing lows from the candle data.
    3. We check if current price has touched or swept any tracked levels.
    4. Touched levels are removed from memory.
    5. New swing levels are added (if not already tracked).
    """

    def __init__(self):
        # { key: Level }
        self._levels = {}
        # stats
        self._touch_count = 0

    @property
    def total_levels(self):
        return len(self._levels)

    def get_all_levels(self):
        """Return all tracked levels as a list."""
        return list(self._levels.values())

    def add_level(self, level):
        """Add a level if it's not already tracked."""
        k = level.key()
        if k not in self._levels:
            self._levels[k] = level

    def level_exists(self, symbol, timeframe, level_type, price):
        """Check if a level with these exact params is already tracked."""
        k = f"{symbol}|{timeframe}|{level_type}|{price:.8f}"
        return k in self._levels

    def find_untouched_swing_levels(self, candles, symbol="", timeframe="4h", exchange=""):
        """
        Find swing highs and lows from candle data that are NOT yet tracked.

        Args:
            candles (list): List of [timestamp, open, high, low, close, volume]
            symbol (str): Trading pair symbol
            timeframe (str): '1d' or '4h'
            exchange (str): Exchange label

        Returns:
            list[Level]: Newly discovered untracked levels
        """
        if len(candles) < 10:
            return []

        new_levels = []

        # ---------- Swing HIGH detection ----------
        for i in range(2, len(candles) - 2):
            high = candles[i][2]
            # Check: is it a local high?
            left_ok = candles[i - 1][2] < high and candles[i - 2][2] < high
            right_ok = candles[i + 1][2] < high and candles[i + 2][2] < high
            if left_ok and right_ok:
                if not self.level_exists(symbol, timeframe, "high", high):
                    level = Level(
                        symbol=symbol,
                        timeframe=timeframe,
                        level_type="high",
                        price=high,
                        candle_time=candles[i][0],
                        exchange=exchange,
                        is_live=False,
                    )
                    new_levels.append(level)
                    self.add_level(level)

        # ---------- Swing LOW detection ----------
        for i in range(2, len(candles) - 2):
            low = candles[i][3]
            left_ok = candles[i - 1][3] > low and candles[i - 2][3] > low
            right_ok = candles[i + 1][3] > low and candles[i + 2][3] > low
            if left_ok and right_ok:
                if not self.level_exists(symbol, timeframe, "low", low):
                    level = Level(
                        symbol=symbol,
                        timeframe=timeframe,
                        level_type="low",
                        price=low,
                        candle_time=candles[i][0],
                        exchange=exchange,
                        is_live=False,
                    )
                    new_levels.append(level)
                    self.add_level(level)

        return new_levels

    def check_touches(self, current_candle, symbol=None, tolerance=0.001):
        """
        Check if the current candle has touched any tracked levels.

        A touch means price wick or close crossed the level.

        Args:
            current_candle (list): Latest candle [timestamp, open, high, low, close, volume]
            symbol (str): Symbol to filter levels by (defaults to _symbol_hint for backward compat)
            tolerance (float): Fractional tolerance for matching

        Returns:
            list[dict]: Touched level events with keys:
                - symbol, timeframe, level_type, level_price, current_price, exchange
        """
        touches = []
        if not current_candle or len(current_candle) < 5:
            return touches

        current_high = current_candle[2]
        current_low = current_candle[3]
        current_close = current_candle[4]

        keys_to_remove = []

        target_symbol = symbol if symbol is not None else getattr(self, "_symbol_hint", None)

        for k, level in self._levels.items():
            if level.symbol != target_symbol:
                continue

            if level.level_type == "high":
                # Price touched/swept this high?
                if current_high >= level.price * (1 - tolerance):
                    touches.append({
                        "symbol": level.symbol,
                        "timeframe": level.timeframe,
                        "level_type": "high",
                        "level_price": level.price,
                        "current_high": current_high,
                        "current_close": current_close,
                        "exchange": level.exchange,
                        "message": (
                            f"🔺 <b>Level Touched</b> [{level.exchange}] {level.symbol}\n"
                            f"   Timeframe: {level.timeframe}\n"
                            f"   Untouched HIGH: <code>{level.price:.8f}</code>\n"
                            f"   Current high: <code>{current_high:.8f}</code>"
                        ),
                    })
                    keys_to_remove.append(k)

            elif level.level_type == "low":
                if current_low <= level.price * (1 + tolerance):
                    touches.append({
                        "symbol": level.symbol,
                        "timeframe": level.timeframe,
                        "level_type": "low",
                        "level_price": level.price,
                        "current_low": current_low,
                        "current_close": current_close,
                        "exchange": level.exchange,
                        "message": (
                            f"🔻 <b>Level Touched</b> [{level.exchange}] {level.symbol}\n"
                            f"   Timeframe: {level.timeframe}\n"
                            f"   Untouched LOW: <code>{level.price:.8f}</code>\n"
                            f"   Current low: <code>{current_low:.8f}</code>"
                        ),
                    })
                    keys_to_remove.append(k)

        # Remove touched levels
        for k in keys_to_remove:
            del self._levels[k]

        return touches

    def check_liquidity_sweeps(self, current_candle, symbol=None, tolerance=0.001):
        """
        Detect liquidity sweeps (false breakouts).

        A sweep occurs when price temporarily breaks a level but closes back.

        Args:
            current_candle (list): Latest candle [timestamp, open, high, low, close, volume]
            symbol (str): Symbol to filter levels by (defaults to _symbol_hint for backward compat)
            tolerance (float): Fractional tolerance

        Returns:
            list[LiquiditySweep]: Detected sweep events
        """
        sweeps = []
        if not current_candle or len(current_candle) < 5:
            return sweeps

        current_high = current_candle[2]
        current_low = current_candle[3]
        current_close = current_candle[4]

        keys_to_remove = []

        target_symbol = symbol if symbol is not None else getattr(self, "_symbol_hint", None)

        for k, level in self._levels.items():
            if level.symbol != target_symbol:
                continue

            if level.level_type == "high":
                # Wick above high but close below = bearish sweep
                if current_high > level.price and current_close < level.price:
                    sweeps.append(LiquiditySweep(
                        symbol=level.symbol,
                        timeframe=level.timeframe,
                        sweep_type="bearish",
                        level_price=level.price,
                        wick_price=current_high,
                        close_price=current_close,
                        exchange=level.exchange,
                    ))
                    keys_to_remove.append(k)

            elif level.level_type == "low":
                # Wick below low but close above = bullish sweep
                if current_low < level.price and current_close > level.price:
                    sweeps.append(LiquiditySweep(
                        symbol=level.symbol,
                        timeframe=level.timeframe,
                        sweep_type="bullish",
                        level_price=level.price,
                        wick_price=current_low,
                        close_price=current_close,
                        exchange=level.exchange,
                    ))
                    keys_to_remove.append(k)

        # Remove swept levels
        for k in keys_to_remove:
            del self._levels[k]

        return sweeps

    def set_symbol(self, symbol):
        """Temporarily set the symbol context for touch/sweep checks."""
        self._symbol_hint = symbol

    def clear_old_levels(self, max_age_hours=48):
        """Remove levels older than max_age_hours."""
        now_ms = datetime.now().timestamp() * 1000
        cutoff = now_ms - (max_age_hours * 3600 * 1000)
        keys_to_remove = [
            k for k, v in self._levels.items()
            if v.candle_time < cutoff
        ]
        for k in keys_to_remove:
            del self._levels[k]
        return len(keys_to_remove)


def format_level_touch_events(events):
    """Format level touch events into a Telegram message."""
    if not events:
        return None

    lines = [
        "🎯 <b>Level Touch Alert</b>",
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</i>\n",
    ]

    for ev in events:
        lines.append(ev["message"])
        lines.append("")

    return "\n".join(lines).strip()


def format_sweep_events(sweeps):
    """Format liquidity sweep events into a Telegram message."""
    if not sweeps:
        return None

    lines = [
        "🔄 <b>Liquidity Sweep Alert</b>",
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</i>\n",
    ]

    for sw in sweeps:
        if sw.sweep_type == "bearish":
            lines.append(
                f"🔻 <b>Bearish Sweep</b> [{sw.exchange}] {sw.symbol}\n"
                f"   Timeframe: {sw.timeframe}\n"
                f"   Level: <code>{sw.level_price:.8f}</code>\n"
                f"   Wicked to: <code>{sw.wick_price:.8f}</code>\n"
                f"   Closed at: <code>{sw.close_price:.8f}</code>\n"
                f"   ❌ Price swept above high then closed below — bearish rejection!"
            )
        else:
            lines.append(
                f"🔺 <b>Bullish Sweep</b> [{sw.exchange}] {sw.symbol}\n"
                f"   Timeframe: {sw.timeframe}\n"
                f"   Level: <code>{sw.level_price:.8f}</code>\n"
                f"   Wicked to: <code>{sw.wick_price:.8f}</code>\n"
                f"   Closed at: <code>{sw.close_price:.8f}</code>\n"
                f"   ✅ Price swept below low then closed above — bullish rejection!"
            )
        lines.append("")

    return "\n".join(lines).strip()