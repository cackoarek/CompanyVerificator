"""Moduł detekcji wirtualnych biur, coworkingów i adresów masowej rejestracji."""

import re
from typing import Optional, Set, Tuple

# Słowa i frazy kluczowe w nazwach lokali, adresach lub siedzibach
VIRTUAL_OFFICE_KEYWORDS = (
    "wirtualne biuro",
    "wirtualny adres",
    "biuro wirtualne",
    "cowork",
    "coworking",
    "business center",
    "centrum biznesowe",
    "ready office",
    "serviced office",
    "office hub",
    "hub biznesowy",
    "smart office",
    "biuro na godziny",
    "adres do rejestracji",
)

# Znane w praktyce compliance / AML adresy masowej rejestracji w Polsce (ulica i numer w znormalizowanej postaci)
# Źródło: Analiza wpisów KRS/CEIDG z rejestracją ponad 100+ podmiotów pod jednym adresem / lokale wirtualnych biur
KNOWN_MASS_REGISTRATION_PATTERNS = [
    # Warszawa
    r"złota\s+59",
    r"chmielna\s+2",
    r"chmielna\s+85",
    r"jerozolimskie\s+85",
    r"jerozolimskie\s+123",
    r"mazowiecka\s+11",
    r"hoża\s+86",
    r"nowogrodzka\s+31",
    r"nowogrodzka\s+50",
    r"jana\s+pawła\s+ii\s+27",
    r"jana\s+pawła\s+ii\s+43",
    r"grzybowska\s+87",
    r"prosta\s+20",
    r"prosta\s+68",
    r"twarda\s+18",
    r"żurawia\s+71",
    r"mokotowska\s+1",
    r"marynarska\s+15",
    r"postępu\s+14",
    r"domaniewska\s+37",
    r"domaniewska\s+47",
    r"wołoska\s+5",
    # Kraków
    r"mogilska\s+43",
    r"mogilska\s+65",
    r"wielicka\s+28",
    r"pawia\s+9",
    r"szlak\s+77",
    r"karmelicka\s+9",
    r"rynek\s+główny\s+28",
    # Wrocław
    r"ruska\s+61",
    r"ruska\s+51",
    r"św\.\s*mikołaja\s+8",
    r"piłsudskiego\s+74",
    r"legnicka\s+52",
    r"powstańców\s+śląskich\s+9",
    # Poznań
    r"półwiejska\s+42",
    r"towarowa\s+35",
    r"św\.\s*marcin\s+29",
    r"roosevelta\s+22",
    # Gdańsk / Trójmiasto
    r"grunwaldzka\s+411",
    r"grunwaldzka\s+472",
    r"lęborska\s+3",
    r"al\.\s*zwycięstwa\s+241",
    # Katowice
    r"sokolska\s+65",
    r"korfantego\s+2",
    r"francuska\s+34",
    # Łódź
    r"piotrkowska\s+115",
    r"piotrkowska\s+173",
    r"kościuszki\s+103",
]

from src.domain.dictionaries.virtual_offices_catalog import (
    KNOWN_MASS_REGISTRATION_PATTERNS,
    VIRTUAL_OFFICE_KEYWORDS,
    detect_virtual_office,
)

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in KNOWN_MASS_REGISTRATION_PATTERNS]


def is_virtual_office_or_mass_address(adres: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Sprawdza, czy podany adres wskazuje na wirtualne biuro lub adres masowej rejestracji podmiotów.
    Zwraca: (czy_wykryto, uzasadnienie)
    """
    return detect_virtual_office(adres)


def check_address_density_in_db(adres: Optional[str], db_records_count: int) -> Tuple[bool, Optional[str]]:
    """
    Sprawdza, czy ten sam adres pojawia się wielokrotnie w wewnętrznej bazie weryfikacji.
    """
    if db_records_count >= 5:
        return True, f"Pod tym samym adresem zarejestrowano w systemie już {db_records_count} różnych podmiotów (zagęszczenie podmiotów)"
    return False, None
