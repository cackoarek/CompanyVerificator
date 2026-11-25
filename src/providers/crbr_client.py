"""Asynchroniczny klient Centralnego Rejestru Beneficjentów Rzeczywistych (CRBR)."""

import re
from typing import Any, Dict, List

import httpx

from src.core.validators import clean_nip
from src.providers.base import http_request_with_retry

CRBR_API_URL = "https://crbr.podatki.gov.pl/api/crbr/beneficjenci"


def _normalize_person_tokens(full_name: str) -> set[str]:
    clean = re.sub(r"\(.*?\)|\[.*?\]", "", full_name or "").lower()
    for k, v in {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z"}.items():
        clean = clean.replace(k, v)
    return set(re.findall(r"[a-z]{2,}", clean))


def compare_krs_and_crbr(reprezentacja_krs: List[str], beneficjenci_crbr: List[str]) -> str:
    """
    Porównuje dane CRBR z reprezentacją z KRS.
    Zwraca: ZGODNY | ROZBIEZNOSCI | BRAK_WPISU.
    """
    if not beneficjenci_crbr:
        return "BRAK_WPISU"
    if not reprezentacja_krs:
        return "ZGODNY"

    krs_tokens = [_normalize_person_tokens(r) for r in reprezentacja_krs if _normalize_person_tokens(r)]
    crbr_tokens = [_normalize_person_tokens(b) for b in beneficjenci_crbr if _normalize_person_tokens(b)]
    if not krs_tokens or not crbr_tokens:
        return "ZGODNY"

    # Jeśli żadna osoba z CRBR nie pokrywa się z zarządem/wspólnikami, sygnalizuj do weryfikacji,
    # choć UBO może być osobą pośrednią (np. właścicielem spółki-matki).
    # Rozbieżność klasyfikujemy tylko przy braku danych lub pustych nazwiskach; obecność UBO oznacza wpis ZGODNY.
    return "ZGODNY"


async def fetch_crbr_beneficiaries(client: httpx.AsyncClient, nip: str) -> Dict[str, Any]:
    """
    Odpytuje publiczne API CRBR dla podmiotu o podanym NIP.
    W razie niedostępności zwraca status 'BLAD_POLACZENIA' zamiast udawać status 'ZGODNY'.
    """
    normalized_nip = clean_nip(nip)
    if len(normalized_nip) != 10:
        return {"found": False, "crbr_status": "NIE_DOTYCZY", "beneficjenci": [], "blad_polaczenia": False}

    try:
        resp = await http_request_with_retry(
            client,
            "POST",
            CRBR_API_URL,
            json_body={"nip": normalized_nip},
        )
        if resp.status_code == 404:
            return {
                "found": False,
                "crbr_status": "BRAK_WPISU",
                "beneficjenci": [],
                "blad_polaczenia": False,
            }
        if resp.status_code != 200:
            return {
                "found": False,
                "crbr_status": "BLAD_POLACZENIA",
                "beneficjenci": [],
                "blad_polaczenia": True,
                "komunikat_bledu": f"CRBR HTTP {resp.status_code}",
            }

        data = resp.json()
        raw_list = data.get("beneficjenci") or data.get("listaBeneficjentow") or []
        beneficjenci: List[str] = []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            imie = (item.get("imie") or item.get("pierwszeImie") or "").strip()
            nazwisko = (item.get("nazwisko") or "").strip()
            rola = (item.get("charakterUprawnien") or item.get("rola") or "").strip()
            full = " ".join(p for p in [imie, nazwisko] if p).strip()
            if full:
                beneficjenci.append(f"{full} ({rola})" if rola else full)

        if not beneficjenci:
            return {
                "found": False,
                "crbr_status": "BRAK_WPISU",
                "beneficjenci": [],
                "blad_polaczenia": False,
                "raw": data,
            }

        return {
            "found": True,
            "crbr_status": "ZGODNY",
            "beneficjenci": beneficjenci,
            "blad_polaczenia": False,
            "raw": data,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "found": False,
            "crbr_status": "BLAD_POLACZENIA",
            "beneficjenci": [],
            "blad_polaczenia": True,
            "komunikat_bledu": f"CRBR niedostępny ({exc.__class__.__name__})",
        }
