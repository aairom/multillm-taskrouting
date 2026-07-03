#!/usr/bin/env bash
# scripts/stop.sh — Gracefully stop routing-v4
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$(dirname "$SCRIPT_DIR")/output/server.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "[stop] No PID file found — server may not be running."
  exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
  echo "[stop] Stopping routing-v4 (PID $PID)…"
  kill -TERM "$PID"
  for i in $(seq 1 10); do
    sleep 0.5
    kill -0 "$PID" 2>/dev/null || break
  done
  kill -0 "$PID" 2>/dev/null && kill -KILL "$PID"
  rm -f "$PID_FILE"
  echo "[stop] Server stopped."
else
  echo "[stop] No process at PID $PID — removing stale PID file."
  rm -f "$PID_FILE"
fi
