"""Asynchroniczny menedżer synchronizacji słowników i baz referencyjnych.

Zarządza:
1. Listami sankcyjnymi MSWiA (Polska) i EU (Komisja Europejska),
2. Słownikiem emitentów giełdowych GPW / NewConnect,
3. Monitorowaniem statusu przedawnienia (stale/outdated) i rejestracją błędów.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
import httpx

from src.core.database import Database
from src.domain.dictionaries.public_companies import (
    CACHE_TTL_SECONDS,
    get_public_companies_stats,
    sync_public_companies_from_web,
)
from src.providers.sanctions.sync_service import (
    seed_default_sanctions,
    sync_all_sanctions,
    sync_eu_sanctions,
    sync_knf_warnings,
    sync_mswia_sanctions,
)

logger = logging.getLogger(__name__)

# Reguły przedawnienia słowników
SANCTIONS_TTL_HOURS = 24  # Listy sankcyjne powinny być odświeżane co 24h
PUBLIC_COMPANIES_TTL_DAYS = 7  # Spółki publiczne co 7 dni


def _parse_iso(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        clean = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class DictionarySyncManager:
    """Centralny zarządca cyklu życia i synchronizacji słowników referencyjnych."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._background_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    def get_dictionaries_status(self) -> List[Dict[str, Any]]:
        """Zwraca kompleksowy stan wszystkich słowników: datę ostatniej synchronizacji,

        status sukces/błąd, liczbę rekordów oraz czy dane są przedawnione.
        """
        now = datetime.now(timezone.utc)
        last_syncs = {s["source"]: s for s in self.db.get_last_sanction_syncs()}
        counts = self.db.count_sanctions_by_source()
        gpw_stats = get_public_companies_stats()

        # 1. Polska Lista Sankcyjna MSWiA
        mswia_log = last_syncs.get("MSWIA")
        mswia_dt = _parse_iso(mswia_log["synced_at"]) if mswia_log else None
        mswia_age_h = (now - mswia_dt).total_seconds() / 3600.0 if mswia_dt else None
        mswia_status = mswia_log["status"] if mswia_log else "NEVER_SYNCED"
        mswia_has_error = mswia_status == "ERROR"
        mswia_stale = mswia_age_h is None or mswia_age_h > SANCTIONS_TTL_HOURS or mswia_has_error

        # 2. Unijna Lista Sankcyjna EU
        eu_log = last_syncs.get("EU")
        eu_dt = _parse_iso(eu_log["synced_at"]) if eu_log else None
        eu_age_h = (now - eu_dt).total_seconds() / 3600.0 if eu_dt else None
        eu_status = eu_log["status"] if eu_log else "NEVER_SYNCED"
        eu_has_error = eu_status == "ERROR"
        eu_stale = eu_age_h is None or eu_age_h > SANCTIONS_TTL_HOURS or eu_has_error

        # 3. Lista Ostrzeżeń Publicznych KNF
        knf_log = last_syncs.get("KNF")
        knf_dt = _parse_iso(knf_log["synced_at"]) if knf_log else None
        knf_age_h = (now - knf_dt).total_seconds() / 3600.0 if knf_dt else None
        knf_status = knf_log["status"] if knf_log else "NEVER_SYNCED"
        knf_has_error = knf_status == "ERROR"
        knf_stale = knf_age_h is None or knf_age_h > SANCTIONS_TTL_HOURS or knf_has_error

        # 4. Spółki publiczne GPW / NewConnect
        gpw_sync_dt = _parse_iso(gpw_stats.get("last_sync_iso"))
        if not gpw_sync_dt and gpw_stats.get("last_sync") and gpw_stats.get("last_sync") != "Brak":
            try:
                gpw_sync_dt = datetime.strptime(gpw_stats["last_sync"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                pass
        gpw_age_days = (now - gpw_sync_dt).total_seconds() / 86400.0 if gpw_sync_dt else None
        gpw_stale = gpw_age_days is None or gpw_age_days > PUBLIC_COMPANIES_TTL_DAYS

        items = [
            {
                "id": "MSWIA",
                "name": "Polska lista sankcyjna MSWiA",
                "category": "SANKCJE",
                "source_url": "gov.pl (MSWiA)",
                "ttl_desc": "Codziennie (co 24h)",
                "is_stale": mswia_stale,
                "status": mswia_status,
                "has_error": mswia_has_error,
                "error_message": mswia_log.get("message") if mswia_has_error else None,
                "count": counts.get("MSWIA", 0),
                "last_synced_at": mswia_log["synced_at"] if mswia_log else None,
            },
            {
                "id": "EU",
                "name": "Unijna lista sankcyjna UE (FSF)",
                "category": "SANKCJE",
                "source_url": "ec.europa.eu (Financial Sanctions Database)",
                "ttl_desc": "Codziennie (co 24h)",
                "is_stale": eu_stale,
                "status": eu_status,
                "has_error": eu_has_error,
                "error_message": eu_log.get("message") if eu_has_error else None,
                "count": counts.get("EU", 0),
                "last_synced_at": eu_log["synced_at"] if eu_log else None,
            },
            {
                "id": "KNF",
                "name": "Lista Ostrzeżeń Publicznych KNF",
                "category": "OSTRZEŻENIA / FRAUD",
                "source_url": "knf.gov.pl (Komisja Nadzoru Finansowego)",
                "ttl_desc": "Codziennie (co 24h)",
                "is_stale": knf_stale,
                "status": knf_status,
                "has_error": knf_has_error,
                "error_message": knf_log.get("message") if knf_has_error else None,
                "count": counts.get("KNF", 0),
                "last_synced_at": knf_log["synced_at"] if knf_log else None,
            },
            {
                "id": "PUBLIC_COMPANIES",
                "name": "Spółki publiczne (GPW & NewConnect)",
                "category": "REFERENCYJNY",
                "source_url": "Biuletyny GPW / NewConnect (Komisja Europejska)",
                "ttl_desc": "Co 7 dni",
                "is_stale": gpw_stale,
                "status": "SUCCESS" if gpw_stats.get("total", 0) > 0 else "ERROR",
                "has_error": gpw_stats.get("total", 0) == 0,
                "error_message": "Brak załadowanych emitentów" if gpw_stats.get("total", 0) == 0 else None,
                "count": gpw_stats.get("total", 0),
                "last_synced_at": gpw_stats.get("last_sync"),
            },
            {
                "id": "VIRTUAL_OFFICES",
                "name": "Wirtualne Biura i Adresy Masowe",
                "category": "KATALOG_AML",
                "source_url": "Krajowa Ocena Ryzyka GIIF / Rejestry KRS",
                "ttl_desc": "Wbudowany z aktualizacją wersji",
                "is_stale": False,
                "status": "SUCCESS",
                "has_error": False,
                "error_message": None,
                "count": 60,
                "last_synced_at": "Wbudowany (aktualny)",
            },
            {
                "id": "PKD_AML",
                "name": "Katalog Branż Ryzyka AML & MPP",
                "category": "KATALOG_AML",
                "source_url": "Załącznik nr 15 ustawy o VAT / KOR GIIF",
                "ttl_desc": "Wbudowany z aktualizacją wersji",
                "is_stale": False,
                "status": "SUCCESS",
                "has_error": False,
                "error_message": None,
                "count": 48,
                "last_synced_at": "Wbudowany (aktualny)",
            },
        ]
        return items

    def has_any_errors_or_stale(self) -> Dict[str, Any]:
        """Sprawdza czy jakikolwiek słownik wymaga uwagi (błąd synchronizacji lub przedawnienie)."""
        statuses = self.get_dictionaries_status()
        errors = [s for s in statuses if s.get("has_error")]
        stale = [s for s in statuses if s.get("is_stale") and not s.get("has_error")]
        return {
            "has_issues": bool(errors or stale),
            "error_count": len(errors),
            "stale_count": len(stale),
            "errors": errors,
            "stale": stale,
        }

    async def sync_stale_dictionaries(self, force: bool = False) -> List[Dict[str, Any]]:
        """Sprawdza reguły przedawnienia i aktualizuje tylko te słowniki, które tego wymagają."""
        results = []
        statuses = {s["id"]: s for s in self.get_dictionaries_status()}
        now = datetime.now(timezone.utc)

        # 1. Spółki publiczne GPW / NewConnect
        gpw_status = statuses.get("PUBLIC_COMPANIES", {})
        if force or gpw_status.get("is_stale"):
            logger.info("DictionarySync: Aktualizacja słownika spółek publicznych GPW...")
            try:
                cnt = await sync_public_companies_from_web(force=True)
                results.append({"source": "PUBLIC_COMPANIES", "status": "SUCCESS", "count": cnt, "message": "Zaktualizowano z sieci"})
            except Exception as e:
                logger.error(f"DictionarySync: Błąd aktualizacji spółek publicznych: {e}")
                results.append({"source": "PUBLIC_COMPANIES", "status": "ERROR", "count": 0, "message": str(e)})

        # 2. Listy sankcyjne MSWiA i UE
        async with httpx.AsyncClient() as client:
            # MSWiA
            mswia_status = statuses.get("MSWIA", {})
            if force or mswia_status.get("is_stale"):
                logger.info("DictionarySync: Aktualizacja listy sankcyjnej MSWiA...")
                try:
                    res_mswia = await sync_mswia_sanctions(client, self.db)
                    results.append(res_mswia)
                except Exception as e:
                    logger.error(f"DictionarySync: Wyjątek MSWiA: {e}")
                    results.append({"source": "MSWIA", "status": "ERROR", "count": 0, "message": str(e)})

            # EU
            eu_status = statuses.get("EU", {})
            if force or eu_status.get("is_stale"):
                logger.info("DictionarySync: Aktualizacja listy sankcyjnej UE...")
                try:
                    res_eu = await sync_eu_sanctions(client, self.db)
                    results.append(res_eu)
                except Exception as e:
                    logger.error(f"DictionarySync: Wyjątek UE: {e}")
                    results.append({"source": "EU", "status": "ERROR", "count": 0, "message": str(e)})

            # KNF
            knf_status = statuses.get("KNF", {})
            if force or knf_status.get("is_stale"):
                logger.info("DictionarySync: Aktualizacja Listy Ostrzeżeń Publicznych KNF...")
                try:
                    res_knf = await sync_knf_warnings(client, self.db)
                    results.append(res_knf)
                except Exception as e:
                    logger.error(f"DictionarySync: Wyjątek KNF: {e}")
                    results.append({"source": "KNF", "status": "ERROR", "count": 0, "message": str(e)})

        return results

    async def run_periodic_sync_loop(self, check_interval_seconds: int = 3600) -> None:
        """Pętla asynchroniczna sprawdzająca w tle co godzinę stan słowników i wykonująca

        automatyczną aktualizację, gdy minie okres ich ważności.
        """
        logger.info(f"Uruchomiono pętlę automatycznej synchronizacji słowników (interwał sprawdzania: {check_interval_seconds}s).")
        # Pierwsze sprawdzenie od razu po starcie z krótkim opóźnieniem
        await asyncio.sleep(5)
        try:
            await self.sync_stale_dictionaries(force=False)
        except Exception as exc:
            logger.error(f"Błąd wstępnej synchronizacji słowników: {exc}")

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=float(check_interval_seconds))
                break  # Otrzymano sygnał zatrzymania
            except asyncio.TimeoutError:
                # Upłynął interwał - sprawdź i zaktualizuj przedawnione słowniki
                try:
                    logger.debug("Automatyczny harmonogram: badanie aktualności słowników...")
                    await self.sync_stale_dictionaries(force=False)
                except Exception as exc:
                    logger.error(f"Błąd cyklicznej synchronizacji słowników: {exc}")

    def start_background_sync(self, check_interval_seconds: int = 3600) -> asyncio.Task:
        """Startuje zadanie w tle powiązane z pętlą zdarzeń asyncio."""
        self._stop_event.clear()
        self._background_task = asyncio.create_task(self.run_periodic_sync_loop(check_interval_seconds))
        return self._background_task

    def stop_background_sync(self) -> None:
        """Bezpiecznie zatrzymuje zadanie w tle."""
        if self._background_task:
            self._stop_event.set()
            self._background_task.cancel()
