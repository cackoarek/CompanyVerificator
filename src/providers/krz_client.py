"""Moduł integracji z Krajowym Rejestrem Zadłużonych (KRZ) oraz danymi o upadłości i restrukturyzacji.

System obsługuje:
1. Głębokie parsowanie Działu 6 Krajowego Rejestru Sądowego (KRS):
   - postępowania upadłościowe (likwidacyjne / układowe, sygnatury akt, syndycy, daty zakończenia)
   - postępowania restrukturyzacyjne (sanacja, przyspieszone układowe, układ częściowy)
   - postępowania układowe
   - likwidacja podmiotu
2. Opcjonalną integrację z zewnętrzną bramką API KRZ (gdy skonfigurowano KRZ_API_URL / KRZ_API_KEY).
3. Klasyfikację statusu podmiotu w KRZ dla silnika ryzyka AML / Compliance.
"""

from typing import Any, Dict, List, Optional
import httpx

from src.config import KRZ_API_KEY, KRZ_API_URL
from src.core.validators import clean_krs, clean_nip
from src.providers.base import http_request_with_retry


def parse_krs_dzial6_insolvency(krs_raw_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Ekstrahuje ustrukturyzowane informacje o postępowaniach upadłościowych i restrukturyzacyjnych z Działu 6 KRS.

    Zwraca słownik:
    - has_insolvency: bool (czy ogłoszono upadłość lub w toku)
    - has_restructuring: bool (czy w toku postępowanie restrukturyzacyjne / sanacja)
    - has_liquidation: bool (czy otwarto likwidację)
    - status: str (CZYSTY | POSTEPOWANIE_UPADLOSCIOWE | RESTRUKTURYZACJA | LIKWIDACJA | BEZSKUTECZNA_EGZEKUCJA)
    - wpisy: List[Dict[str, Any]] (szczegółowe rekordy ze sprawami, sygnaturami i organami)
    - opisy: List[str] (zwięzłe linie tekstowe do kart i raportów)
    """
    if not krs_raw_data or not isinstance(krs_raw_data, dict):
        return {
            "has_insolvency": False,
            "has_restructuring": False,
            "has_liquidation": False,
            "has_enforcement_dismissal": False,
            "status": "CZYSTY",
            "wpisy": [],
            "opisy": [],
        }

    odpis = krs_raw_data.get("odpis") or {}
    dane = odpis.get("dane") or {}
    dzial6 = dane.get("dzial6") or {}

    wpisy: List[Dict[str, Any]] = []
    opisy: List[str] = []

    has_insolvency = False
    has_restructuring = False
    has_liquidation = False
    has_enforcement_dismissal = False

    # 1. Postępowanie upadłościowe
    post_upadlosciowe = dzial6.get("postepowanieUpadlosciowe") or []
    if isinstance(post_upadlosciowe, dict):
        post_upadlosciowe = [post_upadlosciowe]

    for item in post_upadlosciowe:
        if not isinstance(item, dict):
            continue
        has_insolvency = True
        info_ogloszenie = item.get("informacjaOOgloszeniuUpadlosci") or {}
        sposob = item.get("sposobProwadzeniaPostepowania") or ""
        organ = info_ogloszenie.get("organWydajacy") or item.get("organSadowyLubInny") or ""
        sygnatura = info_ogloszenie.get("sygnatura") or item.get("sygnaturaAkt") or ""
        data = info_ogloszenie.get("data") or item.get("dataWszczeciaLubOtwarcia") or ""
        zakonczenie = item.get("opisZakonczeniaProcesuUpadlosci") or {}
        data_zak = zakonczenie.get("dataZakonczeniaPostepowania") or ""
        opis_zak = zakonczenie.get("opisSposobuZakonczeniaPostepowania") or ""

        # Dane syndyka (jeśli występują)
        syndycy = []
        for s in item.get("daneSyndyka") or []:
            if isinstance(s, dict):
                imie = (s.get("imiona") or {}).get("imie", "") if isinstance(s.get("imiona"), dict) else ""
                nazwisko = (s.get("nazwisko") or {}).get("nazwiskoICzlon", "") if isinstance(s.get("nazwisko"), dict) else ""
                full = f"{imie} {nazwisko}".strip() or s.get("nazwa") or "Syndyk"
                syndycy.append(full)

        rec = {
            "rodzaj": "POSTĘPOWANIE UPADŁOŚCIOWE",
            "sposob": sposob,
            "organ": organ,
            "sygnatura": sygnatura,
            "data": data,
            "data_zakonczenia": data_zak,
            "opis_zakonczenia": opis_zak,
            "syndycy": syndycy,
        }
        wpisy.append(rec)

        opis_line = f"Postępowanie upadłościowe (Sygn. {sygnatura or 'brak'}, {organ or 'Sąd Upadłościowy'})"
        if data:
            opis_line += f" z dn. {data}"
        if syndycy:
            opis_line += f" – Syndyk: {', '.join(syndycy)}"
        if data_zak:
            opis_line += f" [Zakończone: {data_zak} – {opis_zak}]"
        opisy.append(opis_line)

    # 2. Postępowanie restrukturyzacyjne / układowe
    post_restrukturyzacyjne = (
        (dzial6.get("postepowanieRestrukturyzacyjne") or [])
        + (dzial6.get("postepowanieUkladowe") or [])
    )
    if isinstance(post_restrukturyzacyjne, dict):
        post_restrukturyzacyjne = [post_restrukturyzacyjne]

    for item in post_restrukturyzacyjne:
        if not isinstance(item, dict):
            continue
        has_restructuring = True
        organ = item.get("organSadowyLubInny") or (item.get("informacjaOPostepowaniu") or {}).get("organWydajacy") or ""
        sygnatura = item.get("sygnaturaAkt") or (item.get("informacjaOPostepowaniu") or {}).get("sygnatura") or ""
        data = item.get("dataWszczeciaLubOtwarcia") or (item.get("informacjaOPostepowaniu") or {}).get("data") or ""
        opis = item.get("informacjaOPostepowaniu") if isinstance(item.get("informacjaOPostepowaniu"), str) else ""

        rec = {
            "rodzaj": "POSTĘPOWANIE RESTRUKTURYZACYJNE",
            "organ": organ,
            "sygnatura": sygnatura,
            "data": data,
            "opis": opis,
        }
        wpisy.append(rec)
        opis_line = f"Postępowanie restrukturyzacyjne (Sygn. {sygnatura or 'brak'}, {organ or 'Sąd Restrukturyzacyjny'})"
        if data:
            opis_line += f" z dn. {data}"
        opisy.append(opis_line)

    # 3. Likwidacja podmiotu
    likwidacja = dzial6.get("likwidacja") or []
    if isinstance(likwidacja, dict):
        likwidacja = [likwidacja]

    for item in likwidacja:
        if not isinstance(item, dict):
            continue
        has_liquidation = True
        opis = item.get("opis") or item.get("otwarcieLikwidacji") or "Otwarcie likwidacji spółki"
        sposob_rep = item.get("sposobReprezentacjiPodmiotuPrzezLikwidatorow") or ""
        likwidatorzy = []
        for likw in item.get("likwidatorzy") or []:
            if isinstance(likw, dict):
                imie = (likw.get("imiona") or {}).get("imie", "") if isinstance(likw.get("imiona"), dict) else ""
                nazw = (likw.get("nazwisko") or {}).get("nazwiskoICzlon", "") if isinstance(likw.get("nazwisko"), dict) else ""
                likwidatorzy.append(f"{imie} {nazw}".strip() or "Likwidator")

        rec = {
            "rodzaj": "LIKWIDACJA",
            "opis": opis,
            "sposob_reprezentacji": sposob_rep,
            "likwidatorzy": likwidatorzy,
        }
        wpisy.append(rec)
        opis_line = f"Podmiot w likwidacji: {opis}"
        if likwidatorzy:
            opis_line += f" (Likwidatorzy: {', '.join(likwidatorzy)})"
        opisy.append(opis_line)

    # Ustalenie syntetycznego statusu
    if has_insolvency:
        status = "POSTEPOWANIE_UPADLOSCIOWE"
    elif has_restructuring:
        status = "RESTRUKTURYZACJA"
    elif has_liquidation:
        status = "LIKWIDACJA"
    else:
        status = "CZYSTY"

    return {
        "has_insolvency": has_insolvency,
        "has_restructuring": has_restructuring,
        "has_liquidation": has_liquidation,
        "has_enforcement_dismissal": has_enforcement_dismissal,
        "status": status,
        "wpisy": wpisy,
        "opisy": opisy,
    }


async def check_krz_status(
    client: httpx.AsyncClient,
    *,
    nip: Optional[str] = None,
    krs: Optional[str] = None,
    krs_raw_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Sprawdza status niewypłacalności i restrukturyzacji w KRZ / Dziale 6 KRS.

    W pierwszej kolejności wykorzystuje ustrukturyzowane dane z rejestru sądowego KRS.
    W przypadku skonfigurowania zewnętrznego API KRZ (KRZ_API_URL) odpytuje bramkę sieciową.
    """
    cleaned_nip = clean_nip(nip) if nip else None
    cleaned_krs = clean_krs(krs) if krs else None

    # Ekstrakcja bazowa z KRS Dział 6
    krs_res = parse_krs_dzial6_insolvency(krs_raw_data)

    # Jeśli skonfigurowano zewnętrzne API KRZ (proxy / provider komercyjny)
    if KRZ_API_URL and (cleaned_nip or cleaned_krs):
        try:
            headers = {"User-Agent": "CompanyVerificator-KRZ/1.0"}
            if KRZ_API_KEY:
                headers["Authorization"] = f"Bearer {KRZ_API_KEY}"

            params: Dict[str, str] = {}
            if cleaned_nip:
                params["nip"] = cleaned_nip
            if cleaned_krs:
                params["krs"] = cleaned_krs

            resp = await http_request_with_retry(
                client,
                "GET",
                KRZ_API_URL,
                params=params,
                headers=headers,
                timeout=5.0,
            )
            if resp.status_code == 200:
                krz_payload = resp.json()
                # Łączymy wpisy z bramki KRZ z danymi z KRS
                external_status = krz_payload.get("status")
                external_wpisy = krz_payload.get("wpisy") or []
                external_opisy = krz_payload.get("opisy") or []

                if external_status in ("POSTEPOWANIE_UPADLOSCIOWE", "RESTRUKTURYZACJA", "BEZSKUTECZNA_EGZEKUCJA"):
                    krs_res["status"] = external_status
                    if external_status == "BEZSKUTECZNA_EGZEKUCJA":
                        krs_res["has_enforcement_dismissal"] = True
                    elif external_status == "POSTEPOWANIE_UPADLOSCIOWE":
                        krs_res["has_insolvency"] = True
                    elif external_status == "RESTRUKTURYZACJA":
                        krs_res["has_restructuring"] = True

                krs_res["wpisy"].extend(external_wpisy)
                krs_res["opisy"].extend(external_opisy)
                krs_res["krz_api_queried"] = True
                return krs_res

        except Exception:
            # W razie awarii zewnętrznego API KRZ przechodzimy na dane z KRS
            pass

    krs_res["krz_api_queried"] = bool(KRZ_API_URL)
    return krs_res
