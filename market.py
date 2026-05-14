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
    """
    Get the list of enabled exchanges from the EXCHANGES env var.

    Returns:
        list: List of exchange names (e.g., ['bybit', 'okx'])
    """
    raw = os.getenv("EXCHANGES", "bybit,okx,mexc,gate")
    enabled = [e.strip().lower() for e in raw.split(",") if e.strip()]
    return [e for e in enabled if e in EXCHANGE_CONFIGS]


def get_scan_interval():
    """
    Get the auto-scan interval in minutes from the SCAN_INTERVAL env var.

    Returns:
        int: Interval in minutes (default: 15, min: 5)
    """
    try:
        interval = int(os.getenv("SCAN_INTERVAL", "15"))
        return max(interval, 5)
    except (ValueError, TypeError):
        return 15


def get_trendline_interval():
    """
    Get the trendline scan interval in minutes from the TRENDLINE_INTERVAL env var.

    Returns:
        int: Interval in minutes (default: 30, min: 10)
    """
    try:
        interval = int(os.getenv("TRENDLINE_INTERVAL", "30"))
        return max(interval, 10)
    except (ValueError, TypeError):
        return 30


class Market:
    """Handles market data connections for a single exchange."""

    def __init__(self, exchange_name="bybit"):
        """
        Initialize the exchange connection.

        Args:
            exchange_name (str): Exchange identifier ('bybit', 'okx', 'mexc', 'gate')
        """
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
        """
        Fetch USDT perpetual futures pairs from the exchange.
        Limited to top ~50 pairs for fast scanning.

        Returns:
            list: List of trading pair symbols (e.g., ['BTC/USDT', 'ETH/USDT'])
        """
        try:
            await self.exchange.load_markets()

            usdt_perpetuals = []
            for symbol, market in self.exchange.markets.items():
                if not symbol.endswith("/USDT"):
                    continue
                if market.get("contract"):
                    usdt_perpetuals.append(symbol)

            print(f"[{self.label}] Found {len(usdt_perpetuals)} USDT perpetual pairs")
            return usdt_perpetuals[:50]

        except Exception as e:
            print(f"[{self.label}] Error fetching markets: {e}")
            return []

    async def fetch_4h_candles(self, symbol, limit=2):
        """Fetch 4-hour candles for a symbol."""
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe="4h", limit=limit)
        except Exception as e:
            print(f"[{self.label}] Error fetching 4h candles for {symbol}: {e}")
            return []

    async def fetch_15m_candles(self, symbol, limit=100):
        """Fetch 15-minute candles for a symbol."""
        try:
            return await self.exchange.fetch_ohlcv(symbol, timeframe="15m", limit=limit)
        except Exception as e:
            print(f"[{self.label}] Error fetching 15m candles for {symbol}: {e}")
            return []

    async def close(self):
        """Close the exchange connection."""
        try:
            await self.exchange.close()
        except Exception:
            pass