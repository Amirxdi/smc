# SMC Crypto Futures Scanner — Complete Audit & Improvement Report

## Overview

Complete rewrite of all core modules for 24/7 production stability, better
signal quality, and significantly improved error handling.  The bot now
handles network failures, API rate limits, crashes, and duplicate alerts
gracefully.

---

## 1.  Architecture Changes

| File | Status | Purpose |
|------|--------|---------|
| `config.py` | **NEW** | Centralised configuration (single source of truth) |
| `market.py` | **REWRITTEN** | Retry logic, session reuse, proper timeouts |
| `level_tracker.py` | **REWRITTEN** | 15m confirmation, cooldown, signal scoring |
| `scanner.py` | **REWRITTEN** | Trend/volume/ATR filters, batch exception handling |
| `telegram_bot.py` | **REWRITTEN** | Safe sender, session filter, compact mobile-friendly messages |
| `trendline_analyzer.py` | **UPDATED** | Exchange label propagation |
| `main.py` | **REWRITTEN** | Auto-restart, graceful shutdown, health server |
| `ai_analyzer.py` | **UNCHANGED** | Still present but not required for core functionality |

---

## 2.  Bug Fixes (Detailed)

### 2.1  Bot Stopping Randomly

**Root cause**:  The `while True` loops in `telegram_bot.py` had bare
`except Exception` blocks that caught errors but didn't re-raise them,
so the loop would silently exit if an unhandled exception occurred
outside the try block (e.g. in `asyncio.gather`).

**Fix (main.py)**:  
- `run_bot()` wraps the entire bot lifecycle in a `while` loop with
  exponential back-off (5s → 300s max) and a restart counter (max 50).
- `_signal_handler` / `_shutdown_event` allow clean exit on `SIGINT`/`SIGTERM`.
- If the bot crashes, it automatically restarts after a delay.

**Fix (telegram_bot.py)**:  
- Both `auto_level_scan_loop()` and `auto_trendline_scan_loop()` now catch
  `asyncio.CancelledError` and break cleanly; all other exceptions are logged
  with `logger.exception()` (which includes full traceback) and the loop
  sleeps for 30s before retrying.

### 2.2  No Signals Being Sent

**Root cause**:  
- The global `LevelTracker` used `set_symbol()` to change symbol context,
  which could confuse touch/sweep checks when multiple symbols were
  processed concurrently.
- Levels were removed after detection but there was no cooldown, so the
  same signal could fire repeatedly until the level was re-discovered.
- No minimum-score filter existed.

**Fix (level_tracker.py)**:  
- `set_symbol()` removed — every method now requires an explicit `symbol`
  parameter, eliminating cross-symbol interference.
- `CooldownMap` class prevents the same `(symbol, level_price)` alert from
  firing more than once per `ALERT_COOLDOWN_SECONDS` (default 1 hour).
- `_compute_signal_strength()` returns a 0–100 score; only sweeps with
  `score >= MIN_SIGNAL_SCORE` (default 50) are sent.

**Fix (scanner.py)**:  
- `scan_all_symbols()` now passes `return_exceptions=True` to
  `asyncio.gather()` so a single symbol failure doesn't crash the batch.

### 2.3  Mobile Telegram Notifications Not Working

**Root cause**:  
- The old `format_level_scan_summary()` produced very long messages (all
  touches and sweeps in one wall of text).  Telegram truncates long
  notifications on mobile.
- No per-signal alert was sent.

**Fix (telegram_bot.py)**:  
- `send_message_safe()` handles `RetryAfter` (rate-limit) and
  `TimedOut`/`NetworkError` with automatic retries.
- `format_sweep_alert()` produces a **short 4-line alert** optimised for
  mobile push notifications.
- Each sweep is sent as an individual message **before** the summary,
  so the phone notification shows the critical alert immediately.
- Messages use `<b>`, `<code>`, and `<i>` HTML tags for rich rendering
  without being bloated.

### 2.4  API / Async / Crash Issues

**Root cause**:  
- `ccxt.async_support` calls had no timeout or retry wrapping.
- `Market` sessions were not always closed in `finally` blocks, causing
  connection leaks in `ccxt`.
- `fetch_ohlcv()` returned `None` on failure but code assumed a list.

**Fix (market.py)**:  
- `_fetch_with_retry()` wraps every API call with exponential back-off
  (up to `FETCH_MAX_RETRIES`, base delay `FETCH_RETRY_DELAY`).
- Recognises `ccxt.NetworkError`, `ExchangeNotAvailable`,
  `RequestTimeout`, and `asyncio.TimeoutError` as retryable.
- Non-retryable exceptions are logged and return `[]` immediately.
- `fetch_ohlcv()` always returns a list (never `None`).
- Exchange sessions have a `timeout` set to `FETCH_TIMEOUT * 1000` ms.

---

## 3.  New Features

### 3.1  Trend Filter
- **File**: `scanner.py` function `_is_trend_aligned()`
- Computes EMA(20) vs EMA(50) from daily close prices.
- Bullish sweeps require EMA20 > EMA50 (uptrend).
- Bearish sweeps require EMA20 < EMA50 (downtrend).
- Passed to `check_liquidity_sweeps()` as `trend_aligned` flag and
  contributes up to +15 to the signal score.

### 3.2  Volume Filter
- **File**: `scanner.py` function `_volume_ratio()`
- Compares the latest candle volume against the 20-period average.
- A ratio ≥ 1.2 contributes +8 to the score; ≥ 1.5 contributes +15.

### 3.3  ATR Filter
- **File**: `scanner.py` function `_atr_pct()`
- ATR as a percentage of the latest close price.
- Configurable via `ATR_MIN_PCT` env var (default 0.5%).
- Low-volatility symbols are automatically filtered out at the scan level
  (not yet applied as a hard filter — planned for v2.1).

### 3.4  Session Filters
- **File**: `config.py` `get_active_sessions()`, `telegram_bot.py` `is_session_active()`
- Configurable via `SESSIONS` env var, e.g. `SESSIONS="london:7-16,newyork:12-21,asia:0-9"`
- If `SESSIONS` is empty, all hours are active.
- If the current UTC hour falls outside any session, the scan loops
  skip execution (logged at DEBUG level).

### 3.5  Signal Strength Score
- **File**: `level_tracker.py` `_compute_signal_strength()`
- Weighted calculation (0–100):
  - Timeframe: 1D = 40, 4H = 20
  - Sweep type base: +10
  - Wick-to-body ratio ≥ threshold: +10
  - 15m confirmation: +30
  - Trend aligned: +15
  - Volume surge 1.2×: +8, 1.5×: +15
- Only sweeps with `score >= MIN_SIGNAL_SCORE` are sent to Telegram.

### 3.6  Signal History Tracking
- **File**: `level_tracker.py` — `LevelTracker.signal_history` list
- Every detected sweep/touch is appended to `signal_history` with
  timestamp, symbol, type, score, and price data.
- Ready for future export or dashboard integration.

### 3.7  Better Telegram Message Formatting
- **Per-sweep alert**: compact 4-line format with direction, exchange,
  symbol, timeframe, level, wick, and score.
- **Summary**: grouped by "Liquidity Sweeps" section with emoji-based
  strength indicators: 🔥🔥🔥 (80+), 🔥🔥 (60+), 🔥 (50+).
- **15m confirmation** badge (✅) shown when confirmed.

---

## 4.  Configuration Reference

### Environment Variables (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | **Required.** Telegram bot token |
| `TELEGRAM_CHAT_ID` | — | **Required.** Chat/user ID to send alerts to |
| `EXCHANGES` | `bybit,okx` | Comma-separated exchange list |
| `MAX_SYMBOLS` | `30` | Max USDT pairs per exchange |
| `SCAN_INTERVAL` | `15` | Level scan interval (minutes, min 5) |
| `TRENDLINE_INTERVAL` | `30` | Trendline scan interval (minutes, min 10) |
| `HEARTBEAT_HOURS` | `4` | Heartbeat when no signals detected (hours) |
| `ATR_MIN_PCT` | `0.5` | Minimum ATR percent for valid signal |
| `VOLUME_MIN_RATIO` | `1.0` | Minimum volume vs 20-avg ratio |
| `MIN_SIGNAL_SCORE` | `50` | Minimum score (0–100) to send alert |
| `SESSIONS` | `london:7-16,newyork:12-21,asia:0-9` | Active trading sessions (empty=24/7) |
| `LEVEL_MAX_AGE_HOURS` | `72` | Untouched level expiry (hours) |
| `LEVEL_TOUCH_TOLERANCE` | `0.001` | Fractional tolerance for price matching |
| `SWEEP_WICK_RATIO` | `0.3` | Min wick-to-body ratio for significance |
| `ALERT_COOLDOWN_SECONDS` | `3600` | Duplicate alert prevention (seconds) |
| `FETCH_MAX_RETRIES` | `3` | Max retries per CCXT call |
| `FETCH_RETRY_DELAY` | `2.0` | Base retry delay (seconds, exponential) |
| `FETCH_TIMEOUT` | `30` | Per-request timeout (seconds) |
| `PORT` | `10000` | Health-check server port |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR) |

---

## 5.  APIs Required

The bot **requires** these APIs:

1. **Telegram Bot API** (mandatory)
   - Obtained from [@BotFather](https://t.me/BotFather) on Telegram.
   - Set as `TELEGRAM_BOT_TOKEN` in `.env`.

2. **Exchange APIs** (mandatory)
   - Bybit, OKX, MEXC, Gate.io — **public** endpoints only.
   - No API keys needed unless you upgrade to authenticated endpoints.

3. **DeepSeek API** (optional)
   - `ai_analyzer.py` uses DeepSeek if `DEEPSEEK_API_KEY` is set.
   - Not used by the core scanner — purely advisory.

No other external APIs are required.

---

## 6.  How to Deploy

### Render (recommended)

```bash
# Procfile and runtime.txt are already configured
# Set environment variables in Render dashboard
git push origin main
```

### Local

```bash
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
copy .env.example .env     # Edit with your values
python main.py
```

---

## 7.  File Structure (Final)

```
smc/
├── config.py              # Centralised configuration
├── market.py              # Exchange data fetching + retry
├── level_tracker.py       # Level storage, sweeps, scoring
├── scanner.py             # Symbol scanning + filters
├── telegram_bot.py        # Telegram bot (all commands + loops)
├── trendline_analyzer.py  # Trendline breakout detection
├── ai_analyzer.py         # Optional AI analysis
├── main.py                # Entry point with auto-restart
├── requirements.txt       # Python dependencies
├── Procfile               # Render deployment
├── runtime.txt            # Python version
├── .gitignore
├── .env                   # (not committed) API keys
└── AUDIT.md               # This file
```

---

## 8.  Change Summary

| Metric | Before | After |
|--------|--------|-------|
| Crash recovery | None | Exponential back-off, 50 restarts |
| Retry on network error | None | 3 retries, exponential delay |
| Duplicate alert prevention | None | Per-symbol cooldown (1h) |
| Signal scoring | None | 0–100 weighted score |
| 15m confirmation | None | Last-opposite-candle breakout check |
| Trend filter | None | EMA20/EMA50 comparison |
| Volume filter | None | 20-period volume ratio |
| Session filter | None | Configurable UTC session windows |
| Signal history | None | In-memory list |
| Mobile notifications | Long walls of text | Short per-sweep alerts |
| Telegram error handling | Crashed on rate-limit | Retry with back-off |
| Exchange timeout | None | 30s configured |
| Config validation | None | On startup |
| Graceful shutdown | None | SIGINT/SIGTERM handler |