"""Router historii i rejestru wykonanych weryfikacji (wyszukiwarka i filtry)."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from src.config import ALLOW_DELETION
from src.web.dependencies import base_context, get_db, templates

router = APIRouter(prefix="/historia", tags=["Historia i Rejestr"])


ALLOWED_PAGE_SIZES = (50, 100, 200)


def _prepare_pagination(
    db,
    q: Optional[str],
    risk: Optional[str],
    offline: bool,
    page: int,
    page_size: int,
):
    if page_size not in ALLOWED_PAGE_SIZES:
        page_size = 50
    if page < 1:
        page = 1

    total_count = db.count_verifications(query=q, risk_level=risk, offline_only=offline)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * page_size
    items = db.list_verifications(
        query=q,
        risk_level=risk,
        offline_only=offline,
        limit=page_size,
        offset=offset,
    )
    start_record = offset + 1 if total_count > 0 else 0
    end_record = min(offset + page_size, total_count)

    return {
        "items": items,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "start_record": start_record,
        "end_record": end_record,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_page": page - 1,
        "next_page": page + 1,
        "allowed_page_sizes": ALLOWED_PAGE_SIZES,
    }


@router.get("", response_class=HTMLResponse)
async def history_page(
    request: Request,
    q: Optional[str] = Query(None),
    risk: Optional[str] = Query(None),
    offline: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50),
):
    """Widok pełnego rejestru wykonanych weryfikacji ze stronnicowaniem."""
    ctx = base_context(request, active_tab="history")
    db = get_db(request)
    pag = _prepare_pagination(db, q=q, risk=risk, offline=offline, page=page, page_size=page_size)
    ctx.update(pag)
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
    page: int = Query(1, ge=1),
    page_size: int = Query(50),
):
    """Zwraca przefiltrowane wiersze tabeli historii wraz ze stopką paginacji (HTMX)."""
    db = get_db(request)
    pag = _prepare_pagination(db, q=q, risk=risk, offline=offline, page=page, page_size=page_size)
    ctx = {
        "request": request,
        "q": q or "",
        "risk": risk or "",
        "offline": offline,
        "allow_deletion": ALLOW_DELETION,
        **pag,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/history_table.html",
        context=ctx,
    )


@router.delete("/{verification_id}", response_class=HTMLResponse)
async def delete_history_item(
    request: Request,
    verification_id: str,
    q: Optional[str] = Query(None),
    risk: Optional[str] = Query(None),
    offline: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50),
):
    """Usuwa pojedynczą weryfikację i zwraca zaktualizowaną tabelę."""
    if not ALLOW_DELETION:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuwanie wpisów weryfikacji zostało wyłączone przez administratora (CV_ALLOW_DELETION=false).",
        )
    db = get_db(request)
    db.delete_verification(verification_id)
    pag = _prepare_pagination(db, q=q, risk=risk, offline=offline, page=page, page_size=page_size)
    ctx = {
        "request": request,
        "q": q or "",
        "risk": risk or "",
        "offline": offline,
        "allow_deletion": ALLOW_DELETION,
        **pag,
    }
    return templates.TemplateResponse(
        request=request,
        name="partials/history_table.html",
        context=ctx,
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
