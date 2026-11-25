"""Serwis weryfikacji wsadowej (CSV, XLSX, lista tekstowa) z kontrolą współbieżności."""

import asyncio
import csv
import io
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

import httpx
from openpyxl import load_workbook

from src.config import AUDITS_DIR, BATCH_CONCURRENCY
from src.core.database import Database
from src.core.io import atomic_write_json, atomic_write_text
from src.domain.models import BatchSummary, VerificationCard
from src.reports.markdown_generator import render_batch_csv, render_batch_markdown
from src.reports.pdf_generator import generate_batch_pdf
from src.services.verification_service import VerificationService


@dataclass
class BatchInputItem:
    identifier: str
    nazwa: Optional[str] = None
    rachunek: Optional[str] = None
    kwota: Optional[Decimal] = None
    status_pep: bool = False


def _parse_decimal(raw: Optional[str]) -> Optional[Decimal]:
    if not raw:
        return None
    clean = str(raw).strip().replace(" ", "").replace(",", ".")
    if not clean:
        return None
    try:
        return Decimal(clean)
    except InvalidOperation:
        return None


def parse_batch_text(raw_text: str) -> List[BatchInputItem]:
    """Parsuje listę identyfikatorów rozdzielonych nową linią, przecinkiem lub średnikiem."""
    items: List[BatchInputItem] = []
    seen: set[str] = set()
    for line in (raw_text or "").splitlines():
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("#"):
            continue
        sep = ";" if ";" in line_clean else ("," if "," in line_clean else None)
        if sep:
            parts = [p.strip() for p in line_clean.split(sep)]
            ident = parts[0]
            rach = parts[1] if len(parts) > 1 and parts[1] else None
            kw = _parse_decimal(parts[2]) if len(parts) > 2 else None
        else:
            ident, rach, kw = line_clean, None, None

        key = ident.upper().replace(" ", "").replace("-", "")
        if key and key not in seen:
            seen.add(key)
            items.append(BatchInputItem(identifier=ident, rachunek=rach, kwota=kw))
    return items


def parse_batch_csv(content_bytes: bytes) -> List[BatchInputItem]:
    """Parsuje plik CSV (obsługuje średnik i przecinek, wykrywa nagłówki)."""
    text = content_bytes.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return []

    header = [c.strip().lower() for c in rows[0]]
    has_header = any(h in ("nip", "krs", "identyfikator", "identifier", "vat", "vat_ue") for h in header)

    idx_id, idx_name, idx_acc, idx_amt = 0, -1, 1, 2
    data_rows = rows[1:] if has_header else rows
    if has_header:
        for i, h in enumerate(header):
            if h in ("nip", "krs", "identyfikator", "identifier", "vat", "vat_ue"):
                idx_id = i
            elif h in ("nazwa", "name", "firma", "kontrahent"):
                idx_name = i
            elif h in ("rachunek", "konto", "iban", "nrb", "account"):
                idx_acc = i
            elif h in ("kwota", "amount", "brutto"):
                idx_amt = i

    items: List[BatchInputItem] = []
    seen: set[str] = set()
    for row in data_rows:
        if idx_id >= len(row):
            continue
        ident = row[idx_id].strip()
        if not ident:
            continue
        key = ident.upper().replace(" ", "").replace("-", "")
        if key in seen:
            continue
        seen.add(key)
        items.append(
            BatchInputItem(
                identifier=ident,
                nazwa=row[idx_name].strip() if 0 <= idx_name < len(row) and row[idx_name].strip() else None,
                rachunek=row[idx_acc].strip() if 0 <= idx_acc < len(row) and row[idx_acc].strip() else None,
                kwota=_parse_decimal(row[idx_amt]) if 0 <= idx_amt < len(row) else None,
            )
        )
    return items


def parse_batch_xlsx(content_bytes: bytes) -> List[BatchInputItem]:
    """Parsuje plik Excel (.xlsx) do listy podmiotów do weryfikacji."""
    wb = load_workbook(io.BytesIO(content_bytes), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        return []
    rows = [[str(cell or "").strip() for cell in r] for r in ws.iter_rows(values_only=True)]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []

    header = [c.lower() for c in rows[0]]
    has_header = any(h in ("nip", "krs", "identyfikator", "identifier", "vat", "vat_ue") for h in header)
    data_rows = rows[1:] if has_header else rows
    idx_id, idx_name, idx_acc, idx_amt = 0, -1, 1, 2
    if has_header:
        for i, h in enumerate(header):
            if h in ("nip", "krs", "identyfikator", "identifier", "vat", "vat_ue"):
                idx_id = i
            elif h in ("nazwa", "name", "firma", "kontrahent"):
                idx_name = i
            elif h in ("rachunek", "konto", "iban", "nrb", "account"):
                idx_acc = i
            elif h in ("kwota", "amount", "brutto"):
                idx_amt = i

    items: List[BatchInputItem] = []
    seen: set[str] = set()
    for row in data_rows:
        if idx_id >= len(row):
            continue
        ident = row[idx_id].strip()
        if not ident:
            continue
        key = ident.upper().replace(" ", "").replace("-", "")
        if key in seen:
            continue
        seen.add(key)
        items.append(
            BatchInputItem(
                identifier=ident,
                nazwa=row[idx_name].strip() if 0 <= idx_name < len(row) and row[idx_name].strip() else None,
                rachunek=row[idx_acc].strip() if 0 <= idx_acc < len(row) and row[idx_acc].strip() else None,
                kwota=_parse_decimal(row[idx_amt]) if 0 <= idx_amt < len(row) else None,
            )
        )
    return items


class BatchService:
    """Orkiestrator weryfikacji wsadowych z zapisem postępu i eksportem raportów."""

    def __init__(self, db: Database, audits_dir: Path = AUDITS_DIR) -> None:
        self.db = db
        self.audits_dir = Path(audits_dir)
        self.verification_service = VerificationService(db=db, audits_dir=self.audits_dir)

    async def run_batch(
        self,
        items: List[BatchInputItem],
        *,
        filename: str = "lista-reczna.txt",
        force: bool = False,
        allow_test_nips: bool = False,
        batch_id: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> BatchSummary:
        bid = batch_id or uuid.uuid4().hex[:12]
        if not self.db.get_batch_job(bid):
            self.db.create_batch_job(bid, filename=filename, total_count=len(items))

        sem = asyncio.Semaphore(BATCH_CONCURRENCY)
        cards: List[VerificationCard] = []
        lock = asyncio.Lock()
        processed = 0

        own_client = client is None
        http_client = client or httpx.AsyncClient()
        try:
            async def _worker(item: BatchInputItem) -> VerificationCard:
                nonlocal processed
                async with sem:
                    card = await self.verification_service.verify_company(
                        identifier=item.identifier,
                        nazwa_hint=item.nazwa,
                        rachunek_bankowy=item.rachunek,
                        kwota_transakcji=item.kwota,
                        status_pep=item.status_pep,
                        force=force,
                        batch_id=bid,
                        allow_test_nips=allow_test_nips,
                        client=http_client,
                    )
                    async with lock:
                        processed += 1
                        self.db.update_batch_job(bid, processed_count=processed)
                    return card

            cards = list(await asyncio.gather(*[_worker(it) for it in items]))
        except Exception as exc:
            self.db.update_batch_job(bid, status="FAILED", error_message=str(exc))
            raise
        finally:
            if own_client:
                await http_client.aclose()

        summary = BatchSummary(batch_id=bid, filename=filename, cards=cards)
        batch_dir = self.audits_dir / "batches" / bid
        batch_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(batch_dir / "raport-wsadowy.json", summary.to_dict())
        atomic_write_text(batch_dir / "raport-wsadowy.md", render_batch_markdown(summary))
        atomic_write_text(batch_dir / "raport-wsadowy.csv", render_batch_csv(summary))
        try:
            generate_batch_pdf(summary, batch_dir / "raport-wsadowy.pdf")
        except Exception:
            pass

        self.db.update_batch_job(bid, status="COMPLETED", processed_count=len(cards), summary=summary.to_dict()["stats"])
        return summary
