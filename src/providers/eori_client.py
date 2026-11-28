"""Asynchroniczny klient walidacji numerów EORI Komisji Europejskiej (DG TAXUD - EOS).

Usługa sprawdza, czy dany podmiot posiada aktywny numer w unijnym systemie
Rejestracji i Identyfikacji Podmiotów Gospodarczych (Economic Operators Registration and Identification).
W Polsce numer EORI przyjmuje schemat: PL + NIP + 00000.
"""

import re
from typing import Any, Dict, Optional
import httpx

from src.core.validators import clean_nip
from src.providers.base import http_request_with_retry

EORI_SOAP_URL = "https://ec.europa.eu/taxation_customs/dds2/eos/validation/services/validation"


def build_eori_number(nip_or_eori: str, country_code: str = "PL") -> str:
    """Tworzy lub normalizuje numer EORI (dla PL: PL + NIP + 00000)."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", nip_or_eori).upper()
    if cleaned.startswith(country_code.upper()):
        return cleaned
    
    # Jeśli podano sam NIP 10-cyfrowy dla Polski
    if country_code.upper() == "PL":
        nip_clean = clean_nip(cleaned)
        if len(nip_clean) == 10:
            return f"PL{nip_clean}00000"
    
    return f"{country_code.upper()}{cleaned}"


def _parse_eori_response(xml_text: str, eori: str) -> Dict[str, Any]:
    """Deterministycznie parsuje odpowiedź XML SOAP z serwisu Komisji Europejskiej."""
    # Status: 0 oznacza Valid, inne wartości to Invalid lub błąd
    status_match = re.search(r"<status>(\d+)</status>", xml_text)
    descr_match = re.search(r"<statusDescr>([^<]+)</statusDescr>", xml_text)
    name_match = re.search(r"<name>([^<]+)</name>", xml_text)
    street_match = re.search(r"<street>([^<]+)</street>", xml_text)
    city_match = re.search(r"<city>([^<]+)</city>", xml_text)
    postal_match = re.search(r"<postalCode>([^<]+)</postalCode>", xml_text)
    country_match = re.search(r"<country>([^<]+)</country>", xml_text)
    date_match = re.search(r"<requestDate>([^<]+)</requestDate>", xml_text)

    status_code = int(status_match.group(1)) if status_match else None
    status_descr = descr_match.group(1).strip() if descr_match else ("Valid" if status_code == 0 else "Invalid")
    is_valid = status_code == 0

    return {
        "valid": is_valid,
        "eori": eori,
        "status_code": status_code,
        "status_descr": status_descr,
        "name": name_match.group(1).strip() if name_match else None,
        "street": street_match.group(1).strip() if street_match else None,
        "city": city_match.group(1).strip() if city_match else None,
        "postal_code": postal_match.group(1).strip() if postal_match else None,
        "country": country_match.group(1).strip() if country_match else None,
        "request_date": date_match.group(1).strip() if date_match else None,
        "blad_polaczenia": False,
        "raw_xml": xml_text,
    }


async def validate_eori(
    client: httpx.AsyncClient,
    *,
    nip: Optional[str] = None,
    eori: Optional[str] = None,
    country_code: str = "PL",
) -> Dict[str, Any]:
    """Weryfikuje numer EORI w systemie EOS Komisji Europejskiej."""
    target_eori = eori or (build_eori_number(nip, country_code) if nip else "")
    if not target_eori or len(target_eori) < 5:
        return {
            "valid": False,
            "eori": target_eori,
            "status_descr": "Brak poprawnego numeru EORI",
            "blad_polaczenia": False,
        }

    soap_body = f"""<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns0="http://eori.ws.eos.dds.s/">
   <soap:Header/>
   <soap:Body>
      <ns0:validateEORI>
         <ns0:eori>{target_eori}</ns0:eori>
      </ns0:validateEORI>
   </soap:Body>
</soap:Envelope>"""

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "User-Agent": "CompanyVerificator-EORI/1.0 (Compliance & AML)",
    }

    try:
        resp = await http_request_with_retry(
            client,
            "POST",
            EORI_SOAP_URL,
            content=soap_body.encode("utf-8"),
            headers=headers,
            timeout=5.0,
        )
        if resp.status_code == 200:
            return _parse_eori_response(resp.text, target_eori)
        
        return {
            "valid": False,
            "eori": target_eori,
            "status_descr": f"Błąd serwisu Komisji Europejskiej (HTTP {resp.status_code})",
            "blad_polaczenia": True,
            "komunikat_bledu": f"EORI HTTP {resp.status_code}",
        }
    except Exception as exc:
        return {
            "valid": False,
            "eori": target_eori,
            "status_descr": f"Brak połączenia z systemem EORI ({exc.__class__.__name__})",
            "blad_polaczenia": True,
            "komunikat_bledu": f"Błąd połączenia EORI: {str(exc)}",
        }
