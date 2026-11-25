"""Asynchroniczny klient Hurtowni Danych CEIDG v2 (dane.biznes.gov.pl)."""

import os
from typing import Any, Dict, List, Optional

import httpx

from src.config import CEIDG_API_TOKEN
from src.core.validators import clean_nip
from src.providers.base import http_request_with_retry

CEIDG_API_URL = "https://dane.biznes.gov.pl/api/ceidg/v2/firmy"


async def fetch_ceidg_info(
    client: httpx.AsyncClient,
    nip: str,
    api_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Pobiera dane JDG (status, data rozpoczęcia, kody PKD) z API CEIDG v2."""
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

        wpis = firmy[0]
        pkd_list: List[str] = list(wpis.get("pkd") or [])
        pkd_glowny = wpis.get("pkdGlowny")
        if pkd_glowny and pkd_glowny not in pkd_list:
            pkd_list.insert(0, pkd_glowny)

        raw_status = (wpis.get("status") or "").upper()
        if "ZAWIESZ" in raw_status:
            status_rejestru = "ZAWIESZONY"
        elif "WYKRESL" in raw_status:
            status_rejestru = "WYKRESLONY"
        else:
            status_rejestru = "AKTYWNY"

        return {
            "found": True,
            "configured": True,
            "nip": normalized_nip,
            "nazwa": (wpis.get("nazwa") or "").strip(),
            "status_rejestru": status_rejestru,
            "data_rozpoczecia": wpis.get("dataRozpoczecia") or "",
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
