#!/usr/bin/env bash
# Start the Tadka backend (port 8000) and the dashboard dev server (port 5173) together.
#   ./dev.sh          real camera mode
#   ./dev.sh --demo   simulated stove, no phone needed
set -euo pipefail
cd "$(dirname "$0")"
[[ "${1:-}" == "--demo" ]] && export TADKA_DEMO=1
if [[ ! -d backend/.venv ]]; then
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements-ml.txt
fi
[[ -d web/node_modules ]] || (cd web && npm install)
(cd backend && exec .venv/bin/python -m app) &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT
cd web && npm run dev
