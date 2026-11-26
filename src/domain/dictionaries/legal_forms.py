"""Słownik form prawnych, statusów rejestrowych oraz uprawnień do uproszczonych środków CDD (art. 42 ustawy AML).

Zgodnie z:
- Ustawą z dnia 1 marca 2018 r. o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu (art. 42 - SDD, art. 58 - zwolnienia z CRBR),
- Kodeksem Spółek Handlowych (KSH),
- Ustawą - Prawo o stowarzyszeniach,
- Ustawą o sporcie (UKS).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class LegalFormType(str, Enum):
    PUBLIC_COMPANY_GPW = "PUBLIC_COMPANY_GPW"       # Spółka publiczna notowana na rynku regulowanym (GPW)
    STATE_OWNED_ENTERPRISE = "STATE_OWNED"          # Spółka Skarbu Państwa / komunalna
    PUBLIC_SECTOR_UNIT = "PUBLIC_SECTOR_UNIT"       # Jednostka sektora finansów publicznych (szkoła, szpital, urząd)
    COMMERCIAL_COMPANY_KRS = "COMMERCIAL_COMPANY"   # Standardowa spółka handlowa (sp. z o.o., S.A., sp.k., sp.j.)
    SOLE_PROPRIETORSHIP_JDG = "SOLE_PROPRIETORSHIP" # Jednoosobowa działalność gospodarcza (CEIDG)
    NGO_FOUNDATION = "NGO_FOUNDATION"               # Fundacja
    NGO_ASSOCIATION = "NGO_ASSOCIATION"             # Stowarzyszenie (rejestrowe / zwykłe)
    SPORTS_CLUB_UKS = "SPORTS_CLUB_UKS"             # Uczniowski Klub Sportowy (ewidencja starosty)
    FOREIGN_ENTITY = "FOREIGN_ENTITY"               # Podmiot zagraniczny
    OTHER = "OTHER"


@dataclass(frozen=True)
class LegalFormEvaluation:
    form_type: LegalFormType
    display_name: str
    exempt_from_crbr: bool
    crbr_exemption_reason: Optional[str]
    eligible_for_simplified_cdd: bool
    simplified_cdd_basis: Optional[str]
    typical_vat_exempt: bool


def evaluate_legal_form(
    forma_prawna: Optional[str],
    nazwa: Optional[str] = None,
    krs: Optional[str] = None,
    kapital_zakladowy: Optional[float] = None,
) -> LegalFormEvaluation:
    """Określa typ formy prawnej i wynikające z niej przywileje regulacyjne (CRBR, SDD)."""
    forma_norm = (forma_prawna or "").upper().strip()
    nazwa_norm = (nazwa or "").upper().strip()

    # 1. Spółka Akcyjna - weryfikacja spółki publicznej / Skarbu Państwa (np. PZU, Orlen, KGHM)
    is_sa = "SPÓŁKA AKCYJNA" in forma_norm or forma_norm == "SA" or " S.A." in nazwa_norm or " S.A" in nazwa_norm
    if is_sa:
        # Duży kapitał zakładowy (>= 5 mln zł) lub znana spółka giełdowa / udział SP
        is_large_cap = (kapital_zakladowy or 0) >= 5_000_000
        if is_large_cap or any(kw in nazwa_norm for kw in ("POWSZECHNY ZAKŁAD UBEZPIECZEŃ", "ORLEN", "PKO BANK POLSKI", "KGHM", "PGE", "TAURON")):
            return LegalFormEvaluation(
                form_type=LegalFormType.PUBLIC_COMPANY_GPW,
                display_name="Spółka Akcyjna (publiczna / rynek regulowany)",
                exempt_from_crbr=True,
                crbr_exemption_reason="Art. 58 ustawy AML: spółka publiczna notowana na rynku regulowanym nie podlega zgłoszeniu do CRBR",
                eligible_for_simplified_cdd=True,
                simplified_cdd_basis="Art. 42 ust. 1 pkt 1 ustawy AML: spółka dopuszczona do obrotu na rynku regulowanym",
                typical_vat_exempt=False,
            )
        return LegalFormEvaluation(
            form_type=LegalFormType.COMMERCIAL_COMPANY_KRS,
            display_name="Spółka Akcyjna",
            exempt_from_crbr=False,
            crbr_exemption_reason=None,
            eligible_for_simplified_cdd=False,
            simplified_cdd_basis=None,
            typical_vat_exempt=False,
        )

    # 2. Uczniowski Klub Sportowy / Klub sportowy z ewidencji starosty
    if "UCZNIOWSKI KLUB SPORTOWY" in nazwa_norm or "UKS" in nazwa_norm or "KLUB SPORTOWY" in forma_norm:
        return LegalFormEvaluation(
            form_type=LegalFormType.SPORTS_CLUB_UKS,
            display_name="Uczniowski Klub Sportowy (UKS)",
            exempt_from_crbr=True,
            crbr_exemption_reason="Podmiot z ewidencji starosty / brak działalności gospodarczej",
            eligible_for_simplified_cdd=False,
            simplified_cdd_basis=None,
            typical_vat_exempt=True,
        )

    # 3. Fundacje i Stowarzyszenia
    if "FUNDACJA" in forma_norm or "FUNDACJA" in nazwa_norm:
        return LegalFormEvaluation(
            form_type=LegalFormType.NGO_FOUNDATION,
            display_name="Fundacja",
            exempt_from_crbr=False,  # Fundacje w Polsce zgłaszają się do CRBR
            crbr_exemption_reason=None,
            eligible_for_simplified_cdd=False,
            simplified_cdd_basis=None,
            typical_vat_exempt=True,
        )

    if "STOWARZYSZENIE" in forma_norm or "STOWARZYSZENIE" in nazwa_norm:
        return LegalFormEvaluation(
            form_type=LegalFormType.NGO_ASSOCIATION,
            display_name="Stowarzyszenie",
            exempt_from_crbr=False,
            crbr_exemption_reason=None,
            eligible_for_simplified_cdd=False,
            simplified_cdd_basis=None,
            typical_vat_exempt=True,
        )

    # 4. Jednostki sektora publicznego (szpitale, SPZOZ, uczelnie, gminy)
    if any(kw in forma_norm or kw in nazwa_norm for kw in ("SZKOŁA", "UNIWERSYTET", "POLITECHNIKA", "AKADEMIA", "GMINA", "MIASTO", "SZPITAL", "SPZOZ", "URZĄD")):
        return LegalFormEvaluation(
            form_type=LegalFormType.PUBLIC_SECTOR_UNIT,
            display_name="Jednostka sektora finansów publicznych",
            exempt_from_crbr=True,
            crbr_exemption_reason="Jednostka sektora finansów publicznych",
            eligible_for_simplified_cdd=True,
            simplified_cdd_basis="Art. 42 ust. 1 pkt 2 ustawy AML: jednostka sektora finansów publicznych",
            typical_vat_exempt=True,
        )

    # 5. JDG (Jednoosobowa działalność gospodarcza)
    if "JEDNOOSOBOWA" in forma_norm or "FIZYCZNA" in forma_norm or "CEIDG" in forma_norm:
        return LegalFormEvaluation(
            form_type=LegalFormType.SOLE_PROPRIETORSHIP_JDG,
            display_name="Jednoosobowa Działalność Gospodarcza (JDG)",
            exempt_from_crbr=True,
            crbr_exemption_reason="Osoby fizyczne prowadzące JDG nie podlegają obowiązkowi zgłoszeń do CRBR (weryfikacja przez CEIDG)",
            eligible_for_simplified_cdd=False,
            simplified_cdd_basis=None,
            typical_vat_exempt=False,
        )

    # 6. Spółki handlowe z o.o., sp.k., sp.j.
    return LegalFormEvaluation(
        form_type=LegalFormType.COMMERCIAL_COMPANY_KRS,
        display_name=forma_prawna or "Spółka Handlowa (KRS)",
        exempt_from_crbr=False,
        crbr_exemption_reason=None,
        eligible_for_simplified_cdd=False,
        simplified_cdd_basis=None,
        typical_vat_exempt=False,
    )
