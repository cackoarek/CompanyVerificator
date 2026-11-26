"""Testy jednostkowe walidatorów identyfikatorów oraz deterministycznego silnika ryzyka."""

from decimal import Decimal

from src.core.validators import (
    classify_identifier,
    validate_iban,
    validate_krs,
    validate_nip,
    validate_regon,
)
from src.domain.enums import DecyzjaWspolpracy, PoziomRyzykaAML, StatusRachunkuBankowego
from src.domain.models import SanctionHit, VerificationCard
from src.domain.risk_engine import RiskEvaluationInput, evaluate_risk
from src.reports.hash_utils import compute_card_sha256


def test_validate_nip_checksum():
    ok, _ = validate_nip("525-000-10-90")
    assert ok is True
    ok_pl, _ = validate_nip("PL5250001090")
    assert ok_pl is True
    bad, msg = validate_nip("5250001091")
    assert bad is False
    assert "cyfra kontrolna" in msg.lower()


def test_validate_regon_and_krs():
    assert validate_regon("012100784")[0] is True
    assert validate_regon("012100785")[0] is False
    assert validate_krs("0000010203")[0] is True
    assert validate_krs("0000000000")[0] is False


def test_validate_iban_pl_and_eu():
    # Poprawny polski NRB (26 cyfr) wyliczony wg Modulo 97-10
    assert validate_iban("PL61 1090 1014 0000 0712 1981 2874")[0] is True
    assert validate_iban("61109010140000071219812874")[0] is True
    assert validate_iban("PL61 1090 1014 0000 0712 1981 2875")[0] is False
    assert validate_iban("DE89370400440532013000")[0] is True


def test_classify_identifier():
    c_nip = classify_identifier("525-000-10-90")
    assert c_nip.kind == "NIP" and c_nip.is_valid

    c_krs = classify_identifier("KRS:10203")
    assert c_krs.kind == "KRS" and c_krs.normalized == "0000010203"

    c_eu = classify_identifier("DE 123456789")
    assert c_eu.kind == "EU_VAT" and c_eu.country_code == "DE" and c_eu.is_valid


def test_risk_engine_sanctions_stop():
    score, factors, level, decision, _, _ = evaluate_risk(
        RiskEvaluationInput(
            is_foreign=False,
            status_rejestru="AKTYWNY",
            upadlosc_lub_likwidacja=False,
            platnik_vat_czynny=True,
            status_vat="Czynny",
            vies_valid=None,
            status_rachunku=StatusRachunkuBankowego.ZGODNY_BIALA_LISTA,
            kwota_transakcji=Decimal("1000"),
            crbr_status="ZGODNY",
            sanction_hits=[
                SanctionHit(
                    source="MSWIA",
                    match_type="NIP",
                    matched_value="5252877567",
                    sanctioned_name="Novatek",
                    confidence="EXACT",
                    reason="Wpis MSWiA",
                )
            ],
            status_pep=False,
            blad_polaczenia=False,
            niekompletne_zrodla=[],
        )
    )
    assert score == 100
    assert level == PoziomRyzykaAML.KRYTYCZNE_STOP
    assert decision == DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP
    assert any(f.code == "SANCTIONS_HIT" for f in factors)


def test_risk_engine_whitelist_threshold_and_offline():
    # Ponad 15 000 zł i brak na Białej Liście -> SREDNIE + WYMAGA_WYJASNIENIA + MPP
    score, factors, level, decision, _, mpp = evaluate_risk(
        RiskEvaluationInput(
            is_foreign=False,
            status_rejestru="AKTYWNY",
            upadlosc_lub_likwidacja=False,
            platnik_vat_czynny=True,
            status_vat="Czynny",
            vies_valid=None,
            status_rachunku=StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE,
            kwota_transakcji=Decimal("20000.00"),
            crbr_status="NIE_DOTYCZY",
            sanction_hits=[],
            status_pep=False,
            blad_polaczenia=False,
            niekompletne_zrodla=[],
        )
    )
    assert level == PoziomRyzykaAML.SREDNIE
    assert decision == DecyzjaWspolpracy.WYMAGA_WYJASNIENIA
    assert mpp is True
    assert any(f.code == "BANK_NOT_ON_WHITELIST" for f in factors)

    # Poniżej 15 000 zł -> brak kary za konto poza listą
    _, factors_small, level_small, dec_small, _, mpp_small = evaluate_risk(
        RiskEvaluationInput(
            is_foreign=False,
            status_rejestru="AKTYWNY",
            upadlosc_lub_likwidacja=False,
            platnik_vat_czynny=True,
            status_vat="Czynny",
            vies_valid=None,
            status_rachunku=StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE,
            kwota_transakcji=Decimal("500.00"),
            crbr_status="NIE_DOTYCZY",
            sanction_hits=[],
            status_pep=False,
            blad_polaczenia=False,
            niekompletne_zrodla=[],
        )
    )
    assert level_small == PoziomRyzykaAML.NISKIE
    assert dec_small == DecyzjaWspolpracy.AKCEPTACJA
    assert mpp_small is False
    assert factors_small == []

    # Czynny podatnik VAT bez podanego rachunku i bez kont w MF -> NO_REGISTERED_BANK_ACCOUNTS (+20 pkt)
    score_no_acc, factors_no_acc, level_no_acc, dec_no_acc, _, _ = evaluate_risk(
        RiskEvaluationInput(
            is_foreign=False,
            status_rejestru="AKTYWNY",
            upadlosc_lub_likwidacja=False,
            platnik_vat_czynny=True,
            status_vat="Czynny",
            vies_valid=None,
            status_rachunku=StatusRachunkuBankowego.NIE_PODANO,
            kwota_transakcji=None,
            crbr_status="NIE_DOTYCZY",
            sanction_hits=[],
            status_pep=False,
            blad_polaczenia=False,
            niekompletne_zrodla=[],
            rachunki_mf=[],
        )
    )
    assert score_no_acc == 20
    assert any(f.code == "NO_REGISTERED_BANK_ACCOUNTS" for f in factors_no_acc)
    assert level_no_acc == PoziomRyzykaAML.SREDNIE


def test_canonical_sha256_covers_evidence():
    card = VerificationCard(
        identifier="5250001090",
        identifier_kind="NIP",
        nazwa="ORANGE POLSKA S.A.",
        nip="5250001090",
        mf_request_id="req-123",
    )
    h1 = compute_card_sha256(card)
    assert len(h1) == 64

    card.mf_request_id = "req-999"
    h2 = compute_card_sha256(card)
    assert h1 != h2
