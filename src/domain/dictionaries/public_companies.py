"""Słownik spółek publicznych (GPW / NewConnect) z automatyczną aktualizacją z Internetu.

Zgodnie z:
- Ustawą o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu (art. 58 - zwolnienie z CRBR dla spółek publicznych),
- Art. 42 ust. 1 pkt 1 ustawy AML - prawo do stosowania uproszczonych środków należytej staranności (SDD).
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "public_companies_cache.json"
SEED_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "public_companies_seed.json"
CACHE_TTL_SECONDS = 7 * 24 * 3600  # Odświeżanie z Internetu co 7 dni


@dataclass(frozen=True)
class PublicCompanyEntry:
    ticker: str
    name: str
    market: str  # GPW lub NEWCONNECT
    krs: Optional[str] = None
    nip: Optional[str] = None


# Kluczowe spółki z przypisanym KRS / NIP na sztywno dla pewności
KNOWN_PUBLIC_COMPANIES_REGISTRY: Dict[str, Dict[str, str]] = {
    # KRS -> Informacje
    "0000009831": {"ticker": "PZU", "name": "POWSZECHNY ZAKŁAD UBEZPIECZEŃ SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000028379": {"ticker": "PKN", "name": "ORLEN SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000023302": {"ticker": "KGH", "name": "KGHM POLSKA MIEDŹ SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000002427": {"ticker": "PKO", "name": "POWSZECHNA KASA OSZCZĘDNOŚCI BANK POLSKI SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000014825": {"ticker": "PEO", "name": "BANK POLSKA KASA OPIEKI SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000006865": {"ticker": "CDR", "name": "CD PROJEKT SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000669488": {"ticker": "DNP", "name": "DINO POLSKA SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000015355": {"ticker": "LPP", "name": "LPP SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000027118": {"ticker": "SPL", "name": "SANTANDER BANK POLSKA SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000011571": {"ticker": "ALE", "name": "ALLEGRO.EU", "market": "GPW"},
    "0000030894": {"ticker": "PGN", "name": "POLSKIE GÓRNICTWO NAFTOWE I GAZOWNICTWO SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000326442": {"ticker": "PGE", "name": "PGE POLSKA GRUPA ENERGETYCZNA SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000085841": {"ticker": "TPE", "name": "TAURON POLSKA ENERGIA SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000007838": {"ticker": "ENG", "name": "ENEA SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000010996": {"ticker": "KRU", "name": "KRUK SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000057132": {"ticker": "CPS", "name": "CYFROWY POLSAT SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000037147": {"ticker": "JSW", "name": "JASTRZĘBSKA SPÓŁKA WĘGLOWA SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000011409": {"ticker": "BDX", "name": "BUDIMEX SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000024477": {"ticker": "ATT", "name": "GRUPA AZOTY SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000041149": {"ticker": "ACP", "name": "ASSECO POLAND SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000049435": {"ticker": "MBK", "name": "MBANK SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000018440": {"ticker": "ING", "name": "ING BANK ŚLĄSKI SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000044191": {"ticker": "CCC", "name": "CCC SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000082983": {"ticker": "MIL", "name": "BANK MILLENNIUM SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000033061": {"ticker": "KTY", "name": "GRUPA KĘTY SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000058860": {"ticker": "LVC", "name": "LIVECHAT SOFTWARE SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000088907": {"ticker": "XTB", "name": "XTB SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000017105": {"ticker": "ALR", "name": "ALIOR BANK SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000056898": {"ticker": "OPL", "name": "ORANGE POLSKA SPÓŁKA AKCYJNA", "market": "GPW"},
    "0000082277": {"ticker": "GPW", "name": "GIEŁDA PAPIERÓW WARTOŚCIOWYCH W WARSZAWIE S.A.", "market": "GPW"},
}

_MEMORY_CACHE: Optional[List[PublicCompanyEntry]] = None
_LAST_SYNC_TIME: float = 0.0


def _normalize_name(name: str) -> str:
    """Upraszcza nazwę spółki do celów porównawczych."""
    n = name.upper()
    n = re.sub(r'\b(SPÓŁKA AKCYJNA|SP\.? ?A\.?|S\.A\.|SA)\b', '', n)
    n = re.sub(r'[^A-Z0-9ĄĆĘŁŃÓŚŹŻ]', ' ', n)
    return ' '.join(n.split())


def load_cached_companies() -> List[PublicCompanyEntry]:
    """Wczytuje listę spółek z pamięci RAM, pliku cache lub pliku seed."""
    global _MEMORY_CACHE, _LAST_SYNC_TIME
    if _MEMORY_CACHE is not None:
        return _MEMORY_CACHE

    target_file = CACHE_FILE if CACHE_FILE.exists() else SEED_FILE
    companies: List[PublicCompanyEntry] = []

    if target_file.exists():
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                for item in raw_data:
                    companies.append(
                        PublicCompanyEntry(
                            ticker=item.get("ticker", ""),
                            name=item.get("name", ""),
                            market=item.get("market", "GPW"),
                            krs=item.get("krs"),
                            nip=item.get("nip"),
                        )
                    )
            _LAST_SYNC_TIME = target_file.stat().st_mtime
        except Exception as e:
            logger.error(f"Błąd odczytu słownika spółek publicznych z {target_file}: {e}")

    _MEMORY_CACHE = companies
    return _MEMORY_CACHE


def get_public_companies_stats() -> dict:
    """Zwraca metryki słownika spółek publicznych na potrzeby widoku Rejestry."""
    companies = load_cached_companies()
    target_file = CACHE_FILE if CACHE_FILE.exists() else SEED_FILE
    mtime = target_file.stat().st_mtime if target_file.exists() else 0.0
    from datetime import datetime
    last_sync_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S") if mtime > 0 else "Brak"
    
    gpw_count = sum(1 for c in companies if c.market == "GPW")
    nc_count = sum(1 for c in companies if c.market == "NEWCONNECT")
    
    return {
        "total": len(companies),
        "gpw_count": gpw_count,
        "nc_count": nc_count,
        "last_sync": last_sync_str,
        "cache_file": str(target_file.name),
        "is_live_cache": CACHE_FILE.exists(),
    }



async def sync_public_companies_from_web(force: bool = False) -> int:
    """Pobiera i aktualizuje listę spółek publicznych (GPW / NewConnect) z Internetu.
    
    Zapisuje wynik w `data/public_companies_cache.json`.
    Zwraca liczbę zaktualizowanych podmiotów.
    """
    global _MEMORY_CACHE, _LAST_SYNC_TIME

    if not force and CACHE_FILE.exists():
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            logger.info(f"Słownik spółek publicznych jest aktualny (wiek: {int(age/3600)}h). Pomijam synchronizację.")
            return len(load_cached_companies())

    url_gpw = "https://www.biznesradar.pl/gielda/akcje_gpw"
    url_nc = "https://www.biznesradar.pl/gielda/newconnect"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    companies: List[dict] = []
    seen = set()

    try:
        async with httpx.AsyncClient(headers=headers, timeout=12.0) as client:
            for market, url in [("GPW", url_gpw), ("NEWCONNECT", url_nc)]:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        matches = re.findall(r'<a href=\"/notowania/([A-Z0-9\-]+)\"[^>]*title=\"([^\"]+)\"', resp.text)
                        for ticker, name in matches:
                            t = ticker.strip().upper()
                            n = name.strip()
                            if t and (t, market) not in seen:
                                seen.add((t, market))
                                companies.append({
                                    "ticker": t,
                                    "name": n,
                                    "market": market,
                                })
                except Exception as ex:
                    logger.warning(f"Błąd pobierania listy {market} z {url}: {ex}")

        if companies:
            # Uzupełnij znane KRS-y
            krs_by_name = {_normalize_name(v["name"]): k for k, v in KNOWN_PUBLIC_COMPANIES_REGISTRY.items()}
            krs_by_ticker = {v["ticker"]: k for k, v in KNOWN_PUBLIC_COMPANIES_REGISTRY.items()}

            for item in companies:
                ticker = item["ticker"]
                norm_name = _normalize_name(item["name"])
                if ticker in krs_by_ticker:
                    item["krs"] = krs_by_ticker[ticker]
                elif norm_name in krs_by_name:
                    item["krs"] = krs_by_name[norm_name]

            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(companies, f, ensure_ascii=False, indent=2)

            _MEMORY_CACHE = [
                PublicCompanyEntry(
                    ticker=c["ticker"],
                    name=c["name"],
                    market=c["market"],
                    krs=c.get("krs"),
                    nip=c.get("nip"),
                )
                for c in companies
            ]
            _LAST_SYNC_TIME = time.time()
            logger.info(f"Pomyślnie zsynchronizowano {len(companies)} spółek publicznych z Internetu.")
            return len(companies)
        else:
            logger.warning("Nie udało się pobrać żadnych danych ze źródeł online. Pozostaję przy dotychczasowym cache.")
            return len(load_cached_companies())

    except Exception as e:
        logger.error(f"Nieoczekiwany błąd podczas synchronizacji spółek publicznych: {e}")
        return len(load_cached_companies())


def is_public_company(
    krs: Optional[str] = None,
    name: Optional[str] = None,
    nip: Optional[str] = None,
) -> Optional[PublicCompanyEntry]:
    """Sprawdza czy dany podmiot jest spółką publiczną (GPW lub NewConnect).
    
    Weryfikacja odbywa się według:
    1. Numeru KRS (jeśli znany)
    2. Dopasowania nazwy do katalogu spółek giełdowych
    """
    clean_krs = (krs or "").strip().zfill(10) if krs and krs.strip() else None

    # 1. Szybkie sprawdzenie po stałym rejestrze KRS
    if clean_krs and clean_krs in KNOWN_PUBLIC_COMPANIES_REGISTRY:
        info = KNOWN_PUBLIC_COMPANIES_REGISTRY[clean_krs]
        return PublicCompanyEntry(
            ticker=info["ticker"],
            name=info["name"],
            market=info["market"],
            krs=clean_krs,
        )

    companies = load_cached_companies()

    # 2. Sprawdzenie po KRS w załadowanym słowniku
    if clean_krs:
        for c in companies:
            if c.krs and c.krs.zfill(10) == clean_krs:
                return c

    # 3. Sprawdzenie po nazwie
    if name:
        target_norm = _normalize_name(name)
        if len(target_norm) >= 3:
            for c in companies:
                c_norm = _normalize_name(c.name)
                if not c_norm or len(c_norm) < 3:
                    continue
                if target_norm == c_norm or (len(c_norm) >= 5 and (target_norm in c_norm or c_norm in target_norm)):
                    return c

    return None
