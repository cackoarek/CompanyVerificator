"""Serwis orkiestrujący procedurę należytej staranności dla pojedynczej firmy."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from src.config import AUDITS_DIR, CACHE_TTL_HOURS
from src.core.database import Database
from src.core.io import atomic_write_json, atomic_write_text
from src.core.logging_config import app_logger
from src.core.validators import classify_identifier, clean_nrb, validate_iban
from src.domain.enums import DecyzjaWspolpracy, PoziomRyzykaAML, StatusRachunkuBankowego
from src.domain.models import VerificationCard
from src.domain.risk_engine import RiskEvaluationInput, evaluate_risk
from src.providers.ceidg_client import fetch_ceidg_info
from src.providers.crbr_client import compare_krs_and_crbr, fetch_crbr_beneficiaries
from src.providers.krs_client import fetch_krs_odpis
from src.providers.mf_white_list import check_mf_bank_account, fetch_mf_white_list
from src.providers.sanctions.matcher import match_sanctions
from src.providers.sanctions.sync_service import seed_default_sanctions
from src.providers.vies_client import check_vies_vat
from src.reports.hash_utils import compute_card_sha256
from src.reports.markdown_generator import render_card_markdown
from src.reports.pdf_generator import generate_card_pdf


class VerificationService:
    """Orkiestrator weryfikacji firmy pod kątem AML, sankcji, VAT, KRS, CRBR i rachunków."""

    def __init__(self, db: Database, audits_dir: Path = AUDITS_DIR) -> None:
        self.db = db
        self.audits_dir = Path(audits_dir)
        seed_default_sanctions(self.db)

    def _archive_card_files(self, card: VerificationCard) -> Path:
        dt = datetime.now(timezone.utc)
        target_dir = self.audits_dir / dt.strftime("%Y") / dt.strftime("%m") / card.id
        target_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target_dir / f"{card.identifier}-raw.json", card.to_dict())
        atomic_write_text(target_dir / f"{card.identifier}-karta.md", render_card_markdown(card))
        try:
            generate_card_pdf(card, target_dir / f"{card.identifier}-karta.pdf")
        except Exception:
            pass
        return target_dir

    async def verify_company(
        self,
        *,
        identifier: str,
        nazwa_hint: Optional[str] = None,
        rachunek_bankowy: Optional[str] = None,
        kwota_transakcji: Optional[Decimal] = None,
        status_pep: bool = False,
        force: bool = False,
        batch_id: Optional[str] = None,
        allow_test_nips: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ) -> VerificationCard:
        """Przeprowadza pełną, deterministyczną procedurę należytej staranności."""
        app_logger.info(f"Rozpoczęcie weryfikacji podmiotu: {identifier} (force={force}, rachunek={rachunek_bankowy is not None})")
        clf = classify_identifier(identifier, allow_test_nips=allow_test_nips)

        if not clf.is_valid:
            app_logger.warning(f"Niepoprawny identyfikator podmiotu: {identifier} ({clf.error})")
            card = VerificationCard(
                identifier=clf.normalized or identifier.strip(),
                identifier_kind="INVALID",
                nazwa=nazwa_hint or "Nieprawidłowy identyfikator podmiotu",
                status_rejestru="NIEZNALEZIONY",
                zrodlo_rejestru="Walidator formalny",
                status_vat="Nie badano (błędny identyfikator)",
                poziom_ryzyka=PoziomRyzykaAML.WYSOKIE,
                decyzja=DecyzjaWspolpracy.WYMAGA_WYJASNIENIA,
                uzasadnienie_decyzji=clf.error or "Nieprawidłowy identyfikator podmiotu.",
                batch_id=batch_id,
            )
            card.sha256_hash = compute_card_sha256(card)
            self._persist_card(card)
            return card

        # Sprawdzenie cache SQLite (tylko gdy nie wymuszono --force i nie badamy nowego rachunku/PEP/kwoty)
        if not force and not rachunek_bankowy and not status_pep and kwota_transakcji is None and not batch_id:
            cached_row = self.db.get_latest_valid_cached_verification(clf.normalized, ttl_hours=CACHE_TTL_HOURS)
            if cached_row:
                import json
                app_logger.info(f"Zwrócono wynik z pamięci podręcznej (cache) dla {clf.normalized}")
                return VerificationCard.from_dict(json.loads(cached_row["card_json"]))

        own_client = client is None
        http_client = client or httpx.AsyncClient()
        try:
            card = await self._execute_live_verification(
                http_client=http_client,
                clf_kind=clf.kind,
                clf_norm=clf.normalized,
                country_code=clf.country_code,
                nazwa_hint=nazwa_hint,
                rachunek_bankowy=rachunek_bankowy,
                kwota_transakcji=kwota_transakcji,
                status_pep=status_pep,
                batch_id=batch_id,
            )
        except Exception as exc:
            app_logger.error(f"Nieoczekiwany błąd weryfikacji {clf.normalized}: {exc}", exc_info=True)
            raise
        finally:
            if own_client:
                await http_client.aclose()

        card.sha256_hash = compute_card_sha256(card)
        self._persist_card(card)

        if card.blad_polaczenia:
            app_logger.warning(f"Weryfikacja zakończona z błędami połączenia: {card.identifier} ({card.komunikat_bledu})")
        else:
            app_logger.info(f"Zakończono weryfikację: {card.identifier} - {card.nazwa} | Ryzyko: {card.poziom_ryzyka.value} ({card.risk_score} pkt) | Decyzja: {card.decyzja.value}")

        return card

    def _persist_card(self, card: VerificationCard) -> None:
        import json

        self._archive_card_files(card)
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
            actor="SYSTEM",
            action="CREATED",
            previous_decision=None,
            new_decision=card.decyzja.value,
            note=f"Weryfikacja automatyczna ({card.poziom_ryzyka.value}, {card.risk_score} pkt)",
        )

    async def _execute_live_verification(
        self,
        *,
        http_client: httpx.AsyncClient,
        clf_kind: str,
        clf_norm: str,
        country_code: str,
        nazwa_hint: Optional[str],
        rachunek_bankowy: Optional[str],
        kwota_transakcji: Optional[Decimal],
        status_pep: bool,
        batch_id: Optional[str],
    ) -> VerificationCard:
        raw_evidence: Dict[str, Any] = {}
        niekompletne_zrodla: List[str] = []
        komunikaty_bledow: List[str] = []

        is_foreign = clf_kind in ("EU_VAT", "FOREIGN_TAX_ID")
        nip: Optional[str] = clf_norm if clf_kind == "NIP" else None
        krs: Optional[str] = clf_norm if clf_kind == "KRS" else None
        vat_ue: Optional[str] = clf_norm if clf_kind == "EU_VAT" else None

        mf_data: Dict[str, Any] = {}
        krs_data: Dict[str, Any] = {}
        crbr_data: Dict[str, Any] = {}
        ceidg_data: Dict[str, Any] = {}
        vies_data: Dict[str, Any] = {}

        # Krok 1: Równoległe odpytanie podstawowych rejestrów dla typu identyfikatora
        if clf_kind == "KRS" and krs:
            krs_data = await fetch_krs_odpis(http_client, krs)
            raw_evidence["krs"] = krs_data.get("raw") or krs_data
            if krs_data.get("blad_polaczenia"):
                niekompletne_zrodla.append("KRS")
                komunikaty_bledow.append(krs_data.get("komunikat_bledu", "Błąd KRS"))
            if krs_data.get("nip"):
                nip = krs_data["nip"]

        if clf_kind == "EU_VAT" and vat_ue:
            vies_data = await check_vies_vat(http_client, vat_ue)
            raw_evidence["vies"] = vies_data.get("raw") or vies_data
            if vies_data.get("blad_polaczenia"):
                niekompletne_zrodla.append("VIES")
                komunikaty_bledow.append(vies_data.get("komunikat_bledu", "Błąd VIES"))

        if nip and not is_foreign:
            mf_data, ceidg_data = await asyncio.gather(
                fetch_mf_white_list(http_client, nip),
                fetch_ceidg_info(http_client, nip),
            )
            raw_evidence["mf_white_list"] = mf_data.get("raw") or mf_data
            if ceidg_data.get("configured"):
                raw_evidence["ceidg"] = ceidg_data.get("raw") or ceidg_data

            if mf_data.get("blad_polaczenia"):
                niekompletne_zrodla.append("MF Biała Lista")
                komunikaty_bledow.append(mf_data.get("komunikat_bledu", "Błąd MF"))
            if ceidg_data.get("blad_polaczenia"):
                niekompletne_zrodla.append("CEIDG")
                komunikaty_bledow.append(ceidg_data.get("komunikat_bledu", "Błąd CEIDG"))

            if not krs and mf_data.get("krs"):
                krs = mf_data["krs"]

        # Krok 2: Jeśli mamy KRS (bezpośrednio lub z MF), pobieramy odpis KRS i CRBR równolegle
        if krs and not is_foreign:
            tasks = []
            need_krs = not krs_data
            if need_krs:
                tasks.append(fetch_krs_odpis(http_client, krs))
            if nip:
                tasks.append(fetch_crbr_beneficiaries(http_client, nip))

            if tasks:
                results = await asyncio.gather(*tasks)
                idx = 0
                if need_krs:
                    krs_data = results[idx]
                    raw_evidence["krs"] = krs_data.get("raw") or krs_data
                    if krs_data.get("blad_polaczenia"):
                        niekompletne_zrodla.append("KRS")
                        komunikaty_bledow.append(krs_data.get("komunikat_bledu", "Błąd KRS"))
                    idx += 1
                if nip and idx < len(results):
                    crbr_data = results[idx]
                    raw_evidence["crbr"] = crbr_data.get("raw") or crbr_data
                    if crbr_data.get("blad_polaczenia"):
                        niekompletne_zrodla.append("CRBR")
                        komunikaty_bledow.append(crbr_data.get("komunikat_bledu", "Błąd CRBR"))

        # Krok 3: Złożenie danych firmy
        final_nazwa = (
            krs_data.get("nazwa")
            or mf_data.get("nazwa")
            or ceidg_data.get("nazwa")
            or vies_data.get("nazwa")
            or nazwa_hint
            or f"Podmiot {clf_norm}"
        )
        final_adres = krs_data.get("adres") or mf_data.get("adres") or vies_data.get("adres") or None
        final_regon = krs_data.get("regon") or mf_data.get("regon") or None
        kody_pkd = krs_data.get("kody_pkd") or ceidg_data.get("kody_pkd") or []
        pkd_glowny = krs_data.get("pkd_glowny") or ceidg_data.get("pkd_glowny")
        data_rozpoczecia = krs_data.get("data_rejestracji") or ceidg_data.get("data_rozpoczecia") or None
        upadlosc_lub_likwidacja = bool(krs_data.get("upadlosc_lub_likwidacja", False))

        if is_foreign:
            forma_prawna = f"PODMIOT ZAGRANICZNY ({country_code})"
            zrodlo_rejestru = "VIES (VAT-UE)" if clf_kind == "EU_VAT" else f"Rejestr zagraniczny ({country_code})"
            crbr_status = "NIE_DOTYCZY_ZAGRANICZNA"
            reprezentacja: List[str] = []
            beneficjenci: List[str] = []
            if vies_data.get("blad_polaczenia"):
                status_rejestru = "BLAD_POLACZENIA"
            elif vies_data.get("valid") is False:
                status_rejestru = "NIEZNALEZIONY"
            else:
                status_rejestru = "AKTYWNY"
        elif krs or krs_data.get("found"):
            forma_prawna = krs_data.get("forma_prawna") or "SPÓŁKA HANDLOWA (KRS)"
            zrodlo_rejestru = "KRS (api-krs.ms.gov.pl) / Biała Lista MF"
            reprezentacja = list(krs_data.get("reprezentacja") or [])
            beneficjenci = list(crbr_data.get("beneficjenci") or [])
            if crbr_data.get("blad_polaczenia"):
                crbr_status = "BLAD_POLACZENIA"
            elif crbr_data.get("crbr_status") == "ZGODNY":
                crbr_status = compare_krs_and_crbr(reprezentacja, beneficjenci)
            else:
                crbr_status = crbr_data.get("crbr_status") or "BRAK_WPISU"
            status_rejestru = krs_data.get("status_rejestru") or ("BLAD_POLACZENIA" if mf_data.get("blad_polaczenia") else "AKTYWNY")
        else:
            forma_prawna = "JEDNOOSOBOWA DZIAŁALNOŚĆ GOSPODARCZA (JDG)"
            _ceidg_configured = ceidg_data.get("configured", False)
            zrodlo_rejestru = (
                "CEIDG / Biała Lista MF" if ceidg_data.get("found")
                else ("Biała Lista MF" if mf_data.get("found") else ("CEIDG / Biała Lista MF" if _ceidg_configured else "Biała Lista MF"))
            )
            reprezentacja = [final_nazwa] if final_nazwa else []
            beneficjenci = []
            crbr_status = "NIE_DOTYCZY"
            if ceidg_data.get("found"):
                status_rejestru = ceidg_data.get("status_rejestru", "AKTYWNY")
            elif mf_data.get("blad_polaczenia"):
                # Rozróżnij: błąd przejściowy MF (WL-196) vs. brak połączenia sieciowego
                _mf_transient = mf_data.get("zrodlo") == "MF_BIALA_LISTA_TRANSIENT"
                status_rejestru = "MF_NIEDOSTEPNY_CHWILOWO" if _mf_transient else "BLAD_POLACZENIA"
            elif mf_data.get("found"):
                status_rejestru = "AKTYWNY"
            else:
                status_rejestru = "NIEZNALEZIONY"

        # Status VAT i rachunek bankowy
        mf_request_id = mf_data.get("request_id") or vies_data.get("request_id")
        if is_foreign:
            if vies_data.get("blad_polaczenia"):
                status_vat = vies_data.get("komunikat_bledu", "Błąd połączenia VIES")
                platnik_vat_czynny = False
            elif vies_data.get("valid") is True:
                status_vat = "Czynny podatnik VAT-UE (VIES)"
                platnik_vat_czynny = True
            elif vies_data.get("valid") is False:
                status_vat = "Nieaktywny w VIES"
                platnik_vat_czynny = False
            else:
                status_vat = "Podmiot spoza UE"
                platnik_vat_czynny = False
            konta_mf: List[str] = []
        else:
            status_vat = mf_data.get("status_vat") or "Niezarejestrowany"
            platnik_vat_czynny = bool(mf_data.get("platnik_vat", False))
            konta_mf = list(mf_data.get("rachunki_bankowe") or [])

        status_rachunku = StatusRachunkuBankowego.NIE_PODANO
        iban_invalid = False
        _mf_down = bool(mf_data.get("blad_polaczenia"))
        if rachunek_bankowy and rachunek_bankowy.strip():
            iban_ok, _ = validate_iban(rachunek_bankowy)
            if not iban_ok:
                iban_invalid = True
            norm_acc = clean_nrb(rachunek_bankowy)
            if is_foreign:
                status_rachunku = StatusRachunkuBankowego.NIE_DOTYCZY_ZAGRANICZNY
            elif norm_acc in konta_mf:
                status_rachunku = StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
            elif nip and len(norm_acc) == 26 and norm_acc.isdigit():
                # Fallback: weryfikacja przez /api/check/nip/{nip}/bank-account/{nrb}
                # Obsługuje rachunki wirtualne i subkonta masowe (np. Alior Bank 2490...)
                check_res = await check_mf_bank_account(http_client, nip, norm_acc)
                raw_evidence["mf_bank_check"] = check_res.get("raw") or check_res
                if check_res.get("request_id"):
                    mf_request_id = check_res["request_id"]
                if check_res.get("blad_polaczenia"):
                    niekompletne_zrodla.append("MF Check Bank Account")
                    # Gdy MF było już niedostępne przy search/nip, nie klasyfikuj jako BRAK na Białej Liście
                    status_rachunku = StatusRachunkuBankowego.BLAD_POLACZENIA_MF if _mf_down else StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE
                elif check_res.get("assigned"):
                    status_rachunku = StatusRachunkuBankowego.ZGODNY_BIALA_LISTA
                    if norm_acc not in konta_mf:
                        konta_mf.append(norm_acc)
                else:
                    status_rachunku = StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE
            else:
                status_rachunku = StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE

        # Krok 4: Listy sankcyjne (MSWiA / UE / baza lokalna)
        sanction_entries = self.db.list_sanction_entries()
        persons_to_check = list(dict.fromkeys(reprezentacja + beneficjenci))
        sanction_hits = match_sanctions(
            nip=nip,
            krs=krs,
            company_name=final_nazwa,
            persons=persons_to_check,
            entries=sanction_entries,
        )
        sankcje_mswia = any(h.source in ("MSWIA", "LOCAL_SEED") for h in sanction_hits)
        sankcje_ue = any(h.source in ("EU", "LOCAL_SEED") for h in sanction_hits)
        sankcje_inne = any(h.source not in ("MSWIA", "EU", "LOCAL_SEED") for h in sanction_hits)
        sankcje_szczegoly = [f"[{h.source} / {h.confidence}] {h.reason}" for h in sanction_hits]

        blad_polaczenia = len(niekompletne_zrodla) > 0

        # Krok 5: Deterministyczna ocena ryzyka
        risk_score, risk_factors, poziom_ryzyka, decyzja, uzasadnienie, wymagany_mpp = evaluate_risk(
            RiskEvaluationInput(
                is_foreign=is_foreign,
                status_rejestru=status_rejestru,
                upadlosc_lub_likwidacja=upadlosc_lub_likwidacja,
                platnik_vat_czynny=platnik_vat_czynny,
                status_vat=status_vat,
                vies_valid=vies_data.get("valid") if is_foreign else None,
                status_rachunku=status_rachunku,
                kwota_transakcji=kwota_transakcji,
                crbr_status=crbr_status,
                sanction_hits=sanction_hits,
                status_pep=status_pep,
                blad_polaczenia=blad_polaczenia,
                niekompletne_zrodla=niekompletne_zrodla,
                data_rozpoczecia=data_rozpoczecia,
                kody_pkd=kody_pkd,
                iban_invalid=iban_invalid,
            )
        )

        return VerificationCard(
            identifier=clf_norm,
            identifier_kind=clf_kind,
            nazwa=final_nazwa,
            nip=nip,
            krs=krs,
            regon=final_regon,
            vat_ue=vat_ue,
            adres=final_adres,
            kraj=country_code or "PL",
            forma_prawna=forma_prawna,
            data_rozpoczecia=data_rozpoczecia,
            kody_pkd=kody_pkd,
            pkd_glowny=pkd_glowny,
            status_rejestru=status_rejestru,
            zrodlo_rejestru=zrodlo_rejestru,
            reprezentacja=reprezentacja,
            upadlosc_lub_likwidacja=upadlosc_lub_likwidacja,
            crbr_status=crbr_status,
            beneficjenci_rzeczywisci=beneficjenci,
            sankcje_mswia=sankcje_mswia,
            sankcje_ue=sankcje_ue,
            sankcje_inne=sankcje_inne,
            sankcje_trafienia=sanction_hits,
            sankcje_szczegoly=sankcje_szczegoly,
            status_vat=status_vat,
            platnik_vat_czynny=platnik_vat_czynny,
            vies_valid=vies_data.get("valid") if is_foreign else None,
            zweryfikowany_rachunek=rachunek_bankowy.strip() if rachunek_bankowy else None,
            status_rachunku=status_rachunku,
            rachunki_zgloszone_mf=konta_mf,
            kwota_transakcji=str(kwota_transakcji) if kwota_transakcji is not None else None,
            wymagany_mpp=wymagany_mpp,
            mf_request_id=mf_request_id,
            status_pep=status_pep,
            risk_score=risk_score,
            risk_factors=risk_factors,
            poziom_ryzyka=poziom_ryzyka,
            decyzja=decyzja,
            uzasadnienie_decyzji=uzasadnienie,
            blad_polaczenia=blad_polaczenia,
            niekompletne_zrodla=niekompletne_zrodla,
            komunikat_bledu="; ".join(komunikaty_bledow) if komunikaty_bledow else None,
            raw_evidence=raw_evidence,
            batch_id=batch_id,
        )
