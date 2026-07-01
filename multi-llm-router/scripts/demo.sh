#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# demo.sh  —  Run the worked scenario from the command line (no server needed)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "Virtual environment not found.  Run ./scripts/launch.sh first, or:"
  echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

source "$VENV_DIR/bin/activate"

cd "$PROJECT_DIR"

# Optional: export DRY_RUN=1 to skip LLM calls and only show routing table
export DRY_RUN="${DRY_RUN:-0}"

echo ""
echo "Running the documentation-vs-code routing scenario…"
echo "(Set DRY_RUN=1 to skip LLM calls and inspect routing only)"
echo ""

python app.py --mode demo
