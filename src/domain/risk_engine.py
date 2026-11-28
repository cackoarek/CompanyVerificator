"""Deterministyczny silnik oceny ryzyka AML / Compliance i należytej staranności."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from src.config import PAYMENT_THRESHOLD_PLN
from src.domain.dictionaries.pkd_catalog import (
    PkdRiskCategory,
    evaluate_company_pkd_profile,
)
from src.domain.enums import (
    DecyzjaWspolpracy,
    KanalRelacji,
    PoziomRyzykaAML,
    ProfilRyzykaKyc,
    StatusRachunkuBankowego,
)
from src.domain.models import KycScorecard, RiskFactor, SanctionHit
from src.domain.virtual_office import is_virtual_office_or_mass_address

# Zachowane dla wstecznej kompatybilności referencje do prefiksów
HIGH_RISK_PKD_PREFIXES = (
    "46.71",  # Sprzedaż hurtowa paliw i produktów pochodnych
    "47.30",  # Sprzedaż detaliczna paliw do pojazdów
    "46.72",  # Sprzedaż hurtowa metali i rud metali
    "46.77",  # Sprzedaż hurtowa odpadów i złomu
    "38.32",  # Odzysk surowców (złom i surowce wtórne)
    "24.41",  # Produkcja metali szlachetnych (złoto, srebro, platyna)
    "24.42",  # Produkcja aluminium
    "46.51",  # Sprzedaż hurtowa komputerów i oprogramowania (karuzele elektroniki)
    "46.52",  # Sprzedaż hurtowa sprzętu elektronicznego i telekomunikacyjnego
    "26.11",  # Produkcja elementów elektronicznych
    "92.",    # Hazard
)

# 2. Kody PKD branż wrażliwych wg KOR GIIF / Załącznika 15 VAT (KOR GIIF Filar 4 - 3 pkt)
# Budownictwo, transport, spedycja, doradztwo niematerialne, e-commerce
SENSITIVE_PKD_PREFIXES = (
    "41.",    # Budownictwo budynków
    "42.",    # Budownictwo obiektów inżynierii lądowej i wodnej
    "43.",    # Roboty budowlane specjalistyczne (podwykonawstwo)
    "49.41",  # Transport drogowy towarów
    "52.29",  # Działalność pozostałych agencji transportowych (spedycja)
    "70.22",  # Doradztwo w zakresie prowadzenia działalności (usługi niematerialne)
    "73.11",  # Działalność agencji reklamowych (puste faktury marketingowe)
    "47.91",  # Sprzedaż detaliczna prowadzona przez domy sprzedaży wysyłkowej lub Internet (e-commerce)
    "68.",    # Obsługa rynku nieruchomości
)


@dataclass
class RiskEvaluationInput:
    """Wejście do deterministycznej oceny ryzyka firmy."""

    is_foreign: bool
    status_rejestru: str
    upadlosc_lub_likwidacja: bool
    platnik_vat_czynny: bool
    status_vat: str
    vies_valid: Optional[bool]
    status_rachunku: StatusRachunkuBankowego
    kwota_transakcji: Optional[Decimal]
    crbr_status: str
    sanction_hits: List[SanctionHit]
    status_pep: bool
    blad_polaczenia: bool
    niekompletne_zrodla: List[str]
    data_rozpoczecia: Optional[str] = None
    data_wpisu_rejestru: Optional[str] = None
    kody_pkd: Optional[List[str]] = None
    iban_invalid: bool = False
    rachunki_mf: Optional[List[str]] = None
    adres: Optional[str] = None
    forma_prawna: Optional[str] = None
    kapital_zakladowy: Optional[Decimal] = None
    beneficjenci: Optional[List[Dict[str, Any]]] = None
    reprezentacja: Optional[List[str]] = None
    kanal_relacji: KanalRelacji = KanalRelacji.ZDALNIE
    address_occurrences_in_db: int = 1
    krz_status: str = "CZYSTY"
    krz_szczegoly: Optional[List[str]] = None
    eori: Optional[str] = None
    eori_valid: Optional[bool] = None


def get_entity_age_days(data_str: Optional[str]) -> Optional[int]:
    """Zwraca wiek podmiotu w dniach na podstawie daty rejestracji/rozpoczęcia."""
    if not data_str:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(data_str[:10], fmt[: len(data_str[:10])] if "T" not in fmt else fmt)
            return (datetime.now(timezone.utc).replace(tzinfo=None) - dt).days
        except ValueError:
            continue
    return None


def _is_young_entity(data_rozpoczecia: Optional[str], months_threshold: int = 6) -> bool:
    days = get_entity_age_days(data_rozpoczecia)
    return days is not None and 0 <= days < months_threshold * 30


def evaluate_risk(inp: RiskEvaluationInput) -> Tuple[int, List[RiskFactor], PoziomRyzykaAML, DecyzjaWspolpracy, str, bool]:
    """
    Deterministycznie wylicza punkty ryzyka, listę czynników ryzyka, poziom ryzyka,
    decyzję o współpracy, uzasadnienie merytoryczne oraz flagę wymaganego MPP.
    """
    factors: List[RiskFactor] = []
    score = 0

    # 1. Sankcje (najwyższy priorytet - STOP)
    exact_or_high_sanctions = [h for h in inp.sanction_hits if h.confidence in ("EXACT", "HIGH")]
    possible_sanctions = [h for h in inp.sanction_hits if h.confidence == "POSSIBLE"]

    if exact_or_high_sanctions:
        score += 100
        has_knf = any(h.source == "KNF" for h in exact_or_high_sanctions)
        has_sanctions = any(h.source != "KNF" for h in exact_or_high_sanctions)

        if has_knf and not has_sanctions:
            title = f"Wpis na Liście Ostrzeżeń Publicznych KNF ({len(exact_or_high_sanctions)})"
            legal_basis = "Art. 6b ustawy o nadzorze nad rynkiem finansowym / Kodeks karny"
            rec = "BEZWZGLĘDNA BLOKADA: Wobec podmiotu złożono zawiadomienie o podejrzeniu popełnienia przestępstwa. Rozważ zgłoszenie GSP do GIIF."
        elif has_knf and has_sanctions:
            title = f"Trafienie na liście sankcyjnej oraz Liście Ostrzeżeń KNF ({len(exact_or_high_sanctions)})"
            legal_basis = "Ustawa sankcyjna z 13.04.2022 r. / Art. 6b ustawy o nadzorze KNF"
            rec = "BEZWZGLĘDNA BLOKADA: Zakaz udostępniania środków oraz podejrzenie przestępstwa finansowego."
        else:
            title = f"Trafienie na liście sankcyjnej ({len(exact_or_high_sanctions)})"
            legal_basis = "Ustawa z 13.04.2022 r. (Dz.U. 2022 poz. 835) / Rozporządzenia Rady UE"
            rec = "BEZWZGLĘDNA BLOKADA współpracy i zamrożenie/zakaz udostępniania środków."

        factors.append(
            RiskFactor(
                code="SANCTIONS_HIT",
                title=title,
                severity=PoziomRyzykaAML.KRYTYCZNE_STOP,
                points=100,
                legal_basis=legal_basis,
                recommendation=rec,
            )
        )
    elif possible_sanctions:
        score += 45
        has_knf = any(h.source == "KNF" for h in possible_sanctions)
        if has_knf:
            title = f"Potencjalna zbieżność z Listą Ostrzeżeń Publicznych KNF / Sankcji ({len(possible_sanctions)})"
        else:
            title = f"Potencjalna zbieżność z listą sankcyjną ({len(possible_sanctions)})"

        factors.append(
            RiskFactor(
                code="SANCTIONS_POSSIBLE_MATCH",
                title=title,
                severity=PoziomRyzykaAML.WYSOKIE,
                points=45,
                legal_basis="Art. 34 i 35 ustawy AML",
                recommendation="Zweryfikuj ręcznie tożsamość podmiotu/reprezentantów przed zawarciem transakcji.",
            )
        )

    # 2. Błąd połączenia / tryb offline
    if inp.blad_polaczenia:
        score += 30
        src_list = ", ".join(inp.niekompletne_zrodla) if inp.niekompletne_zrodla else "rejestry publiczne"
        factors.append(
            RiskFactor(
                code="OFFLINE_INCOMPLETE",
                title=f"Weryfikacja niekompletna – brak połączenia ({src_list})",
                severity=PoziomRyzykaAML.SREDNIE,
                points=30,
                legal_basis="Procedura należytej staranności VAT i AML",
                recommendation="Nie zatwierdzaj płatności na podstawie niekompletnego raportu. Ponów weryfikację na żywo (--force).",
            )
        )

    # 3. Status rejestru i niewypłacalność (KRZ / Upadłość / Restrukturyzacja / Likwidacja)
    if inp.krz_status == "POSTEPOWANIE_UPADLOSCIOWE":
        score += 60
        szczegol = f": {inp.krz_szczegoly[0]}" if inp.krz_szczegoly else ""
        factors.append(
            RiskFactor(
                code="INSOLVENCY_PROCEEDINGS",
                title=f"W toku postępowanie upadłościowe (KRZ / KRS Dział 6){szczegol}",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=60,
                legal_basis="Ustawa z dn. 28.02.2003 r. Prawo upadłościowe / KRZ",
                recommendation="Wstrzymaj bezpośrednie płatności. Weryfikacja umocowania syndyka masy upadłości i zgoda sędziego-komisarza.",
            )
        )
    elif inp.krz_status == "RESTRUKTURYZACJA":
        score += 40
        szczegol = f": {inp.krz_szczegoly[0]}" if inp.krz_szczegoly else ""
        factors.append(
            RiskFactor(
                code="RESTRUCTURING_PROCEEDINGS",
                title=f"W toku postępowanie restrukturyzacyjne (KRZ / KRS Dział 6){szczegol}",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=40,
                legal_basis="Ustawa z dn. 15.05.2015 r. Prawo restrukturyzacyjne / KRZ",
                recommendation="Zalecane transakcje wyłącznie z przedpłatą 100%. Weryfikacja zgody nadzorcy sądowego lub zarządcy.",
            )
        )
    elif inp.krz_status == "BEZSKUTECZNA_EGZEKUCJA":
        score += 50
        factors.append(
            RiskFactor(
                code="KRZ_ENFORCEMENT_DISMISSAL",
                title="Wpis w Krajowym Rejestrze Zadłużonych: bezskuteczna egzekucja komornicza",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=50,
                legal_basis="Art. 10 ustawy o Krajowym Rejestrze Zadłużonych",
                recommendation="Wysokie ryzyko niewypłacalności i braku majątku dłużnika. Odmowa kredytu kupieckiego.",
            )
        )
    elif inp.krz_status == "LIKWIDACJA" or inp.upadlosc_lub_likwidacja:
        score += 60
        factors.append(
            RiskFactor(
                code="INSOLVENCY_OR_LIQUIDATION",
                title="Podmiot w stanie likwidacji, upadłości lub restrukturyzacji",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=60,
                legal_basis="Należyta staranność VAT (metodyka MF)",
                recommendation="Wymagana pogłębiona weryfikacja możliwości realizacji świadczenia oraz umocowania likwidatora/syndyka.",
            )
        )
    elif inp.status_rejestru in ("WYKRESLONY", "NIEZNALEZIONY"):
        score += 60
        factors.append(
            RiskFactor(
                code="REGISTRY_INACTIVE",
                title=f"Nieaktywny lub brak wpisu w rejestrze ({inp.status_rejestru})",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=60,
                legal_basis="Art. 96b / 86 ustawy o VAT",
                recommendation="Wstrzymaj współpracę do czasu wyjaśnienia statusu prawnego podmiotu.",
            )
        )
    elif inp.status_rejestru == "ZAWIESZONY":
        score += 35
        factors.append(
            RiskFactor(
                code="REGISTRY_SUSPENDED",
                title="Działalność gospodarcza zawieszona",
                severity=PoziomRyzykaAML.SREDNIE,
                points=35,
                legal_basis="Prawo przedsiębiorców / należyta staranność VAT",
                recommendation="Wyjaśnij podstawę wystawienia faktury w okresie zawieszenia działalności.",
            )
        )

    # 4. CRBR (Beneficjenci rzeczywiści)
    if inp.crbr_status == "BRAK_WPISU":
        score += 30
        factors.append(
            RiskFactor(
                code="CRBR_MISSING",
                title="Brak wymaganego wpisu w Centralnym Rejestrze Beneficjentów Rzeczywistych (CRBR)",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=30,
                legal_basis="Art. 58-61 ustawy AML (obowiązek zgłoszenia UBO)",
                recommendation="Uzyskaj wyjaśnienie od kontrahenta i zweryfikuj strukturę właścicielską przed nawiązaniem relacji.",
            )
        )
    elif inp.crbr_status == "ROZBIEZNOSCI":
        score += 35
        factors.append(
            RiskFactor(
                code="CRBR_DISCREPANCY",
                title="Wykryto rozbieżności między reprezentacją KRS a CRBR",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=35,
                legal_basis="Art. 61a ustawy AML (obowiązek odnotowania rozbieżności)",
                recommendation="Zweryfikuj beneficjentów rzeczywistych i rozważ zgłoszenie rozbieżności do CRBR.",
            )
        )

    # 5. Rachunek bankowy i próg 15 000 PLN
    over_threshold = inp.kwota_transakcji is None or inp.kwota_transakcji >= PAYMENT_THRESHOLD_PLN
    wymagany_mpp = bool(inp.kwota_transakcji is not None and inp.kwota_transakcji >= PAYMENT_THRESHOLD_PLN)

    if inp.iban_invalid:
        score += 25
        factors.append(
            RiskFactor(
                code="IBAN_INVALID",
                title="Nieprawidłowa suma kontrolna numeru rachunku bankowego",
                severity=PoziomRyzykaAML.SREDNIE,
                points=25,
                legal_basis="ISO 7064 Modulo 97-10",
                recommendation="Zweryfikuj poprawność numeru konta bezpośrednio z kontrahentem przed wykonaniem przelewu.",
            )
        )
    elif inp.status_rachunku == StatusRachunkuBankowego.BLAD_POLACZENIA_MF:
        # Nie przypisujemy kary punktowej za brak rachunku, ponieważ to MF miało awarię/aktualizację bazy
        factors.append(
            RiskFactor(
                code="BANK_VERIFICATION_FAILED_MF",
                title="Nie zweryfikowano rachunku – chwilowa niedostępność serwisu MF",
                severity=PoziomRyzykaAML.SREDNIE,
                points=10,
                legal_basis="Art. 22p ustawy o PIT / Dostępność rejestru MF",
                recommendation="Ponów sprawdzenie za kilka minut na żywo (zaznaczając pominięcie cache), aby potwierdzić obecność rachunku w wykazie MF.",
            )
        )
    elif inp.status_rachunku == StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE and over_threshold:
        score += 35
        factors.append(
            RiskFactor(
                code="BANK_NOT_ON_WHITELIST",
                title="Rachunek bankowy poza Białą Listą VAT MF",
                severity=PoziomRyzykaAML.SREDNIE,
                points=35,
                legal_basis="Art. 22p ustawy o PIT / art. 117ba Ordynacji podatkowej",
                recommendation="Dla płatności >= 15 000 zł złóż zawiadomienie ZAW-NR w ciągu 7 dni, użyj MPP lub żądaj konta z Białej Listy.",
            )
        )
    elif (
        inp.status_rachunku == StatusRachunkuBankowego.NIE_PODANO
        and inp.platnik_vat_czynny
        and not inp.is_foreign
        and not inp.blad_polaczenia
        and not inp.rachunki_mf
        and not ("grup" in (inp.status_vat or "").lower() and "vat" in (inp.status_vat or "").lower())
        and "96 ust. 7ba" not in (inp.status_vat or "").lower()
    ):
        score += 20
        factors.append(
            RiskFactor(
                code="NO_REGISTERED_BANK_ACCOUNTS",
                title="Brak zarejestrowanych rachunków firmowych w wykazie MF (Biała Lista)",
                severity=PoziomRyzykaAML.SREDNIE,
                points=20,
                legal_basis="Art. 96b ust. 3 pkt 13 ustawy o VAT / art. 22p ustawy o PIT",
                recommendation="Czynny podatnik VAT nie posiada zgłoszonych rachunków rozliczeniowych. Przed realizacją płatności (szczególnie >= 15 000 zł) zażądaj od kontrahenta zgłoszenia rachunku firmowego w urzędzie skarbowym.",
            )
        )

    # 6. Status VAT / VIES
    if not inp.is_foreign and not inp.blad_polaczenia:
        vat_lower = (inp.status_vat or "").lower()
        forma_lower = (inp.forma_prawna or "").lower()
        is_statutory_nonprofit = (
            "stowarzyszen" in forma_lower
            or "klub sportow" in forma_lower
            or "związek sportow" in forma_lower
        )
        is_vat_exempt_or_group = (
            "zwolnion" in vat_lower
            or ("grup" in vat_lower and "vat" in vat_lower)
            or "96 ust. 7ba" in vat_lower
            or is_statutory_nonprofit
        )
        if not inp.platnik_vat_czynny and not is_vat_exempt_or_group:
            score += 25
            factors.append(
                RiskFactor(
                    code="VAT_NOT_ACTIVE",
                    title=f"Brak statusu czynnego podatnika VAT ({inp.status_vat})",
                    severity=PoziomRyzykaAML.SREDNIE,
                    points=25,
                    legal_basis="Art. 88 ust. 3a oraz art. 96b ustawy o VAT",
                    recommendation="Zweryfikuj prawo do odliczenia podatku VAT z otrzymanej faktury.",
                )
            )
    elif inp.is_foreign and inp.vies_valid is False:
        score += 40
        factors.append(
            RiskFactor(
                code="VIES_INVALID",
                title="Numer VAT-UE nieaktywny w systemie VIES",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=40,
                legal_basis="Art. 97 / art. 42 ustawy o VAT (transakcje wewnątrzwspólnotowe)",
                recommendation="Wstrzymaj zastosowanie stawki 0% WDT lub zweryfikuj poprawność numeru VAT-UE.",
            )
        )

    # 6a. Status celny EORI (Komisja Europejska – DG TAXUD)
    # Jeśli podmiot operuje w branży wysokiego ryzyka (np. paliwa, elektronika, metale), a nie ma EORI:
    has_high_risk_pkd = any(
        (code.startswith("46.71") or code.startswith("46.72") or code.startswith("46.51") or code.startswith("46.52"))
        for code in (inp.kody_pkd or [])
    )
    if inp.eori_valid is False and has_high_risk_pkd:
        score += 15
        factors.append(
            RiskFactor(
                code="EORI_NOT_ACTIVE_HIGH_RISK_TRADE",
                title=f"Brak aktywnego numeru EORI w rejestrze celnym UE ({inp.eori or 'PL'})",
                severity=PoziomRyzykaAML.SREDNIE,
                points=15,
                legal_basis="Unijny Kodeks Celny (Rozporządzenie UE 952/2013) / Procedura KYC",
                recommendation="Podmiot deklaruje handel towarowy w branży wrażliwej, lecz nie posiada aktywnego numeru EORI do odpraw celnych. Zweryfikuj realność łańcucha dostaw.",
            )
        )

    # 7. Status PEP (osoba zajmująca eksponowane stanowisko polityczne)
    if inp.status_pep:
        score += 30
        factors.append(
            RiskFactor(
                code="PEP_STATUS",
                title="Zadeklarowany / ustalony status PEP",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=30,
                legal_basis="Art. 46 ustawy AML (wzmożone środki bezpieczeństwa finansowego)",
                recommendation="Wymagana zgoda kadry kierowniczej wyższego szczebla oraz ustalenie źródła pochodzenia majątku.",
            )
        )

    # 8. Krótki staż działalności i ryzykowne PKD (informacyjne sygnały należytej staranności)
    effective_reg_date = inp.data_wpisu_rejestru or inp.data_rozpoczecia
    reg_days = get_entity_age_days(effective_reg_date)
    if reg_days is not None and 0 <= reg_days < 180:
        score += 20
        factors.append(
            RiskFactor(
                code="VERY_YOUNG_ENTITY",
                title=f"Firma niedawno założona – wpis do rejestru poniżej 6 miesięcy (od {effective_reg_date}, ok. {reg_days} dni)",
                severity=PoziomRyzykaAML.SREDNIE,
                points=20,
                legal_basis="Metodyka MF należytej staranności w VAT / Wzmożona uwaga AML (KOR GIIF)",
                recommendation="UWAGA DLA OSOBY SPRAWDZAJĄCEJ: Podmiot powstał bardzo niedawno (poniżej 6 miesięcy). Należy zachować szczególną ostrożność, zażądać potwierdzenia tożsamości osób reprezentujących, referencji handlowych oraz zweryfikować realne zaplecze gospodarcze przed realizacją transakcji.",
            )
        )

    # 9. Profil branżowy PKD (z katalogu PKD i Załącznika 15 VAT)
    if inp.kody_pkd:
        pkd_cat, special_entries, pkd_requires_mpp = evaluate_company_pkd_profile(
            inp.kody_pkd,
            forma_prawna=inp.forma_prawna,
        )
        if pkd_requires_mpp and not wymagany_mpp and inp.kwota_transakcji and inp.kwota_transakcji >= PAYMENT_THRESHOLD_PLN:
            wymagany_mpp = True

        if pkd_cat == PkdRiskCategory.HIGH_RISK_AML and special_entries:
            score += 15
            names = [f"{e.code} ({e.name})" for e in special_entries[:2]]
            factors.append(
                RiskFactor(
                    code="HIGH_RISK_PKD",
                    title=f"Branża podwyższonego ryzyka AML/VAT: {'; '.join(names)}",
                    severity=PoziomRyzykaAML.SREDNIE,
                    points=15,
                    legal_basis="Art. 33 i 43 ustawy AML / zał. nr 15 ustawy o VAT / KOR GIIF",
                    recommendation="Zastosuj wzmożoną weryfikację celu transakcji, dokumentacji transportowej / magazynowej oraz MPP.",
                )
            )
        elif pkd_cat == PkdRiskCategory.SENSITIVE_VAT and special_entries:
            # Informacyjny czynnik dla branż wrażliwych podatkowo
            names = [f"{e.code} ({e.name})" for e in special_entries[:2]]
            factors.append(
                RiskFactor(
                    code="SENSITIVE_INDUSTRY_VAT",
                    title=f"Branża wrażliwa podatkowo (Załącznik 15 VAT / KOR GIIF): {'; '.join(names)}",
                    severity=PoziomRyzykaAML.NISKIE,
                    points=5,
                    legal_basis="Załącznik nr 15 do ustawy o VAT / Wytyczne MF",
                    recommendation="Zachowaj należytą staranność podatkową, zweryfikuj czy transakcja nie podlega pod obowiązkowy mechanizm podzielonej płatności (MPP).",
                )
            )

    # Sprawdzenie wirtualnego biura / adresu masowego
    if inp.adres:
        is_vo, vo_reason = is_virtual_office_or_mass_address(inp.adres)
        if is_vo:
            score += 20
            factors.append(
                RiskFactor(
                    code="VIRTUAL_OFFICE_MASS_ADDRESS",
                    title=f"Wirtualne biuro / adres masowej rejestracji: {vo_reason}",
                    severity=PoziomRyzykaAML.SREDNIE,
                    points=20,
                    legal_basis="Metodyka MF należytej staranności VAT / Wytyczne GIIF w zakresie wirtualnych biur",
                    recommendation="Zweryfikuj faktyczne miejsce zarządu i prowadzenia księgowości oraz dostępność osób uprawnionych pod podanym adresem.",
                )
            )

    # Wyznaczenie końcowego poziomu ryzyka i decyzji
    if exact_or_high_sanctions:
        poziom = PoziomRyzykaAML.KRYTYCZNE_STOP
        decyzja = DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP
        uzasadnienie = (
            "KONTRAHENT LUB OSOBA POWIĄZANA FIGURUJE NA LIŚCIE SANKCYJNEJ. "
            "Obowiązuje bezwzględny zakaz współpracy i udostępniania środków finansowych."
        )
    elif inp.blad_polaczenia:
        poziom = PoziomRyzykaAML.SREDNIE
        decyzja = DecyzjaWspolpracy.WYMAGA_WYJASNIENIA
        uzasadnienie = (
            "WERYFIKACJA NIEKOMPLETNA – wystąpił błąd połączenia z rejestrami publicznymi. "
            "Raport nie może stanowić podstawy do zatwierdzenia płatności; wymagane ponowienie po odzyskaniu sieci."
        )
    elif any(f.severity == PoziomRyzykaAML.WYSOKIE for f in factors) or score >= 55:
        poziom = PoziomRyzykaAML.WYSOKIE
        decyzja = DecyzjaWspolpracy.WYMAGA_WYJASNIENIA
        uzasadnienie = "Wykryto istotne czynniki ryzyka AML/VAT: " + "; ".join(f.title for f in factors) + "."
    elif factors or score >= 15:
        poziom = PoziomRyzykaAML.SREDNIE
        decyzja = DecyzjaWspolpracy.WYMAGA_WYJASNIENIA
        uzasadnienie = "Wykryto punkty wymagające uwagi w procedurze należytej staranności: " + "; ".join(
            f.title for f in factors
        ) + "."
    else:
        poziom = PoziomRyzykaAML.NISKIE
        decyzja = DecyzjaWspolpracy.AKCEPTACJA
        uzasadnienie = (
            "Kontrahent zweryfikowany pozytywnie: podmiot aktywny w rejestrach, brak trafień na listach sankcyjnych, "
            "status podatkowy i rachunek bankowy nie wykazują nieprawidłowości."
        )

    # Obliczenie punktacji KYC wg GIIF/KOR
    kyc_scorecard = evaluate_kyc_scorecard(inp)

    return min(score, 100), factors, poziom, decyzja, uzasadnienie, wymagany_mpp, kyc_scorecard


def evaluate_kyc_scorecard(inp: RiskEvaluationInput) -> KycScorecard:
    """
    Wylicza punktację profilu ryzyka klienta KYC (0–25 pkt) zgodnie z wytycznymi GIIF i Krajowej Oceny Ryzyka:
    1. Staż rynkowy (0, 2 lub 5 pkt)
    2. Siedziba i zaplecze (0, 1 lub 4 pkt)
    3. Struktura i beneficjent UBO (0, 3 lub 6 pkt)
    4. Branża i kapitał zakładowy (0, 3 lub 6 pkt)
    5. Kanał nawiązania relacji (0 lub 3 pkt)
    """
    # 1. Staż rynkowy
    effective_date = inp.data_wpisu_rejestru or inp.data_rozpoczecia
    days = get_entity_age_days(effective_date)
    if days is not None and days < 180:
        staz_pts = 5
        staz_desc = f"Poniżej 6 miesięcy ({days} dni, od {effective_date}) – wysokie ryzyko spółki typu shelf company lub 'słupa'"
    elif days is not None and 180 <= days < 730:
        staz_pts = 2
        staz_desc = f"Od 6 do 24 miesięcy ({days} dni) – ograniczona historia, standardowy monitoring"
    elif days is not None and days >= 730:
        staz_pts = 0
        staz_desc = f"Powyżej 24 miesięcy ({days} dni, od {effective_date}) – stabilna historia gospodarcza"
    else:
        staz_pts = 2
        staz_desc = "Brak jednoznacznej daty rejestracji – monitoring standardowy"

    # 2. Siedziba i zaplecze
    if inp.adres:
        is_vo, vo_reason = is_virtual_office_or_mass_address(inp.adres)
        if is_vo or inp.address_occurrences_in_db >= 5:
            siedziba_pts = 4
            siedziba_desc = f"Wirtualne biuro / adres masowy ({vo_reason or 'zagęszczenie podmiotów w bazie'})"
        elif any(kw in inp.adres.lower() for kw in ("m.", "lok.", "mieszkania", "/")):
            # Adres z numerem lokalu o charakterze prywatnym lub małego biura
            is_jdg = "jednoosobowa" in (inp.forma_prawna or "").lower() or inp.crbr_status == "NIE_DOTYCZY"
            siedziba_pts = 1 if is_jdg else 0
            siedziba_desc = "Adres prywatny / mieszkaniowy (naturalny dla mikroprzedsiębiorców i JDG)" if is_jdg else "Standardowy lokal handlowy/biurowy"
        else:
            siedziba_pts = 0
            siedziba_desc = "Standardowa siedziba / lokal komercyjny adekwatny do skali"
    else:
        siedziba_pts = 1
        siedziba_desc = "Brak ujawnionego pełnego adresu siedziby"

    # 3. Struktura i UBO
    has_foreign_ubo = False
    if inp.beneficjenci:
        for b in inp.beneficjenci:
            if isinstance(b, dict):
                obyw = str(b.get("obywatelstwo", "")).upper()
            else:
                # Format stringowy np. "Anna Nowak [Obywatelstwo: CYPR]"
                b_str = str(b).upper()
                if "OBYWATELSTWO:" in b_str:
                    obyw = b_str.split("OBYWATELSTWO:")[1].split("]")[0].strip()
                else:
                    obyw = ""
            if obyw and obyw not in ("POLSKA", "PL", "POLSKIE"):
                has_foreign_ubo = True
                break

    if has_foreign_ubo or inp.is_foreign:
        ubo_pts = 6
        ubo_desc = "Nierezydent / podmiot zagraniczny w strukturze UBO lub zagraniczna forma prawna (ryzyko ukrycia beneficjenta)"
    elif inp.crbr_status == "ZWOLNIONY_USTAWOWO_GPW":
        ubo_pts = 0
        ubo_desc = "Spółka publiczna notowana na rynku regulowanym (GPW) – ustawowe zwolnienie z CRBR (art. 58 ustawy AML)"
    elif inp.crbr_status in ("ROZBIEZNOSCI", "BRAK_WPISU"):
        ubo_pts = 3
        ubo_desc = f"Brak spójności lub brak wymaganego wpisu w CRBR ({inp.crbr_status})"
    else:
        ubo_pts = 0
        ubo_desc = "Przejrzysta struktura właścicielska, beneficjent będący rezydentem PL ujawniony w CRBR"

    # 4. Branża i skala obrotów (ocena wg katalogu PKD)
    pkd_cat = PkdRiskCategory.STANDARD
    special_entries = []
    if inp.kody_pkd:
        pkd_cat, special_entries, _ = evaluate_company_pkd_profile(
            inp.kody_pkd,
            forma_prawna=inp.forma_prawna,
        )

    # Flaga kapitału 5 000 zł przy wysokich obrotach (np. transakcja >= 100 000 zł)
    low_capital_high_tx = (
        inp.kapital_zakladowy is not None
        and inp.kapital_zakladowy <= Decimal("5000")
        and inp.kwota_transakcji is not None
        and inp.kwota_transakcji >= Decimal("100000")
    )

    if pkd_cat == PkdRiskCategory.HIGH_RISK_AML or low_capital_high_tx:
        branza_pts = 6
        reasons = []
        if pkd_cat == PkdRiskCategory.HIGH_RISK_AML and special_entries:
            names = [f"{e.code} ({e.name})" for e in special_entries[:2]]
            reasons.append(f"Branża wysokiego ryzyka GIIF/VAT ({'; '.join(names)})")
        if low_capital_high_tx:
            reasons.append(f"Wysoka transakcja ({inp.kwota_transakcji:,.2f} zł) przy minimalnym kapitale zakładowym ({inp.kapital_zakladowy} zł)")
        branza_desc = " | ".join(reasons) if reasons else "Branża wysokiego ryzyka AML"
    elif pkd_cat == PkdRiskCategory.SENSITIVE_VAT:
        branza_pts = 3
        names = [f"{e.code} ({e.name})" for e in special_entries[:2]] if special_entries else []
        branza_desc = f"Branża wrażliwa podatkowo (Załącznik nr 15 VAT / KOR GIIF: {'; '.join(names)})"
    elif pkd_cat == PkdRiskCategory.REGULATED_KNF_SAFE:
        branza_pts = 0
        branza_desc = "Sektor instytucji finansowych i ubezpieczeniowych nadzorowanych przez KNF (zaufanie publiczne)"
    else:
        branza_pts = 0
        branza_desc = "Standardowa branża o niskim profilu ryzyka operacyjnego"

    # 5. Kanał nawiązania relacji
    if inp.kanal_relacji == KanalRelacji.SPOTKANIE_OSOBISTE:
        kanal_pts = 0
        kanal_desc = "Spotkanie osobiste z bezpośrednią weryfikacją tożsamości i umocowania"
    else:
        kanal_pts = 3
        kanal_desc = "Relacja nawiązana zdalnie (online) – art. 43 ust. 2 pkt 3 ustawy AML"

    suma = staz_pts + siedziba_pts + ubo_pts + branza_pts + kanal_pts

    if suma <= 4:
        profil = ProfilRyzykaKyc.NISKIE
        podsumowanie = f"Niski profil ryzyka KYC ({suma} pkt GIIF). Wystarczające standardowe środki bezpieczeństwa finansowego (SDD)."
    elif suma <= 9:
        profil = ProfilRyzykaKyc.STANDARDOWE
        podsumowanie = f"Standardowy profil ryzyka KYC ({suma} pkt GIIF). Wymagany rutynowy monitoring transakcji i aktualności danych."
    elif suma <= 14:
        profil = ProfilRyzykaKyc.PODWYZSZONE_EDD
        podsumowanie = f"Podwyższony profil ryzyka KYC ({suma} pkt GIIF). Wymagane wzmożone środki bezpieczeństwa finansowego (EDD) oraz weryfikacja źródła pochodzenia majątku."
    else:
        profil = ProfilRyzykaKyc.WYSOKIE_NIEAKCEPTOWALNE
        podsumowanie = f"Wysoki / nieakceptowalny profil ryzyka KYC ({suma} pkt GIIF). Wymagana zgoda kierownictwa wyższego szczebla lub odmowa nawiązania relacji gospodarczej."

    return KycScorecard(
        staz_punkty=staz_pts,
        staz_opis=staz_desc,
        siedziba_punkty=siedziba_pts,
        siedziba_opis=siedziba_desc,
        ubo_punkty=ubo_pts,
        ubo_opis=ubo_desc,
        branza_punkty=branza_pts,
        branza_opis=branza_desc,
        kanal_punkty=kanal_pts,
        kanal_opis=kanal_desc,
        suma_punktow=suma,
        profil_ryzyka=profil,
        podsumowanie=podsumowanie,
    )

