#!/usr/bin/env python3
"""
config.py — Centralised configuration for the SMC Crypto Futures Scanner.

All environment variables are read here. Every other module imports from
this file so there is a single source of truth.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram ────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str   = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Exchanges ───────────────────────────────────────────────────────────────

# Comma-separated list of exchange IDs to enable, e.g. "bybit,okx"
EXCHANGES_RAW: str = os.getenv("EXCHANGES", "bybit,okx")

# Maximum USDT-perpetual pairs to scan per exchange (keep low to avoid rate limits)
MAX_SYMBOLS_PER_EXCHANGE: int = int(os.getenv("MAX_SYMBOLS", "30"))

# ─── Scan intervals ──────────────────────────────────────────────────────────

# How often (minutes) to run the main SMC level scan
SCAN_INTERVAL_MIN: int = max(5, int(os.getenv("SCAN_INTERVAL", "15")))

# How often (minutes) to run the trendline breakout scan
TRENDLINE_INTERVAL_MIN: int = max(10, int(os.getenv("TRENDLINE_INTERVAL", "30")))

# Heartbeat message when no signals for this many hours
HEARTBEAT_HOURS: int = int(os.getenv("HEARTBEAT_HOURS", "4"))

# ─── Signal filters ──────────────────────────────────────────────────────────

# Minimum ATR-to-price ratio (%) for a signal to be valid (filters low-volatility)
ATR_MIN_PCT: float = float(os.getenv("ATR_MIN_PCT", "0.5"))

# Minimum volume ratio vs 20-period average (e.g. 1.2 = 20 % above average)
VOLUME_MIN_RATIO: float = float(os.getenv("VOLUME_MIN_RATIO", "1.0"))

# Minimum signal strength score (0–100) to send an alert
MIN_SIGNAL_SCORE: int = int(os.getenv("MIN_SIGNAL_SCORE", "50"))

# ─── Session filter ──────────────────────────────────────────────────────────
# Active trading sessions in UTC hours (inclusive).  Set SESSIONS="" to disable.
# Format: "london:7-16,newyork:12-21,asia:0-9"
SESSIONS_RAW: str = os.getenv("SESSIONS", "london:7-16,newyork:12-21,asia:0-9")

# ─── Level tracker ───────────────────────────────────────────────────────────

# Remove levels older than this many hours
LEVEL_MAX_AGE_HOURS: int = int(os.getenv("LEVEL_MAX_AGE_HOURS", "72"))

# Tolerance (fraction) for price-to-level matching
LEVEL_TOUCH_TOLERANCE: float = float(os.getenv("LEVEL_TOUCH_TOLERANCE", "0.001"))

# Minimum wick-to-body ratio for a sweep to be considered significant
SWEEP_WICK_RATIO: float = float(os.getenv("SWEEP_WICK_RATIO", "0.3"))

# ─── 15-minute confirmation ──────────────────────────────────────────────────

# Number of 15m candles to look back for confirmation
CONFIRM_15M_LOOKBACK: int = int(os.getenv("CONFIRM_15M_LOOKBACK", "10"))

# ─── Duplicate-alert prevention ──────────────────────────────────────────────

# Seconds before the same symbol+level can fire again
ALERT_COOLDOWN_SECONDS: int = int(os.getenv("ALERT_COOLDOWN_SECONDS", "3600"))

# ─── Retry / network ─────────────────────────────────────────────────────────

# Max retries for CCXT calls
FETCH_MAX_RETRIES: int = int(os.getenv("FETCH_MAX_RETRIES", "3"))

# Base delay (seconds) between retries (exponential back-off)
FETCH_RETRY_DELAY: float = float(os.getenv("FETCH_RETRY_DELAY", "2.0"))

# Per-request timeout (seconds)
FETCH_TIMEOUT: int = int(os.getenv("FETCH_TIMEOUT", "30"))

# ─── Health server ───────────────────────────────────────────────────────────

HEALTH_PORT: int = int(os.getenv("PORT", "10000"))

# ─── Logging ─────────────────────────────────────────────────────────────────

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

# ─── Validation ──────────────────────────────────────────────────────────────

def validate() -> list[str]:
    """Return a list of configuration errors (empty = all good)."""
    errors: list[str] = []
    if not TELEGRAM_BOT_TOKEN:
        errors.append("TELEGRAM_BOT_TOKEN is not set")
    if not TELEGRAM_CHAT_ID:
        errors.append("TELEGRAM_CHAT_ID is not set")
    try:
        int(TELEGRAM_CHAT_ID)
    except ValueError:
        errors.append("TELEGRAM_CHAT_ID must be an integer")
    return errors


def get_chat_id() -> int:
    """Return the Telegram chat ID as an integer."""
    return int(TELEGRAM_CHAT_ID)


def get_enabled_exchanges() -> list[str]:
    """Return the list of enabled exchange IDs."""
    from market import EXCHANGE_CONFIGS  # avoid circular at module level
    raw = [e.strip().lower() for e in EXCHANGES_RAW.split(",") if e.strip()]
    return [e for e in raw if e in EXCHANGE_CONFIGS]


def get_active_sessions() -> list[dict]:
    """
    Parse SESSIONS_RAW into a list of {name, start_hour, end_hour} dicts.
    Returns empty list if SESSIONS_RAW is blank (= no filter).
    """
    if not SESSIONS_RAW.strip():
        return []
    sessions = []
    for part in SESSIONS_RAW.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        name, hours = part.split(":", 1)
        if "-" not in hours:
            continue
        try:
            start, end = hours.split("-")
            sessions.append({
                "name": name.strip(),
                "start": int(start),
                "end": int(end),
            })
        except ValueError:
            pass
    return sessions
