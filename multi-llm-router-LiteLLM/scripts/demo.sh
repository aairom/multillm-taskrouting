#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# demo.sh  —  Run the worked routing scenario in the terminal (no server needed)
#
# What it does:
#   1. Activates the virtual environment (creates it + installs deps if absent)
#   2. Copies .env.example → .env if .env is missing
#   3. Runs the demo scenario:
#        "Write the API docs AND implement the OAuth2 middleware"
#      → Split into 2 sub-tasks
#      → Classified + routed via the utility function U = β·Q − α·C
#      → Dispatched in parallel through the LiteLLM AI Gateway Router → Ollama
#      → Merged Markdown response printed to the terminal
#
# Usage:
#   ./scripts/demo.sh              # full run (calls Ollama)
#   DRY_RUN=1 ./scripts/demo.sh    # routing table only, no LLM calls
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

# ── Ensure virtual environment ────────────────────────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
  echo "[demo] Virtual environment not found — creating it…"
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

# ── Install / verify dependencies ─────────────────────────────────────────────
echo "[demo] Verifying dependencies (litellm, fastapi, uvicorn)…"
pip install -q -r "$PROJECT_DIR/requirements.txt"

# ── Copy .env if missing ──────────────────────────────────────────────────────
if [ ! -f "$PROJECT_DIR/.env" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  echo "[demo] Created .env from .env.example — edit it to adjust model mappings."
fi

# ── Ensure output directory exists ────────────────────────────────────────────
mkdir -p "$PROJECT_DIR/output"

# ── Optional dry-run mode ─────────────────────────────────────────────────────
export DRY_RUN="${DRY_RUN:-0}"

echo ""
if [ "$DRY_RUN" = "1" ]; then
  echo "┌──────────────────────────────────────────────────────────────┐"
  echo "│  DRY RUN MODE — routing table shown, no LLM calls made      │"
  echo "└──────────────────────────────────────────────────────────────┘"
else
  echo "┌──────────────────────────────────────────────────────────────┐"
  echo "│  Multi-LLM Task Router — LiteLLM Edition  demo              │"
  echo "│  Gateway: LiteLLM AI Router → Ollama (localhost:11434)      │"
  echo "│                                                              │"
  echo "│  Tip: set DRY_RUN=1 to inspect routing without LLM calls    │"
  echo "└──────────────────────────────────────────────────────────────┘"
fi
echo ""

cd "$PROJECT_DIR"
python app.py --mode demo
