"""Deterministyczne walidatory identyfikatorów podatkowych, rejestrowych i bankowych."""

import re
from dataclasses import dataclass
from typing import Optional, Set, Tuple

_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)
_REGON_9_WEIGHTS = (8, 9, 2, 3, 4, 5, 6, 7)
_REGON_14_WEIGHTS = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)

EU_VAT_PREFIXES: Set[str] = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR",
    "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PT", "RO", "SE",
    "SI", "SK", "XI",
}
NON_EU_PREFIXES: Set[str] = {"GB", "CH", "NO", "US", "UA"}

# Syntetyczne NIP-y testowe wykorzystywane wyłącznie gdy allow_test_nips=True
TEST_NIPS: Set[str] = {
    "7770001122",
    "1111111111",
    "2222222222",
    "1234567890",
}


@dataclass(frozen=True)
class IdentifierClassification:
    """Wynik klasyfikacji identyfikatora wpisanego przez użytkownika."""

    raw: str
    normalized: str
    kind: str  # NIP | KRS | EU_VAT | FOREIGN_TAX_ID | INVALID
    country_code: str
    is_valid: bool
    error: str = ""


def clean_nip(raw_nip: Optional[str]) -> str:
    """Oczyszcza polski NIP ze spacji, myślników i prefiksu PL."""
    if not raw_nip:
        return ""
    clean = re.sub(r"[\s\-\.]", "", raw_nip.strip()).upper()
    if clean.startswith("PL") and len(clean) == 12 and clean[2:].isdigit():
        return clean[2:]
    return re.sub(r"[^0-9]", "", clean)


def validate_nip(raw_nip: Optional[str], allow_test_nips: bool = False) -> Tuple[bool, str]:
    """Weryfikuje sumę kontrolną polskiego NIP (modulo 11)."""
    nip = clean_nip(raw_nip)
    if not nip:
        return False, "NIP nie może być pusty"
    if len(nip) != 10:
        return False, f"NIP musi składać się dokładnie z 10 cyfr (podano: {len(nip)})"
    if allow_test_nips and nip in TEST_NIPS:
        return True, ""

    digits = [int(c) for c in nip]
    weighted_sum = sum(w * d for w, d in zip(_NIP_WEIGHTS, digits[:9]))
    control_digit = weighted_sum % 11
    if control_digit == 10:
        return False, "Nieprawidłowa suma kontrolna NIP (reszta modulo 11 wynosi 10)"
    if control_digit != digits[9]:
        return False, f"Błędna cyfra kontrolna NIP: oczekiwano {control_digit}, otrzymano {digits[9]}"
    return True, ""


def clean_krs(raw_krs: Optional[str]) -> str:
    """Oczyszcza i uzupełnia zerami wiodącymi numer KRS do 10 cyfr."""
    if not raw_krs:
        return ""
    digits = re.sub(r"[^0-9]", "", raw_krs.strip())
    if 1 <= len(digits) <= 10:
        return digits.zfill(10)
    return digits


def validate_krs(raw_krs: Optional[str]) -> Tuple[bool, str]:
    """Weryfikuje format numeru KRS (10 cyfr, nie same zera)."""
    krs = clean_krs(raw_krs)
    if not krs:
        return False, "KRS nie może być pusty"
    if len(krs) != 10 or not krs.isdigit() or krs == "0000000000":
        return False, "KRS musi składać się z 10 cyfr (np. 0000123456)"
    return True, ""


def clean_regon(raw_regon: Optional[str]) -> str:
    """Oczyszcza numer REGON."""
    if not raw_regon:
        return ""
    return re.sub(r"[^0-9]", "", raw_regon.strip())


def validate_regon(raw_regon: Optional[str]) -> Tuple[bool, str]:
    """Weryfikuje sumę kontrolną REGON (9 lub 14 cyfr)."""
    regon = clean_regon(raw_regon)
    if not regon:
        return False, "REGON nie może być pusty"
    if len(regon) not in (9, 14):
        return False, f"REGON musi mieć 9 lub 14 cyfr (podano: {len(regon)})"

    digits = [int(c) for c in regon]
    sum_9 = sum(w * d for w, d in zip(_REGON_9_WEIGHTS, digits[:8]))
    control_9 = sum_9 % 11
    if control_9 == 10:
        control_9 = 0
    if control_9 != digits[8]:
        return False, f"Błędna cyfra kontrolna REGON-9: oczekiwano {control_9}, otrzymano {digits[8]}"

    if len(regon) == 14:
        sum_14 = sum(w * d for w, d in zip(_REGON_14_WEIGHTS, digits[:13]))
        control_14 = sum_14 % 11
        if control_14 == 10:
            control_14 = 0
        if control_14 != digits[13]:
            return False, f"Błędna cyfra kontrolna REGON-14: oczekiwano {control_14}, otrzymano {digits[13]}"
    return True, ""


def clean_nrb(raw_account: Optional[str]) -> str:
    """Oczyszcza polski numer rachunku (NRB) ze spacji i prefiksu PL."""
    if not raw_account:
        return ""
    clean = re.sub(r"[^0-9A-Za-z]", "", raw_account.strip()).upper()
    if clean.startswith("PL"):
        clean = clean[2:]
    return clean


def validate_iban(raw_account: Optional[str]) -> Tuple[bool, str]:
    """
    Weryfikuje numer rachunku bankowego (polski NRB 26 cyfr lub międzynarodowy IBAN)
    algorytmem ISO 7064 Modulo 97-10.
    """
    if not raw_account or not raw_account.strip():
        return False, "Numer rachunku nie może być pusty"

    compact = re.sub(r"[^0-9A-Za-z]", "", raw_account.strip()).upper()
    if compact.isdigit():
        if len(compact) != 26:
            return False, f"Polski NRB musi mieć 26 cyfr (podano: {len(compact)})"
        iban = f"PL{compact}"
    else:
        if len(compact) < 15 or len(compact) > 34 or not re.match(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$", compact):
            return False, "Nieprawidłowy format numeru IBAN"
        iban = compact

    rearranged = iban[4:] + iban[:4]
    numeric_str = "".join(str(ord(ch) - 55) if ch.isalpha() else ch for ch in rearranged)
    if int(numeric_str) % 97 != 1:
        return False, "Nieprawidłowa suma kontrolna rachunku bankowego (Modulo 97-10)"
    return True, ""


def classify_identifier(raw_identifier: Optional[str], allow_test_nips: bool = False) -> IdentifierClassification:
    """Rozpoznaje typ identyfikatora (NIP, KRS, VAT-UE, zagraniczny Tax ID)."""
    raw = (raw_identifier or "").strip()
    compact = re.sub(r"[\s\-\.]", "", raw).upper()

    if not compact:
        return IdentifierClassification(raw=raw, normalized="", kind="INVALID", country_code="", is_valid=False, error="Pusty identyfikator")

    # Jawne wskazanie KRS: np. "KRS 0000123456" lub "KRS:0000123456"
    if compact.startswith("KRS:") or compact.startswith("KRS"):
        krs_candidate = compact.replace("KRS:", "").replace("KRS", "")
        ok, err = validate_krs(krs_candidate)
        return IdentifierClassification(
            raw=raw,
            normalized=clean_krs(krs_candidate),
            kind="KRS" if ok else "INVALID",
            country_code="PL",
            is_valid=ok,
            error=err,
        )

    # Polski NIP z lub bez prefiksu PL
    if compact.startswith("PL") and len(compact) == 12 and compact[2:].isdigit():
        ok, err = validate_nip(compact[2:], allow_test_nips=allow_test_nips)
        return IdentifierClassification(
            raw=raw,
            normalized=compact[2:],
            kind="NIP" if ok else "INVALID",
            country_code="PL",
            is_valid=ok,
            error=err,
        )

    # Inny prefiks kraju (VAT-UE lub poza UE)
    prefix = compact[:2]
    if prefix.isalpha() and len(compact) >= 5:
        if prefix in EU_VAT_PREFIXES:
            return IdentifierClassification(
                raw=raw,
                normalized=compact,
                kind="EU_VAT",
                country_code=prefix,
                is_valid=bool(re.match(r"^[A-Z]{2}[A-Z0-9]{2,14}$", compact)),
                error="" if re.match(r"^[A-Z]{2}[A-Z0-9]{2,14}$", compact) else "Nieprawidłowy format VAT-UE",
            )
        if prefix in NON_EU_PREFIXES:
            return IdentifierClassification(
                raw=raw,
                normalized=compact,
                kind="FOREIGN_TAX_ID",
                country_code=prefix,
                is_valid=True,
            )

    # Sam numer 10-cyfrowy -> domyślnie traktujemy jako polski NIP
    if compact.isdigit() and len(compact) == 10:
        ok, err = validate_nip(compact, allow_test_nips=allow_test_nips)
        return IdentifierClassification(
            raw=raw,
            normalized=compact,
            kind="NIP" if ok else "INVALID",
            country_code="PL",
            is_valid=ok,
            error=err,
        )

    return IdentifierClassification(
        raw=raw,
        normalized=compact,
        kind="INVALID",
        country_code="",
        is_valid=False,
        error="Nierozpoznany lub nieprawidłowy identyfikator (podaj 10-cyfrowy NIP, KRS:<10 cyfr> lub VAT-UE np. DE123456789)",
    )
