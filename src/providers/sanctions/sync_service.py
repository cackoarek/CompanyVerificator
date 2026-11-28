"""Synchronizacja oficjalnych list sankcyjnych (MSWiA, UE) oraz baza startowa."""

import html as html_lib
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

import httpx

from src.config import KNF_WARNINGS_URL
from src.core.database import Database
from src.providers.base import http_request_with_retry
from src.providers.sanctions.matcher import normalize_name

# Oficjalne źródła list sankcyjnych i ostrzeżeń
MSWIA_SANCTIONS_URL = "https://www.gov.pl/web/mswia/lista-osob-i-podmiotow-objetych-sankcjami"
EU_SANCTIONS_XML_URL = "https://webgate.ec.europa.eu/fsd/fsf/public/files/xmlFullSanctionsList_1_1/content?token=dG9rZW4tMjAxNw"

# Referencyjne wpisy startowe (MSWiA / UE), aby system działał od pierwszego uruchomienia także offline
LOCAL_SEED_ENTRIES: List[Dict[str, Any]] = [
    {"entry_type": "ENTITY", "name": "Novatek Green Energy Sp. z o.o.", "nip": "5252877567", "krs": "0000340774", "aliases": ["Novatek"], "reason": "Lista sankcyjna MSWiA (ustawa z 13.04.2022 r.)"},
    {"entry_type": "ENTITY", "name": "PAO Gazprom", "nip": None, "krs": None, "aliases": ["Gazprom", "Gazprom Export"], "reason": "Sankcje sektorowe UE / MSWiA"},
    {"entry_type": "ENTITY", "name": "Sulnoil / Barlenco / Powiązania oligarchiczne", "nip": "5260307849", "krs": None, "aliases": [], "reason": "Lista sankcyjna MSWiA"},
    {"entry_type": "ENTITY", "name": "Podmiot z listy MSWiA", "nip": "7010486022", "krs": None, "aliases": [], "reason": "Lista sankcyjna MSWiA"},
    {"entry_type": "ENTITY", "name": "Severstal", "nip": None, "krs": None, "aliases": ["PAO Severstal"], "reason": "Sankcje UE"},
    {"entry_type": "ENTITY", "name": "Acron", "nip": None, "krs": None, "aliases": ["PJSC Acron", "Norica Holding"], "reason": "Lista sankcyjna MSWiA / UE"},
    {"entry_type": "ENTITY", "name": "PhosAgro", "nip": None, "krs": None, "aliases": ["PAO PhosAgro"], "reason": "Lista sankcyjna MSWiA / UE"},
    {"entry_type": "ENTITY", "name": "SUEK", "nip": None, "krs": None, "aliases": ["Siberian Coal Energy Company"], "reason": "Sankcje UE"},
    {"entry_type": "ENTITY", "name": "EuroChem", "nip": None, "krs": None, "aliases": ["EuroChem Group"], "reason": "Lista sankcyjna MSWiA / UE"},
    {"entry_type": "ENTITY", "name": "Kamaz", "nip": None, "krs": None, "aliases": ["PTC Kamaz"], "reason": "Sankcje UE / MSWiA"},
    {"entry_type": "ENTITY", "name": "Rostec", "nip": None, "krs": None, "aliases": [], "reason": "Sankcje UE"},
    {"entry_type": "ENTITY", "name": "Sberbank", "nip": None, "krs": None, "aliases": ["Sberbank of Russia"], "reason": "Sankcje UE"},
    {"entry_type": "ENTITY", "name": "VTB Bank", "nip": None, "krs": None, "aliases": ["VTB"], "reason": "Sankcje UE"},
    {"entry_type": "ENTITY", "name": "Alrosa", "nip": None, "krs": None, "aliases": [], "reason": "Sankcje UE"},
    {"entry_type": "ENTITY", "name": "Lukoil", "nip": None, "krs": None, "aliases": ["PAO Lukoil"], "reason": "Sankcje sektorowe"},
    {"entry_type": "ENTITY", "name": "Rosneft", "nip": None, "krs": None, "aliases": ["NK Rosneft"], "reason": "Sankcje UE"},
    {"entry_type": "PERSON", "name": "Wiaczesław Kantor", "aliases": ["Vyacheslav Kantor", "Moshe Kantor"], "reason": "Lista sankcyjna MSWiA / UE"},
    {"entry_type": "PERSON", "name": "Oleg Deripaska", "aliases": ["Deripaska"], "reason": "Lista sankcyjna MSWiA / UE"},
    {"entry_type": "PERSON", "name": "Roman Abramowicz", "aliases": ["Roman Abramovich"], "reason": "Lista sankcyjna UE"},
    {"entry_type": "PERSON", "name": "Giennadij Timczenko", "aliases": ["Gennady Timchenko"], "reason": "Lista sankcyjna UE"},
    {"entry_type": "PERSON", "name": "Arkadij Rotenberg", "aliases": ["Arkady Rotenberg", "Boris Rotenberg"], "reason": "Lista sankcyjna UE"},
    {"entry_type": "PERSON", "name": "Aliszer Usmanow", "aliases": ["Alisher Usmanov"], "reason": "Lista sankcyjna UE"},
    {"entry_type": "PERSON", "name": "Igor Sieczin", "aliases": ["Igor Sechin"], "reason": "Lista sankcyjna UE"},
    {"entry_type": "PERSON", "name": "Aleksiej Miller", "aliases": ["Alexey Miller"], "reason": "Lista sankcyjna UE"},
    {"entry_type": "PERSON", "name": "Aleksiej Mordaszow", "aliases": ["Alexey Mordashov"], "reason": "Lista sankcyjna UE"},
    {"entry_type": "PERSON", "name": "Andriej Mielniczenko", "aliases": ["Andrey Melnichenko"], "reason": "Lista sankcyjna UE"},
]


def seed_default_sanctions(db: Database) -> int:
    """Zasiewa bazę referencyjną jeśli tabela sankcji jest pusta."""
    counts = db.count_sanctions_by_source()
    if sum(counts.values()) > 0:
        return 0
    prepared = []
    for item in LOCAL_SEED_ENTRIES:
        prepared.append(
            {
                "entry_type": item["entry_type"],
                "name": item["name"],
                "normalized_name": normalize_name(item["name"]),
                "nip": item.get("nip"),
                "krs": item.get("krs"),
                "aliases": item.get("aliases", []),
                "reason": item.get("reason", ""),
                "listed_at": "",
            }
        )
    inserted = db.replace_sanctions_for_source("LOCAL_SEED", prepared)
    db.log_sanction_sync("LOCAL_SEED", "SUCCESS", inserted, "Załadowano wbudowaną bazę referencyjną MSWiA/UE")
    return inserted


def parse_eu_sanctions_xml(xml_content: str) -> List[Dict[str, Any]]:
    """Parsuje oficjalny plik XML EU Consolidated Financial Sanctions."""
    entries: List[Dict[str, Any]] = []
    root = ET.fromstring(xml_content)

    for entity in root.iter():
        tag = entity.tag.split("}")[-1]
        if tag != "sanctionEntity":
            continue

        subject_code = "enterprise"
        for child in entity:
            ctag = child.tag.split("}")[-1]
            if ctag == "subjectType":
                subject_code = (child.attrib.get("code") or "enterprise").lower()
                break

        entry_type = "PERSON" if subject_code == "person" else "ENTITY"
        names: List[str] = []
        regulation_info = ""

        for child in entity:
            ctag = child.tag.split("}")[-1]
            if ctag == "nameAlias":
                whole_name = (child.attrib.get("wholeName") or "").strip()
                if whole_name and whole_name not in names:
                    names.append(whole_name)
            elif ctag == "regulation" and not regulation_info:
                number_title = (child.attrib.get("numberTitle") or "").strip()
                if number_title:
                    regulation_info = f"EU Regulation {number_title}"

        if not names:
            continue

        primary = names[0]
        entries.append(
            {
                "entry_type": entry_type,
                "name": primary,
                "normalized_name": normalize_name(primary),
                "nip": None,
                "krs": None,
                "aliases": names[1:15],
                "reason": regulation_info or "EU Consolidated Financial Sanctions",
                "listed_at": "",
            }
        )

    return entries


def parse_mswia_html(html_content: str) -> List[Dict[str, Any]]:
    """Parsuje listę sankcyjną ze strony MSWiA (ekstrakcja wierszy tabel z nazwą, NIP/KRS i datą)."""
    entries: List[Dict[str, Any]] = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_content, flags=re.IGNORECASE | re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
        if len(cells) < 2:
            continue
        clean_cells = [html_lib.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]
        clean_cells = [re.sub(r"\s+", " ", c) for c in clean_cells]

        # Pomijamy wiersze nagłówkowe
        joined = " ".join(clean_cells)
        if not joined or "imię i nazwisko" in joined.lower() or "nazwa podmiotu" in joined.lower():
            continue

        name_candidate = clean_cells[1] if len(clean_cells) >= 3 and clean_cells[0].isdigit() else clean_cells[0]
        if len(name_candidate) < 3:
            continue

        nip_match = re.search(r"NIP[:\s]*([0-9]{10})", joined, flags=re.IGNORECASE)
        krs_match = re.search(r"KRS[:\s]*([0-9]{10})", joined, flags=re.IGNORECASE)

        is_company = any(
            kw in name_candidate.lower()
            for kw in ("sp.", "spółka", "s.a.", "ooo", "pao", "oao", "zao", "gmbh", "llc", "ltd", "limited", "holding", "bank")
        )
        entry_type = "ENTITY" if (is_company or nip_match or krs_match) else "PERSON"

        listed_at = ""
        if len(clean_cells) >= 5 and clean_cells[4]:
            listed_at = clean_cells[4].strip()

        entries.append(
            {
                "entry_type": entry_type,
                "name": name_candidate[:250],
                "normalized_name": normalize_name(name_candidate),
                "nip": nip_match.group(1) if nip_match else None,
                "krs": krs_match.group(1) if krs_match else None,
                "aliases": [],
                "reason": "Lista sankcyjna MSWiA (gov.pl)",
                "listed_at": listed_at,
            }
        )

    return entries


async def sync_eu_sanctions(client: httpx.AsyncClient, db: Database) -> Dict[str, Any]:
    """Pobiera i zapisuje aktualną unijną listę sankcyjną."""
    try:
        resp = await http_request_with_retry(
            client,
            "GET",
            EU_SANCTIONS_XML_URL,
            headers={"Accept": "application/xml, text/xml, */*"},
            timeout=25.0,
            max_retries=1,
        )
        if resp.status_code != 200:
            msg = f"HTTP {resp.status_code}"
            db.log_sanction_sync("EU", "ERROR", 0, msg)
            return {"source": "EU", "status": "ERROR", "count": 0, "message": msg}

        entries = parse_eu_sanctions_xml(resp.text)
        if not entries:
            msg = "Pusty lub nierozpoznany XML listy UE"
            db.log_sanction_sync("EU", "ERROR", 0, msg)
            return {"source": "EU", "status": "ERROR", "count": 0, "message": msg}

        count = db.replace_sanctions_for_source("EU", entries)
        db.log_sanction_sync("EU", "SUCCESS", count, f"Zsynchronizowano {count} podmiotów i osób z listy UE")
        return {"source": "EU", "status": "SUCCESS", "count": count, "message": "OK"}
    except Exception as exc:
        msg = f"{exc.__class__.__name__}: {exc}"
        db.log_sanction_sync("EU", "ERROR", 0, msg)
        return {"source": "EU", "status": "ERROR", "count": 0, "message": msg}


async def sync_mswia_sanctions(client: httpx.AsyncClient, db: Database) -> Dict[str, Any]:
    """Pobiera i zapisuje aktualną polską listę sankcyjną MSWiA."""
    try:
        resp = await http_request_with_retry(
            client,
            "GET",
            MSWIA_SANCTIONS_URL,
            headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            timeout=20.0,
            max_retries=1,
        )
        if resp.status_code != 200:
            msg = f"HTTP {resp.status_code}"
            db.log_sanction_sync("MSWIA", "ERROR", 0, msg)
            return {"source": "MSWIA", "status": "ERROR", "count": 0, "message": msg}

        entries = parse_mswia_html(resp.text)
        if not entries:
            msg = "Nie znaleziono tabeli wpisów na stronie MSWiA"
            db.log_sanction_sync("MSWIA", "ERROR", 0, msg)
            return {"source": "MSWIA", "status": "ERROR", "count": 0, "message": msg}

        count = db.replace_sanctions_for_source("MSWIA", entries)
        db.log_sanction_sync("MSWIA", "SUCCESS", count, f"Zsynchronizowano {count} wpisów z MSWiA")
        return {"source": "MSWIA", "status": "SUCCESS", "count": count, "message": "OK"}
    except Exception as exc:
        msg = f"{exc.__class__.__name__}: {exc}"
        db.log_sanction_sync("MSWIA", "ERROR", 0, msg)
        return {"source": "MSWIA", "status": "ERROR", "count": 0, "message": msg}


def parse_knf_html(html_content: str) -> List[Dict[str, Any]]:
    """Parsuje oficjalną Listę Ostrzeżeń Publicznych KNF ze strony knf.gov.pl."""
    entries: List[Dict[str, Any]] = []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_content, flags=re.IGNORECASE | re.DOTALL)
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.IGNORECASE | re.DOTALL)
        if len(cells) < 3:
            continue
        clean_cells = [html_lib.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in cells]
        clean_cells = [re.sub(r"\s+", " ", c) for c in clean_cells]

        # cells: [lp, nazwa, identyfikatory, prokuratura, wzmianki, info]
        name_raw = clean_cells[1] if len(clean_cells) > 1 else ""
        id_raw = clean_cells[2] if len(clean_cells) > 2 else ""
        prosecutor = clean_cells[3] if len(clean_cells) > 3 else ""
        info = clean_cells[5] if len(clean_cells) > 5 else ""

        if not name_raw or len(name_raw) < 2:
            continue

        nip_m = re.search(r"\bNIP[:\s]*([0-9]{10})\b", id_raw, flags=re.IGNORECASE) or re.search(r"\b([0-9]{10})\b", id_raw)
        krs_m = re.search(r"\bKRS[:\s]*([0-9]{10})\b", id_raw, flags=re.IGNORECASE)

        # Oczyszczenie nazwy podmiotu z numeracji wiersza typu '1. '
        name_clean = re.sub(r"^\d+\.\s*", "", name_raw).strip()

        reason_parts = []
        if info and info != "-":
            reason_parts.append(info)
        if prosecutor and prosecutor != "-":
            reason_parts.append(f"Właściwa: {prosecutor}")
        reason = " • ".join(reason_parts) or "Lista Ostrzeżeń Publicznych KNF (art. 6b ustawy o nadzorze)"

        is_company = any(
            kw in name_clean.lower()
            for kw in ("sp.", "spółka", "s.a.", "sa", "z o.o.", "ltd", "inc", "corp", "bank", "fundusz", "holding", "coop")
        )
        entry_type = "ENTITY" if (is_company or nip_m or krs_m) else "PERSON"

        entries.append(
            {
                "entry_type": entry_type,
                "name": name_clean[:250],
                "normalized_name": normalize_name(name_clean),
                "nip": nip_m.group(1) if nip_m else None,
                "krs": krs_m.group(1) if krs_m else None,
                "aliases": [],
                "reason": reason[:500],
                "listed_at": "",
            }
        )

    return entries


async def sync_knf_warnings(client: httpx.AsyncClient, db: Database) -> Dict[str, Any]:
    """Pobiera i synchronizuje Listę Ostrzeżeń Publicznych KNF."""
    try:
        resp = await http_request_with_retry(
            client,
            "GET",
            KNF_WARNINGS_URL,
            headers={
                "Accept": "text/html,application/xhtml+xml,*/*",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            },
            timeout=25.0,
            max_retries=1,
        )
        if resp.status_code != 200:
            msg = f"HTTP {resp.status_code}"
            db.log_sanction_sync("KNF", "ERROR", 0, msg)
            return {"source": "KNF", "status": "ERROR", "count": 0, "message": msg}

        entries = parse_knf_html(resp.text)
        if not entries:
            msg = "Nie znaleziono tabeli ostrzeżeń na stronie KNF"
            db.log_sanction_sync("KNF", "ERROR", 0, msg)
            return {"source": "KNF", "status": "ERROR", "count": 0, "message": msg}

        count = db.replace_sanctions_for_source("KNF", entries)
        db.log_sanction_sync("KNF", "SUCCESS", count, f"Zsynchronizowano {count} podmiotów z Listy Ostrzeżeń KNF")
        return {"source": "KNF", "status": "SUCCESS", "count": count, "message": "OK"}
    except Exception as exc:
        msg = f"{exc.__class__.__name__}: {exc}"
        db.log_sanction_sync("KNF", "ERROR", 0, msg)
        return {"source": "KNF", "status": "ERROR", "count": 0, "message": msg}


async def sync_all_sanctions(client: httpx.AsyncClient, db: Database) -> List[Dict[str, Any]]:
    """Synchronizuje wszystkie oficjalne listy sankcyjne i ostrzeżenia publiczne."""
    seed_default_sanctions(db)
    mswia_res = await sync_mswia_sanctions(client, db)
    eu_res = await sync_eu_sanctions(client, db)
    knf_res = await sync_knf_warnings(client, db)
    return [mswia_res, eu_res, knf_res]
