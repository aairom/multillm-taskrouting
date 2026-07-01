#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# demo.sh  —  Launch the LLM Routing Chat UI and open it in the browser
#
# Usage:
#   ./scripts/demo.sh           # auto-selects a free port starting at 8080
#   PORT=9090 ./scripts/demo.sh # force a specific port
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_FILE="$PROJECT_DIR/output/server.log"
PID_FILE="$PROJECT_DIR/output/server.pid"

mkdir -p "$PROJECT_DIR/output"

# ── Ensure venv ───────────────────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
  echo "[demo] Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

echo "[demo] Verifying dependencies..."
pip install -q -r "$PROJECT_DIR/requirements.txt"

# ── .env ──────────────────────────────────────────────────────────────────────
if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo "[demo] Created .env from .env.example"
fi

# ── Kill stale instance from a previous run of THIS app ───────────────────────
if [ -f "$PID_FILE" ]; then
  OLD=$(cat "$PID_FILE")
  if kill -0 "$OLD" 2>/dev/null; then
    echo "[demo] Stopping previous instance (PID $OLD)..."
    kill "$OLD" && sleep 1
  fi
  rm -f "$PID_FILE"
fi

# ── Find a free port (default 8080, auto-increment if busy) ───────────────────
_want_port="${PORT:-8080}"
PORT="$_want_port"
for _try in $(seq 0 9); do
  _candidate=$(( _want_port + _try ))
  if ! lsof -iTCP:"$_candidate" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
    PORT="$_candidate"
    break
  fi
done

if lsof -iTCP:"$PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
  echo "[demo] ERROR: could not find a free port near $_want_port. Stop other servers first."
  exit 1
fi

[ "$PORT" != "$_want_port" ] && echo "[demo] Port $_want_port busy — using $PORT instead."

# ── Start server ──────────────────────────────────────────────────────────────
echo "[demo] Starting server on port $PORT..."
cd "$PROJECT_DIR"
nohup .venv/bin/python app.py --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

# ── Wait for readiness (up to 10 s) ──────────────────────────────────────────
echo -n "[demo] Waiting for server"
READY=0
for i in $(seq 1 20); do
  sleep 0.5
  if curl -sf "http://localhost:${PORT}/health" > /dev/null 2>&1; then
    echo " ready"
    READY=1
    break
  fi
  echo -n "."
done

if [ "$READY" -eq 0 ]; then
  echo ""
  echo "[demo] Server did not respond in time. Check output/server.log:"
  tail -20 "$LOG_FILE"
  exit 1
fi

# ── Print URL ─────────────────────────────────────────────────────────────────
echo ""
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║   🔀  LLM Routing Chat UI — Ready                        ║"
echo "╠═══════════════════════════════════════════════════════════╣"
echo "║   -> Open in browser:  http://localhost:${PORT}              ║"
echo "║                                                          ║"
echo "║   The chat UI demonstrates intelligent LLM routing:     ║"
echo "║   * Prompt splitting on AND / additionally / plus       ║"
echo "║   * Complexity scoring (0-1) per sub-task               ║"
echo "║   * Model selection via  U = 0.60*Q - 0.40*C           ║"
echo "║   * Parallel execution via LiteLLM -> Ollama            ║"
echo "║   * Live routing card per response                      ║"
echo "║                                                          ║"
echo "║   Stop server:  ./scripts/stop.sh                       ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo ""
echo "  Open:  http://localhost:${PORT}"
echo "  Logs:  output/server.log"
echo "  Stop:  ./scripts/stop.sh"
echo ""
