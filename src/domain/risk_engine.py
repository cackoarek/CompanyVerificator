"""Deterministyczny silnik oceny ryzyka AML / Compliance i należytej staranności."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Tuple

from src.config import PAYMENT_THRESHOLD_PLN
from src.domain.enums import DecyzjaWspolpracy, PoziomRyzykaAML, StatusRachunkuBankowego
from src.domain.models import RiskFactor, SanctionHit

# Wybrane kody PKD wymagające wzmożonej uwagi AML (finanse, krypto, nieruchomości, obrót metalami/paliwami, hazard)
HIGH_RISK_PKD_PREFIXES = (
    "46.71",  # Sprzedaż hurtowa paliw
    "47.30",  # Sprzedaż detaliczna paliw
    "64.",    # Finansowa działalność usługowa
    "66.",    # Działalność wspomagająca usługi finansowe
    "68.",    # Obsługa rynku nieruchomości
    "92.",    # Działalność związana z grami losowymi i zakładami wzajemnymi
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
    kody_pkd: Optional[List[str]] = None
    iban_invalid: bool = False


def _is_young_entity(data_rozpoczecia: Optional[str], months_threshold: int = 6) -> bool:
    if not data_rozpoczecia:
        return False
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(data_rozpoczecia[:10], fmt[: len(data_rozpoczecia[:10])] if "T" not in fmt else fmt)
            age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - dt).days
            return 0 <= age_days < months_threshold * 30
        except ValueError:
            continue
    return False


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
        factors.append(
            RiskFactor(
                code="SANCTIONS_HIT",
                title=f"Trafienie na liście sankcyjnej ({len(exact_or_high_sanctions)})",
                severity=PoziomRyzykaAML.KRYTYCZNE_STOP,
                points=100,
                legal_basis="Ustawa z 13.04.2022 r. (Dz.U. 2022 poz. 835) / Rozporządzenia Rady UE",
                recommendation="BEZWZGLĘDNA BLOKADA współpracy i zamrożenie/zakaz udostępniania środków.",
            )
        )
    elif possible_sanctions:
        score += 45
        factors.append(
            RiskFactor(
                code="SANCTIONS_POSSIBLE_MATCH",
                title=f"Potencjalna zbieżność z listą sankcyjną ({len(possible_sanctions)})",
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

    # 3. Status rejestru (wykreślony / zawieszony / upadłość / likwidacja)
    if inp.upadlosc_lub_likwidacja:
        score += 60
        factors.append(
            RiskFactor(
                code="INSOLVENCY_OR_LIQUIDATION",
                title="Podmiot w stanie likwidacji, upadłości lub restrukturyzacji",
                severity=PoziomRyzykaAML.WYSOKIE,
                points=60,
                legal_basis="Należyta staranność VAT (metodyka MF)",
                recommendation="Wymagana pogłębiona weryfikacja możliwości realizacji świadczenia oraz umocowania syndyka/likwidatora.",
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

    # 6. Status VAT / VIES
    if not inp.is_foreign and not inp.blad_polaczenia:
        if not inp.platnik_vat_czynny and "zwolnion" not in (inp.status_vat or "").lower():
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
    if _is_young_entity(inp.data_rozpoczecia):
        score += 15
        factors.append(
            RiskFactor(
                code="YOUNG_ENTITY",
                title=f"Podmiot działa krócej niż 6 miesięcy (od {inp.data_rozpoczecia})",
                severity=PoziomRyzykaAML.SREDNIE,
                points=15,
                legal_basis="Metodyka MF należytej staranności w VAT",
                recommendation="Zweryfikuj faktyczne zaplecze techniczne, stronę WWW i referencje nowego kontrahenta.",
            )
        )

    if inp.kody_pkd:
        matched_pkd = [p for p in inp.kody_pkd if any(p.startswith(pref) for pref in HIGH_RISK_PKD_PREFIXES)]
        if matched_pkd:
            score += 15
            factors.append(
                RiskFactor(
                    code="HIGH_RISK_PKD",
                    title=f"Branża podwyższonego ryzyka AML/VAT (PKD: {', '.join(matched_pkd[:3])})",
                    severity=PoziomRyzykaAML.SREDNIE,
                    points=15,
                    legal_basis="Art. 33 i 43 ustawy AML / zał. nr 15 ustawy o VAT",
                    recommendation="Zastosuj standardową lub wzmożoną weryfikację celu transakcji oraz MPP.",
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

    return min(score, 100), factors, poziom, decyzja, uzasadnienie, wymagany_mpp
