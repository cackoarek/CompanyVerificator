"""Testy jednostkowe walidatorów identyfikatorów oraz deterministycznego silnika ryzyka."""

from decimal import Decimal
import pytest

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

    c_regon9 = classify_identifier("012100784")
    assert c_regon9.kind == "REGON" and c_regon9.is_valid and c_regon9.normalized == "012100784"

    c_regon_pref = classify_identifier("REGON: 012100784")
    assert c_regon_pref.kind == "REGON" and c_regon_pref.is_valid

    c_eu = classify_identifier("DE 123456789")
    assert c_eu.kind == "EU_VAT" and c_eu.country_code == "DE" and c_eu.is_valid


def test_risk_engine_sanctions_stop():
    score, factors, level, decision, _, _, _ = evaluate_risk(
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
    score, factors, level, decision, _, mpp, _ = evaluate_risk(
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
    _, factors_small, level_small, dec_small, _, mpp_small, _ = evaluate_risk(
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
    score_no_acc, factors_no_acc, level_no_acc, dec_no_acc, _, _, _ = evaluate_risk(
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


def test_kyc_scorecard_giif_and_virtual_office_detection():
    """Testuje wyliczanie 5 filarów oceny ryzyka KYC wg wytycznych GIIF/KOR oraz detekcję wirtualnego biura."""
    from src.domain.enums import KanalRelacji, ProfilRyzykaKyc
    from src.domain.virtual_office import is_virtual_office_or_mass_address

    # 1. Test detekcji wirtualnego biura
    is_vo, reason = is_virtual_office_or_mass_address("ul. Złota 59, 00-120 Warszawa")
    assert is_vo is True
    assert "złota 59" in reason.lower()

    is_vo_kw, _ = is_virtual_office_or_mass_address("ul. Prosta 1, Coworking Hub, Kraków")
    assert is_vo_kw is True

    is_normal, _ = is_virtual_office_or_mass_address("ul. Leśna 15, 05-500 Piaseczno")
    assert is_normal is False

    # 2. Test scorecardu KYC GIIF dla podmiotu wysokiego ryzyka
    # Staż < 6 mies (5 pkt), Siedziba: wirtualne biuro (4 pkt), UBO: zagranica (6 pkt), Branża: krypto/paliwa (6 pkt), Kanał: zdalnie (3 pkt) = 24 pkt
    inp_high = RiskEvaluationInput(
        is_foreign=False,
        status_rejestru="AKTYWNY",
        upadlosc_lub_likwidacja=False,
        platnik_vat_czynny=True,
        status_vat="Czynny",
        vies_valid=None,
        status_rachunku=StatusRachunkuBankowego.ZGODNY_BIALA_LISTA,
        kwota_transakcji=Decimal("150000"),
        crbr_status="ZGODNY",
        sanction_hits=[],
        status_pep=False,
        blad_polaczenia=False,
        niekompletne_zrodla=[],
        data_wpisu_rejestru="2026-10-15",  # Bardzo świeża spółka (< 60 dni)
        adres="ul. Złota 59, Warszawa",    # Wirtualne biuro
        kody_pkd=["46.71.Z"],              # Paliwa - wysokie ryzyko
        kapital_zakladowy=Decimal("5000"), # Minimalny kapitał przy transakcji 150k
        beneficjenci=[{"imie": "John", "nazwisko": "Doe", "obywatelstwo": "CYPR"}],
        kanal_relacji=KanalRelacji.ZDALNIE,
    )
    score, factors, level, decision, _, _, scorecard = evaluate_risk(inp_high)

    assert scorecard is not None
    assert scorecard.staz_punkty == 5
    assert scorecard.siedziba_punkty == 4
    assert scorecard.branza_punkty == 6
    assert scorecard.ubo_punkty == 6
    assert scorecard.kanal_punkty == 3
    assert scorecard.profil_ryzyka == ProfilRyzykaKyc.WYSOKIE_NIEAKCEPTOWALNE
    assert any(f.code == "VIRTUAL_OFFICE_MASS_ADDRESS" for f in factors)


def test_public_companies_dictionary_and_legal_forms():
    from src.domain.dictionaries.public_companies import is_public_company, load_cached_companies
    from src.domain.dictionaries.legal_forms import evaluate_legal_form, LegalFormType

    # 1. Weryfikacja załadowania bazy
    companies = load_cached_companies()
    assert len(companies) > 0

    # 2. Rozpoznawanie PZU po KRS
    pzu = is_public_company(krs="0000009831")
    assert pzu is not None
    assert pzu.ticker == "PZU"
    assert pzu.market == "GPW"

    # 3. Rozpoznawanie po nazwie (np. Dino Polska)
    dino = is_public_company(name="Dino Polska S.A.")
    assert dino is not None
    assert dino.ticker == "DNP"

    # 4. Sprawdzenie ewaluacji prawnej (evaluate_legal_form)
    eval_pzu = evaluate_legal_form(
        forma_prawna="SPÓŁKA AKCYJNA",
        nazwa="POWSZECHNY ZAKŁAD UBEZPIECZEŃ SPÓŁKA AKCYJNA",
        krs="0000009831",
    )
    assert eval_pzu.form_type == LegalFormType.PUBLIC_COMPANY_GPW
    assert eval_pzu.exempt_from_crbr is True
    assert eval_pzu.eligible_for_simplified_cdd is True
    assert "GPW" in eval_pzu.display_name


    # 5. Zwykła mała spółka akcyjna niepubliczna
    eval_private_sa = evaluate_legal_form(
        forma_prawna="SPÓŁKA AKCYJNA",
        nazwa="Prywatna Hurtownia Spożywcza S.A.",
        krs="0000999999",
        kapital_zakladowy=100_000,
    )
    assert eval_private_sa.form_type == LegalFormType.COMMERCIAL_COMPANY_KRS
    assert eval_private_sa.exempt_from_crbr is False


def test_krz_parser_and_risk_evaluation():
    from src.providers.krz_client import parse_krs_dzial6_insolvency
    from src.domain.risk_engine import RiskEvaluationInput, evaluate_risk
    from src.domain.enums import PoziomRyzykaAML

    # 1. Test parsera Działu 6 KRS
    sample_dzial6_krs = {
        "odpis": {
            "dane": {
                "dzial6": {
                    "postepowanieUpadlosciowe": [
                        {
                            "informacjaOOgloszeniuUpadlosci": {
                                "organWydajacy": "SĄD REJONOWY DLA M.ST. WARSZAWY X WYDZIAŁ GOSPODARCZY",
                                "sygnatura": "WA1M/GUp/123/2025",
                                "data": "2025-06-10",
                            },
                            "sposobProwadzeniaPostepowania": "LIKWIDACYJNE",
                            "daneSyndyka": [
                                {
                                    "imiona": {"imie": "Jan"},
                                    "nazwisko": {"nazwiskoICzlon": "Kowalski"},
                                }
                            ],
                        }
                    ],
                    "postepowanieRestrukturyzacyjne": [
                        {
                            "sygnaturaAkt": "WA1M/GR/45/2024",
                            "organSadowyLubInny": "SĄD REJONOWY DLA M.ST. WARSZAWY",
                            "dataWszczeciaLubOtwarcia": "2024-02-15",
                        }
                    ],
                }
            }
        }
    }

    parsed = parse_krs_dzial6_insolvency(sample_dzial6_krs)
    assert parsed["has_insolvency"] is True
    assert parsed["has_restructuring"] is True
    assert parsed["status"] == "POSTEPOWANIE_UPADLOSCIOWE"
    assert len(parsed["wpisy"]) == 2
    assert "WA1M/GUp/123/2025" in parsed["opisy"][0]
    assert "Jan Kowalski" in parsed["opisy"][0]

    # 2. Test silnika ryzyka dla KRZ (upadłość: +60 pkt)
    inp = RiskEvaluationInput(
        is_foreign=False,
        status_rejestru="AKTYWNY",
        upadlosc_lub_likwidacja=True,
        platnik_vat_czynny=True,
        status_vat="Czynny",
        vies_valid=None,
        status_rachunku=StatusRachunkuBankowego.NIE_PODANO,
        kwota_transakcji=None,
        crbr_status="ZGODNY",
        sanction_hits=[],
        status_pep=False,
        blad_polaczenia=False,
        niekompletne_zrodla=[],
        krz_status="POSTEPOWANIE_UPADLOSCIOWE",
        krz_szczegoly=parsed["opisy"],
    )
    score, factors, level, decision, _, _, _ = evaluate_risk(inp)
    assert any(f.code == "INSOLVENCY_PROCEEDINGS" for f in factors)
    assert level in (PoziomRyzykaAML.WYSOKIE, PoziomRyzykaAML.KRYTYCZNE_STOP)
    assert score >= 60


def test_eori_client_and_risk_evaluation():
    from src.providers.eori_client import _parse_eori_response, build_eori_number
    from src.domain.risk_engine import RiskEvaluationInput, evaluate_risk

    # 1. Sprawdzenie formatowania numeru EORI
    assert build_eori_number("5260251049", "PL") == "PL526025104900000"
    assert build_eori_number("PL526025104900000", "PL") == "PL526025104900000"

    # 2. Parsowanie odpowiedzi SOAP (Valid)
    valid_xml = """<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body>
    <ns0:validateEORIResponse xmlns:ns0="http://eori.ws.eos.dds.s/">
    <return><requestDate>28/11/2026</requestDate><result>
    <eori>PL526025104900000</eori><status>0</status><statusDescr>Valid</statusDescr>
    <name>PRZYKLADOWA SPOLKA S.A.</name>
    </result></return></ns0:validateEORIResponse></S:Body></S:Envelope>"""
    parsed = _parse_eori_response(valid_xml, "PL526025104900000")
    assert parsed["valid"] is True
    assert parsed["status_code"] == 0
    assert parsed["name"] == "PRZYKLADOWA SPOLKA S.A."

    # 3. Parsowanie odpowiedzi SOAP (Invalid)
    invalid_xml = """<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body>
    <ns0:validateEORIResponse xmlns:ns0="http://eori.ws.eos.dds.s/">
    <return><requestDate>28/11/2026</requestDate><result>
    <eori>PL000000000000000</eori><status>1</status><statusDescr>Not valid</statusDescr>
    </result></return></ns0:validateEORIResponse></S:Body></S:Envelope>"""
    parsed_invalid = _parse_eori_response(invalid_xml, "PL000000000000000")
    assert parsed_invalid["valid"] is False
    assert parsed_invalid["status_code"] == 1

    # 4. Ocena ryzyka: brak EORI przy handlu paliwami (PKD 46.71)
    inp = RiskEvaluationInput(
        is_foreign=False,
        status_rejestru="AKTYWNY",
        upadlosc_lub_likwidacja=False,
        platnik_vat_czynny=True,
        status_vat="Czynny",
        vies_valid=None,
        status_rachunku=StatusRachunkuBankowego.NIE_PODANO,
        kwota_transakcji=None,
        crbr_status="ZGODNY",
        sanction_hits=[],
        status_pep=False,
        blad_polaczenia=False,
        niekompletne_zrodla=[],
        kody_pkd=["46.71.Z"],
        eori="PL123456789000000",
        eori_valid=False,
    )
    score, factors, _, _, _, _, _ = evaluate_risk(inp)
    assert any(f.code == "EORI_NOT_ACTIVE_HIGH_RISK_TRADE" for f in factors)
    assert score >= 15


@pytest.mark.asyncio
async def test_crypto_mica_and_risk_evaluation():
    from src.providers.crypto_mica_client import CryptoMicaClient, _normalize_name

    # 1. Test normalizacji nazw
    assert _normalize_name("Revolut Digital Assets (Europe) Ltd") == "REVOLUT DIGITAL ASSETS EUROPE"
    assert _normalize_name("Swipelux OÜ") == "SWIPELUX"
    assert _normalize_name("KRYPTO SPÓŁKA Z O.O.") == "KRYPTO"

    client = CryptoMicaClient()

    # 2. Mockowanie danych CASP i Non-compliant
    sample_casps = [
        {
            "name": "Revolut Digital Assets (Europe) Ltd",
            "lei": "549300ET4IUR6RCZOL84",
            "brand": "Revolut",
            "state": "CY",
            "authority": "Cyprus Securities and Exchange Commission (CySEC)",
            "authorisationStatus": "active",
        }
    ]
    sample_nc = [
        {
            "name": "Swipelux OÜ",
            "authority": "Estonian Financial Supervision Authority (EFSA)",
            "reason": "Unauthorised crypto-asset services",
        }
    ]

    async def mock_casps(c):
        return sample_casps

    async def mock_nc(c):
        return sample_nc

    client._get_casps_data = mock_casps
    client._get_non_compliant_data = mock_nc

    import httpx
    dummy_http = httpx.AsyncClient()

    # 3. Weryfikacja podmiotu autoryzowanego (CASP)
    res_casp = await client.verify_crypto_status(dummy_http, "Revolut Digital Assets (Europe) Ltd")
    assert res_casp["status"] == "AUTORYZOWANY_CASP"
    assert res_casp["is_casp"] is True
    assert res_casp["is_non_compliant"] is False

    # 4. Weryfikacja podmiotu z listy ostrzeżeń (Non-compliant)
    res_nc = await client.verify_crypto_status(dummy_http, "Swipelux OÜ")
    assert res_nc["status"] == "OSTRZEZENIE_NIEAUTORYZOWANY"
    assert res_nc["is_non_compliant"] is True
    assert res_nc["is_casp"] is False

    # 5. Weryfikacja zwykłej firmy (Brak wpisu)
    res_std = await client.verify_crypto_status(dummy_http, "ZWYKŁA FIRMA HANDLOWA SP Z O O")
    assert res_std["status"] == "BRAK_WPISU"
    assert res_std["is_casp"] is False

    # 6. Ocena ryzyka: trafienie na liście ostrzeżeń MiCA -> KRYTYCZNE_STOP
    inp_stop = RiskEvaluationInput(
        is_foreign=False,
        status_rejestru="AKTYWNY",
        upadlosc_lub_likwidacja=False,
        platnik_vat_czynny=True,
        status_vat="Czynny",
        vies_valid=None,
        status_rachunku=StatusRachunkuBankowego.NIE_PODANO,
        kwota_transakcji=None,
        crbr_status="ZGODNY",
        sanction_hits=[],
        status_pep=False,
        blad_polaczenia=False,
        niekompletne_zrodla=[],
        mica_status="OSTRZEZENIE_NIEAUTORYZOWANY",
    )
    score_stop, factors_stop, poziom_stop, decyzja_stop, _, _, _ = evaluate_risk(inp_stop)
    assert score_stop == 100
    assert any(f.code == "MICA_NON_COMPLIANT_WARNING" for f in factors_stop)
    assert poziom_stop == PoziomRyzykaAML.KRYTYCZNE_STOP
    assert decyzja_stop == DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP

    # 7. Ocena ryzyka: autoryzowany CASP -> +20 pkt (EDD)
    inp_casp = RiskEvaluationInput(
        is_foreign=False,
        status_rejestru="AKTYWNY",
        upadlosc_lub_likwidacja=False,
        platnik_vat_czynny=True,
        status_vat="Czynny",
        vies_valid=None,
        status_rachunku=StatusRachunkuBankowego.NIE_PODANO,
        kwota_transakcji=None,
        crbr_status="ZGODNY",
        sanction_hits=[],
        status_pep=False,
        blad_polaczenia=False,
        niekompletne_zrodla=[],
        mica_status="AUTORYZOWANY_CASP",
    )
    score_casp, factors_casp, _, _, _, _, _ = evaluate_risk(inp_casp)
    assert any(f.code == "MICA_AUTHORIZED_CASP_EDD" for f in factors_casp)
    assert score_casp >= 20




