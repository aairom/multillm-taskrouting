#!/usr/bin/env bash
# scripts/start.sh — Start the Routing Chat UI server in detached mode
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"
LOG_FILE="$PROJECT_DIR/output/server.log"
PID_FILE="$PROJECT_DIR/output/server.pid"

mkdir -p "$PROJECT_DIR/output"

if [ ! -d "$VENV_DIR" ]; then
  echo "[start] Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
echo "[start] Installing dependencies..."
pip install -q -r "$PROJECT_DIR/requirements.txt"

if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo "[start] Created .env from .env.example"
fi

# Kill stale instance
if [ -f "$PID_FILE" ]; then
  OLD=$(cat "$PID_FILE")
  kill -0 "$OLD" 2>/dev/null && kill "$OLD" && sleep 1
  rm -f "$PID_FILE"
fi

cd "$PROJECT_DIR"
nohup .venv/bin/python app.py --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   LLM Routing Chat UI                                    ║"
echo "╠═══════════════════════════════════════════════════════════╣"
printf "║   Chat UI:   http://localhost:%-28s ║\n" "$PORT"
printf "║   API docs:  http://localhost:$PORT/api/docs%-14s ║\n" " "
printf "║   Health:    http://localhost:$PORT/health%-16s ║\n" " "
echo "║                                                          ║"
echo "║   Log:  output/server.log   Stop: ./scripts/stop.sh     ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "  → Open http://localhost:${PORT} in your browser"
echo ""
