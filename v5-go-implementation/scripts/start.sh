#!/usr/bin/env bash
# start.sh — launch routing-v5 (Go) in detached mode
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
LOG="$ROOT/output/routing-v5.log"
PID_FILE="$ROOT/output/routing-v5.pid"
PORT="${PORT:-8080}"

mkdir -p "$ROOT/output"
cd "$ROOT"

# Build first
echo "⚙️  Building routing-v5..."
go build -o routing-v5 . 2>&1 | tee "$LOG"

echo "🚀 Starting routing-v5 on port $PORT..."
nohup ./routing-v5 >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"

echo ""
echo "✅ routing-v5 is running  (PID $(cat "$PID_FILE"))"
echo "🌐 URL: http://localhost:$PORT"
echo "📋 Logs: $LOG"
