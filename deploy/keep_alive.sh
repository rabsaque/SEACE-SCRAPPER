#!/bin/bash
# ── SEACE keep-alive — run this via cPanel Cron Jobs ─────────────────────────
# Checks if the backend is running and restarts it if not.
# Recommended cron schedule: every 5 minutes
#
# cPanel Cron Jobs entry:
#   */5 * * * * /home/YOUR_CPANEL_USER/seace-scraper/deploy/keep_alive.sh >> /home/YOUR_CPANEL_USER/seace-scraper/logs/cron.log 2>&1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/.seace_pid"
LOG_FILE="$PROJECT_DIR/logs/dashboard.log"

mkdir -p "$PROJECT_DIR/logs"

is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill -0 "$PID" 2>/dev/null && return 0
    fi
    # Also check by process name in case PID file is stale
    pgrep -f "main.py dashboard" > /dev/null 2>&1 && return 0
    return 1
}

if is_running; then
    echo "[$(date)] SEACE backend is running — OK"
else
    echo "[$(date)] SEACE backend not running — restarting..."
    cd "$PROJECT_DIR"
    source .venv/bin/activate
    nohup python main.py dashboard --host 127.0.0.1 --port 8765 \
        >> "$LOG_FILE" 2>&1 &
    PID=$!
    echo $PID > "$PID_FILE"
    echo "[$(date)] Restarted with PID $PID"
fi
