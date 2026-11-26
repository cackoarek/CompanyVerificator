"""Testy integracyjne serwisów weryfikacji, wsadu, Audit Trail oraz generatorów PDF/MD/CSV."""

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from src.core.database import Database
from src.domain.enums import AnalystStatus, DecyzjaWspolpracy, PoziomRyzykaAML, StatusRachunkuBankowego
from src.reports.pdf_generator import generate_card_pdf
from src.services.audit_service import AuditService
from src.services.batch_service import BatchService, parse_batch_csv, parse_batch_text
from src.services.verification_service import VerificationService


@pytest.mark.asyncio
async def test_verification_service_full_flow_and_pdf(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    audits_dir = tmp_path / "audits"
    svc = VerificationService(db=db, audits_dir=audits_dir)
    audit_svc = AuditService(db=db, audits_dir=audits_dir)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://wl-api\.mf\.gov\.pl/api/search/nip/5250001090.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "result": {
                        "requestId": "mf-req-555",
                        "subject": {
                            "name": "ORANGE & PARTNERS S.A.",
                            "nip": "5250001090",
                            "statusVat": "Czynny",
                            "regon": "012100784",
                            "krs": "0000010681",
                            "workingAddress": "Al. Jerozolimskie 160, Warszawa",
                            "accountNumbers": ["61109010140000071219812874"],
                        },
                    }
                },
            )
        )
        mock.get("https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/0000010681?rejestr=P&format=json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "odpis": {
                        "naglowekA": {"dataRejestracjiWKRS": "2001-05-07"},
                        "dane": {
                            "dzial1": {"danePodmiotu": {"nazwa": "ORANGE & PARTNERS S.A.", "formaPrawna": "SPÓŁKA AKCYJNA", "identyfikatory": {"nip": "5250001090"}}},
                            "dzial2": {"reprezentacja": {"sklad": [{"imiona": {"imie": "Anna"}, "nazwisko": {"nazwiskoICzlon": "Nowak"}, "funkcjaWOrganie": "PREZES"}]}},
                            "dzial3": {},
                            "dzial6": {},
                        },
                    }
                },
            )
        )
        mock.get(url__regex=r"https://dane\.biznes\.gov\.pl/api/ceidg/.*").mock(
            return_value=httpx.Response(404, json={"firmy": []})
        )
        mock.post("https://crbr.podatki.gov.pl/adcrbr/api/pobierzZgloszeniaPoNIP").mock(
            return_value=httpx.Response(
                200,
                json={"beneficjenci": [{"imie": "Anna", "nazwisko": "Nowak", "charakterUprawnien": "akcjonariusz"}]},
            )
        )

        card = await svc.verify_company(
            identifier="5250001090",
            rachunek_bankowy="PL61 1090 1014 0000 0712 1981 2874",
            kwota_transakcji=Decimal("25000.00"),
        )

    assert card.poziom_ryzyka == PoziomRyzykaAML.NISKIE
    assert card.decyzja == DecyzjaWspolpracy.AKCEPTACJA
    assert card.status_rachunku == StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
    assert card.mf_request_id == "mf-req-555"
    assert len(card.sha256_hash) == 64

    # Test PDF z nazwą zawierającą znak '&'
    pdf_path = generate_card_pdf(card, tmp_path / "karta.pdf")
    assert pdf_path.exists() and pdf_path.stat().st_size > 1500

    # Test aktualizacji decyzji analityka
    updated = audit_svc.update_analyst_decision(
        card.id,
        new_status=AnalystStatus.APPROVED_AFTER_REVIEW,
        note="Zweryfikowano umowę",
        actor="Jan Audytor",
    )
    assert updated is not None and updated.analyst_status == AnalystStatus.APPROVED_AFTER_REVIEW
    events = audit_svc.get_audit_history(card.id)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_offline_blocks_analyst_approval(tmp_path: Path):
    db = Database(tmp_path / "offline.db")
    svc = VerificationService(db=db, audits_dir=tmp_path / "audits")
    audit_svc = AuditService(db=db, audits_dir=tmp_path / "audits")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://dane\.biznes\.gov\.pl/api/ceidg/.*").mock(return_value=httpx.Response(404))
        mock.get(url__regex=r"https://wl-api\.mf\.gov\.pl/.*").mock(return_value=httpx.Response(503))
        card = await svc.verify_company(identifier="5250001090", force=True)

    assert card.blad_polaczenia is True
    assert card.decyzja == DecyzjaWspolpracy.WYMAGA_WYJASNIENIA

    with pytest.raises(ValueError):
        audit_svc.update_analyst_decision(
            card.id,
            new_status=AnalystStatus.APPROVED_AFTER_REVIEW,
            note="Próba obejścia",
        )


@pytest.mark.asyncio
async def test_batch_parsing_and_execution(tmp_path: Path):
    text_items = parse_batch_text("5250001090\n5250001090\nDE123456789; ;12000")
    assert len(text_items) == 2

    csv_bytes = "nip;nazwa;rachunek;kwota\n5252877567;Novatek;;50000\n".encode("utf-8")
    csv_items = parse_batch_csv(csv_bytes)
    assert len(csv_items) == 1
    assert csv_items[0].kwota == Decimal("50000")

    db = Database(tmp_path / "batch.db")
    audits_dir = tmp_path / "audits"
    batch_svc = BatchService(db=db, audits_dir=audits_dir)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://dane\.biznes\.gov\.pl/api/ceidg/.*").mock(return_value=httpx.Response(404))
        mock.get(url__regex=r"https://wl-api\.mf\.gov\.pl/.*").mock(
            return_value=httpx.Response(404)
        )
        summary = await batch_svc.run_batch(csv_items, filename="test.csv")

    assert summary.total == 1
    assert summary.critical_stop == 1
    batch_dir = audits_dir / "batches" / summary.batch_id
    assert (batch_dir / "raport-wsadowy.pdf").exists()
    assert (batch_dir / "raport-wsadowy.md").exists()
    assert (batch_dir / "raport-wsadowy.csv").exists()
