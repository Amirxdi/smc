#!/usr/bin/env python3
"""
Main entry point for SMC Crypto Futures Scanner.
Launches the Telegram bot with a lightweight HTTP health-check server
for Render deployment.
"""

import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram_bot import main as start_bot


class HealthHandler(BaseHTTPRequestHandler):
    """Minimal health-check endpoint for Render."""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"SMC Scanner Bot is running")

    def log_message(self, format, *args):
        pass  # Suppress HTTP logs


def run_health_server():
    """Start a lightweight HTTP server on $PORT for Render health checks."""
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"✅ Health server listening on port {port}")
    server.serve_forever()


if __name__ == "__main__":
    # Start health server in a background thread
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    # Start the Telegram bot (blocking)
    start_bot()