"""Główny punkt wejścia aplikacji webowej CompanyVerificator (FastAPI)."""

import html
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from src import __version__
from src.config import (
    ACCESS_TOKEN,
    AUDITS_DIR,
    COOKIE_AUTH_TOKEN,
    DB_PATH,
    DEBUG,
    DEFAULT_HOST,
    DEFAULT_PORT,
    LOGIN_LOCKOUT_HOURS,
    STATIC_DIR,
    WEB_PASSWORD,
)
from src.core.database import Database
from src.core.logging_config import app_logger
from src.core.security import (
    is_ip_locked_out,
    is_safe_redirect_url,
    is_secure_request,
    is_trusted_origin,
    record_failed_login_attempt,
)
from src.providers.sanctions.sync_service import seed_default_sanctions
from src.web.routers import batch, history, sanctions, verify


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicjalizuje bazę SQLite, katalog audytów oraz referencyjne listy sankcyjne."""
    if not getattr(app.state, "db", None):
        app.state.db = Database(DB_PATH)
    if not getattr(app.state, "audits_dir", None):
        app.state.audits_dir = AUDITS_DIR
    seed_default_sanctions(app.state.db)
    yield


app = FastAPI(
    title="CompanyVerificator",
    description="System weryfikacji firm pod kątem AML, Compliance i Należytej Staranności",
    version=__version__,
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Dodaje nagłówki bezpieczeństwa HTTP do wszystkich odpowiedzi."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    return response


@app.middleware("http")
async def csrf_origin_protection_middleware(request: Request, call_next):
    """Chroni żądania mutujące stan przed atakami CSRF."""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if not is_trusted_origin(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF: Odrzucono żądanie z niezaufanego źródła (Origin/Referer)"},
            )
    return await call_next(request)


@app.middleware("http")
async def optional_token_auth_middleware(request: Request, call_next):
    """
    Ochrona aplikacji:
    1. Jeśli ustawione jest WEB_PASSWORD w .env -> wymaga hasła do panelu webowego.
    2. Jeśli ustawione jest CV_ACCESS_TOKEN -> wymaga tokena Bearer / x-access-token / cookie.
    3. Jeśli oba są puste -> dostęp otwarty bez konieczności logowania.
    """
    required_web_pass = os.getenv("WEB_PASSWORD", "").strip() or WEB_PASSWORD
    required_token = os.getenv("CV_ACCESS_TOKEN", "").strip() or ACCESS_TOKEN

    path = request.url.path
    if path.startswith("/static") or path in ("/health", "/favicon.ico", "/login", "/logout"):
        return await call_next(request)

    # 1. Sprawdzenie WEB_PASSWORD
    if required_web_pass:
        cookie_val = request.cookies.get(COOKIE_AUTH_TOKEN, "")
        if not cookie_val or not secrets.compare_digest(cookie_val, required_web_pass):
            client_ip = request.client.host if request.client else "127.0.0.1"
            safe_redirect = html.escape(request.url.path if is_safe_redirect_url(request.url.path) else "/", quote=True)
            locked = is_ip_locked_out(client_ip)
            lockout_h = int(float(os.getenv("LOGIN_LOCKOUT_HOURS", str(LOGIN_LOCKOUT_HOURS))))

            if "text/html" in request.headers.get("accept", ""):
                if locked:
                    app_logger.warning(f"Odrzucono żądanie z zablokowanego IP: {client_ip}")
                    return HTMLResponse(
                        content=f"""<!DOCTYPE html><html lang="pl"><head><meta charset="utf-8"><title>Blokada IP</title>
                        <script src="https://cdn.tailwindcss.com"></script></head>
                        <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4">
                        <div class="bg-white p-6 rounded-2xl border border-red-200 shadow-sm max-w-sm w-full text-center space-y-3">
                        <div class="text-3xl">🚫</div>
                        <h1 class="text-base font-bold text-slate-900">Dostęp tymczasowo zablokowany</h1>
                        <p class="text-xs text-slate-500">Przekroczono limit 5 nieudanych prób logowania z adresu <code>{client_ip}</code>. Kolejna próba możliwa za {lockout_h}h.</p>
                        </div></body></html>""",
                        status_code=429,
                        headers={"Cache-Control": "no-store"},
                    )

                return HTMLResponse(
                    content=f"""<!DOCTYPE html><html lang="pl"><head><meta charset="utf-8"><title>Logowanie – CompanyVerificator</title>
                    <script src="https://cdn.tailwindcss.com"></script></head>
                    <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4">
                    <form method="POST" action="/login" class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm max-w-sm w-full space-y-4">
                    <div class="space-y-1">
                      <h1 class="text-base font-bold text-slate-900">🔒 Wymagane hasło dostępu</h1>
                      <p class="text-xs text-slate-500">Dostęp do panelu CompanyVerificator jest chroniony hasłem.</p>
                    </div>
                    <input type="hidden" name="redirect_url" value="{safe_redirect}">
                    <div>
                      <input type="password" name="password" required autofocus placeholder="Wpisz hasło z .env (WEB_PASSWORD)" class="w-full px-3 py-2 text-xs border rounded-lg focus:ring-2 focus:ring-blue-500 focus:outline-none">
                    </div>
                    <button type="submit" class="w-full py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-bold transition-colors cursor-pointer">Odblokuj panel</button>
                    </form></body></html>""",
                    status_code=401,
                    headers={"Cache-Control": "no-store"},
                )
            return JSONResponse(status_code=401, content={"detail": "Wymagane logowanie (WEB_PASSWORD)"})

    # 2. Sprawdzenie tokena API (jeśli zdefiniowany, a brak WEB_PASSWORD)
    elif required_token:
        token_candidate = None
        auth_header = request.headers.get("authorization", "")
        if auth_header:
            token_candidate = auth_header.split()[-1]
        if not token_candidate:
            token_candidate = request.cookies.get(COOKIE_AUTH_TOKEN) or request.headers.get("x-access-token")

        if not (token_candidate and len(token_candidate) <= 256 and secrets.compare_digest(token_candidate, required_token)):
            safe_redirect = html.escape(request.url.path if is_safe_redirect_url(request.url.path) else "/", quote=True)
            if "text/html" in request.headers.get("accept", ""):
                return HTMLResponse(
                    content=f"""<!DOCTYPE html><html lang="pl"><head><meta charset="utf-8"><title>Autoryzacja</title>
                    <script src="https://cdn.tailwindcss.com"></script></head>
                    <body class="bg-slate-50 flex items-center justify-center min-h-screen p-4">
                    <form method="POST" action="/login" class="bg-white p-6 rounded-xl border border-slate-200 shadow-sm max-w-sm w-full space-y-3">
                    <h1 class="text-base font-bold text-slate-900">Wymagany Token Dostępu</h1>
                    <input type="hidden" name="redirect_url" value="{safe_redirect}">
                    <input type="password" name="token" required placeholder="CV_ACCESS_TOKEN" class="w-full px-3 py-2 text-sm border rounded-lg">
                    <button type="submit" class="w-full py-2 bg-blue-600 text-white rounded-lg text-sm font-bold">Zaloguj</button>
                    </form></body></html>""",
                    status_code=401,
                    headers={"Cache-Control": "no-store"},
                )
            return JSONResponse(status_code=401, content={"detail": "Wymagana autoryzacja (CV_ACCESS_TOKEN)"})

    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(verify.router)
app.include_router(batch.router)
app.include_router(history.router)
app.include_router(sanctions.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "app": "CompanyVerificator", "version": __version__}


@app.post("/login")
async def login_post(request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    lockout_h = int(float(os.getenv("LOGIN_LOCKOUT_HOURS", str(LOGIN_LOCKOUT_HOURS))))

    if is_ip_locked_out(client_ip):
        app_logger.warning(f"Próba logowania z zablokowanego adresu IP: {client_ip}")
        return JSONResponse(
            status_code=429,
            content={"detail": f"Zbyt wiele błędnych prób logowania. Adres IP zablokowany na {lockout_h}h."},
            headers={"Retry-After": str(int(lockout_h * 3600))},
        )

    required_web_pass = os.getenv("WEB_PASSWORD", "").strip() or WEB_PASSWORD
    required_token = os.getenv("CV_ACCESS_TOKEN", "").strip() or ACCESS_TOKEN
    form_data = await request.form()

    # Logowanie hasłem (WEB_PASSWORD) lub tokenem
    pass_candidate = str(form_data.get("password", "")).strip()
    token_candidate = str(form_data.get("token", "")).strip()

    is_valid = False
    auth_secret = ""

    if required_web_pass:
        auth_secret = required_web_pass
        if pass_candidate and secrets.compare_digest(pass_candidate, required_web_pass):
            is_valid = True
    elif required_token:
        auth_secret = required_token
        candidate = token_candidate or pass_candidate
        if candidate and secrets.compare_digest(candidate, required_token):
            is_valid = True
    else:
        is_valid = True

    if is_valid:
        app_logger.info(f"Pomyślne logowanie do panelu z adresu IP: {client_ip}")
        raw_redirect = str(form_data.get("redirect_url", "/")).strip()
        target_url = raw_redirect if is_safe_redirect_url(raw_redirect) else "/"
        resp = RedirectResponse(url=target_url, status_code=303)
        if auth_secret:
            resp.set_cookie(
                key=COOKIE_AUTH_TOKEN,
                value=auth_secret,
                httponly=True,
                secure=is_secure_request(request),
                samesite="lax",
            )
        return resp

    # Błędne logowanie
    record_failed_login_attempt(client_ip)
    app_logger.warning(f"Nieudana próba logowania do panelu z adresu IP: {client_ip}")
    time.sleep(0.5)

    if is_ip_locked_out(client_ip):
        app_logger.error(f"Adres IP {client_ip} został zablokowany na {lockout_h}h po 5 nieudanych próbach logowania")
        return JSONResponse(
            status_code=429,
            content={"detail": f"Przekroczono limit prób logowania. Adres IP zablokowany na {lockout_h}h."},
            headers={"Retry-After": str(int(lockout_h * 3600))},
        )

    return JSONResponse(status_code=401, content={"detail": "Nieprawidłowe hasło lub token dostępu"})


@app.get("/logout")
async def logout(request: Request):
    client_ip = request.client.host if request.client else "127.0.0.1"
    app_logger.info(f"Wylogowanie użytkownika z adresu IP: {client_ip}")
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(COOKIE_AUTH_TOKEN, httponly=True, secure=is_secure_request(request), samesite="lax")
    return resp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host=DEFAULT_HOST, port=DEFAULT_PORT, reload=DEBUG)
