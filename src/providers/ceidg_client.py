"""Asynchroniczny klient Hurtowni Danych CEIDG v3 (dane.biznes.gov.pl)."""

import os
from typing import Any, Dict, List, Optional

import httpx

from src.config import CEIDG_API_TOKEN
from src.core.validators import clean_nip
from src.providers.base import http_request_with_retry

CEIDG_API_URL = "https://dane.biznes.gov.pl/api/ceidg/v3/firmy"


def _format_ceidg_address(adres_obj: Optional[Dict[str, Any]]) -> Optional[str]:
    """Formatuje obiekt adresu z CEIDG v3 do czytelnego ciągu tekstowego."""
    if not adres_obj or not isinstance(adres_obj, dict):
        return None
    ulica = adres_obj.get("ulica") or ""
    budynek = adres_obj.get("budynek") or ""
    lokal = adres_obj.get("lokal")
    kod = adres_obj.get("kod") or ""
    miasto = adres_obj.get("miasto") or ""

    parts = []
    if ulica and budynek:
        parts.append(f"{ulica} {budynek}" + (f"/{lokal}" if lokal else ""))
    elif ulica:
        parts.append(ulica)
    elif budynek:
        parts.append(f"bud. {budynek}" + (f"/{lokal}" if lokal else ""))

    if kod or miasto:
        parts.append(f"{kod} {miasto}".strip())

    return ", ".join(parts) if parts else None


async def fetch_ceidg_info(
    client: httpx.AsyncClient,
    nip: str,
    api_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Pobiera dane JDG (status, nazwa, adres, REGON, kody PKD) z API CEIDG v3."""
    normalized_nip = clean_nip(nip)
    token = (api_token if api_token is not None else os.getenv("CEIDG_API_TOKEN", "").strip()) or CEIDG_API_TOKEN

    if not token:
        return {"found": False, "configured": False, "blad_polaczenia": False}
    if len(normalized_nip) != 10:
        return {"found": False, "configured": True, "blad_polaczenia": False}

    url = f"{CEIDG_API_URL}?nip={normalized_nip}"
    try:
        resp = await http_request_with_retry(
            client,
            "GET",
            url,
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            # Sprawdź czy to 404 bramki API czy brak danych
            text_resp = resp.text
            if "No context-path" in text_resp:
                return {
                    "found": False,
                    "configured": True,
                    "blad_polaczenia": True,
                    "komunikat_bledu": "CEIDG API Gateway 404 (nieprawidłowy context-path)",
                }
            return {"found": False, "configured": True, "blad_polaczenia": False}

        if resp.status_code != 200:
            return {
                "found": False,
                "configured": True,
                "blad_polaczenia": True,
                "komunikat_bledu": f"CEIDG HTTP {resp.status_code}",
            }

        data = resp.json()
        firmy = data.get("firmy") or []
        if not firmy:
            return {"found": False, "configured": True, "blad_polaczenia": False}

        # Jeśli jest więcej niż 1 wpis (np. historyczne wykreślone JDG),
        # preferujemy wpis AKTYWNY lub ZAWIESZONY
        wpis = firmy[0]
        for f in firmy:
            st = (f.get("status") or "").upper()
            if st in ("AKTYWNY", "ZAWIESZONY"):
                wpis = f
                break

        # Dane bazowe z listy firm
        raw_status = (wpis.get("status") or "").upper()
        if "ZAWIESZ" in raw_status:
            status_rejestru = "ZAWIESZONY"
        elif "WYKRESL" in raw_status:
            status_rejestru = "WYKRESLONY"
        else:
            status_rejestru = "AKTYWNY"

        wlasciciel = wpis.get("wlasciciel") or {}
        regon = wlasciciel.get("regon")
        adres_str = _format_ceidg_address(wpis.get("adresDzialalnosci"))
        data_rozpoczecia = wpis.get("dataRozpoczecia") or ""
        nazwa = (wpis.get("nazwa") or "").strip()

        # Sprawdź kody PKD bezpośrednio lub pobierz szczegóły z linku jeśli dostępne
        pkd_list: List[str] = []
        pkd_glowny: Optional[str] = None

        if "pkd" in wpis or "pkdGlowny" in wpis:
            raw_pkd = wpis.get("pkd") or []
            for p in raw_pkd:
                kod = p.get("kod") if isinstance(p, dict) else str(p)
                if kod and kod not in pkd_list:
                    pkd_list.append(kod)
            glowny_raw = wpis.get("pkdGlowny")
            pkd_glowny = glowny_raw.get("kod") if isinstance(glowny_raw, dict) else (str(glowny_raw) if glowny_raw else None)
        elif wpis.get("link"):
            # Pobierz szczegóły wpisu (kody PKD, dokładny adres)
            try:
                detail_resp = await http_request_with_retry(
                    client,
                    "GET",
                    wpis["link"],
                    headers={"Authorization": f"Bearer {token}"},
                )
                if detail_resp.status_code == 200:
                    detail_data = detail_resp.json()
                    firma_list = detail_data.get("firma") or []
                    if firma_list:
                        f_detail = firma_list[0]
                        wpis = {**wpis, **f_detail}
                        raw_pkd = f_detail.get("pkd") or []
                        for p in raw_pkd:
                            kod = p.get("kod") if isinstance(p, dict) else str(p)
                            if kod and kod not in pkd_list:
                                pkd_list.append(kod)
                        glowny_raw = f_detail.get("pkdGlowny")
                        pkd_glowny = glowny_raw.get("kod") if isinstance(glowny_raw, dict) else (str(glowny_raw) if glowny_raw else None)
                        if not adres_str:
                            adres_str = _format_ceidg_address(f_detail.get("adresDzialalnosci"))
            except Exception:
                pass

        if pkd_glowny and pkd_glowny not in pkd_list:
            pkd_list.insert(0, pkd_glowny)

        return {
            "found": True,
            "configured": True,
            "nip": normalized_nip,
            "nazwa": nazwa,
            "regon": regon,
            "adres": adres_str,
            "status_rejestru": status_rejestru,
            "data_rozpoczecia": data_rozpoczecia,
            "kody_pkd": pkd_list,
            "pkd_glowny": pkd_glowny,
            "blad_polaczenia": False,
            "raw": wpis,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "found": False,
            "configured": True,
            "blad_polaczenia": True,
            "komunikat_bledu": f"CEIDG błąd sieci ({exc.__class__.__name__})",
        }
