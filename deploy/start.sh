#!/bin/bash
# ── SEACE Dashboard — Start backend ──────────────────────────────────────────
# Run this via SSH or cPanel Terminal to start the Python backend.
# The FastAPI server binds to 127.0.0.1:8765 (not exposed to the internet).
#
# Usage:
#   bash ~/seace-scraper/deploy/start.sh
#
# To stop:
#   bash ~/seace-scraper/deploy/stop.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/.seace_pid"
LOG_FILE="$PROJECT_DIR/logs/dashboard.log"

mkdir -p "$PROJECT_DIR/logs"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "SEACE backend already running (PID $OLD_PID)"
        exit 0
    fi
    rm -f "$PID_FILE"
fi

echo "Starting SEACE backend..."
cd "$PROJECT_DIR"
source .venv/bin/activate

nohup python main.py dashboard --host 127.0.0.1 --port 8765 \
    >> "$LOG_FILE" 2>&1 &

PID=$!
echo $PID > "$PID_FILE"
echo "Started with PID $PID  (log: $LOG_FILE)"
echo "Dashboard accessible at your subdirectory URL."
