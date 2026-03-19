#!/usr/bin/env bash
set -euo pipefail

CHROME_BIN="${CHROME_BIN:-google-chrome}"
PROFILE_DIR="${AMAZON_REFUND_CHROME_PROFILE:-$HOME/.config/amazon-refund-chrome}"
CDP_PORT="${AMAZON_REFUND_CDP_PORT:-9222}"

"${CHROME_BIN}" \
  --remote-debugging-port="${CDP_PORT}" \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="${PROFILE_DIR}" \
  --no-first-run \
  "https://www.amazon.com" &

echo "Chrome started with CDP on port ${CDP_PORT}."
echo "Log into Amazon in that browser window, then run: ar collect"
