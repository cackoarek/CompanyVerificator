"""Hermetyczne testy asynchronicznych providerów rejestrów oraz parserów/matchera sankcji."""

import httpx
import pytest
import respx

from src.providers.ceidg_client import fetch_ceidg_info
from src.providers.crbr_client import fetch_crbr_beneficiaries
from src.providers.krs_client import fetch_krs_odpis
from src.providers.mf_white_list import check_mf_bank_account, fetch_mf_white_list
from src.providers.sanctions.matcher import match_sanctions
from src.providers.sanctions.sync_service import parse_eu_sanctions_xml, parse_mswia_html
from src.providers.vies_client import check_vies_vat


@pytest.mark.asyncio
async def test_mf_white_list_and_virtual_account():
    with respx.mock(assert_all_called=True) as mock:
        mock.get(url__regex=r"https://wl-api\.mf\.gov\.pl/api/search/nip/9512120077.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "result": {
                        "requestId": "mf-search-001",
                        "subject": {
                            "name": "P4 SP. Z O.O.",
                            "nip": "9512120077",
                            "statusVat": "Czynny",
                            "regon": "015808609",
                            "krs": "0000217207",
                            "workingAddress": "Wynalazek 1, Warszawa",
                            "accountNumbers": ["74109000040000001178980015"],
                        },
                    }
                },
            )
        )
        mock.get(
            url__regex=r"https://wl-api\.mf\.gov\.pl/api/check/nip/9512120077/bank-account/93109000047777010097655657.*"
        ).mock(
            return_value=httpx.Response(
                200,
                json={"result": {"accountAssigned": "TAK", "requestId": "mf-check-999"}},
            )
        )

        async with httpx.AsyncClient() as client:
            res = await fetch_mf_white_list(client, "9512120077")
            assert res["found"] is True
            assert res["platnik_vat"] is True
            assert res["krs"] == "0000217207"
            assert res["request_id"] == "mf-search-001"

            chk = await check_mf_bank_account(client, "9512120077", "93109000047777010097655657")
            assert chk["assigned"] is True
            assert chk["request_id"] == "mf-check-999"


@pytest.mark.asyncio
async def test_krs_parser_and_crbr_and_ceidg_and_vies():
    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/0000217207?rejestr=P&format=json").mock(
            return_value=httpx.Response(
                200,
                json={
                    "odpis": {
                        "naglowekA": {"dataRejestracjiWKRS": "2004-09-17"},
                        "dane": {
                            "dzial1": {
                                "danePodmiotu": {
                                    "nazwa": "P4 SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
                                    "formaPrawna": "SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ",
                                    "identyfikatory": {"nip": "9512120077", "regon": "015808609"},
                                },
                                "siedzibaIAdres": {
                                    "adres": {"ulica": "Wynalazek", "nrDomu": "1", "kodPocztowy": "02-677", "miejscowosc": "Warszawa"}
                                },
                            },
                            "dzial2": {
                                "reprezentacja": {
                                    "sklad": [
                                        {"imiona": {"imie": "Jan"}, "nazwisko": {"nazwiskoICzlon": "Kowalski"}, "funkcjaWOrganie": "PREZES ZARZĄDU"}
                                    ]
                                }
                            },
                            "dzial3": {
                                "przedmiotDzialalnosci": {
                                    "przedmiotPrzewazajacejDzialalnosci": [{"kodDzial": "61", "kodKlasa": "20", "kodPodklasa": "Z"}]
                                }
                            },
                            "dzial6": {},
                        },
                    }
                },
            )
        )
        mock.post("https://crbr.podatki.gov.pl/adcrbr/api/pobierzZgloszeniaPoNIP").mock(
            return_value=httpx.Response(
                200,
                json={"beneficjenci": [{"imie": "Jan", "nazwisko": "Kowalski", "charakterUprawnien": "udziałowiec"}]},
            )
        )
        mock.get("https://dane.biznes.gov.pl/api/ceidg/v3/firmy?nip=5250001090").mock(
            return_value=httpx.Response(
                200,
                json={"firmy": [{"nazwa": "FIRMA JDG", "status": "ZAWIESZONY", "pkdGlowny": "62.01.Z", "pkd": ["62.01.Z"], "dataRozpoczecia": "2020-01-01"}]},
            )
        )
        mock.post("https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number").mock(
            return_value=httpx.Response(
                200,
                json={"valid": True, "name": "ACME GMBH", "address": "Berlin", "requestIdentifier": "VIES-123"},
            )
        )

        async with httpx.AsyncClient() as client:
            krs_res = await fetch_krs_odpis(client, "0000217207")
            assert krs_res["found"] is True
            assert "Jan Kowalski (PREZES ZARZĄDU)" in krs_res["reprezentacja"]
            assert krs_res["pkd_glowny"] == "61.20.Z"

            crbr_res = await fetch_crbr_beneficiaries(client, "9512120077")
            assert crbr_res["crbr_status"] == "ZGODNY"
            assert len(crbr_res["beneficjenci"]) == 1

            ceidg_res = await fetch_ceidg_info(client, "5250001090", api_token="test-token")
            assert ceidg_res["status_rejestru"] == "ZAWIESZONY"

            vies_res = await check_vies_vat(client, "DE123456789")
            assert vies_res["valid"] is True
            assert vies_res["nazwa"] == "ACME GMBH"


def test_sanctions_parsers_and_matcher():
    eu_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <export>
      <sanctionEntity>
        <subjectType code="enterprise"/>
        <nameAlias wholeName="Alpha Sanctions Corp"/>
        <regulation numberTitle="2022/263"/>
      </sanctionEntity>
      <sanctionEntity>
        <subjectType code="person"/>
        <nameAlias wholeName="Ivan Petrovich Testov"/>
      </sanctionEntity>
    </export>"""
    eu_entries = parse_eu_sanctions_xml(eu_xml)
    assert len(eu_entries) == 2
    assert eu_entries[0]["entry_type"] == "ENTITY"
    assert eu_entries[1]["entry_type"] == "PERSON"

    mswia_html = """
    <table>
      <tr><td>Lp</td><td>Nazwa podmiotu</td><td>Uwagi</td></tr>
      <tr><td>1</td><td>Evil Corp Sp. z o.o.</td><td>NIP: 5252877567 KRS: 0000340774</td></tr>
    </table>
    """
    mswia_entries = parse_mswia_html(mswia_html)
    assert len(mswia_entries) == 1
    assert mswia_entries[0]["nip"] == "5252877567"
    assert mswia_entries[0]["krs"] == "0000340774"

    hits = match_sanctions(
        nip="5252877567",
        krs=None,
        company_name="Dowolna Firma",
        persons=["Ivan Testov"],
        entries=[
            {"source": "MSWIA", "entry_type": "ENTITY", "name": "Evil Corp", "nip": "5252877567", "krs": None, "aliases": [], "reason": "Lista MSWiA"},
            {"source": "EU", "entry_type": "PERSON", "name": "Ivan Petrovich Testov", "nip": None, "krs": None, "aliases": [], "reason": "EU Reg"},
        ],
    )
    assert any(h.match_type == "NIP" and h.confidence == "EXACT" for h in hits)
    assert any(h.match_type == "PERSON" and h.confidence == "HIGH" for h in hits)
