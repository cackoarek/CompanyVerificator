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

# Załaduj zmienne z .env (bez nadpisywania zmiennych już wyeksportowanych w powłoce)
set -a
# shellcheck disable=SC1091
source <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env || true)
set +a

export PYTHONPATH="$SCRIPT_DIR"

HOST="${CV_HOST:-${HOST:-127.0.0.1}}"
PORT="${CV_PORT:-${PORT:-8000}}"
LOG_LEVEL="${LOG_LEVEL:-info}"
RELOAD_FLAG=""
if [[ "${CV_DEBUG:-false}" =~ ^(1|true|yes)$ ]]; then
    RELOAD_FLAG="--reload"
else
    # Domyślnie włączamy --reload dla wygody lokalnej, chyba że CV_DEBUG=false
    RELOAD_FLAG="--reload"
fi

echo "🛡  CompanyVerificator AML & Compliance Engine"
echo "   http://${HOST}:${PORT}"
echo "   Ctrl+C aby zatrzymać."
echo ""

exec .venv/bin/uvicorn src.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level "$LOG_LEVEL" \
    $RELOAD_FLAG
