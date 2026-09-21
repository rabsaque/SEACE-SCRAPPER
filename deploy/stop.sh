#!/bin/bash
# Stop the SEACE backend process

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/.seace_pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found. Trying to find process..."
    pkill -f "main.py dashboard" && echo "Stopped." || echo "No running process found."
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    rm -f "$PID_FILE"
    echo "Stopped SEACE backend (PID $PID)"
else
    echo "Process $PID not running. Cleaning up PID file."
    rm -f "$PID_FILE"
fi
