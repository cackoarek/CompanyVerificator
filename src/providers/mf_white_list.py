"""Asynchroniczny klient Białej Listy Podatników VAT (Ministerstwo Finansów)."""

import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

from src.core.validators import clean_nip, clean_nrb, clean_regon
from src.providers.base import http_request_with_retry

MF_SEARCH_URL = "https://wl-api.mf.gov.pl/api/search/nip"
MF_SEARCH_REGON_URL = "https://wl-api.mf.gov.pl/api/search/regon"
MF_CHECK_URL = "https://wl-api.mf.gov.pl/api/check/nip"


async def fetch_mf_white_list(
    client: httpx.AsyncClient,
    nip: str,
    date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """Odpytuje Białą Listę Podatników VAT MF po numerze NIP."""
    normalized_nip = clean_nip(nip)
    if len(normalized_nip) != 10:
        return {
            "nip": normalized_nip,
            "found": False,
            "status_vat": "Nieprawidłowy NIP",
            "platnik_vat": False,
            "blad_polaczenia": False,
            "zrodlo": "MF_BIALA_LISTA",
        }

    query_date = date_str or datetime.now().strftime("%Y-%m-%d")
    url = f"{MF_SEARCH_URL}/{normalized_nip}?date={query_date}"

    try:
        resp = await http_request_with_retry(client, "GET", url)
        if resp.status_code == 404:
            return {
                "nip": normalized_nip,
                "found": False,
                "status_vat": "Niezarejestrowany (brak w wykazie MF)",
                "platnik_vat": False,
                "blad_polaczenia": False,
                "zrodlo": "MF_BIALA_LISTA",
            }
        if resp.status_code == 400:
            # Sprawdź czy to znany błąd przejściowy MF (np. WL-196 = aktualizacja bazy)
            try:
                err_body = resp.json()
            except Exception:
                err_body = {}
            err_code = err_body.get("code", "")
            err_msg = err_body.get("message", "")
            if err_code in ("WL-196", "WL-002"):
                # Jednorazowy dodatkowy retry po 2 sekundach
                await asyncio.sleep(2.0)
                try:
                    resp2 = await http_request_with_retry(client, "GET", url)
                    if resp2.status_code == 200:
                        resp = resp2
                    elif resp2.status_code == 400:
                        return {
                            "nip": normalized_nip,
                            "found": False,
                            "status_vat": f"Serwis MF chwilowo niedostępny ({err_code}: aktualizacja bazy). Spróbuj ponownie za kilka minut.",
                            "platnik_vat": False,
                            "blad_polaczenia": True,
                            "komunikat_bledu": f"MF API {err_code}: {err_msg}",
                            "zrodlo": "MF_BIALA_LISTA_TRANSIENT",
                        }
                except (httpx.HTTPError, ValueError):
                    pass
            else:
                return {
                    "nip": normalized_nip,
                    "found": False,
                    "status_vat": f"Błąd serwisu MF (HTTP {resp.status_code})",
                    "platnik_vat": False,
                    "blad_polaczenia": True,
                    "komunikat_bledu": f"Odpowiedź API MF: HTTP {resp.status_code}",
                    "zrodlo": "MF_BIALA_LISTA_ERROR",
                }
        if resp.status_code != 200:
            return {
                "nip": normalized_nip,
                "found": False,
                "status_vat": f"Błąd serwisu MF (HTTP {resp.status_code})",
                "platnik_vat": False,
                "blad_polaczenia": True,
                "komunikat_bledu": f"Odpowiedź API MF: HTTP {resp.status_code}",
                "zrodlo": "MF_BIALA_LISTA_ERROR",
            }

        data = resp.json()
        result = data.get("result") or {}
        subject = result.get("subject")
        request_id = result.get("requestId")

        if not subject:
            return {
                "nip": normalized_nip,
                "found": False,
                "request_id": request_id,
                "status_vat": "Niezarejestrowany (brak w wykazie MF)",
                "platnik_vat": False,
                "blad_polaczenia": False,
                "zrodlo": "MF_BIALA_LISTA",
            }

        status_vat_raw = (subject.get("statusVat") or "").strip()
        platnik_vat = status_vat_raw.lower() == "czynny"
        adres = (subject.get("workingAddress") or subject.get("residenceAddress") or "").strip()
        krs_val = (subject.get("krs") or "").strip() or None
        regon_val = (subject.get("regon") or "").strip() or None
        nazwa = (subject.get("name") or "").strip()
        accounts = [clean_nrb(acc) for acc in (subject.get("accountNumbers") or []) if acc]

        return {
            "nip": normalized_nip,
            "found": True,
            "request_id": request_id,
            "nazwa": nazwa,
            "regon": regon_val,
            "krs": krs_val,
            "adres": adres,
            "status_vat": status_vat_raw or "Nieznany",
            "platnik_vat": platnik_vat,
            "rachunki_bankowe": accounts,
            "raw": data,
            "blad_polaczenia": False,
            "zrodlo": "MF_BIALA_LISTA",
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "nip": normalized_nip,
            "found": False,
            "status_vat": "Brak połączenia z API MF (błąd sieci / offline)",
            "platnik_vat": False,
            "blad_polaczenia": True,
            "komunikat_bledu": f"Błąd połączenia z API MF: {exc.__class__.__name__}",
            "zrodlo": "MF_BIALA_LISTA_ERROR",
        }


async def fetch_mf_white_list_by_regon(
    client: httpx.AsyncClient,
    regon: str,
    date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """Odpytuje Białą Listę Podatników VAT MF po numerze REGON (9 lub 14 cyfr)."""
    normalized_regon = clean_regon(regon)
    if len(normalized_regon) not in (9, 14):
        return {
            "regon": normalized_regon,
            "found": False,
            "status_vat": "Nieprawidłowy REGON",
            "platnik_vat": False,
            "blad_polaczenia": False,
            "zrodlo": "MF_BIALA_LISTA",
        }

    query_date = date_str or datetime.now().strftime("%Y-%m-%d")
    url = f"{MF_SEARCH_REGON_URL}/{normalized_regon}?date={query_date}"

    try:
        resp = await http_request_with_retry(client, "GET", url)
        if resp.status_code == 404:
            return {
                "regon": normalized_regon,
                "found": False,
                "status_vat": "Niezarejestrowany (brak w wykazie MF)",
                "platnik_vat": False,
                "blad_polaczenia": False,
                "zrodlo": "MF_BIALA_LISTA",
            }
        if resp.status_code == 400:
            try:
                err_body = resp.json()
            except Exception:
                err_body = {}
            err_code = err_body.get("code", "")
            err_msg = err_body.get("message", "")
            if err_code in ("WL-196", "WL-002"):
                await asyncio.sleep(2.0)
                try:
                    resp2 = await http_request_with_retry(client, "GET", url)
                    if resp2.status_code == 200:
                        resp = resp2
                    elif resp2.status_code == 400:
                        return {
                            "regon": normalized_regon,
                            "found": False,
                            "status_vat": f"Serwis MF chwilowo niedostępny ({err_code}: aktualizacja bazy). Spróbuj ponownie za kilka minut.",
                            "platnik_vat": False,
                            "blad_polaczenia": True,
                            "komunikat_bledu": f"MF API {err_code}: {err_msg}",
                            "zrodlo": "MF_BIALA_LISTA_TRANSIENT",
                        }
                except (httpx.HTTPError, ValueError):
                    pass
            else:
                return {
                    "regon": normalized_regon,
                    "found": False,
                    "status_vat": f"Błąd serwisu MF (HTTP {resp.status_code})",
                    "platnik_vat": False,
                    "blad_polaczenia": True,
                    "komunikat_bledu": f"Odpowiedź API MF: HTTP {resp.status_code}",
                    "zrodlo": "MF_BIALA_LISTA_ERROR",
                }
        if resp.status_code != 200:
            return {
                "regon": normalized_regon,
                "found": False,
                "status_vat": f"Błąd serwisu MF (HTTP {resp.status_code})",
                "platnik_vat": False,
                "blad_polaczenia": True,
                "komunikat_bledu": f"Odpowiedź API MF: HTTP {resp.status_code}",
                "zrodlo": "MF_BIALA_LISTA_ERROR",
            }

        data = resp.json()
        result = data.get("result") or {}
        subject = result.get("subject")
        request_id = result.get("requestId")

        if not subject:
            return {
                "regon": normalized_regon,
                "found": False,
                "request_id": request_id,
                "status_vat": "Niezarejestrowany (brak w wykazie MF)",
                "platnik_vat": False,
                "blad_polaczenia": False,
                "zrodlo": "MF_BIALA_LISTA",
            }

        status_vat_raw = (subject.get("statusVat") or "").strip()
        platnik_vat = status_vat_raw.lower() == "czynny"
        adres = (subject.get("workingAddress") or subject.get("residenceAddress") or "").strip()
        nip_val = (subject.get("nip") or "").strip() or None
        krs_val = (subject.get("krs") or "").strip() or None
        regon_val = (subject.get("regon") or "").strip() or normalized_regon
        nazwa = (subject.get("name") or "").strip()
        accounts = [clean_nrb(acc) for acc in (subject.get("accountNumbers") or []) if acc]

        return {
            "nip": nip_val,
            "regon": regon_val,
            "found": True,
            "request_id": request_id,
            "nazwa": nazwa,
            "krs": krs_val,
            "adres": adres,
            "status_vat": status_vat_raw or "Nieznany",
            "platnik_vat": platnik_vat,
            "rachunki_bankowe": accounts,
            "raw": data,
            "blad_polaczenia": False,
            "zrodlo": "MF_BIALA_LISTA",
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "regon": normalized_regon,
            "found": False,
            "status_vat": "Brak połączenia z API MF (błąd sieci / offline)",
            "platnik_vat": False,
            "blad_polaczenia": True,
            "komunikat_bledu": f"Błąd połączenia z API MF: {exc.__class__.__name__}",
            "zrodlo": "MF_BIALA_LISTA_ERROR",
        }


async def check_mf_bank_account(
    client: httpx.AsyncClient,
    nip: str,
    account: str,
    date_str: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Weryfikuje powiązanie pary NIP + rachunek bankowy (w tym rachunki wirtualne / subkonta masowe)
    w endpoincie /api/check/nip/{nip}/bank-account/{bankAccount}.
    """
    normalized_nip = clean_nip(nip)
    normalized_acc = clean_nrb(account)
    if len(normalized_nip) != 10 or len(normalized_acc) != 26 or not normalized_acc.isdigit():
        return {"assigned": False, "request_id": None, "blad_polaczenia": False}

    query_date = date_str or datetime.now().strftime("%Y-%m-%d")
    url = f"{MF_CHECK_URL}/{normalized_nip}/bank-account/{normalized_acc}?date={query_date}"

    try:
        resp = await http_request_with_retry(client, "GET", url)
        if resp.status_code == 200:
            data = resp.json()
            result = data.get("result") or {}
            return {
                "assigned": result.get("accountAssigned") == "TAK",
                "request_id": result.get("requestId"),
                "blad_polaczenia": False,
                "raw": data,
            }
        if resp.status_code in (400, 404):
            return {"assigned": False, "request_id": None, "blad_polaczenia": False}
        return {
            "assigned": False,
            "request_id": None,
            "blad_polaczenia": True,
            "komunikat_bledu": f"HTTP {resp.status_code}",
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "assigned": False,
            "request_id": None,
            "blad_polaczenia": True,
            "komunikat_bledu": exc.__class__.__name__,
        }
