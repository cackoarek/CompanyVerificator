"""Centralna konfiguracja aplikacji CompanyVerificator."""

import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def get_data_dir() -> Path:
    """Zwraca katalog bazowy na bazę SQLite i archiwum dowodowe."""
    raw = os.getenv("CV_DATA_DIR", "data").strip() or "data"
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


DATA_DIR = get_data_dir()
AUDITS_DIR = DATA_DIR / "audits"
DB_PATH = DATA_DIR / "company_verificator.db"

WEB_DIR = Path(__file__).resolve().parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

DEFAULT_HOST = os.getenv("CV_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("CV_PORT", "8000"))
DEBUG = os.getenv("CV_DEBUG", "false").lower() in ("1", "true", "yes")

COOKIE_AUTH_TOKEN = "cv_access_token"
ACCESS_TOKEN = os.getenv("CV_ACCESS_TOKEN", "").strip()

# Ochrona hasłem strony WWW (WEB_PASSWORD)
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "").strip()
LOGIN_LOCKOUT_HOURS = float(os.getenv("LOGIN_LOCKOUT_HOURS", "5"))

CEIDG_API_TOKEN = os.getenv("CEIDG_API_TOKEN", "").strip()
CACHE_TTL_HOURS = int(os.getenv("CV_CACHE_TTL_HOURS", "24"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("CV_HTTP_TIMEOUT_SECONDS", "8.0"))
BATCH_CONCURRENCY = int(os.getenv("CV_BATCH_CONCURRENCY", "4"))
PAYMENT_THRESHOLD_PLN = Decimal(os.getenv("CV_PAYMENT_THRESHOLD_PLN", "15000.00"))

# Plik logów aplikacji
LOG_FILE_PATH = PROJECT_ROOT / "companyVerificator.log"

APP_USER_AGENT = "CompanyVerificator/0.1.0 (Compliance & AML)"

# GUS REGON (Baza BIR 1.1)
GUS_ENABLED = os.getenv("GUS_ENABLED", "true").lower() in ("1", "true", "yes")
GUS_API_URL = os.getenv(
    "GUS_API_URL", "https://wyszukiwarkaregontest.stat.gov.pl/wsBIR/UslugaBIRzewnPubl.svc"
).strip()
# Domyślnie publiczny klucz testowy GUS; po otrzymaniu z maila regon_bir@stat.gov.pl wpisujemy w .env produkcyjny
GUS_USER_KEY = os.getenv("GUS_USER_KEY", "abcde12345abcde12345").strip()

# Uprawnienia do usuwania wpisów i czyszczenia historii (Delete)
ALLOW_DELETION = os.getenv("CV_ALLOW_DELETION", "true").lower() in ("1", "true", "yes")

# Strefa czasowa aplikacji (np. Europe/Warsaw)
APP_TIMEZONE = os.getenv("CV_TIMEZONE", os.getenv("TZ", "Europe/Warsaw")).strip() or "Europe/Warsaw"

