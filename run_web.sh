#!/usr/bin/env bash
# CompanyVerificator – uruchomienie serwera aplikacji
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ ! -f ".venv/bin/uvicorn" ]]; then
    echo "ERROR: .venv nie istnieje. Utwórz je poleceniem:"
    echo "  python3 -m virtualenv .venv && .venv/bin/pip install -r requirements-prod.txt"
    exit 1
fi

if [[ ! -f ".env" ]]; then
    echo "WARN: Brak pliku .env – kopiuję .env.example → .env"
    cp .env.example .env
fi

export PYTHONPATH="$SCRIPT_DIR"

# Odczytaj parametry bezpośrednio z Pythona (który ładuje .env przez python-dotenv)
read -r HOST PORT DEBUG_VAL < <(
    .venv/bin/python3 -c '
from src.config import DEFAULT_HOST, DEFAULT_PORT, DEBUG
print(f"{DEFAULT_HOST} {DEFAULT_PORT} {DEBUG}")
'
)

HOST="${CV_HOST:-${HOST:-127.0.0.1}}"
PORT="${CV_PORT:-${PORT:-8000}}"
LOG_LEVEL="${LOG_LEVEL:-info}"

RELOAD_ARGS=()
if [[ "${DEBUG_VAL,,}" == "true" || "${DEBUG_VAL,,}" == "1" ]]; then
    echo "⚙️  Tryb developerski (CV_DEBUG=true) – przeładowywanie aktywne."
    RELOAD_ARGS=(
        "--reload"
        "--reload-dir" "src"
    )
else
    echo "🚀 Tryb produkcyjny (CV_DEBUG=false) – przeładowywanie wyłączone (oszczędność CPU)."
fi

echo "🛡  CompanyVerificator AML & Compliance Engine"
echo "   http://${HOST}:${PORT}"
echo "   Ctrl+C aby zatrzymać."
echo ""

exec .venv/bin/uvicorn src.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --log-level "$LOG_LEVEL" \
    "${RELOAD_ARGS[@]}"
