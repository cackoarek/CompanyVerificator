"""Katalog kodów PKD (Polska Klasyfikacja Działalności) dla procedur AML, KYC i należytej staranności VAT.

Sklasyfikowany zgodnie z:
1. Krajową Oceną Ryzyka (KOR GIIF 2023/2024),
2. Załącznikiem nr 15 do ustawy o VAT (obowiązkowy Mechanizm Podzielonej Płatności - MPP),
3. Metodyką Ministerstwa Finansów w zakresie należytej staranności w VAT,
4. Sektorem podmiotów regulowanych i nadzorowanych przez KNF (Komisja Nadzoru Finansowego).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class PkdRiskCategory(str, Enum):
    """Kategoria ryzyka branżowego PKD."""
    REGULATED_KNF_SAFE = "REGULATED_KNF_SAFE"  # Podmioty regulowane/zaufania (banki, ubezpieczyciele, domy maklerskie)
    HIGH_RISK_AML = "HIGH_RISK_AML"            # Wysokie ryzyko AML (krypto, złom, paliwa, hazard, odpady)
    SENSITIVE_VAT = "SENSITIVE_VAT"            # Branże wrażliwe podatkowo (budownictwo, transport, doradztwo, agencje, e-commerce)
    STANDARD = "STANDARD"                      # Działalność standardowa


@dataclass(frozen=True)
class PkdEntry:
    code: str
    name: str
    category: PkdRiskCategory
    description: str
    requires_mpp: bool = False
    legal_basis: str = ""


# 1. Kody podmiotów regulowanych i nadzorowanych przez KNF (Zaufane, Niskie ryzyko bazowe)
REGULATED_KNF_PKD: Dict[str, str] = {
    "64.11.Z": "Działalność banku centralnego",
    "64.19.Z": "Pozostałe pośrednictwo pieniężne (Banki komercyjne i spółdzielcze)",
    "64.30.Z": "Działalność trustów, funduszów i podobnych instytucji finansowych (TFI, FIO, FIZ)",
    "65.11.Z": "Ubezpieczenia na życie",
    "65.12.Z": "Pozostałe ubezpieczenia osobowe oraz ubezpieczenia majątkowe",
    "65.20.Z": "Reasekuracja",
    "65.30.Z": "Fundusze emerytalne (PTE, OFE)",
    "66.11.Z": "Zarządzanie rynkami finansowymi (GPW, KDPW)",
}

# 2. Kody wysokiego ryzyka AML wg KOR GIIF i Załącznika 15 VAT (6 pkt KYC / Filar 4)
HIGH_RISK_AML_PKD: Dict[str, Tuple[str, bool, str]] = {
    # format: opis, czy_mpp, podstawa_prawna
    "46.71.Z": ("Sprzedaż hurtowa paliw i produktów pochodnych", True, "Załącznik nr 15 ustawy o VAT / KOR GIIF"),
    "47.30.Z": ("Sprzedaż detaliczna paliw do pojazdów silnikowych na stacjach paliw", True, "Załącznik nr 15 ustawy o VAT / KOR GIIF"),
    "46.72.Z": ("Sprzedaż hurtowa metali i rud metali (stal, miedź, wyroby hutnicze)", True, "Załącznik nr 15 ustawy o VAT / Karuzele VAT"),
    "46.77.Z": ("Sprzedaż hurtowa odpadów i złomu", True, "Załącznik nr 15 ustawy o VAT (złom) / KOR GIIF"),
    "38.32.Z": ("Odzysk surowców z materiałów segregowanych (złom i surowce wtórne)", True, "Załącznik nr 15 ustawy o VAT"),
    "24.41.Z": ("Produkcja metali szlachetnych (złoto, srebro, platyna)", True, "Załącznik nr 15 ustawy o VAT / AML"),
    "24.42.B": ("Produkcja aluminium hutniczego i wyrobów", True, "Załącznik nr 15 ustawy o VAT"),
    "32.12.Z": ("Produkcja wyrobów jubilerskich i podobnych", True, "Załącznik nr 15 ustawy o VAT"),
    "46.51.Z": ("Sprzedaż hurtowa komputerów, urządzeń peryferyjnych i oprogramowania (elektronika)", True, "Załącznik nr 15 ustawy o VAT (karuzele elektroniki)"),
    "46.52.Z": ("Sprzedaż hurtowa sprzętu elektronicznego i telekomunikacyjnego oraz części", True, "Załącznik nr 15 ustawy o VAT"),
    "26.11.Z": ("Produkcja elementów elektronicznych", True, "Załącznik nr 15 ustawy o VAT"),
    "26.20.Z": ("Produkcja komputerów i urządzeń peryferyjnych", True, "Załącznik nr 15 ustawy o VAT"),
    "26.30.Z": ("Produkcja sprzętu (tele)komunikacyjnego (w tym smartfony)", True, "Załącznik nr 15 ustawy o VAT"),
    "92.00.Z": ("Działalność związana z grami losowymi i zakładami wzajemnymi (hazard)", False, "Ustawa o grach hazardowych / KOR GIIF"),
    "66.12.Z": ("Działalność maklerska oraz kantory wymiany walut (obrót gotówkowy)", False, "KOR GIIF / Prawo dewizowe"),
    # Działalność w zakresie walut wirtualnych (krypto) klasyfikowana w 64.19 / 64.99 / 66.19
}

# 3. Kody branż wrażliwych wg KOR GIIF i ustawy o VAT (3 pkt KYC / Filar 4)
SENSITIVE_VAT_PKD: Dict[str, Tuple[str, bool, str]] = {
    # Budownictwo i podwykonawstwo (Załącznik nr 15 poz. 98-144)
    "41.10.Z": ("Realizacja projektów budowlanych związanych ze wznoszeniem budynków", False, "KOR GIIF"),
    "41.20.Z": ("Roboty budowlane związane ze wznoszeniem budynków mieszkalnych i niemieszkalnych", True, "Załącznik nr 15 ustawy o VAT"),
    "42.11.Z": ("Roboty związane z budową dróg i autostrad", True, "Załącznik nr 15 ustawy o VAT"),
    "42.21.Z": ("Roboty związane z budową rurociągów przesyłowych i sieci rozdzielczych", True, "Załącznik nr 15 ustawy o VAT"),
    "43.11.Z": ("Rozbiórka i burzenie obiektów budowlanych", True, "Załącznik nr 15 ustawy o VAT"),
    "43.12.Z": ("Przygotowanie terenu pod budowę", True, "Załącznik nr 15 ustawy o VAT"),
    "43.21.Z": ("Wykonywanie instalacji elektrycznych", True, "Załącznik nr 15 ustawy o VAT"),
    "43.22.Z": ("Wykonywanie instalacji wodno-kanalizacyjnych, cieplnych, gazowych i klimatyzacyjnych", True, "Załącznik nr 15 ustawy o VAT"),
    "43.99.Z": ("Pozostałe specjalistyczne roboty budowlane", True, "Załącznik nr 15 ustawy o VAT"),
    # Transport i spedycja
    "49.41.Z": ("Transport drogowy towarów", False, "KOR GIIF Filar 4"),
    "52.29.C": ("Działalność pozostałych agencji transportowych (spedycja)", False, "KOR GIIF Filar 4"),
    # Usługi niematerialne (ryzyko pustych faktur kosztowych wg MF)
    "70.22.Z": ("Pozostałe doradztwo w zakresie prowadzenia działalności gospodarczej i zarządzania", False, "Metodyka należytej staranności MF"),
    "73.11.Z": ("Działalność agencji reklamowych", False, "Metodyka należytej staranności MF"),
    "73.12.C": ("Pośrednictwo w sprzedaży miejsca na cele reklamowe w mediach elektronicznych (Internet)", False, "Metodyka należytej staranności MF"),
    # E-commerce i części motoryzacyjne
    "47.91.Z": ("Sprzedaż detaliczna prowadzona przez domy sprzedaży wysyłkowej lub Internet", False, "KOR GIIF / Załącznik nr 15"),
    "45.31.Z": ("Sprzedaż hurtowa części i akcesoriów do pojazdów samochodowych", True, "Załącznik nr 15 ustawy o VAT"),
    "45.32.Z": ("Sprzedaż detaliczna części i akcesoriów do pojazdów samochodowych", True, "Załącznik nr 15 ustawy o VAT"),
    # Nieruchomości
    "68.10.Z": ("Kupno i sprzedaż nieruchomości na własny rachunek", False, "KOR GIIF"),
    "68.31.Z": ("Pośrednictwo w obrocie nieruchomościami", False, "Ustawa AML (instytucje obowiązane)"),
}


def classify_pkd_code(pkd: str, company_name: Optional[str] = None) -> PkdEntry:
    """Klasyfikuje pojedynczy kod PKD pod kątem ryzyka AML/VAT oraz wymogu MPP."""
    clean = pkd.strip().upper()

    # 1. Sprawdzenie sektora KNF / regulowanego
    if clean in REGULATED_KNF_PKD:
        return PkdEntry(
            code=clean,
            name=REGULATED_KNF_PKD[clean],
            category=PkdRiskCategory.REGULATED_KNF_SAFE,
            description="Sektor instytucji finansowych i ubezpieczeniowych nadzorowanych przez KNF",
            requires_mpp=False,
            legal_basis="Nadzór KNF / Ustawa Prawo bankowe / Ustawa o działalności ubezpieczeniowej",
        )

    # 2. Sprawdzenie wysokiego ryzyka AML
    if clean in HIGH_RISK_AML_PKD:
        name, mpp, basis = HIGH_RISK_AML_PKD[clean]
        return PkdEntry(
            code=clean,
            name=name,
            category=PkdRiskCategory.HIGH_RISK_AML,
            description=f"Branża wysokiego ryzyka AML/VAT ({name})",
            requires_mpp=mpp,
            legal_basis=basis,
        )
    # Prefiksy wysokiego ryzyka (np. 46.71, 46.77, 24.41, 38.32, 92.)
    for pref in ("46.71", "46.77", "38.32", "24.41", "24.42", "46.72", "46.51", "46.52", "26.11", "92."):
        if clean.startswith(pref):
            return PkdEntry(
                code=clean,
                name=f"Branża wysokiego ryzyka (prefiks {pref})",
                category=PkdRiskCategory.HIGH_RISK_AML,
                description="Branża podwyższonego ryzyka AML/VAT",
                requires_mpp=True,
                legal_basis="Załącznik nr 15 ustawy o VAT / KOR GIIF",
            )

    # 3. Sprawdzenie branż wrażliwych (SENSITIVE_VAT)
    if clean in SENSITIVE_VAT_PKD:
        name, mpp, basis = SENSITIVE_VAT_PKD[clean]
        return PkdEntry(
            code=clean,
            name=name,
            category=PkdRiskCategory.SENSITIVE_VAT,
            description=f"Branża wrażliwa podatkowo/operacyjnie ({name})",
            requires_mpp=mpp,
            legal_basis=basis,
        )
    for pref in ("41.", "42.", "43.", "49.41", "52.29", "70.22", "73.11", "47.91", "45.31", "45.32", "68."):
        if clean.startswith(pref):
            return PkdEntry(
                code=clean,
                name=f"Branża wrażliwa (prefiks {pref})",
                category=PkdRiskCategory.SENSITIVE_VAT,
                description="Branża wrażliwa podatkowo (budownictwo, transport, doradztwo, motoryzacja, e-commerce)",
                requires_mpp=pref in ("41.", "42.", "43.", "45.31", "45.32"),
                legal_basis="Załącznik nr 15 ustawy o VAT / Metodyka MF",
            )

    # 4. Standard
    return PkdEntry(
        code=clean,
        name="Działalność gospodarcza standardowa",
        category=PkdRiskCategory.STANDARD,
        description="Standardowy profil branżowy",
        requires_mpp=False,
    )


def evaluate_company_pkd_profile(
    kody_pkd: Optional[List[str]],
    forma_prawna: Optional[str] = None,
    nazwa: Optional[str] = None,
) -> Tuple[PkdRiskCategory, List[PkdEntry], bool]:
    """Dokonuje całościowej oceny profilu branżowego podmiotu na podstawie listy kodów PKD.

    Zwraca: (Ogólna kategoria ryzyka, lista wykrytych pozycji specjalnych, czy wymagany MPP)
    """
    if not kody_pkd:
        return PkdRiskCategory.STANDARD, [], False

    classified = [classify_pkd_code(p, nazwa) for p in kody_pkd]

    # Sprawdź czy to podmiot regulowany KNF (ubezpieczyciel, bank)
    is_knf = any(e.category == PkdRiskCategory.REGULATED_KNF_SAFE for e in classified)
    if is_knf:
        # Jeśli podmiot jest ubezpieczycielem lub bankiem, inne kody finansowe nie podnoszą ryzyka
        return PkdRiskCategory.REGULATED_KNF_SAFE, [e for e in classified if e.category == PkdRiskCategory.REGULATED_KNF_SAFE], False

    high_risk_entries = [e for e in classified if e.category == PkdRiskCategory.HIGH_RISK_AML]
    sensitive_entries = [e for e in classified if e.category == PkdRiskCategory.SENSITIVE_VAT]
    requires_mpp = any(e.requires_mpp for e in classified)

    if high_risk_entries:
        return PkdRiskCategory.HIGH_RISK_AML, high_risk_entries, requires_mpp
    if sensitive_entries:
        return PkdRiskCategory.SENSITIVE_VAT, sensitive_entries, requires_mpp

    return PkdRiskCategory.STANDARD, [], False
