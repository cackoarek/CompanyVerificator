"""Serwis audytowy do obsługi decyzji analityka compliance i eksportów kart."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import AUDITS_DIR
from src.core.database import Database
from src.domain.enums import AnalystStatus
from src.domain.models import VerificationCard
from src.reports.pdf_generator import generate_card_pdf


class AuditService:
    """Zarządza historią weryfikacji, ręcznymi decyzjami compliance oraz plikami dowodowymi."""

    def __init__(self, db: Database, audits_dir: Path = AUDITS_DIR) -> None:
        self.db = db
        self.audits_dir = Path(audits_dir)

    def get_card(self, verification_id: str) -> Optional[VerificationCard]:
        row = self.db.get_verification_by_id(verification_id)
        if not row:
            return None
        return VerificationCard.from_dict(json.loads(row["card_json"]))

    def get_audit_history(self, verification_id: str) -> List[Dict[str, Any]]:
        return self.db.list_audit_events(verification_id)

    def update_analyst_decision(
        self,
        verification_id: str,
        *,
        new_status: AnalystStatus,
        note: str,
        actor: str = "Analityk Compliance",
    ) -> Optional[VerificationCard]:
        """Zapisuje decyzję analityka (np. po złożeniu ZAW-NR lub wyjaśnień) w Audit Trail."""
        row = self.db.get_verification_by_id(verification_id)
        if not row:
            return None

        card = VerificationCard.from_dict(json.loads(row["card_json"]))
        prev_status = card.analyst_status.value

        # Blokada zatwierdzenia karty niekompletnej (błąd sieci) lub objętej sankcjami
        if new_status == AnalystStatus.APPROVED_AFTER_REVIEW:
            if card.blad_polaczenia:
                raise ValueError("Nie można zatwierdzić niekompletnej weryfikacji (błąd połączenia z rejestrami).")
            if card.sankcje_mswia or card.sankcje_ue:
                raise ValueError("Nie można zatwierdzić podmiotu objętego sankcjami (STOP).")

        card.analyst_status = new_status
        if note.strip():
            prefix = f"{card.uwagi_dodatkowe}\n" if card.uwagi_dodatkowe else ""
            card.uwagi_dodatkowe = f"{prefix}[{actor}] {note.strip()}"

        self.db.save_verification(
            {
                "id": card.id,
                "identifier": card.identifier,
                "identifier_kind": card.identifier_kind,
                "nip": card.nip,
                "krs": card.krs,
                "regon": card.regon,
                "nazwa": card.nazwa,
                "forma_prawna": card.forma_prawna,
                "poziom_ryzyka": card.poziom_ryzyka.value,
                "decyzja": card.decyzja.value,
                "analyst_status": card.analyst_status.value,
                "status_vat": card.status_vat,
                "status_rachunku": card.status_rachunku.value,
                "blad_polaczenia": card.blad_polaczenia,
                "sankcje_hit": bool(card.sankcje_mswia or card.sankcje_ue or card.sankcje_inne),
                "status_pep": card.status_pep,
                "sha256_hash": card.sha256_hash,
                "mf_request_id": card.mf_request_id,
                "card_json": json.dumps(card.to_dict(), ensure_ascii=False),
                "batch_id": card.batch_id,
                "created_at": card.data_weryfikacji,
            }
        )
        self.db.add_audit_event(
            verification_id=card.id,
            actor=actor,
            action="ANALYST_DECISION",
            previous_decision=prev_status,
            new_decision=new_status.value,
            note=note.strip(),
        )
        return card

    def ensure_card_pdf(self, verification_id: str) -> Optional[Path]:
        card = self.get_card(verification_id)
        if not card:
            return None
        pdf_path = self.audits_dir / "exports" / f"karta-{card.identifier}-{card.id[:8]}.pdf"
        generate_card_pdf(card, pdf_path)
        return pdf_path
