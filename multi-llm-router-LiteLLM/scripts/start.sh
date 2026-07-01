#!/usr/bin/env bash
# scripts/start.sh — Start the Multi-LLM Router (LiteLLM edition) in detached mode
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"
LOG_FILE="$PROJECT_DIR/output/server.log"
PID_FILE="$PROJECT_DIR/output/server.pid"

# ── Ensure virtual environment exists ────────────────────────────────────────
if [ ! -d "$PROJECT_DIR/.venv" ]; then
  echo "[start] Creating virtual environment…"
  python3 -m venv "$PROJECT_DIR/.venv"
fi

# ── Activate and install dependencies ────────────────────────────────────────
source "$PROJECT_DIR/.venv/bin/activate"

echo "[start] Installing / verifying dependencies…"
pip install -q -r "$PROJECT_DIR/requirements.txt"

# ── Copy .env if not present ──────────────────────────────────────────────────
if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo "[start] Created .env from .env.example — edit it to adjust model mappings."
fi

# ── Create output dir ─────────────────────────────────────────────────────────
mkdir -p "$PROJECT_DIR/output"

# ── Launch server in background ───────────────────────────────────────────────
cd "$PROJECT_DIR"
nohup .venv/bin/python app.py --mode server --host "$HOST" --port "$PORT" \
  > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   Multi-LLM Task Router — LiteLLM Edition               ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║   Server started (PID $(cat "$PID_FILE"))                          ║"
echo "║                                                          ║"
echo "║   API:       http://localhost:${PORT}                       ║"
echo "║   Docs:      http://localhost:${PORT}/docs                  ║"
echo "║   Health:    http://localhost:${PORT}/health                ║"
echo "║   Feedback:  http://localhost:${PORT}/feedback              ║"
echo "║                                                          ║"
echo "║   Log file:  output/server.log                           ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
