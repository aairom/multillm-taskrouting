#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# shutdown.sh  —  Gracefully stop the Multi-LLM Task Router server
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/output/server.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "No PID file found at $PID_FILE — server may not be running."
  exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
  echo "Sending SIGTERM to process $PID…"
  kill "$PID"
  # Wait up to 5 seconds for graceful shutdown
  for i in $(seq 1 5); do
    sleep 1
    if ! kill -0 "$PID" 2>/dev/null; then
      echo "  ✅  Server stopped."
      rm -f "$PID_FILE"
      exit 0
    fi
  done
  echo "Process did not stop gracefully — sending SIGKILL."
  kill -9 "$PID"
  rm -f "$PID_FILE"
  echo "  ✅  Server killed."
else
  echo "Process $PID is not running."
  rm -f "$PID_FILE"
fi
