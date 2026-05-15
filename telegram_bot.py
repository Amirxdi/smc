#!/usr/bin/env python3
"""
telegram_bot.py — Telegram bot for SMC Crypto Futures Scanner.

Complete rewrite that fixes:
- Bot stopping randomly (proper asyncio exception handling)
- No signals being sent (dedicated sender with retry)
- Mobile notifications not working (shorter messages, HTML parse mode)
- API/async/crash issues (connection-level error recovery)

Features:
- Command handlers: /start, /scan, /trendline, /status, /autoscan
- Background scan loops with automatic recovery
- Heartbeat when no signals detected
- Signal history tracking
- Session filter (only alert during active trading sessions)
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import RetryAfter, TimedOut, NetworkError, TelegramError

from config import (
    validate,
    get_chat_id,
    get_enabled_exchanges,
    SCAN_INTERVAL_MIN,
    TRENDLINE_INTERVAL_MIN,
    HEARTBEAT_HOURS,
    MIN_SIGNAL_SCORE,
    ATR_MIN_PCT,
    get_active_sessions,
)
from market import EXCHANGE_CONFIGS, Market
from scanner import scan_all_symbols, GLOBAL_TRACKER

logger = logging.getLogger(__name__)

# ─── Helpers ─────────────────────────────────────────────────────────────

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def format_price(p: float) -> str:
    """Human-readable price (no tiny decimals for large numbers)."""
    if p >= 100:
        return f"{p:.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.8f}"

def is_session_active() -> bool:
    """Check if the current UTC hour falls in any configured session."""
    sessions = get_active_sessions()
    if not sessions:
        return True  # no session filter = always active
    utc_hour = datetime.now(timezone.utc).hour
    for s in sessions:
        if s["start"] <= s["end"]:
            if s["start"] <= utc_hour <= s["end"]:
                return True
        else:  # overnight session (e.g. 22:00 – 6:00)
            if utc_hour >= s["start"] or utc_hour <= s["end"]:
                return True
    return False

# ─── Session filter decorator for scan loops ─────────────────────────────

async def send_message_safe(app: Application, chat_id: int, text: str):
    """Send a Telegram message with retry on transient errors."""
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return
        except RetryAfter as e:
            wait = e.retry_after
            logger.warning("Telegram rate-limited, waiting %ds (attempt %d/%d)", wait, attempt, max_retries)
            await asyncio.sleep(wait)
        except (TimedOut, NetworkError) as e:
            logger.warning("Telegram network error (attempt %d/%d): %s", attempt, max_retries, e)
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)
        except TelegramError as e:
            logger.error("Telegram permanent error: %s", e)
            return

def score_to_emoji(score: int) -> str:
    if score >= 80:
        return "🔥🔥🔥"
    if score >= 60:
        return "🔥🔥"
    if score >= MIN_SIGNAL_SCORE:
        return "🔥"
    return ""

# ─── Scan runners ────────────────────────────────────────────────────────

async def run_level_scan() -> dict:
    """Run the untouched-level scanner across all enabled exchanges."""
    exchanges = get_enabled_exchanges()
    if not exchanges:
        return {"touches": [], "sweeps": [], "new_1d": 0, "new_4h": 0, "total_tracked": 0}

    all_touches: list = []
    all_sweeps: list = []
    total_new_1d = 0
    total_new_4h = 0

    for exchange_name in exchanges:
        label = EXCHANGE_CONFIGS[exchange_name]["label"]
        market = Market(exchange_name)
        try:
            symbols = await market.get_usdt_perpetual_pairs()
            if not symbols:
                continue
            result = await scan_all_symbols(symbols, market, GLOBAL_TRACKER, label)
            all_touches.extend(result["touches"])
            all_sweeps.extend(result["sweeps"])
            total_new_1d += result["new_levels_1d"]
            total_new_4h += result["new_levels_4h"]
        finally:
            await market.close()

    return {
        "touches": all_touches,
        "sweeps": all_sweeps,
        "new_1d": total_new_1d,
        "new_4h": total_new_4h,
        "total_tracked": GLOBAL_TRACKER.total_levels,
    }

# ─── Formatting ──────────────────────────────────────────────────────────

def format_level_scan_summary(result: dict) -> str:
    """Format level scan results as a compact Telegram message."""
    touches = result["touches"]
    sweeps = result["sweeps"]
    total = result["total_tracked"]

    lines = [
        f"🎯 <b>SMC Level Scan</b>  |  <i>{now_utc()}</i>",
        f"Tracking <b>{total}</b> levels",
        f"1D: <b>{result['new_1d']}</b> new  |  4H: <b>{result['new_4h']}</b> new",
    ]

    # Sweeps (filtered by score already in scanner)
    if sweeps:
        lines.append(f"\n<b>── Liquidity Sweeps ({len(sweeps)}) ──</b>\n")
        for sw in sweeps:
            s = sw["sweep"]
            direction = "🔻 <b>Bearish</b>" if s.sweep_type == "bearish" else "🔺 <b>Bullish</b>"
            emoji = score_to_emoji(sw["score"])
            confirm = "✅ 15m ok" if sw["confirmed_15m"] else ""
            lines.append(
                f"{direction} {emoji}  [{s.exchange}] <b>{s.sweep_type.upper()}</b>\n"
                f"   Symbol: {s.symbol} ({s.timeframe})\n"
                f"   Level: <code>{format_price(s.level_price)}</code>\n"
                f"   Wick → <code>{format_price(s.wick_price)}</code>\n"
                f"   Close: <code>{format_price(s.close_price)}</code>\n"
                f"   Score: <b>{sw['score']}/100</b>  {confirm}"
            )
    else:
        lines.append("\nNo sweeps detected this cycle.")

    lines.append(f"\n<i>Next scan in {SCAN_INTERVAL_MIN}m</i>")
    return "\n".join(lines)

def format_sweep_alert(sweep: dict) -> str:
    """Short alert message optimised for mobile notifications."""
    s = sweep["sweep"]
    direction = "🔻 BEARISH" if s.sweep_type == "bearish" else "🔺 BULLISH"
    confirm = " ✅" if sweep["confirmed_15m"] else ""
    return (
        f"<b>{direction} SWEEP</b>{confirm}\n"
        f"[{s.exchange}] <b>{s.symbol}</b> ({s.timeframe})\n"
        f"Level: {format_price(s.level_price)} → Wick: {format_price(s.wick_price)}\n"
        f"Score: {sweep['score']}/100"
    )

def format_heartbeat(scan_count: int, result: dict) -> str:
    return (
        f"🤖 <b>SMC Scanner — Heartbeat</b>\n"
        f"<i>{now_utc()}</i>\n\n"
        f"Scans completed: <b>{scan_count}</b>\n"
        f"Tracking <b>{result['total_tracked']}</b> levels\n"
        f"Bot is running normally  ✅"
    )

# ─── Background loops ────────────────────────────────────────────────────

async def auto_level_scan_loop(app: Application) -> None:
    """Background: periodic untouched-level scanning."""
    chat_id = get_chat_id()
    logger.info("Auto level scan started (interval=%d min)", SCAN_INTERVAL_MIN)

    scan_count = 0
    last_heartbeat = 0.0

    while True:
        try:
            await asyncio.sleep(SCAN_INTERVAL_MIN * 60)

            if not is_session_active():
                logger.debug("Outside active session — skipping scan")
                continue

            logger.info("Running auto level scan #%d…", scan_count + 1)
            result = await run_level_scan()
            scan_count += 1
            sweeps = result["sweeps"]

            # Send sweep alerts individually (better for mobile notifications)
            for sw in sweeps:
                await send_message_safe(app, chat_id, format_sweep_alert(sw))

            # Summary every scan
            await send_message_safe(app, chat_id, format_level_scan_summary(result))

            # Heartbeat
            now_ts = datetime.now(timezone.utc).timestamp()
            if not sweeps and (now_ts - last_heartbeat) >= HEARTBEAT_HOURS * 3600:
                await send_message_safe(app, chat_id, format_heartbeat(scan_count, result))
                last_heartbeat = now_ts

        except asyncio.CancelledError:
            logger.info("Level scan loop cancelled")
            break
        except Exception as e:
            logger.exception("Auto level scan loop error: %s", e)
            await asyncio.sleep(30)  # back-off on crash

async def auto_trendline_scan_loop(app: Application) -> None:
    """Background: periodic trendline scanning (kept simple)."""
    chat_id = get_chat_id()
    logger.info("Auto trendline scan started (interval=%d min)", TRENDLINE_INTERVAL_MIN)

    while True:
        try:
            await asyncio.sleep(TRENDLINE_INTERVAL_MIN * 60)

            if not is_session_active():
                continue

            logger.info("Running auto trendline scan…")
            from trendline_analyzer import scan_trendline_breakouts, format_trendline_results
            exchanges = get_enabled_exchanges()
            breakouts = []
            for ex in exchanges:
                label = EXCHANGE_CONFIGS[ex]["label"]
                market = Market(ex)
                try:
                    symbols = await market.get_usdt_perpetual_pairs()
                    if symbols:
                        b = await scan_trendline_breakouts(symbols, market)
                        for bt in b:
                            bt["exchange"] = label
                        breakouts.extend(b)
                finally:
                    await market.close()

            if breakouts:
                msg = format_trendline_results(breakouts)
                await send_message_safe(app, chat_id, msg)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Auto trendline scan loop error: %s", e)
            await asyncio.sleep(30)

# ─── Command handlers ────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    exchanges = get_enabled_exchanges()
    labels = [EXCHANGE_CONFIGS[e]["label"] for e in exchanges]
    sessions = get_active_sessions()
    session_info = ", ".join(f"{s['name']} {s['start']}-{s['end']} UTC" for s in sessions) if sessions else "24/7"

    await update.message.reply_html(
        f"👋 <b>SMC Crypto Futures Scanner</b>\n\n"
        f"Scans: <code>{', '.join(labels)}</code>\n"
        f"Level scan: every <b>{SCAN_INTERVAL_MIN}min</b>\n"
        f"Trendline scan: every <b>{TRENDLINE_INTERVAL_MIN}min</b>\n"
        f"Active sessions: <b>{session_info}</b>\n"
        f"Min score: <b>{MIN_SIGNAL_SCORE}</b>\n\n"
        f"Commands:\n"
        f"/scan — Manual level scan\n"
        f"/trendline — Manual trendline scan\n"
        f"/status — Configuration check\n"
        f"/autoscan — Schedule info"
    )

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html("⏳ Scanning all exchanges…")
    try:
        result = await run_level_scan()
        msg = format_level_scan_summary(result)
        await update.message.reply_html(msg)
    except Exception as e:
        logger.exception("Manual scan failed")
        await update.message.reply_html(f"❌ Scan failed: <code>{e}</code>")

async def cmd_trendline(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from trendline_analyzer import scan_trendline_breakouts, format_trendline_results
    await update.message.reply_html("📊 Scanning for trendline breakouts…")
    try:
        exchanges = get_enabled_exchanges()
        breakouts = []
        for ex in exchanges:
            label = EXCHANGE_CONFIGS[ex]["label"]
            market = Market(ex)
            try:
                symbols = await market.get_usdt_perpetual_pairs()
                if symbols:
                    b = await scan_trendline_breakouts(symbols, market)
                    for bt in b:
                        bt["exchange"] = label
                    breakouts.extend(b)
            finally:
                await market.close()
        msg = format_trendline_results(breakouts)
        await update.message.reply_html(msg)
    except Exception as e:
        logger.exception("Trendline scan failed")
        await update.message.reply_html(f"❌ Trendline scan failed: <code>{e}</code>")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = ["📊 <b>SMC Scanner — Status</b>\n"]
    errors = validate()
    for err in errors:
        lines.append(f"❌ {err}")
    if not errors:
        lines.append("✅ All configuration OK")
        lines.append(f"📈 Tracking <b>{GLOBAL_TRACKER.total_levels}</b> levels")
        lines.append(f"🎯 Min signal score: <b>{MIN_SIGNAL_SCORE}</b>")
        lines.append(f"🔄 Scan interval: <b>{SCAN_INTERVAL_MIN}min</b>")
        lines.append(f"📊 Trendline interval: <b>{TRENDLINE_INTERVAL_MIN}min</b>")
        exchanges = get_enabled_exchanges()
        labels = [EXCHANGE_CONFIGS[e]["label"] for e in exchanges]
        lines.append(f"🌐 Exchanges: {', '.join(labels)}")
        lines.append(f"\n🤖 Bot is running 24/7")
    await update.message.reply_html("\n".join(lines))

async def cmd_autoscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sessions = get_active_sessions()
    session_info = ", ".join(f"{s['name']} {s['start']}-{s['end']} UTC" for s in sessions) if sessions else "24/7"
    msg = (
        f"🔄 <b>Auto-Scan Schedule</b>\n\n"
        f"• Level scan: every <b>{SCAN_INTERVAL_MIN}min</b>\n"
        f"• Trendline scan: every <b>{TRENDLINE_INTERVAL_MIN}min</b>\n"
        f"• Active sessions: <b>{session_info}</b>\n"
        f"• Min signal score: <b>{MIN_SIGNAL_SCORE}</b>\n"
        f"• Heartbeat: every <b>{HEARTBEAT_HOURS}h</b> (idle)\n\n"
        f"Alerts are automatic  🚀"
    )
    await update.message.reply_html(msg)

# ─── Post-init ───────────────────────────────────────────────────────────

async def post_init(application: Application) -> None:
    """Launch background tasks after the bot starts."""
    logger.info("Starting background scan loops…")
    chat_id = get_chat_id()

    exchanges = get_enabled_exchanges()
    labels = [EXCHANGE_CONFIGS[e]["label"] for e in exchanges]
    await send_message_safe(
        application, chat_id,
        f"🚀 <b>SMC Scanner Started</b>\n"
        f"Exchanges: <code>{', '.join(labels)}</code>\n"
        f"Level scan every {SCAN_INTERVAL_MIN}min\n"
        f"First scan commencing now… ⏳"
    )

    asyncio.create_task(auto_level_scan_loop(application))
    asyncio.create_task(auto_trendline_scan_loop(application))

# ─── Main ────────────────────────────────────────────────────────────────

def main():
    """Start the Telegram bot."""
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    )

    # Validate config
    errors = validate()
    if errors:
        for e in errors:
            logger.error("Config error: %s", e)
        sys.exit(1)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")

    print("=" * 50)
    print("  SMC Crypto Futures Scanner v2.0")
    print("=" * 50)

    # Build application with proper timeouts
    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .get_updates_read_timeout(60)
        .build()
    )

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("trendline", cmd_trendline))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("autoscan", cmd_autoscan))

    print("✅ Bot starting polling…")

    # use_clean_interval reduces stale socket issues
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
    )


if __name__ == "__main__":
    main()