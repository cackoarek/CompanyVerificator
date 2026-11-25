"""Asynchroniczny klient systemu VIES (Komisja Europejska) dla numerów VAT-UE."""

from typing import Any, Dict

import httpx

from src.providers.base import http_request_with_retry

VIES_REST_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"


async def check_vies_vat(client: httpx.AsyncClient, full_vat_number: str) -> Dict[str, Any]:
    """Weryfikuje numer VAT-UE (np. DE123456789, IE9825613N) w europejskim API VIES."""
    clean = (full_vat_number or "").strip().upper().replace(" ", "").replace("-", "")
    if len(clean) < 4 or not clean[:2].isalpha():
        return {"valid": False, "blad_polaczenia": False, "komunikat_bledu": "Nieprawidłowy format VAT-UE"}

    country_code = clean[:2]
    vat_number = clean[2:]

    try:
        resp = await http_request_with_retry(
            client,
            "POST",
            VIES_REST_URL,
            json_body={"countryCode": country_code, "vatNumber": vat_number},
        )
        if resp.status_code != 200:
            return {
                "valid": None,
                "country_code": country_code,
                "vat_number": clean,
                "blad_polaczenia": True,
                "komunikat_bledu": f"VIES HTTP {resp.status_code}",
            }

        data = resp.json()
        # API VIES zwraca {"valid": true/false, "name": "...", "address": "...", "requestIdentifier": "..."}
        # lub przy niedostępności kraju członkowskiego {"userError": "MS_UNAVAILABLE"}
        user_error = data.get("userError")
        if user_error and user_error not in ("VALID", "INVALID"):
            return {
                "valid": None,
                "country_code": country_code,
                "vat_number": clean,
                "blad_polaczenia": True,
                "komunikat_bledu": f"VIES niedostępny: {user_error}",
                "raw": data,
            }

        return {
            "valid": bool(data.get("valid", False)),
            "country_code": country_code,
            "vat_number": clean,
            "nazwa": (data.get("name") or "").strip(),
            "adres": (data.get("address") or "").strip(),
            "request_id": data.get("requestIdentifier"),
            "blad_polaczenia": False,
            "raw": data,
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "valid": None,
            "country_code": country_code,
            "vat_number": clean,
            "blad_polaczenia": True,
            "komunikat_bledu": f"Błąd połączenia z VIES ({exc.__class__.__name__})",
        }
