"""Mechanizmy bezpieczeństwa warstwy webowej (CSRF, Open Redirect, HTTPS, Rate Limiting)."""

import os
import time
import urllib.parse
from collections import defaultdict
from typing import Dict, List

from fastapi import Request

_login_attempts: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT_MAX_ATTEMPTS = 5


def get_lockout_seconds() -> float:
    from src.config import LOGIN_LOCKOUT_HOURS
    try:
        val = float(os.getenv("LOGIN_LOCKOUT_HOURS", str(LOGIN_LOCKOUT_HOURS)))
        return max(val * 3600.0, 60.0)
    except Exception:
        return 5 * 3600.0


def reset_login_rate_limits() -> None:
    """Czyści licznik prób logowania (używane w testach)."""
    _login_attempts.clear()


def is_ip_locked_out(client_ip: str) -> bool:
    """Sprawdza czy dane IP jest obecnie zablokowane z powodu zbyt wielu błędnych prób."""
    now = time.time()
    lockout_sec = get_lockout_seconds()
    attempts = _login_attempts[client_ip]
    attempts[:] = [t for t in attempts if now - t < lockout_sec]
    return len(attempts) >= _RATE_LIMIT_MAX_ATTEMPTS


def record_failed_login_attempt(client_ip: str) -> None:
    """Rejestruje nieudaną próbę logowania dla danego IP."""
    _login_attempts[client_ip].append(time.time())


def check_login_rate_limit(client_ip: str) -> bool:
    """Zwraca True jeśli IP nie jest zablokowane (kompatybilność wsteczna)."""
    return not is_ip_locked_out(client_ip)


def is_secure_request(request: Request) -> bool:
    """Wykrywa połączenie HTTPS (bezpośrednie lub za reverse-proxy)."""
    if os.getenv("CV_COOKIE_SECURE", "").lower() in ("1", "true", "yes"):
        return True
    if request.url.scheme == "https":
        return True
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return False


def is_safe_redirect_url(url: str) -> bool:
    """Ochrona przed Open Redirect (akceptuje wyłącznie bezpieczne ścieżki względne)."""
    if not url:
        return False
    clean = url.strip()
    if not clean.startswith("/") or clean.startswith("//") or clean.startswith("/\\"):
        return False
    if any(c in clean for c in ("\r", "\n", "\t", "\x00", "\\")):
        return False
    try:
        parsed = urllib.parse.urlsplit(clean)
        return not parsed.scheme and not parsed.netloc
    except Exception:
        return False


def is_trusted_origin(request: Request) -> bool:
    """Weryfikuje nagłówki Origin i Referer przed atakami CSRF."""
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    host = request.headers.get("host")

    trusted_hosts = {"127.0.0.1", "localhost", "testserver"}
    if host:
        host_clean = host.split(":")[0].lower()
        if host_clean:
            trusted_hosts.add(host_clean)

    for header_val in (origin, referer):
        if not header_val:
            continue
        if header_val.strip().lower() == "null":
            return False
        try:
            parsed = urllib.parse.urlsplit(header_val)
            header_host = (parsed.hostname or "").lower()
            if header_host and header_host not in trusted_hosts:
                return False
        except Exception:
            return False

    return True
