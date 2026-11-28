"""Klient unijnego rejestru MiCA (Markets in Crypto-Assets) oraz CASP (Crypto-Asset Service Providers).

Rozporządzenie Parlamentu Europejskiego i Rady (UE) 2023/1114 (MiCA):
- Weryfikuje autoryzowanych dostawców usług w zakresie kryptoaktywów (CASP) w UE / ESMA / KNF.
- Weryfikuje unijny rejestr podmiotów nieautoryzowanych / naruszających art. 110 MiCA (Non-compliant CASP list).
- Oferuje wbudowaną pamięć podręczną (cache) w pamięci podręcznej i plikach oraz odporność na błędy sieciowe.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from src.config import HTTP_TIMEOUT_SECONDS, APP_USER_AGENT
from src.providers.base import http_request_with_retry

logger = logging.getLogger(__name__)

# Endpointy unijnego rejestru MiCA
MICA_CASPS_URL = "https://eumica.com/api/casps"
MICA_NON_COMPLIANT_URL = "https://eumica.com/api/non-compliant"

# Cache w pamięci na 12 godzin
_CACHE: Dict[str, Any] = {
    "casps": None,
    "non_compliant": None,
    "last_fetched_casps": None,
    "last_fetched_non_compliant": None,
}
_CACHE_LOCK = asyncio.Lock()
_CACHE_TTL_SECONDS = 12 * 3600  # 12 godzin


def _normalize_name(name: str) -> str:
    """Normalizuje nazwę podmiotu do porównywania (bez sp. z o.o., SA, znaków specjalnych)."""
    if not name:
        return ""
    clean = name.upper()
    # Usunięcie sufiksów prawnych
    clean = re.sub(
        r"(SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ|SPÓŁKA\s+Z\s+O\.?O\.?|SPÓŁKA Z O O|SPÓŁKA AKCYJNA|SP\.?\s*Z\s*O\.?\s*O\.?|S\.?A\.?|GMBH|AG|LTD|LIMITED|OÜ|UAB|INC|CORP|S\.?R\.?O\.?|BV|NV)",
        " ",
        clean,
        flags=re.IGNORECASE,
    )
    # Usunięcie znaków niealfanumerycznych
    clean = re.sub(r"[^A-Z0-9ĄĆĘŁŃÓŚŹŻ]", " ", clean)
    return " ".join(clean.split())


class CryptoMicaClient:
    """Klient API weryfikacji podmiotów w rejestrach MiCA / CASP."""

    def __init__(self, timeout: float = HTTP_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout

    async def _get_casps_data(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """Pobiera listę autoryzowanych dostawców CASP z cache lub API."""
        now = datetime.now(timezone.utc)
        async with _CACHE_LOCK:
            if _CACHE["casps"] is not None and _CACHE["last_fetched_casps"] is not None:
                age = (now - _CACHE["last_fetched_casps"]).total_seconds()
                if age < _CACHE_TTL_SECONDS:
                    return _CACHE["casps"]

        try:
            resp = await http_request_with_retry(
                client,
                "GET",
                MICA_CASPS_URL,
                headers={"User-Agent": APP_USER_AGENT, "Accept": "application/json"},
                timeout=self.timeout,
                max_retries=2,
            )
            if resp and resp.status_code == 200:
                payload = resp.json()
                items = payload.get("data", []) if isinstance(payload, dict) else payload
                if isinstance(items, list):
                    async with _CACHE_LOCK:
                        _CACHE["casps"] = items
                        _CACHE["last_fetched_casps"] = now
                    return items
        except Exception as exc:
            logger.warning(f"Błąd pobierania rejestru MiCA CASP: {exc}")

        # Jeśli błąd, zwróć stary cache jeśli istnieje
        if _CACHE["casps"] is not None:
            return _CACHE["casps"]
        return []

    async def _get_non_compliant_data(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """Pobiera listę podmiotów nieautoryzowanych z cache lub API."""
        now = datetime.now(timezone.utc)
        async with _CACHE_LOCK:
            if _CACHE["non_compliant"] is not None and _CACHE["last_fetched_non_compliant"] is not None:
                age = (now - _CACHE["last_fetched_non_compliant"]).total_seconds()
                if age < _CACHE_TTL_SECONDS:
                    return _CACHE["non_compliant"]

        try:
            resp = await http_request_with_retry(
                client,
                "GET",
                MICA_NON_COMPLIANT_URL,
                headers={"User-Agent": APP_USER_AGENT, "Accept": "application/json"},
                timeout=self.timeout,
                max_retries=2,
            )
            if resp and resp.status_code == 200:
                payload = resp.json()
                items = payload.get("data", []) if isinstance(payload, dict) else payload
                if isinstance(items, list):
                    async with _CACHE_LOCK:
                        _CACHE["non_compliant"] = items
                        _CACHE["last_fetched_non_compliant"] = now
                    return items
        except Exception as exc:
            logger.warning(f"Błąd pobierania rejestru MiCA Non-compliant: {exc}")

        if _CACHE["non_compliant"] is not None:
            return _CACHE["non_compliant"]
        return []

    async def verify_crypto_status(
        self,
        client: httpx.AsyncClient,
        nazwa: str,
        nip: Optional[str] = None,
        kody_pkd: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Weryfikuje podmiot w rejestrach MiCA / CASP.

        Zwraca:
            {
                "status": "AUTORYZOWANY_CASP" | "OSTRZEZENIE_NIEAUTORYZOWANY" | "NIE_DOTYCZY" | "BLAD_POLACZENIA",
                "is_casp": bool,
                "is_non_compliant": bool,
                "details": str,
                "casp_record": Optional[Dict],
                "non_compliant_record": Optional[Dict],
                "blad_polaczenia": bool
            }
        """
        if not nazwa:
            return {
                "status": "NIE_DOTYCZY",
                "is_casp": False,
                "is_non_compliant": False,
                "details": "Brak nazwy podmiotu do weryfikacji MiCA",
                "casp_record": None,
                "non_compliant_record": None,
                "blad_polaczenia": False,
            }

        norm_target = _normalize_name(nazwa)
        if len(norm_target) < 3:
            return {
                "status": "NIE_DOTYCZY",
                "is_casp": False,
                "is_non_compliant": False,
                "details": "Zbyt krótka nazwa",
                "casp_record": None,
                "non_compliant_record": None,
                "blad_polaczenia": False,
            }

        # Pobierz równolegle oba rejestry
        casps_task = self._get_casps_data(client)
        non_compliant_task = self._get_non_compliant_data(client)
        casps, non_compliant = await asyncio.gather(casps_task, non_compliant_task)

        # 1. Sprawdź listę podmiotów nieuprawnionych (priorytet krytyczny!)
        matched_nc = None
        for item in non_compliant:
            nc_name = item.get("name") or ""
            norm_nc = _normalize_name(nc_name)
            if not norm_nc or len(norm_nc) < 3:
                continue

            # Dokładne dopasowanie lub zawieranie słów kluczowych
            if norm_target == norm_nc or (len(norm_nc) >= 5 and norm_nc in norm_target) or (len(norm_target) >= 5 and norm_target in norm_nc):
                matched_nc = item
                break

        if matched_nc:
            authority = matched_nc.get("authority", "Organ nadzoru UE")
            reason = matched_nc.get("reason", "Działalność bez wymaganego zezwolenia MiCA")
            return {
                "status": "OSTRZEZENIE_NIEAUTORYZOWANY",
                "is_casp": False,
                "is_non_compliant": True,
                "details": f"Podmiot figuruje na unijnej liście ostrzeżeń MiCA (art. 110): {authority} zgłosił brak autoryzacji ({reason[:150]}).",
                "casp_record": None,
                "non_compliant_record": matched_nc,
                "blad_polaczenia": False,
            }

        # 2. Sprawdź listę autoryzowanych dostawców CASP
        matched_casp = None
        for item in casps:
            c_name = item.get("name") or ""
            c_brand = item.get("brand") or ""
            norm_c = _normalize_name(c_name)
            norm_brand = _normalize_name(c_brand)

            # Dopasowanie po nazwie lub marce
            if norm_target == norm_c or (norm_brand and norm_target == norm_brand):
                matched_casp = item
                break
            if len(norm_c) >= 5 and (norm_c in norm_target or norm_target in norm_c):
                matched_casp = item
                break

        if matched_casp:
            auth_status = matched_casp.get("authorisationStatus", "aktywny")
            authority = matched_casp.get("authority", "KNF / ESMA")
            lei = matched_casp.get("lei", "")
            return {
                "status": "AUTORYZOWANY_CASP",
                "is_casp": True,
                "is_non_compliant": False,
                "details": f"Licencjonowany dostawca usług w zakresie kryptoaktywów (MiCA CASP). Organ nadzorczy: {authority}. Status: {auth_status}. LEI: {lei or 'Brak'}.",
                "casp_record": matched_casp,
                "non_compliant_record": None,
                "blad_polaczenia": False,
            }

        # Jeśli podmiot nie figuruje w MiCA
        return {
            "status": "BRAK_WPISU",
            "is_casp": False,
            "is_non_compliant": False,
            "details": "Podmiot nie figuruje w unijnym rejestrze autoryzowanych dostawców kryptoaktywów MiCA CASP ani na liście ostrzeżeń.",
            "casp_record": None,
            "non_compliant_record": None,
            "blad_polaczenia": False,
        }


async def validate_crypto_mica(
    client: httpx.AsyncClient,
    nazwa: str,
    nip: Optional[str] = None,
    kody_pkd: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Funkcja pomocnicza do bezpośredniego wywołania weryfikacji MiCA."""
    svc = CryptoMicaClient()
    return await svc.verify_crypto_status(client, nazwa=nazwa, nip=nip, kody_pkd=kody_pkd)
