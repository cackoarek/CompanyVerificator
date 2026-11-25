#!/usr/bin/env bash
# CompanyVerificator – uruchomienie serwera deweloperskiego
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f ".venv/bin/uvicorn" ]]; then
    echo "ERROR: .venv nie istnieje. Utwórz je poleceniem:"
    echo "  python3 -m virtualenv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

if [[ ! -f ".env" ]]; then
    echo "WARN: Brak pliku .env – kopiuję .env.example → .env"
    cp .env.example .env
fi

export PYTHONPATH="$SCRIPT_DIR"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
LOG_LEVEL="${LOG_LEVEL:-info}"

echo "🛡  CompanyVerificator AML & Compliance Engine"
echo "   http://${HOST}:${PORT}"
echo "   Ctrl+C aby zatrzymać."
echo ""

exec .venv/bin/uvicorn src.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level "$LOG_LEVEL" \
    --reload
