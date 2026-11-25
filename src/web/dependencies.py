"""Zależności FastAPI (baza danych, serwisy domenowe, kontekst szablonów)."""

from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from fastapi.templating import Jinja2Templates

from src import __version__
from src.config import AUDITS_DIR, TEMPLATES_DIR
from src.core.database import Database
from src.services.audit_service import AuditService
from src.services.batch_service import BatchService
from src.services.verification_service import VerificationService

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


def base_context(request: Request, active_tab: str) -> Dict[str, Any]:
    db = get_db(request)
    return {
        "request": request,
        "app_version": __version__,
        "active_tab": active_tab,
        "stats": db.get_verification_stats(),
        "sanctions_counts": db.count_sanctions_by_source(),
    }
