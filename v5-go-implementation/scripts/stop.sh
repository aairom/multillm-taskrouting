#!/usr/bin/env bash
# stop.sh — gracefully stop routing-v5 (Go)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
PID_FILE="$ROOT/output/routing-v5.pid"
BINARY="$ROOT/routing-v5"

if [ ! -f "$PID_FILE" ]; then
  echo "⚠️  No PID file found at $PID_FILE — is routing-v5 running?"
  exit 1
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
  echo "🛑 Stopping routing-v5 (PID $PID)..."
  kill -TERM "$PID"
  sleep 1
  kill -0 "$PID" 2>/dev/null && kill -KILL "$PID" || true
  echo "✅ Stopped."
else
  echo "⚠️  Process $PID not found — already stopped?"
fi

rm -f "$PID_FILE" "$BINARY"
