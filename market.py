#!/usr/bin/env python3
"""
Market data module for multiple crypto exchanges (Bybit, OKX, MEXC, Gate.io).
Uses ccxt to fetch market data asynchronously.
"""

import ccxt.async_support as ccxt
import os
from dotenv import load_dotenv

load_dotenv()

# Map of exchange names to ccxt exchange classes and options
EXCHANGE_CONFIGS = {
    "bybit": {
        "class": ccxt.bybit,
        "label": "Bybit",
        "options": {"defaultType": "swap", "defaultSubType": "linear"},
    },
    "okx": {
        "class": ccxt.okx,
        "label": "OKX",
        "options": {"defaultType": "swap"},
    },
    "mexc": {
        "class": ccxt.mexc,
        "label": "MEXC",
        "options": {"defaultType": "swap"},
    },
    "gate": {
        "class": ccxt.gateio,
        "label": "Gate.io",
        "options": {"defaultType": "swap"},
    },
}


def get_enabled_exchanges():
    """Get the list of enabled exchanges from the EXCHANGES env var."""
    raw = os.getenv("EXCHANGES", "bybit,okx,mexc,gate")
    enabled = [e.strip().lower() for e in raw.split(",") if e.strip()]
    return [e for e in enabled if e in EXCHANGE_CONFIGS]


def get_scan_interval():
    """Get the auto-scan interval in minutes (default: 15, min: 5)."""
    try:
        interval = int(os.getenv("SCAN_INTERVAL", "15"))
        return max(interval, 5)
    except (ValueError, TypeError):
        return 15


def get_trendline_interval():
    """Get the trendline scan interval in minutes (default: 30, min: 10)."""
    try:
        interval = int(os.getenv("TRENDLINE_INTERVAL", "30"))
        return max(interval, 10)
    except (ValueError, TypeError):
        return 30


class Market:
    """Handles market data connections for a single exchange."""

    def __init__(self, exchange_name="bybit"):
        self.name = exchange_name
        config = EXCHANGE_CONFIGS.get(exchange_name)
        if not config:
            raise ValueError(
                f"Unsupported exchange: {exchange_name}. "
                f"Choose from: {list(EXCHANGE_CONFIGS.keys())}"
            )

        self.label = config["label"]
        self.exchange = config["class"]({
            "enableRateLimit": True,
            "options": config["options"],
        })

    async def get_usdt_perpetual_pairs(self):
        """Fetch top ~50 USDT perpetual futures pairs."""
        try:
            await self.exchange.load_markets()
            usdt_perpetuals = [
                s for s, m in self.exchange.markets.items()
                if s.endswith("/USDT") and m.get("contract")
            ]
            print(f"[{self.label}] Found {len(usdt_perpetuals)} USDT perpetual pairs")
            return usdt_perpetuals[:50]
        except Exception as e:
            print(f"[{self.label}] Error fetching markets: {e}")
            return []

    async def fetch_candles(self, symbol, timeframe="4h", limit=100):
        """
        Generic candle fetcher for any timeframe.

        Args:
            symbol (str): Trading pair symbol (e.g., 'BTC/USDT')
            timeframe (str): Candle timeframe ('1d', '4h', '15m', etc.)
            limit (int): Number of candles to fetch

        Returns:
            list: List of candle data [timestamp, open, high, low, close, volume]
        """
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as e:
            print(f"[{self.label}] Error fetching {timeframe} candles for {symbol}: {e}")
            return []

    async def fetch_1d_candles(self, symbol, limit=50):
        """Fetch daily candles for a symbol."""
        return await self.fetch_candles(symbol, timeframe="1d", limit=limit)

    async def fetch_4h_candles(self, symbol, limit=2):
        """Fetch 4-hour candles for a symbol."""
        return await self.fetch_candles(symbol, timeframe="4h", limit=limit)

    async def fetch_15m_candles(self, symbol, limit=100):
        """Fetch 15-minute candles for a symbol."""
        return await self.fetch_candles(symbol, timeframe="15m", limit=limit)

    async def close(self):
        """Close the exchange connection."""
        try:
            await self.exchange.close()
        except Exception:
            pass