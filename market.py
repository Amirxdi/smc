#!/usr/bin/env python3
"""
market.py — Asynchronous market-data fetcher with automatic retry / reconnect.
"""

import asyncio
import logging

import ccxt.async_support as ccxt

from config import (
    FETCH_MAX_RETRIES,
    FETCH_RETRY_DELAY,
    FETCH_TIMEOUT,
    MAX_SYMBOLS_PER_EXCHANGE,
)

logger = logging.getLogger(__name__)

# ─── Exchange definitions ────────────────────────────────────────────────────

EXCHANGE_CONFIGS: dict = {
    "bybit": {
        "class": ccxt.bybit,
        "label": "Bybit",
        "options": {
            "defaultType": "swap",
            "defaultSubType": "linear",
        },
        "market_type": "linear",
    },
    "okx": {
        "class": ccxt.okx,
        "label": "OKX",
        "options": {
            "defaultType": "swap",
        },
        "market_type": "SWAP",
    },
    "mexc": {
        "class": ccxt.mexc,
        "label": "MEXC",
        "options": {
            "defaultType": "swap",
        },
        "market_type": "swap",
    },
    "gate": {
        "class": ccxt.gateio,
        "label": "Gate.io",
        "options": {
            "defaultType": "swap",
        },
        "market_type": "swap",
    },
}


# ─── Retry helper ─────────────────────────────────────────────────────────────


async def _fetch_with_retry(coro_factory, label: str, symbol: str = "") -> any:
    last_exc = None
    for attempt in range(1, FETCH_MAX_RETRIES + 1):
        try:
            result = await coro_factory()
            return result
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable,
                ccxt.RequestTimeout, asyncio.TimeoutError) as exc:
            last_exc = exc
            wait = FETCH_RETRY_DELAY * (2 ** (attempt - 1))
            logger.warning(
                "[%s] Attempt %d/%d failed for %s: %s. Retrying in %.1fs…",
                label, attempt, FETCH_MAX_RETRIES, symbol or "?", exc, wait,
            )
            await asyncio.sleep(wait)
        except Exception:
            logger.exception("[%s] Non-retryable error for %s", label, symbol or "?")
            return []
    logger.error(
        "[%s] All %d retries exhausted for %s. Last error: %s",
        label, FETCH_MAX_RETRIES, symbol or "?", last_exc,
    )
    return []


# ─── Market class ─────────────────────────────────────────────────────────────


class Market:
    """Wraps a single ccxt exchange with automatic retries."""

    def __init__(self, exchange_name: str = "bybit"):
        config = EXCHANGE_CONFIGS.get(exchange_name)
        if not config:
            raise ValueError(
                f"Unsupported exchange: {exchange_name}. "
                f"Choose from: {list(EXCHANGE_CONFIGS.keys())}"
            )
        self.name = exchange_name
        self.label = config["label"]
        self._market_type = config.get("market_type", "swap")

        options = dict(config["options"])
        options.update({
            "enableRateLimit": True,
            "timeout": FETCH_TIMEOUT * 1000,
        })
        self.exchange = config["class"](options)

    # ── Public methods ────────────────────────────────────────────────────

    async def get_usdt_perpetual_pairs(self) -> list[str]:
        """Return USDT perpetual futures pairs (capped)."""
        async def _load():
            # Direct fetch_markets with correct type for each exchange
            if self.name == "bybit":
                markets = await self.exchange.fetch_markets({"category": "linear"})
            elif self.name == "okx":
                markets = await self.exchange.fetch_markets({"instType": "SWAP"})
            else:
                markets = await self.exchange.fetch_markets()

            # Parse only USDT-margined swaps
            usdt_perps = []
            for m in markets:
                symbol = m.get("symbol", "")
                if symbol.endswith("/USDT") and m.get("contract") and m.get("linear", False):
                    usdt_perps.append(symbol)
            return usdt_perps

        raw: list[str] = await _fetch_with_retry(_load, self.label, "fetch_markets")
        if not raw:
            logger.warning("[%s] No USDT perpetual pairs found", self.label)
            return []

        selected = raw[:MAX_SYMBOLS_PER_EXCHANGE]
        logger.info(
            "[%s] %d USDT perpetuals loaded (scanning %d)",
            self.label, len(raw), len(selected),
        )
        return selected

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "4h", limit: int = 100
    ) -> list:
        async def _fetch():
            return await self.exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, limit=limit
            )
        result = await _fetch_with_retry(_fetch, self.label, symbol)
        return result if isinstance(result, list) else []

    async def fetch_1d_candles(self, symbol: str, limit: int = 50) -> list:
        return await self.fetch_ohlcv(symbol, timeframe="1d", limit=limit)

    async def fetch_4h_candles(self, symbol: str, limit: int = 50) -> list:
        return await self.fetch_ohlcv(symbol, timeframe="4h", limit=limit)

    async def fetch_15m_candles(self, symbol: str, limit: int = 100) -> list:
        return await self.fetch_ohlcv(symbol, timeframe="15m", limit=limit)

    async def close(self):
        try:
            await self.exchange.close()
        except Exception:
            pass