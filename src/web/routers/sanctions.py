"""Router zarządzania rejestrami publicznymi i synchronizacją list sankcyjnych."""

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.config import CEIDG_API_TOKEN
from src.providers.sanctions.sync_service import seed_default_sanctions, sync_all_sanctions
from src.web.dependencies import base_context, get_db, templates

router = APIRouter(prefix="/rejestry", tags=["Rejestry i Sankcje"])


@router.get("", response_class=HTMLResponse)
async def registries_page(request: Request):
    """Widok statusu rejestrów publicznych i aktualności list sankcyjnych."""
    db = get_db(request)
    seed_default_sanctions(db)
    ctx = base_context(request, active_tab="registries")
    ctx["sync_logs"] = db.get_last_sanction_syncs()
    ctx["ceidg_configured"] = bool(CEIDG_API_TOKEN)
    return templates.TemplateResponse(request=request, name="pages/registries.html", context=ctx)


@router.post("/sync", response_class=HTMLResponse)
async def trigger_sanctions_sync(request: Request):
    """Ręcznie synchronizuje oficjalne listy sankcyjne MSWiA i UE."""
    db = get_db(request)
    async with httpx.AsyncClient() as client:
        results = await sync_all_sanctions(client, db)

    return templates.TemplateResponse(
        request=request,
        name="partials/sanctions_sync_status.html",
        context={
            "request": request,
            "sync_logs": db.get_last_sanction_syncs(),
            "sanctions_counts": db.count_sanctions_by_source(),
            "results": results,
        },
    )


@router.get("/entries/{source}", response_class=HTMLResponse)
async def view_sanction_entries_modal(request: Request, source: str):
    """Zwraca modal z listą wpisów sankcyjnych dla wybranego źródła (HTMX)."""
    db = get_db(request)
    source_upper = source.upper()
    titles = {
        "LOCAL_SEED": "Baza startowa podmiotów sankcyjnych",
        "MSWIA": "Polska lista sankcyjna MSWiA",
        "EU": "Unijna lista sankcyjna UE (FSF)",
    }
    entries = db.list_sanction_entries(source=source_upper, limit=100)
    return templates.TemplateResponse(
        request=request,
        name="partials/sanction_entries_modal.html",
        context={
            "request": request,
            "source": source_upper,
            "title": titles.get(source_upper, f"Lista {source_upper}"),
            "entries": entries,
        },
    )
