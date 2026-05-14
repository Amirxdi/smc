#!/usr/bin/env python3
"""
Telegram bot module for SMC Crypto Futures Scanner.
Supports interactive commands + automatic periodic scanning.

Commands:
  /start     — Welcome message
  /scan      — Run SMC price touch scan now
  /trendline — Run trendline breakout scan now
  /autoscan  — Show auto-scan status
  /exchanges — Show which exchanges are active
  /status    — Check bot configuration

Auto-scans:
  - Price touches: every SCAN_INTERVAL (default 15 min)
  - Trendline breakouts: every TRENDLINE_INTERVAL (default 30 min)
"""

import os
import asyncio
import logging
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from market import (
    Market,
    get_enabled_exchanges,
    EXCHANGE_CONFIGS,
    get_scan_interval,
    get_trendline_interval,
)
from scanner import Scanner
from trendline_analyzer import scan_trendline_breakouts, format_trendline_results

load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_bot_token():
    """Get the Telegram bot token from environment."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")
    return token


def get_chat_id():
    """Get the Telegram chat ID from environment."""
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise ValueError("TELEGRAM_CHAT_ID not set in .env")
    return int(chat_id)


# ====== SCAN FUNCTIONS ======


async def run_price_touch_scan() -> list:
    """Run the SMC price touch scanner across all enabled exchanges."""
    exchanges = get_enabled_exchanges()
    if not exchanges:
        return []

    results = []
    for exchange_name in exchanges:
        label = EXCHANGE_CONFIGS[exchange_name]["label"]
        logger.info(f"Price touch scan on {label}...")

        market = Market(exchange_name)
        scanner = Scanner(market)

        try:
            symbols = await market.get_usdt_perpetual_pairs()
            if not symbols:
                results.append({
                    "exchange": exchange_name,
                    "label": label,
                    "touches": [],
                    "analyses": None,
                })
                continue

            touches = await scanner.scan_all(symbols)

            analyses = None
            if touches:
                analyses = await scanner.ai_analyzer.analyze_multiple(touches)

            results.append({
                "exchange": exchange_name,
                "label": label,
                "touches": touches,
                "analyses": analyses,
            })

        finally:
            await market.close()

    return results


def format_price_touch_results(exchange_results: list) -> str:
    """Format price touch scan results into a Telegram message."""
    total_touches = sum(len(r["touches"]) for r in exchange_results)

    if total_touches == 0:
        return (
            "🔍 <b>SMC Crypto Scanner</b>\n\n"
            "No price touches detected across any exchange.\n"
            "Try again later when the market moves."
        )

    lines = [
        f"🔍 <b>SMC Crypto Scanner — Results</b>",
        f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</i>\n",
    ]

    for result in exchange_results:
        touches = result["touches"]
        analyses = result["analyses"]
        label = result["label"]

        if not touches:
            continue

        lines.append(f"<b>── {label} ──</b>\n")

        for touch in touches:
            symbol = touch["symbol"]
            price = touch["current_price"]

            if touch["touch_high"]:
                icon = "🔺"
                level_type = "previous <b>HIGH</b>"
                level_price = touch["prev_high"]
            else:
                icon = "🔻"
                level_type = "previous <b>LOW</b>"
                level_price = touch["prev_low"]

            lines.append(
                f"{icon} <b>{symbol}</b>\n"
                f"   Price: <code>{price:.8f}</code>\n"
                f"   Touched {level_type}: <code>{level_price:.8f}</code>"
            )

            if analyses and symbol in analyses:
                analysis = analyses[symbol]
                if analysis:
                    lines.append(f"   🤖 {analysis}")

            lines.append("")

    lines.append("Use /scan to run again.")
    return "\n".join(lines).strip()


async def run_trendline_scan() -> list:
    """Run the trendline breakout scanner across all enabled exchanges."""
    exchanges = get_enabled_exchanges()
    if not exchanges:
        return []

    all_breakouts = []

    for exchange_name in exchanges:
        label = EXCHANGE_CONFIGS[exchange_name]["label"]
        logger.info(f"Trendline scan on {label}...")

        market = Market(exchange_name)
        try:
            symbols = await market.get_usdt_perpetual_pairs()
            if not symbols:
                continue

            breakouts = await scan_trendline_breakouts(symbols, market)
            for b in breakouts:
                b["exchange"] = label
            all_breakouts.extend(breakouts)
        finally:
            await market.close()

    return all_breakouts


def format_trendline_auto_results(breakouts: list) -> str:
    """Format trendline breakout results with exchange tags."""
    if not breakouts:
        return (
            "📊 <b>Trendline Breakout Scanner</b>\n\n"
            "No trendline breakouts detected on the 15-minute chart.\n"
            "Next scan will run automatically."
        )

    lines = [
        "📊 <b>Trendline Breakout Scanner — Results</b>",
        f"<i>15-minute chart analysis</i>\n",
    ]

    for b in breakouts:
        lines.append(f"🔹 <b>[{b['exchange']}] {b['symbol']}</b>")
        lines.append(b["description"])
        lines.append("")

    lines.append("Use /trendline to run again.")
    return "\n".join(lines).strip()


# ====== AUTO-SCAN BACKGROUND TASKS ======


async def auto_price_touch_scan_loop(app: Application) -> None:
    """Background loop: periodically run price touch scans."""
    interval = get_scan_interval()
    chat_id = get_chat_id()
    logger.info(f"Auto price touch scan started. Interval: every {interval} min")

    while True:
        await asyncio.sleep(interval * 60)

        try:
            logger.info("Running auto price touch scan...")
            results = await run_price_touch_scan()
            total = sum(len(r["touches"]) for r in results)

            if total > 0:
                message = format_price_touch_results(results)
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                logger.info(f"Auto scan sent: {total} touches detected.")
            else:
                logger.info("Auto scan: no touches detected.")
        except Exception as e:
            logger.error(f"Auto price touch scan error: {e}")


async def auto_trendline_scan_loop(app: Application) -> None:
    """Background loop: periodically run trendline scans."""
    interval = get_trendline_interval()
    chat_id = get_chat_id()
    logger.info(f"Auto trendline scan started. Interval: every {interval} min")

    while True:
        await asyncio.sleep(interval * 60)

        try:
            logger.info("Running auto trendline scan...")
            breakouts = await run_trendline_scan()

            if breakouts:
                message = format_trendline_auto_results(breakouts)
                await app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                logger.info(f"Auto trendline sent: {len(breakouts)} breakouts.")
            else:
                logger.info("Auto trendline: no breakouts detected.")
        except Exception as e:
            logger.error(f"Auto trendline scan error: {e}")


# ====== COMMAND HANDLERS ======


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message when /start is issued."""
    user = update.effective_user
    exchanges = get_enabled_exchanges()
    exchange_labels = [EXCHANGE_CONFIGS[e]["label"] for e in exchanges]
    scan_interval = get_scan_interval()
    trend_interval = get_trendline_interval()

    logger.info(f"User {user.first_name} ({user.id}) started the bot.")
    await update.message.reply_html(
        f"👋 Hello <b>{user.first_name}</b>!\n\n"
        f"Welcome to the <b>SMC Crypto Futures Scanner</b> 🤖\n\n"
        f"Scans USDT perpetual futures across:\n"
        f"<code>{', '.join(exchange_labels)}</code>\n\n"
        f"<b>Auto-Scan is ON</b> 🔄\n"
        f"• Price touches every <b>{scan_interval} min</b>\n"
        f"• Trendline breakouts every <b>{trend_interval} min</b>\n\n"
        f"<b>Commands:</b>\n"
        f"🔹 /start  — Show this message\n"
        f"🔹 /scan   — Manual price touch scan\n"
        f"🔹 /trendline — Manual trendline scan\n"
        f"🔹 /autoscan — Show auto-scan schedule\n"
        f"🔹 /exchanges — Show active exchanges\n"
        f"🔹 /status — Check configuration\n\n"
        f"Sit back — alerts come automatically! 🚀"
    )


async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a manual price touch scan."""
    user = update.effective_user
    exchanges = get_enabled_exchanges()
    exchange_labels = [EXCHANGE_CONFIGS[e]["label"] for e in exchanges]

    logger.info(f"User {user.first_name} requested a manual scan.")
    await update.message.reply_html(
        f"⏳ <b>Scanning {', '.join(exchange_labels)}...</b>\n"
        "This may take up to 60 seconds. Please wait..."
    )

    try:
        results = await run_price_touch_scan()
        total = sum(len(r["touches"]) for r in results)
        logger.info(f"Scan complete: {total} touches detected.")
        message = format_price_touch_results(results)
        await update.message.reply_html(message)
    except Exception as e:
        logger.error(f"Error during scan: {e}")
        await update.message.reply_html(
            f"❌ <b>Scan failed:</b>\n<code>{e}</code>\n\n"
            "Check your internet connection or API configuration."
        )


async def trendline_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run a manual trendline breakout scan."""
    user = update.effective_user
    logger.info(f"User {user.first_name} requested a manual trendline scan.")

    await update.message.reply_html(
        "📊 <b>Analyzing trendlines on 15-minute charts...</b>\n"
        "This may take up to 120 seconds. Please wait..."
    )

    try:
        breakouts = await run_trendline_scan()
        logger.info(f"Trendline scan complete: {len(breakouts)} breakouts.")
        message = format_trendline_auto_results(breakouts)
        await update.message.reply_html(message)
    except Exception as e:
        logger.error(f"Error during trendline scan: {e}")
        await update.message.reply_html(
            f"❌ <b>Trendline scan failed:</b>\n<code>{e}</code>\n\n"
            "Check your internet connection or API configuration."
        )


async def autoscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show auto-scan configuration and schedule."""
    scan_interval = get_scan_interval()
    trend_interval = get_trendline_interval()
    exchanges = get_enabled_exchanges()
    exchange_labels = [EXCHANGE_CONFIGS[e]["label"] for e in exchanges]

    lines = [
        "🔄 <b>SMC Scanner — Auto-Scan Status</b>\n",
        f"✅ Auto price touch scan: <b>ON</b>",
        f"   Interval: every <b>{scan_interval} minutes</b>\n",
        f"✅ Auto trendline scan: <b>ON</b>",
        f"   Interval: every <b>{trend_interval} minutes</b>\n",
        f"🌐 Exchanges: <code>{', '.join(exchange_labels)}</code>\n",
        "Alerts are sent automatically — no need to type commands!",
    ]

    await update.message.reply_html("\n".join(lines))


async def exchanges_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show which exchanges are active."""
    enabled = get_enabled_exchanges()
    all_exchanges = list(EXCHANGE_CONFIGS.keys())

    lines = ["🌐 <b>SMC Scanner — Exchanges</b>\n"]

    for ex in all_exchanges:
        label = EXCHANGE_CONFIGS[ex]["label"]
        if ex in enabled:
            lines.append(f"✅ <b>{label}</b> — Active")
        else:
            lines.append(f"❌ {label} — Disabled")

    lines.append(
        "\nEdit <code>EXCHANGES</code> in <code>.env</code> to change."
    )
    await update.message.reply_html("\n".join(lines))


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check and report bot configuration status."""
    enabled = get_enabled_exchanges()
    lines = ["📊 <b>SMC Scanner — Status</b>\n"]

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    lines.append("✅ Telegram Bot: Configured" if token else "❌ Telegram Bot: Missing token")

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    lines.append("✅ Telegram Chat: Configured" if chat_id else "❌ Telegram Chat: Missing")

    if enabled:
        labels = [EXCHANGE_CONFIGS[e]["label"] for e in enabled]
        lines.append(f"✅ Exchanges: {', '.join(labels)}")
    else:
        lines.append("❌ No exchanges enabled")

    deepseek = os.getenv("DEEPSEEK_API_KEY")
    lines.append("✅ DeepSeek AI: Configured" if deepseek else "❌ DeepSeek AI: Missing")

    lines.append(f"\n🔄 Auto price touch: every {get_scan_interval()} min")
    lines.append(f"🔄 Auto trendline: every {get_trendline_interval()} min")

    lines.append(f"\n🤖 Bot is running and ready!")
    await update.message.reply_html("\n".join(lines))


# ====== POST-INIT SETUP ======


async def post_init(application: Application) -> None:
    """Called after the Application starts. Launches auto-scan background tasks."""
    logger.info("Starting background auto-scan tasks...")
    asyncio.create_task(auto_price_touch_scan_loop(application))
    asyncio.create_task(auto_trendline_scan_loop(application))
    logger.info("Background auto-scan tasks started.")


# ====== MAIN ======


def main():
    """Start the Telegram bot."""
    print("=" * 50)
    print("  SMC Crypto Futures Scanner Bot")
    print("=" * 50)
    print()

    token = get_bot_token()
    print(f"✅ Bot token loaded: {token[:10]}...")

    enabled = get_enabled_exchanges()
    labels = [EXCHANGE_CONFIGS[e]["label"] for e in enabled]
    print(f"✅ Active exchanges: {', '.join(labels) if enabled else 'NONE!'}")

    scan_int = get_scan_interval()
    trend_int = get_trendline_interval()
    print(f"✅ Auto price touch scan: every {scan_int} min")
    print(f"✅ Auto trendline scan: every {trend_int} min")

    # Build application
    application = Application.builder().token(token).post_init(post_init).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_cmd))
    application.add_handler(CommandHandler("trendline", trendline_cmd))
    application.add_handler(CommandHandler("autoscan", autoscan))
    application.add_handler(CommandHandler("exchanges", exchanges_cmd))
    application.add_handler(CommandHandler("status", status))

    print("✅ Command handlers registered")
    print()
    print("🚀 Bot is running!")
    print("   Auto-scans will alert you automatically 🔄")
    print("   Bot username: @smc_3768745bot")
    print("   Press Ctrl+C to stop.")
    print()

    # Start polling
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()