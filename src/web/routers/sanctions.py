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
    """Widok statusu rejestrów publicznych, list sankcyjnych oraz wbudowanych słowników."""
    from src.domain.dictionaries.public_companies import get_public_companies_stats
    from src.domain.dictionaries.virtual_offices_catalog import KNOWN_MASS_REGISTRATION_PATTERNS, VIRTUAL_OFFICE_KEYWORDS
    from src.domain.dictionaries.pkd_catalog import HIGH_RISK_AML_PKD, REGULATED_KNF_PKD
    from src.web.dependencies import get_dict_sync_manager

    db = get_db(request)
    seed_default_sanctions(db)
    sync_mgr = get_dict_sync_manager(request)
    ctx = base_context(request, active_tab="registries")
    ctx["sync_logs"] = db.get_last_sanction_syncs()
    ctx["ceidg_configured"] = bool(CEIDG_API_TOKEN)
    ctx["sanctions_counts"] = db.count_sanctions_by_source()
    ctx["public_companies_stats"] = get_public_companies_stats()
    ctx["all_dictionaries"] = sync_mgr.get_dictionaries_status()
    ctx["dictionaries_stats"] = {
        "virtual_offices_patterns": len(KNOWN_MASS_REGISTRATION_PATTERNS),
        "virtual_offices_keywords": len(VIRTUAL_OFFICE_KEYWORDS),
        "pkd_high_risk": len(HIGH_RISK_AML_PKD),
        "pkd_knf": len(REGULATED_KNF_PKD),
    }
    return templates.TemplateResponse(request=request, name="pages/registries.html", context=ctx)


@router.post("/sync-all", response_class=HTMLResponse)
async def trigger_sync_all_dictionaries(request: Request):
    """Wymusza natychmiastową synchronizację wszystkich słowników i list sankcyjnych."""
    from src.web.dependencies import get_dict_sync_manager

    sync_mgr = get_dict_sync_manager(request)
    results = await sync_mgr.sync_stale_dictionaries(force=True)
    db = get_db(request)

    return templates.TemplateResponse(
        request=request,
        name="partials/sanctions_sync_status.html",
        context={
            "request": request,
            "sync_logs": db.get_last_sanction_syncs(),
            "sanctions_counts": db.count_sanctions_by_source(),
            "all_dictionaries": sync_mgr.get_dictionaries_status(),
            "results": results,
        },
    )


@router.post("/sync-public-companies", response_class=HTMLResponse)
async def trigger_public_companies_sync(request: Request):
    """Ręcznie synchronizuje listę spółek publicznych (GPW / NewConnect) z Internetu."""
    from src.domain.dictionaries.public_companies import sync_public_companies_from_web, get_public_companies_stats

    count = await sync_public_companies_from_web(force=True)
    stats = get_public_companies_stats()
    return templates.TemplateResponse(
        request=request,
        name="partials/public_companies_card.html",
        context={
            "request": request,
            "public_companies_stats": stats,
            "sync_message": f"Pomyślnie pobrano i zaktualizowano {count} spółek giełdowych z Internetu!",
        },
    )


@router.get("/dictionaries/public-companies", response_class=HTMLResponse)
async def view_public_companies_modal(request: Request, q: str = ""):
    """Zwraca modal z listą spółek publicznych (GPW / NewConnect) z filtrowaniem."""
    from src.domain.dictionaries.public_companies import load_cached_companies

    companies = load_cached_companies()
    query = (q or "").strip().upper()
    if query:
        companies = [
            c for c in companies
            if query in c.name.upper() or query in c.ticker or (c.krs and query in c.krs)
        ]

    return templates.TemplateResponse(
        request=request,
        name="partials/public_companies_modal.html",
        context={
            "request": request,
            "companies": companies[:150],  # limit do 150 najtrafniejszych
            "total_count": len(companies),
            "query": q,
        },
    )


@router.get("/dictionaries/virtual-offices", response_class=HTMLResponse)
async def view_virtual_offices_modal(request: Request):
    """Zwraca modal ze wzorcami adresów masowych i wirtualnych biur."""
    from src.domain.dictionaries.virtual_offices_catalog import KNOWN_MASS_REGISTRATION_PATTERNS, VIRTUAL_OFFICE_KEYWORDS

    return templates.TemplateResponse(
        request=request,
        name="partials/virtual_offices_modal.html",
        context={
            "request": request,
            "patterns": KNOWN_MASS_REGISTRATION_PATTERNS,
            "keywords": VIRTUAL_OFFICE_KEYWORDS,
        },
    )


@router.get("/dictionaries/pkd-catalog", response_class=HTMLResponse)
async def view_pkd_catalog_modal(request: Request):
    """Zwraca modal z katalogiem kodów PKD wysokiego ryzyka AML i MPP."""
    from src.domain.dictionaries.pkd_catalog import HIGH_RISK_AML_PKD, REGULATED_KNF_PKD

    return templates.TemplateResponse(
        request=request,
        name="partials/pkd_catalog_modal.html",
        context={
            "request": request,
            "high_risk_pkd": HIGH_RISK_AML_PKD,
            "regulated_pkd": REGULATED_KNF_PKD,
        },
    )



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
