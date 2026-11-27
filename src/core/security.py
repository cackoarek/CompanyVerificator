import hashlib
import hmac
import os
import secrets
import time
import urllib.parse
from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import Request

_login_attempts: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT_MAX_ATTEMPTS = 5
DEFAULT_SESSION_MAX_AGE_SECONDS = 12 * 3600.0  # 12 godzin


def _get_signing_key(secret: str) -> bytes:
    """Tworzy bezpieczny klucz sygnatury z sekretu aplikacji."""
    return hashlib.sha256(f"cv-session-key:{secret}".encode("utf-8")).digest()


def create_session_token(secret: str, max_age: float = DEFAULT_SESSION_MAX_AGE_SECONDS) -> str:
    """Generuje kryptograficznie podpisany token sesji z timestampem (HMAC-SHA256).
    
    Format: timestamp.random_nonce.hmac_signature
    """
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    payload = f"{ts}.{nonce}"
    sig = hmac.new(_get_signing_key(secret), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: str, secret: str, max_age: float = DEFAULT_SESSION_MAX_AGE_SECONDS) -> bool:
    """Weryfikuje autentyczność, podpis HMAC oraz ważność czasową tokena sesyjnego."""
    if not token or not secret:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        # Obsługa kompatybilności wstecznej (dla surowego tokena)
        return secrets.compare_digest(token, secret)

    ts_str, nonce, received_sig = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return False

    # Sprawdzenie ważności czasowej
    now = time.time()
    if now < ts - 60 or now - ts > max_age:
        return False

    payload = f"{ts_str}.{nonce}"
    expected_sig = hmac.new(_get_signing_key(secret), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return secrets.compare_digest(received_sig, expected_sig)


def is_request_authenticated(request: Request) -> bool:
    """Sprawdza, czy bieżące żądanie posiada uwierzytelnioną sesję użytkownika / analityka."""
    from src.config import ACCESS_TOKEN, COOKIE_AUTH_TOKEN, WEB_PASSWORD

    required_web_pass = os.getenv("WEB_PASSWORD", "").strip() or WEB_PASSWORD
    required_token = os.getenv("CV_ACCESS_TOKEN", "").strip() or ACCESS_TOKEN

    # Jeśli nie ustawiono ani hasła ani tokena, dostęp jest w pełni otwarty
    if not required_web_pass and not required_token:
        return True

    if required_web_pass:
        cookie_val = request.cookies.get(COOKIE_AUTH_TOKEN, "")
        return bool(cookie_val and verify_session_token(cookie_val, required_web_pass))

    if required_token:
        token_candidate = None
        auth_header = request.headers.get("authorization", "")
        if auth_header:
            token_candidate = auth_header.split()[-1]
        if not token_candidate:
            token_candidate = request.cookies.get(COOKIE_AUTH_TOKEN) or request.headers.get("x-access-token")
        if token_candidate:
            return bool(
                secrets.compare_digest(token_candidate, required_token)
                or verify_session_token(token_candidate, required_token)
            )

    return False


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


_verify_attempts: Dict[str, List[float]] = defaultdict(list)
_VERIFY_MAX_RPM = 60  # Maksymalnie 60 zapytań weryfikacyjnych na minutę z jednego IP


def check_verify_rate_limit(client_ip: str, max_requests: int = _VERIFY_MAX_RPM, window_seconds: float = 60.0) -> bool:
    """Ochrona przed floodem zapytań do rejestrów rządowych (Sliding Window Rate Limiter).
    
    Zwraca True jeśli żądanie mieści się w limicie, False jeśli przekroczono.
    """
    now = time.time()
    history = _verify_attempts[client_ip]
    history[:] = [t for t in history if now - t < window_seconds]
    if len(history) >= max_requests:
        return False
    history.append(now)
    return True


def reset_verify_rate_limits() -> None:
    """Czyści licznik prób weryfikacji (używane w testach)."""
    _verify_attempts.clear()



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
