#!/usr/bin/env python3
"""
main.py — Entry point for SMC Crypto Futures Scanner (v2.0).

Improvements over v1:
- Graceful shutdown on SIGINT/SIGTERM
- Crash auto-restart (wraps bot start in a retry loop)
- Health-check HTTP server for Render/Railway
- Logging configuration
"""

import asyncio
import logging
import os
import signal
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import HEALTH_PORT, LOG_LEVEL

# Must configure logging before importing other modules
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Health server (for Render / Railway) ────────────────────────────────


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal health-check endpoint."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"SMC Scanner Bot v2.0 is running")

    def log_message(self, fmt, *args):
        pass  # suppress HTTP debug logs


def run_health_server():
    """Run a lightweight HTTP health server in a background thread."""
    port = HEALTH_PORT
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info("Health server listening on port %d", port)
    server.serve_forever()


# ─── Graceful shutdown ───────────────────────────────────────────────────


_shutdown_event = threading.Event()


def _signal_handler(signum, frame):
    logger.info("Received signal %d — shutting down…", signum)
    _shutdown_event.set()


def _register_signal_handlers():
    """Register OS signal handlers for graceful shutdown."""
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)


# ─── Main runner with auto-restart ───────────────────────────────────────


def run_bot():
    """
    Start the Telegram bot with automatic crash recovery.
    Loops forever, restarting the bot on unexpected errors or
    when the polling connection drops (Telegram long-polling
    connections often time out after ~30–50 minutes).
    """
    from telegram_bot import main as bot_main

    max_restarts = 9999       # practically infinite
    restart_count = 0
    base_delay = 5  # seconds

    while not _shutdown_event.is_set():
        if restart_count >= max_restarts:
            logger.critical("Max restarts (%d) reached — giving up", max_restarts)
            sys.exit(1)

        try:
            logger.info(
                "Starting bot (restart #%d)…",
                restart_count,
            )
            bot_main()
            # bot_main() blocks — if it returns (even "cleanly"),
            # it's usually because the long-polling connection
            # dropped.  We restart instead of exiting.
            restart_count += 1
            delay = min(base_delay * (2 ** min(restart_count - 1, 5)), 300)
            logger.info(
                "Bot polling returned (restart #%d). Restarting in %ds…",
                restart_count, delay,
            )
            _shutdown_event.wait(delay)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received.")
            break
        except SystemExit as e:
            # Config validation failures exit with code 1 — don't restart
            if e.code != 0:
                logger.error("Bot exited with code %d — stopping.", e.code)
                sys.exit(e.code)
            logger.info("SystemExit(0) — stopping.")
            break
        except Exception as e:
            restart_count += 1
            delay = min(base_delay * (2 ** min(restart_count - 1, 5)), 300)
            logger.exception(
                "Bot crashed (restart #%d). Restarting in %ds…",
                restart_count, delay,
            )
            _shutdown_event.wait(delay)

    logger.info("Main loop exited.")


# ─── Main ────────────────────────────────────────────────────────────────


def main():
    print("=" * 50)
    print("  SMC Crypto Futures Scanner v2.0")
    print("  Starting up…")
    print("=" * 50)

    # Signal handlers for graceful shutdown
    _register_signal_handlers()

    # Health server thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info("Health server thread started on port %d", HEALTH_PORT)

    # Run the bot with auto-restart
    run_bot()

    print("\nBot has stopped. Goodbye!")


if __name__ == "__main__":
    main()