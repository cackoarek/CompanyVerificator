"""Zależności FastAPI (baza danych, serwisy domenowe, kontekst szablonów)."""

from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from fastapi.templating import Jinja2Templates

from src import __version__
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from src.config import ALLOW_DELETION, APP_TIMEZONE, AUDITS_DIR, TEMPLATES_DIR
from src.core.database import Database
from src.core.security import is_request_authenticated
from src.services.audit_service import AuditService
from src.services.batch_service import BatchService
from src.services.verification_service import VerificationService

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def format_app_datetime(dt_val: Any, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Konwertuje znacznik czasu UTC / ISO do lokalnej strefy czasowej aplikacji."""
    if not dt_val:
        return ""
    try:
        s = str(dt_val).strip()
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        elif "+" in s or (len(s) > 10 and "-" in s[10:]):
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        
        try:
            target_tz = ZoneInfo(APP_TIMEZONE)
        except Exception:
            target_tz = ZoneInfo("Europe/Warsaw")
            
        local_dt = dt.astimezone(target_tz)
        return local_dt.strftime(fmt)
    except Exception:
        # Fallback na proste zastąpienie T spacją
        return str(dt_val)[:16].replace("T", " ")


templates.env.filters["app_dt"] = format_app_datetime


def format_analyst_status(status_val: Any) -> str:
    """Tłumaczy kod statusu analityka na elegancką polską etykietę biznesową."""
    if not status_val:
        return ""
    val = getattr(status_val, "value", str(status_val))
    labels = {
        "AUTO": "Oczekuje na ocenę analityka",
        "AUTO_APPROVED": "Automatycznie zatwierdzono (Brak uwag)",
        "AUTO_BLOCKED": "Automatyczna blokada (Sankcje STOP)",
        "PENDING_EXPLANATION": "Oczekuje na wyjaśnienie",
        "APPROVED_AFTER_REVIEW": "Zatwierdzono po wyjaśnieniu",
        "REJECTED": "Odrzucono / Blokada",
    }
    return labels.get(val, val)


def format_decyzja_label(decyzja_val: Any) -> str:
    """Tłumaczy kod decyzji compliance na czytelną polską etykietę."""
    if not decyzja_val:
        return ""
    val = getattr(decyzja_val, "value", str(decyzja_val))
    labels = {
        "AKCEPTACJA": "Akceptacja",
        "WYMAGA_WYJASNIENIA": "Wymaga wyjaśnienia",
        "ODMOWA_WSPOLPRACY_STOP": "Odmowa współpracy (STOP)",
    }
    return labels.get(val, val)


templates.env.filters["analyst_label"] = format_analyst_status
templates.env.filters["decyzja_label"] = format_decyzja_label




def get_db(request: Request) -> Database:
    db: Database = getattr(request.app.state, "db", None)
    if db is None:
        db = Database()
        request.app.state.db = db
    return db


def get_audits_dir(request: Request) -> Path:
    return Path(getattr(request.app.state, "audits_dir", AUDITS_DIR))


def get_verification_service(request: Request) -> VerificationService:
    return VerificationService(db=get_db(request), audits_dir=get_audits_dir(request))


def get_batch_service(request: Request) -> BatchService:
    return BatchService(db=get_db(request), audits_dir=get_audits_dir(request))


def get_audit_service(request: Request) -> AuditService:
    return AuditService(db=get_db(request), audits_dir=get_audits_dir(request))


def get_dict_sync_manager(request: Request):
    from src.services.dictionary_sync_manager import DictionarySyncManager
    mgr = getattr(request.app.state, "dict_sync_manager", None)
    if not mgr:
        mgr = DictionarySyncManager(get_db(request))
        request.app.state.dict_sync_manager = mgr
    return mgr


def base_context(request: Request, active_tab: str) -> Dict[str, Any]:
    db = get_db(request)
    sync_mgr = get_dict_sync_manager(request)
    dict_issues = sync_mgr.has_any_errors_or_stale()
    return {
        "request": request,
        "app_version": __version__,
        "active_tab": active_tab,
        "stats": db.get_verification_stats(),
        "sanctions_counts": db.count_sanctions_by_source(),
        "allow_deletion": ALLOW_DELETION,
        "dict_issues": dict_issues,
        "is_authenticated": is_request_authenticated(request),
    }
