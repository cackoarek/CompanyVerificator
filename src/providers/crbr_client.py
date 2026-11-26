"""Asynchroniczny klient Centralnego Rejestru Beneficjentów Rzeczywistych (CRBR)."""

import re
from typing import Any, Dict, List

import httpx

from src.core.validators import clean_nip
from src.providers.base import http_request_with_retry

CRBR_API_URL = "https://crbr.podatki.gov.pl/adcrbr/api/pobierzZgloszeniaPoNIP"
CRBR_HEADERS = {
    "Content-Type": "application/json",
    "Referer": "https://crbr.podatki.gov.pl/adcrbr/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _normalize_person_tokens(full_name: str) -> set[str]:
    clean = re.sub(r"\(.*?\)|\[.*?\]", "", full_name or "").lower()
    for k, v in {"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z"}.items():
        clean = clean.replace(k, v)
    return set(re.findall(r"[a-z]{2,}", clean))


def matches_masked(masked: str, raw: str) -> bool:
    """Sprawdza czy zanonimizowana wartość z KRS (np. P*****, I***, 6**********) pasuje do pełnej wartości."""
    if not masked or not raw:
        return False
    m = masked.strip().upper()
    r = raw.strip().upper()
    if m == r:
        return True
    # Maskowanie w KRS to litera i gwiazdki, np. P***** lub I***
    pattern = "^" + re.escape(m).replace(r"\*", ".*") + "$"
    return bool(re.match(pattern, r))


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

    return "ZGODNY"


def _format_beneficiary_entry(item: Dict[str, Any]) -> str:
    """Formatuje pojedynczy wpis beneficjenta z obiektu CRBR."""
    imie = (item.get("imie") or item.get("pierwszeImie") or item.get("imiePierwsze") or "").strip()
    nazwisko = (item.get("nazwisko") or "").strip()
    full = " ".join(p for p in [imie, nazwisko] if p).strip()

    # Obywatelstwo
    obyw_list = item.get("obywatelstwo") or []
    obyw_strs: List[str] = []
    if isinstance(obyw_list, list):
        for o in obyw_list:
            if isinstance(o, dict):
                obyw_strs.append(o.get("nazwa") or o.get("kodKraju") or "")
            elif isinstance(o, str):
                obyw_strs.append(o)
    obyw_label = f" [Obywatelstwo: {', '.join(filter(None, obyw_strs))}]" if obyw_strs else ""

    # Uprawnienia / rola
    uprawnienia = item.get("informacjeOUdzialeLubUprawnieniach") or []
    rola_parts: List[str] = []
    if isinstance(uprawnienia, list):
        for u in uprawnienia:
            if isinstance(u, dict):
                r_opis = u.get("rodzajWlasnosciOpis") or ""
                ilosc = u.get("ilosc")
                jm = u.get("jednostkaMiaryUdzialuOpis") or ""
                if r_opis and ilosc:
                    rola_parts.append(f"{r_opis}: {ilosc} {jm}".strip())
                elif r_opis:
                    rola_parts.append(r_opis)
    
    if not rola_parts:
        r_legacy = (item.get("charakterUprawnien") or item.get("rola") or "").strip()
        if r_legacy:
            rola_parts.append(r_legacy)

    rola_label = f" ({'; '.join(rola_parts)})" if rola_parts else ""
    return f"{full}{obyw_label}{rola_label}".strip()


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
            headers=CRBR_HEADERS,
        )
        if resp.status_code == 404:
            return {
                "found": False,
                "crbr_status": "BRAK_WPISU",
                "beneficjenci": [],
                "blad_polaczenia": False,
            }
        # CRBR zwraca HTTP 400 z komunikatem "Niepoprawny NIP" dla podmiotów niemających zgłoszenia lub JDG
        if resp.status_code == 400:
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
        beneficjenci: List[str] = []

        raw_list = []
        if isinstance(data, list):
            # Odpowiedź z /adcrbr/api/pobierzZgloszeniaPoNIP to lista zgłoszeń, najświeższe na początku
            if not data:
                return {
                    "found": False,
                    "crbr_status": "BRAK_WPISU",
                    "beneficjenci": [],
                    "beneficjenci_details": [],
                    "blad_polaczenia": False,
                    "raw": data,
                }
            latest = data[0]
            raw_list = latest.get("listaBeneficjentow") or latest.get("beneficjenci") or []
        elif isinstance(data, dict):
            # Wsparcie dla starszego formatu / mocków testowych
            raw_list = data.get("beneficjenci") or data.get("listaBeneficjentow") or []

        beneficjenci_details: List[Dict[str, Any]] = []
        for item in raw_list:
            if isinstance(item, dict):
                formatted = _format_beneficiary_entry(item)
                if formatted and formatted not in beneficjenci:
                    beneficjenci.append(formatted)

                imie = (item.get("imie") or item.get("pierwszeImie") or item.get("imiePierwsze") or "").strip()
                nazwisko = (item.get("nazwisko") or "").strip()
                pesel = (item.get("pesel") or "").strip()

                obyw_list = item.get("obywatelstwo") or []
                obyw_strs: List[str] = []
                if isinstance(obyw_list, list):
                    for o in obyw_list:
                        if isinstance(o, dict):
                            obyw_strs.append(o.get("nazwa") or o.get("kodKraju") or "")
                        elif isinstance(o, str):
                            obyw_strs.append(o)
                obywatelstwo = ", ".join(filter(None, obyw_strs))

                beneficjenci_details.append(
                    {
                        "imie": imie,
                        "nazwisko": nazwisko,
                        "pesel": pesel,
                        "obywatelstwo": obywatelstwo,
                        "formatted": formatted,
                    }
                )

        if not beneficjenci:
            return {
                "found": False,
                "crbr_status": "BRAK_WPISU",
                "beneficjenci": [],
                "beneficjenci_details": [],
                "blad_polaczenia": False,
                "raw": data,
            }

        return {
            "found": True,
            "crbr_status": "ZGODNY",
            "beneficjenci": beneficjenci,
            "beneficjenci_details": beneficjenci_details,
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
