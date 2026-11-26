"""Asynchroniczny klient otwartego API Krajowego Rejestru Sądowego (api-krs.ms.gov.pl)."""

from typing import Any, Dict, List

import httpx

from src.core.validators import clean_krs
from src.providers.base import http_request_with_retry

KRS_API_BASE = "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny"


def _format_address(addr: Dict[str, Any]) -> str:
    if not isinstance(addr, dict):
        return ""
    ulica = addr.get("ulica", "")
    nr_domu = addr.get("nrDomu", "")
    nr_lok = addr.get("nrLokalu", "")
    kod = addr.get("kodPocztowy", "")
    miejscowosc = addr.get("miejscowosc", "")

    street_part = " ".join(p for p in [ulica, f"{nr_domu}/{nr_lok}" if nr_lok else nr_domu] if p).strip()
    city_part = " ".join(p for p in [kod, miejscowosc] if p).strip()
    return ", ".join(p for p in [street_part, city_part] if p)


def _extract_person_name(person: Dict[str, Any]) -> str:
    nazwisko = person.get("nazwisko", {})
    if isinstance(nazwisko, dict):
        nazwisko_str = nazwisko.get("nazwiskoICzlon", "")
    else:
        nazwisko_str = str(nazwisko or "")

    imiona = person.get("imiona", {})
    if isinstance(imiona, dict):
        imie_str = imiona.get("imie", "")
    else:
        imie_str = str(imiona or "")

    funkcja = person.get("funkcjaWOrganie", "")
    full_name = " ".join(p for p in [imie_str, nazwisko_str] if p).strip()
    if full_name and funkcja:
        return f"{full_name} ({funkcja})"
    return full_name


def parse_krs_odpis(data: Dict[str, Any], krs: str) -> Dict[str, Any]:
    """Deterministycznie parsuje JSON z API KRS (OdpisAktualny)."""
    odpis = data.get("odpis") or {}
    dane = odpis.get("dane") or {}
    dzial1 = dane.get("dzial1") or {}
    dzial2 = dane.get("dzial2") or {}
    dzial3 = dane.get("dzial3") or {}
    dzial6 = dane.get("dzial6") or {}

    podmiot = dzial1.get("danePodmiotu") or {}
    identyfikatory = podmiot.get("identyfikatory") or {}
    siedziba_adres = dzial1.get("siedzibaIAdres") or {}

    nazwa = (podmiot.get("nazwa") or "").strip()
    forma_prawna = (podmiot.get("formaPrawna") or "SPÓŁKA HANDLOWA").strip()
    nip = (identyfikatory.get("nip") or "").strip() or None
    regon = (identyfikatory.get("regon") or "").strip() or None
    adres = _format_address(siedziba_adres.get("adres") or {})

    naglowek = odpis.get("naglowekA") or {}
    data_rejestracji = naglowek.get("dataRejestracjiWKRS") or ""
    status_wykreslenia = bool(naglowek.get("stanPozycji") == "WYKRESLONY" or naglowek.get("dataWykreslenia"))

    # Reprezentacja (Dział 2)
    reprezentacja: List[str] = []
    rep_block = dzial2.get("reprezentacja") or {}
    sklad = rep_block.get("sklad") or []
    for member in sklad:
        if isinstance(member, dict):
            name = _extract_person_name(member)
            if name and name not in reprezentacja:
                reprezentacja.append(name)

    for prok in dzial2.get("prokurenci") or []:
        if isinstance(prok, dict):
            name = _extract_person_name(prok)
            if name:
                reprezentacja.append(f"{name} [Prokurent]")

    # PKD (Dział 3)
    kody_pkd: List[str] = []
    pkd_glowny = None
    przedmiot = dzial3.get("przedmiotDzialalnosci") or {}
    for pkd_item in przedmiot.get("przedmiotPrzewazajacejDzialalnosci") or []:
        kod = _format_pkd_code(pkd_item)
        if kod:
            pkd_glowny = kod
            kody_pkd.append(kod)
    for pkd_item in przedmiot.get("przedmiotPozostalejDzialalnosci") or []:
        kod = _format_pkd_code(pkd_item)
        if kod and kod not in kody_pkd:
            kody_pkd.append(kod)

    # Upadłość / Likwidacja (Dział 6)
    upadlosc_lub_likwidacja = bool(
        dzial6.get("likwidacja")
        or dzial6.get("postepowanieUpadlosciowe")
        or dzial6.get("postepowanieRestrukturyzacyjne")
        or dzial6.get("postepowanieUkladowe")
    )

    # Wspólnicy (Dział 1)
    wspolnicy: List[str] = []
    for wsp_item in (dzial1.get("wspolnicySpzoo") or dzial1.get("wspolnicy") or []):
        if isinstance(wsp_item, dict):
            name = _extract_person_name(wsp_item)
            udzialy = wsp_item.get("posiadaneUdzialy")
            if name:
                wspolnicy.append(f"{name} ({udzialy})" if udzialy else name)

    return {
        "found": True,
        "krs": clean_krs(krs),
        "nip": nip,
        "regon": regon,
        "nazwa": nazwa,
        "forma_prawna": forma_prawna,
        "adres": adres,
        "data_rejestracji": data_rejestracji,
        "status_rejestru": "WYKRESLONY" if status_wykreslenia else "AKTYWNY",
        "upadlosc_lub_likwidacja": upadlosc_lub_likwidacja,
        "reprezentacja": reprezentacja,
        "wspolnicy": wspolnicy,
        "kody_pkd": kody_pkd,
        "pkd_glowny": pkd_glowny,
        "blad_polaczenia": False,
        "raw": data,
    }


def _format_pkd_code(item: Dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ""
    dzial = str(item.get("kodDzial") or "").strip()
    klasa = str(item.get("kodKlasa") or "").strip()
    podklasa = str(item.get("kodPodklasa") or "").strip()
    if dzial and klasa and podklasa:
        return f"{dzial}.{klasa}.{podklasa}"
    return ""


async def fetch_krs_odpis(client: httpx.AsyncClient, krs: str) -> Dict[str, Any]:
    """Pobiera aktualny odpis podmiotu z otwartego API KRS (rejestr P, fallback S)."""
    normalized_krs = clean_krs(krs)
    if len(normalized_krs) != 10:
        return {"found": False, "krs": normalized_krs, "blad_polaczenia": False}

    for rejestr in ("P", "S"):
        url = f"{KRS_API_BASE}/{normalized_krs}?rejestr={rejestr}&format=json"
        try:
            resp = await http_request_with_retry(client, "GET", url)
            if resp.status_code == 200:
                data = resp.json()
                return parse_krs_odpis(data, normalized_krs)
            if resp.status_code == 404:
                continue
            return {
                "found": False,
                "krs": normalized_krs,
                "blad_polaczenia": True,
                "komunikat_bledu": f"API KRS HTTP {resp.status_code}",
            }
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "found": False,
                "krs": normalized_krs,
                "blad_polaczenia": True,
                "komunikat_bledu": f"Błąd API KRS: {exc.__class__.__name__}",
            }

    return {"found": False, "krs": normalized_krs, "blad_polaczenia": False, "status_rejestru": "NIEZNALEZIONY"}
