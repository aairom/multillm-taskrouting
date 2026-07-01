#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# launch.sh  —  Start the Multi-LLM Task Router in detached mode
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_FILE="$PROJECT_DIR/output/server.log"
PID_FILE="$PROJECT_DIR/output/server.pid"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

# Ensure output directory exists
mkdir -p "$PROJECT_DIR/output"

# Create virtual environment if missing
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# Install dependencies
pip install -q -r "$PROJECT_DIR/requirements.txt"

# Copy .env.example → .env if .env does not exist
if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo "Created .env from .env.example — edit it to configure your Ollama models."
fi

# Kill any existing instance
if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping previous instance (PID $OLD_PID)…"
    kill "$OLD_PID"
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

# Launch server in background
echo "Starting Multi-LLM Task Router on http://$HOST:$PORT …"
cd "$PROJECT_DIR"
nohup "$VENV_DIR/bin/python" app.py --mode server --host "$HOST" --port "$PORT" \
  >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

sleep 1
echo ""
echo "  ✅  Server running  → http://localhost:$PORT"
echo "  📋  API docs        → http://localhost:$PORT/docs"
echo "  📊  Feedback stats  → http://localhost:$PORT/feedback"
echo "  📄  Logs            → $LOG_FILE"
echo "  🔴  Stop server     → ./scripts/shutdown.sh"
