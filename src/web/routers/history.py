"""Router historii i rejestru wykonanych weryfikacji (wyszukiwarka i filtry)."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from src.config import ALLOW_DELETION
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
    ctx["allow_deletion"] = ALLOW_DELETION
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
        context={"request": request, "items": items, "allow_deletion": ALLOW_DELETION},
    )


@router.delete("/{verification_id}", response_class=HTMLResponse)
async def delete_history_item(
    request: Request,
    verification_id: str,
    q: Optional[str] = Query(None),
    risk: Optional[str] = Query(None),
    offline: bool = Query(False),
):
    """Usuwa pojedynczą weryfikację i zwraca zaktualizowaną tabelę."""
    if not ALLOW_DELETION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuwanie wpisów weryfikacji zostało wyłączone przez administratora (CV_ALLOW_DELETION=false).",
        )
    db = get_db(request)
    db.delete_verification(verification_id)
    items = db.list_verifications(query=q, risk_level=risk, offline_only=offline, limit=100)
    return templates.TemplateResponse(
        request=request,
        name="partials/history_table.html",
        context={"request": request, "items": items, "allow_deletion": ALLOW_DELETION},
    )


@router.post("/wyczysc", response_class=HTMLResponse)
async def clear_all_history(request: Request):
    """Czyści całą historię weryfikacji i zwraca pustą tabelę."""
    if not ALLOW_DELETION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Czyszczenie historii weryfikacji zostało wyłączone przez administratora (CV_ALLOW_DELETION=false).",
        )
    db = get_db(request)
    db.delete_all_verifications()
    return templates.TemplateResponse(
        request=request,
        name="partials/history_table.html",
        context={"request": request, "items": [], "allow_deletion": ALLOW_DELETION},
    )
