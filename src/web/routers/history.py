"""Router historii i rejestru wykonanych weryfikacji (wyszukiwarka i filtry)."""

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from src.web.dependencies import base_context, get_db, templates

router = APIRouter(prefix="/historia", tags=["Historia i Rejestr"])


@router.get("", response_class=HTMLResponse)
async def history_page(
    request: Request,
    q: Optional[str] = Query(None),
    risk: Optional[str] = Query(None),
    offline: bool = Query(False),
):
    """Widok pełnego rejestru wykonanych weryfikacji."""
    ctx = base_context(request, active_tab="history")
    db = get_db(request)
    ctx["items"] = db.list_verifications(query=q, risk_level=risk, offline_only=offline, limit=100)
    ctx["q"] = q or ""
    ctx["risk"] = risk or ""
    ctx["offline"] = offline
    return templates.TemplateResponse(request=request, name="pages/history.html", context=ctx)


@router.get("/lista", response_class=HTMLResponse)
async def history_table_partial(
    request: Request,
    q: Optional[str] = Query(None),
    risk: Optional[str] = Query(None),
    offline: bool = Query(False),
):
    """Zwraca przefiltrowane wiersze tabeli historii (HTMX)."""
    db = get_db(request)
    items = db.list_verifications(query=q, risk_level=risk, offline_only=offline, limit=100)
    return templates.TemplateResponse(
        request=request,
        name="partials/history_table.html",
        context={"request": request, "items": items},
    )
