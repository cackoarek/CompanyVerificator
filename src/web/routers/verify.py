"""Router weryfikacji pojedynczej firmy i obsługi karty dowodowej (HTMX + eksporty)."""

from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from src.domain.enums import AnalystStatus
from src.reports.markdown_generator import render_card_markdown
from src.web.dependencies import (
    base_context,
    get_audit_service,
    get_db,
    get_verification_service,
    templates,
)

router = APIRouter(tags=["Weryfikacja"])


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    """Strona główna – Centrum Weryfikacji Kontrahenta."""
    ctx = base_context(request, active_tab="verify")
    db = get_db(request)
    ctx["recent_verifications"] = db.list_verifications(limit=8)
    return templates.TemplateResponse(request=request, name="pages/verify.html", context=ctx)


@router.post("/verify", response_class=HTMLResponse)
async def verify_single_company(
    request: Request,
    identifier: str = Form(...),
    nazwa: Optional[str] = Form(None),
    rachunek: Optional[str] = Form(None),
    kwota: Optional[str] = Form(None),
    status_pep: bool = Form(False),
    kanal_relacji: str = Form("ZDALNIE"),
    force: bool = Form(False),
):
    """Uruchamia asynchroniczną weryfikację ad-hoc i zwraca kartę wyniku HTMX."""
    kwota_dec: Optional[Decimal] = None
    if kwota and kwota.strip():
        try:
            kwota_dec = Decimal(kwota.strip().replace(" ", "").replace(",", "."))
        except InvalidOperation:
            pass

    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip", "").strip()
        or (request.client.host if request.client else "127.0.0.1")
    )

    from src.domain.enums import KanalRelacji
    kanal_enum = KanalRelacji.SPOTKANIE_OSOBISTE if kanal_relacji == "SPOTKANIE_OSOBISTE" else KanalRelacji.ZDALNIE

    svc = get_verification_service(request)
    card = await svc.verify_company(
        identifier=identifier.strip(),
        nazwa_hint=nazwa.strip() if nazwa and nazwa.strip() else None,
        rachunek_bankowy=rachunek.strip() if rachunek and rachunek.strip() else None,
        kwota_transakcji=kwota_dec,
        status_pep=status_pep,
        kanal_relacji=kanal_enum,
        force=force,
        client_ip=client_ip,
    )

    audit_svc = get_audit_service(request)
    ctx = {
        "request": request,
        "karta": card,
        "audit_events": audit_svc.get_audit_history(card.id),
    }
    return templates.TemplateResponse(request=request, name="partials/card_result.html", context=ctx)


@router.get("/karta/{verification_id}", response_class=HTMLResponse)
async def view_card_detail(request: Request, verification_id: str):
    """Widok pełnej karty audytowej z historią decyzji analityka."""
    audit_svc = get_audit_service(request)
    card = audit_svc.get_card(verification_id)
    if not card:
        raise HTTPException(status_code=404, detail="Nie znaleziono karty weryfikacji")

    ctx = base_context(request, active_tab="history")
    ctx["karta"] = card
    ctx["audit_events"] = audit_svc.get_audit_history(verification_id)
    return templates.TemplateResponse(request=request, name="pages/card_detail.html", context=ctx)


@router.post("/karta/{verification_id}/decision", response_class=HTMLResponse)
async def update_card_decision(
    request: Request,
    verification_id: str,
    analyst_status: str = Form(...),
    note: str = Form(""),
    actor: str = Form("Analityk Compliance"),
):
    """Zapisuje decyzję analityka compliance w Audit Trail (HTMX partial)."""
    audit_svc = get_audit_service(request)
    try:
        new_status = AnalystStatus(analyst_status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Nieprawidłowy status decyzji") from exc

    error_msg: Optional[str] = None
    card = audit_svc.get_card(verification_id)
    if not card:
        raise HTTPException(status_code=404, detail="Nie znaleziono karty weryfikacji")

    try:
        card = audit_svc.update_analyst_decision(
            verification_id,
            new_status=new_status,
            note=note,
            actor=actor.strip() or "Analityk Compliance",
        )
    except ValueError as exc:
        error_msg = str(exc)

    ctx = {
        "request": request,
        "karta": card,
        "audit_events": audit_svc.get_audit_history(verification_id),
        "decision_error": error_msg,
    }
    return templates.TemplateResponse(request=request, name="partials/card_result.html", context=ctx)


@router.get("/karta/{verification_id}/pdf")
async def download_card_pdf(request: Request, verification_id: str):
    """Pobiera oficjalną Kartę Weryfikacji Kontrahenta (PDF A4)."""
    audit_svc = get_audit_service(request)
    card = audit_svc.get_card(verification_id)
    if not card:
        raise HTTPException(status_code=404, detail="Nie znaleziono karty weryfikacji")
    pdf_path = audit_svc.ensure_card_pdf(verification_id)
    if not pdf_path or not pdf_path.exists():
        raise HTTPException(status_code=500, detail="Nie udało się wygenerować pliku PDF")

    return FileResponse(
        path=str(pdf_path),
        filename=f"karta-weryfikacji-{card.identifier}.pdf",
        media_type="application/pdf",
    )


@router.get("/karta/{verification_id}/md")
async def download_card_md(request: Request, verification_id: str):
    """Pobiera Kartę Weryfikacji w formacie Markdown."""
    audit_svc = get_audit_service(request)
    card = audit_svc.get_card(verification_id)
    if not card:
        raise HTTPException(status_code=404, detail="Nie znaleziono karty weryfikacji")
    md_text = render_card_markdown(card)
    return Response(
        content=md_text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="karta-weryfikacji-{card.identifier}.md"'},
    )


@router.get("/karta/{verification_id}/json")
async def download_card_json(request: Request, verification_id: str):
    """Pobiera pełny zrzut dowodowy JSON wraz z podpisem SHA-256."""
    audit_svc = get_audit_service(request)
    card = audit_svc.get_card(verification_id)
    if not card:
        raise HTTPException(status_code=404, detail="Nie znaleziono karty weryfikacji")
    return JSONResponse(
        content=card.to_dict(),
        headers={"Content-Disposition": f'attachment; filename="karta-weryfikacji-{card.identifier}.json"'},
    )
