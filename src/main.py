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
    STATIC_DIR,
)
from src.core.database import Database
from src.core.security import (
    check_login_rate_limit,
    is_safe_redirect_url,
    is_secure_request,
    is_trusted_origin,
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
    """Opcjonalna ochrona tokenem CV_ACCESS_TOKEN (jeśli pusty -> tryb lokalny bez logowania)."""
    required_token = os.getenv("CV_ACCESS_TOKEN", "").strip() or ACCESS_TOKEN
    if not required_token:
        return await call_next(request)

    path = request.url.path
    if path.startswith("/static") or path in ("/health", "/favicon.ico", "/login", "/logout"):
        return await call_next(request)

    token_candidate = None
    auth_header = request.headers.get("authorization", "")
    if auth_header:
        token_candidate = auth_header.split()[-1]
    if not token_candidate:
        token_candidate = request.cookies.get(COOKIE_AUTH_TOKEN) or request.headers.get("x-access-token")

    if token_candidate and len(token_candidate) <= 256 and secrets.compare_digest(token_candidate, required_token):
        return await call_next(request)

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
    if not check_login_rate_limit(client_ip):
        return JSONResponse(status_code=429, content={"detail": "Zbyt wiele prób logowania"}, headers={"Retry-After": "60"})

    required_token = os.getenv("CV_ACCESS_TOKEN", "").strip() or ACCESS_TOKEN
    form_data = await request.form()
    token_candidate = str(form_data.get("token", "")).strip()
    if len(token_candidate) > 256:
        token_candidate = ""

    is_valid = (not required_token) or (token_candidate and secrets.compare_digest(token_candidate, required_token))
    if is_valid:
        raw_redirect = str(form_data.get("redirect_url", "/")).strip()
        target_url = raw_redirect if is_safe_redirect_url(raw_redirect) else "/"
        resp = RedirectResponse(url=target_url, status_code=303)
        if required_token:
            resp.set_cookie(
                key=COOKIE_AUTH_TOKEN,
                value=required_token,
                httponly=True,
                secure=is_secure_request(request),
                samesite="lax",
            )
        return resp

    time.sleep(0.5)
    return JSONResponse(status_code=401, content={"detail": "Nieprawidłowy token dostępu"})


@app.get("/logout")
async def logout(request: Request):
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(COOKIE_AUTH_TOKEN, httponly=True, secure=is_secure_request(request), samesite="lax")
    return resp


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host=DEFAULT_HOST, port=DEFAULT_PORT, reload=DEBUG)
