#!/usr/bin/env bash
# scripts/stop.sh — Gracefully stop the Multi-LLM Router server
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PID_FILE="$PROJECT_DIR/output/server.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "[stop] No PID file found at $PID_FILE — server may not be running."
  exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
  echo "[stop] Sending SIGTERM to PID $PID…"
  kill -TERM "$PID"
  # Wait up to 5 seconds for graceful shutdown
  for i in $(seq 1 10); do
    sleep 0.5
    if ! kill -0 "$PID" 2>/dev/null; then
      break
    fi
  done
  if kill -0 "$PID" 2>/dev/null; then
    echo "[stop] Process still alive — sending SIGKILL…"
    kill -KILL "$PID"
  fi
  rm -f "$PID_FILE"
  echo "[stop] Server stopped."
else
  echo "[stop] No process found for PID $PID — removing stale PID file."
  rm -f "$PID_FILE"
fi
