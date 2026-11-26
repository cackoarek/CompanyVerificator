"""Asynchroniczny klient rejestru REGON (GUS BIR 1.1 / BIR 1.2)."""

import asyncio
import re
from typing import Any, Dict, Optional
from xml.etree import ElementTree as ET

import httpx

from src.config import GUS_API_URL, GUS_ENABLED, GUS_USER_KEY
from src.core.logging_config import app_logger
from src.core.validators import clean_krs, clean_nip, clean_regon

# Akcje SOAP WCF
ACTION_LOGIN = "http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Zaloguj"
ACTION_SEARCH = "http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DaneSzukajPodmioty"
ACTION_LOGOUT = "http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/Wyloguj"


def _extract_xml_from_multipart(text: str) -> str:
    """Wyciąga kopertę SOAP XML z odpowiedzi multipart/related zwracanej przez WCF GUS."""
    match = re.search(r"(<[a-zA-Z0-9_:]*Envelope.*?</[a-zA-Z0-9_:]*Envelope>)", text, re.DOTALL)
    if match:
        return match.group(1)
    return text


def _build_soap_envelope(action_url: str, body_xml: str, service_url: str) -> str:
    """Buduje kopertę SOAP 1.2 z nagłówkami WS-Addressing wymaganymi przez GUS BIR."""
    return f"""<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
xmlns:ns="http://CIS/BIR/PUBL/2014/07"
xmlns:dat="http://CIS/BIR/PUBL/2014/07/DataContract"
xmlns:wsa="http://www.w3.org/2005/08/addressing">
<soap:Header>
    <wsa:Action>{action_url}</wsa:Action>
    <wsa:To>{service_url}</wsa:To>
</soap:Header>
<soap:Body>
    {body_xml}
</soap:Body>
</soap:Envelope>""".strip()


def _format_address(dane: Dict[str, str]) -> Optional[str]:
    """Składa sformatowany adres z pól zwróconych przez GUS REGON."""
    ulica = dane.get("Ulica", "").strip()
    nr_domu = dane.get("NrNieruchomosci", "").strip()
    nr_lokalu = dane.get("NrLokalu", "").strip()
    kod = dane.get("KodPocztowy", "").strip()
    miejscowosc = dane.get("Miejscowosc", "").strip()

    street_part = ""
    if ulica:
        nr = f"{nr_domu}/{nr_lokalu}" if nr_lokalu else nr_domu
        street_part = f"{ulica} {nr}".strip()
    elif nr_domu:
        street_part = f"{nr_domu}/{nr_lokalu}" if nr_lokalu else nr_domu

    city_part = f"{kod} {miejscowosc}".strip() if kod else miejscowosc

    parts = [p for p in (street_part, city_part) if p]
    return ", ".join(parts) if parts else None


class GusBirClient:
    """Klient API Bazy Internetowej REGON GUS (usługa BIR 1.1 / 1.2)."""

    def __init__(
        self,
        service_url: Optional[str] = None,
        user_key: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self.service_url = (service_url or GUS_API_URL).strip()
        self.user_key = (user_key or GUS_USER_KEY).strip()
        self.enabled = GUS_ENABLED if enabled is None else enabled

    async def _login(self, client: httpx.AsyncClient) -> Optional[str]:
        """Loguje się do usługi GUS i zwraca identyfikator sesji (sid)."""
        if not self.user_key:
            app_logger.warning("GUS BIR: Brak zdefiniowanego klucza użytkownika (GUS_USER_KEY).")
            return None

        body = f"""<ns:Zaloguj><ns:pKluczUzytkownika>{self.user_key}</ns:pKluczUzytkownika></ns:Zaloguj>"""
        env = _build_soap_envelope(ACTION_LOGIN, body, self.service_url)

        try:
            resp = await client.post(
                self.service_url,
                content=env.encode("utf-8"),
                headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                timeout=10.0,
            )
            if resp.status_code != 200:
                app_logger.error(f"GUS BIR: Błąd logowania HTTP {resp.status_code}: {resp.text[:200]}")
                return None

            xml_str = _extract_xml_from_multipart(resp.text)
            root = ET.fromstring(xml_str)
            sid_elem = root.find(".//{http://CIS/BIR/PUBL/2014/07}ZalogujResult")
            if sid_elem is not None and sid_elem.text:
                return sid_elem.text.strip()
            return None
        except Exception as exc:
            app_logger.error(f"GUS BIR: Wyjątek podczas logowania: {exc}")
            return None

    async def _logout(self, client: httpx.AsyncClient, sid: str) -> None:
        """Zamyka aktywną sesję w GUS BIR."""
        if not sid:
            return
        body = f"""<ns:Wyloguj><ns:pIdentyfikatorSesji>{sid}</ns:pIdentyfikatorSesji></ns:Wyloguj>"""
        env = _build_soap_envelope(ACTION_LOGOUT, body, self.service_url)
        try:
            await client.post(
                self.service_url,
                content=env.encode("utf-8"),
                headers={"Content-Type": "application/soap+xml; charset=utf-8", "sid": sid},
                timeout=5.0,
            )
        except Exception:
            pass  # Ignoruj błędy przy wylogowywaniu

    async def search_entity(
        self,
        client: httpx.AsyncClient,
        *,
        nip: Optional[str] = None,
        regon: Optional[str] = None,
        krs: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Przeszukuje rejestr REGON po numerze NIP, REGON lub KRS.

        Zwraca słownik ze znormalizowanymi danymi podmiotu lub None.
        """
        if not self.enabled:
            return None

        # Zbuduj kryterium wyszukiwania
        param_xml = ""
        if nip:
            clean = clean_nip(nip)
            if len(clean) == 10:
                param_xml = f"<dat:Nip>{clean}</dat:Nip>"
        if not param_xml and regon:
            clean = clean_regon(regon)
            if len(clean) in (9, 14):
                param_xml = f"<dat:Regon>{clean}</dat:Regon>"
        if not param_xml and krs:
            clean = clean_krs(krs)
            if len(clean) == 10:
                param_xml = f"<dat:Krs>{clean}</dat:Krs>"

        if not param_xml:
            return None

        sid = await self._login(client)
        if not sid:
            return None

        body_search = f"""<ns:DaneSzukajPodmioty>
    <ns:pParametryWyszukiwania>
        {param_xml}
    </ns:pParametryWyszukiwania>
</ns:DaneSzukajPodmioty>"""
        env_search = _build_soap_envelope(ACTION_SEARCH, body_search, self.service_url)

        try:
            resp = await client.post(
                self.service_url,
                content=env_search.encode("utf-8"),
                headers={"Content-Type": "application/soap+xml; charset=utf-8", "sid": sid},
                timeout=12.0,
            )
            if resp.status_code != 200:
                app_logger.warning(f"GUS BIR: Błąd wyszukiwania HTTP {resp.status_code}")
                return None

            xml_str = _extract_xml_from_multipart(resp.text)
            root = ET.fromstring(xml_str)
            res_elem = root.find(".//{http://CIS/BIR/PUBL/2014/07}DaneSzukajPodmiotyResult")
            if res_elem is None or not res_elem.text:
                return None

            inner_xml = res_elem.text.strip()
            if not inner_xml or "<dane>" not in inner_xml:
                return None

            # Parsowanie wewnętrznego XML-a z danymi
            inner_root = ET.fromstring(inner_xml)
            dane_node = inner_root.find("dane")
            if dane_node is None:
                return None

            # Sprawdź czy to nie komunikat błędu (np. ErrorCode)
            if dane_node.find("ErrorCode") is not None:
                err_code = dane_node.findtext("ErrorCode")
                app_logger.info(f"GUS BIR: Podmiot nie znaleziony (kod błędu GUS: {err_code})")
                return None

            raw: Dict[str, str] = {}
            for child in dane_node:
                raw[child.tag] = (child.text or "").strip()

            typ_podmiotu = raw.get("Typ", "")
            forma_prawna = "Osoba prawna / jednostka organizacyjna" if typ_podmiotu == "P" else ("Osoba fizyczna (działalność)" if typ_podmiotu == "F" else "Inna forma organizacyjna")

            # Jeśli typ == "P" (osoba prawna), spróbuj pobrać KRS, daty powstania oraz dokładną formę z pełnego raportu
            krs_val = raw.get("Krs") or None
            data_powstania_val = None
            data_rozpoczecia_val = None
            data_wpisu_rejestru_val = None
            if typ_podmiotu == "P" and raw.get("Regon"):
                try:
                    full_body = f"""<ns:DanePobierzPelnyRaport>
<ns:pRegon>{raw.get("Regon")}</ns:pRegon>
<ns:pNazwaRaportu>PublDaneRaportPrawna</ns:pNazwaRaportu>
</ns:DanePobierzPelnyRaport>"""
                    action_full = "http://CIS/BIR/PUBL/2014/07/IUslugaBIRzewnPubl/DanePobierzPelnyRaport"
                    env_full = _build_soap_envelope(action_full, full_body, self.service_url)
                    resp_full = await client.post(
                        self.service_url,
                        content=env_full.encode("utf-8"),
                        headers={"Content-Type": "application/soap+xml; charset=utf-8", "sid": sid},
                        timeout=8.0,
                    )
                    if resp_full.status_code == 200:
                        full_xml_str = _extract_xml_from_multipart(resp_full.text)
                        full_root = ET.fromstring(full_xml_str)
                        full_res_elem = full_root.find(".//{http://CIS/BIR/PUBL/2014/07}DanePobierzPelnyRaportResult")
                        if full_res_elem is not None and full_res_elem.text:
                            inner_full_root = ET.fromstring(full_res_elem.text.strip())
                            dane_full = inner_full_root.find("dane")
                            if dane_full is not None:
                                krs_cand = dane_full.findtext("praw_numerWrejestrzeEwidencji") or dane_full.findtext("praw_numerWRejestrzeEwidencji")
                                rod_rejestru = dane_full.findtext("praw_rodzajRejestruEwidencji_Nazwa") or ""
                                if not krs_val and krs_cand and ("KRS" in rod_rejestru or "PRZEDSIĘBIORCÓW" in rod_rejestru or len(krs_cand) == 10):
                                    krs_val = krs_cand.strip().zfill(10)
                                    app_logger.info(f"GUS BIR: Pozyskano KRS {krs_val} z pełnego raportu dla REGON {raw.get('Regon')}")
                                
                                # Daty założenia / rejestracji z rejestru REGON
                                data_powstania_val = dane_full.findtext("praw_dataPowstania") or None
                                data_rozpoczecia_val = dane_full.findtext("praw_dataRozpoczeciaDzialalnosci") or None
                                data_wpisu_rejestru_val = dane_full.findtext("praw_dataWpisuDoRejestruEwidencji") or None
                                
                                # Dokładniejsza forma prawna z REGON (np. STOWARZYSZENIA NIEWPISANE DO KRS)
                                szczegolna_forma = dane_full.findtext("praw_szczegolnaFormaPrawna_Nazwa")
                                if szczegolna_forma:
                                    forma_prawna = szczegolna_forma.strip()
                except Exception as exc_full:
                    app_logger.debug(f"GUS BIR: Nie udało się pobrać pełnego raportu KRS: {exc_full}")

            # Mapowanie pól na zunifikowany model
            parsed_data = {
                "nip": raw.get("Nip") or None,
                "regon": raw.get("Regon") or None,
                "krs": krs_val,
                "nazwa": raw.get("Nazwa") or None,
                "wojewodztwo": raw.get("Wojewodztwo") or None,
                "powiat": raw.get("Powiat") or None,
                "gmina": raw.get("Gmina") or None,
                "miejscowosc": raw.get("Miejscowosc") or None,
                "kod_pocztowy": raw.get("KodPocztowy") or None,
                "ulica": raw.get("Ulica") or None,
                "adres_rejestrowy": _format_address(raw),
                "typ": typ_podmiotu,
                "forma_prawna": forma_prawna,
                "data_powstania": data_powstania_val,
                "data_rozpoczecia": data_rozpoczecia_val,
                "data_wpisu_rejestru": data_wpisu_rejestru_val,
                "data_zakonczenia": raw.get("DataZakonczeniaDzialalnosci") or None,
                "zrodlo": "GUS_REGON_BIR",
            }

            app_logger.info(f"GUS BIR: Znaleziono podmiot: {parsed_data['nazwa']} (REGON: {parsed_data['regon']}, KRS: {parsed_data['krs']})")
            return parsed_data

        except Exception as exc:
            app_logger.error(f"GUS BIR: Wyjątek podczas wyszukiwania podmiotu: {exc}")
            return None
        finally:
            await self._logout(client, sid)

