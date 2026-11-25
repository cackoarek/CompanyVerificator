"""Router weryfikacji wsadowej (upload CSV/XLSX lub lista identyfikatorów)."""

import asyncio
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from src.services.batch_service import (
    BatchInputItem,
    parse_batch_csv,
    parse_batch_text,
    parse_batch_xlsx,
)
from src.web.dependencies import (
    base_context,
    get_audits_dir,
    get_batch_service,
    get_db,
    templates,
)

router = APIRouter(prefix="/wsadowa", tags=["Weryfikacja Wsadowa"])

_MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB


@router.get("", response_class=HTMLResponse)
async def batch_page(request: Request):
    """Ekran weryfikacji wsadowej i lista ostatnich zadań."""
    ctx = base_context(request, active_tab="batch")
    db = get_db(request)
    ctx["batch_jobs"] = db.list_batch_jobs(limit=15)
    return templates.TemplateResponse(request=request, name="pages/batch.html", context=ctx)


@router.post("/start", response_class=HTMLResponse)
async def start_batch_verification(
    request: Request,
    raw_list: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    force: bool = Form(False),
):
    """Uruchamia zadanie weryfikacji wsadowej w tle i zwraca panel postępu HTMX."""
    items: List[BatchInputItem] = []
    source_name = "lista-reczna.txt"

    if file and file.filename:
        fname = file.filename.lower()
        content = await file.read(_MAX_UPLOAD_BYTES + 1)
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="Plik przekracza maksymalny rozmiar 2 MB")
        source_name = file.filename
        if fname.endswith(".xlsx"):
            items = parse_batch_xlsx(content)
        elif fname.endswith(".csv") or fname.endswith(".txt"):
            items = parse_batch_csv(content)
        else:
            raise HTTPException(status_code=400, detail="Obsługiwane formaty plików: .csv, .xlsx, .txt")
    elif raw_list and raw_list.strip():
        items = parse_batch_text(raw_list)

    if not items:
        return templates.TemplateResponse(
            request=request,
            name="partials/batch_status.html",
            context={"request": request, "job": None, "error": "Brak poprawnych identyfikatorów do weryfikacji."},
        )

    db = get_db(request)
    batch_service = get_batch_service(request)
    batch_id = uuid.uuid4().hex[:12]
    db.create_batch_job(batch_id, filename=source_name, total_count=len(items))

    # W środowisku produkcyjnym uruchamiamy jako zadanie tła i odpytujemy paskiem postępu HTMX
    task = asyncio.create_task(
        batch_service.run_batch(items, filename=source_name, force=force, batch_id=batch_id)
    )
    # Zabezpieczenie referencji przed GC
    if not hasattr(request.app.state, "background_tasks"):
        request.app.state.background_tasks = set()
    request.app.state.background_tasks.add(task)
    task.add_done_callback(request.app.state.background_tasks.discard)

    job = db.get_batch_job(batch_id)
    return templates.TemplateResponse(
        request=request,
        name="partials/batch_status.html",
        context={"request": request, "job": job, "cards": []},
    )


@router.get("/{batch_id}/status", response_class=HTMLResponse)
async def batch_status_partial(request: Request, batch_id: str):
    """Zwraca aktualny postęp i wyniki zadania wsadowego (HTMX polling)."""
    db = get_db(request)
    job = db.get_batch_job(batch_id)
    if not job:
        raise HTTPException(status_code=404, detail="Nie znaleziono zadania wsadowego")

    cards = db.list_verifications(batch_id=batch_id, limit=500)
    return templates.TemplateResponse(
        request=request,
        name="partials/batch_status.html",
        context={"request": request, "job": job, "cards": cards},
    )


@router.get("/{batch_id}/pdf")
async def download_batch_pdf(request: Request, batch_id: str):
    pdf_path = get_audits_dir(request) / "batches" / batch_id / "raport-wsadowy.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="Raport PDF dla tego zadania nie istnieje")
    return FileResponse(path=str(pdf_path), filename=f"raport-wsadowy-{batch_id}.pdf", media_type="application/pdf")


@router.get("/{batch_id}/md")
async def download_batch_md(request: Request, batch_id: str):
    md_path = get_audits_dir(request) / "batches" / batch_id / "raport-wsadowy.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Raport Markdown dla tego zadania nie istnieje")
    return Response(
        content=md_path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="raport-wsadowy-{batch_id}.md"'},
    )


@router.get("/{batch_id}/csv")
async def download_batch_csv(request: Request, batch_id: str):
    csv_path = get_audits_dir(request) / "batches" / batch_id / "raport-wsadowy.csv"
    if not csv_path.exists():
        raise HTTPException(status_code=404, detail="Raport CSV dla tego zadania nie istnieje")
    return Response(
        content=csv_path.read_text(encoding="utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="raport-wsadowy-{batch_id}.csv"'},
    )
