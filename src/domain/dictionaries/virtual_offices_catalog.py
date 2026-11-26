"""Katalog i baza wzorców wirtualnych biur, centrów coworkingowych i adresów masowej rejestracji w Polsce."""

import re
from typing import List, Optional, Tuple

VIRTUAL_OFFICE_KEYWORDS = (
    "wirtualne biuro",
    "wirtualny adres",
    "biuro wirtualne",
    "cowork",
    "coworking",
    "business center",
    "business centre",
    "centrum biznesowe",
    "ready office",
    "serviced office",
    "office hub",
    "hub biznesowy",
    "smart office",
    "biuro na godziny",
    "adres do rejestracji",
    "adres dla firmy",
    "skrytka pocztowa",
)

# Adresy masowej rejestracji podmiotów w największych ośrodkach gospodarczych
KNOWN_MASS_REGISTRATION_PATTERNS = [
    # Warszawa - Centrum / Wola / Mokotów
    r"złota\s+59",
    r"chmielna\s+2",
    r"chmielna\s+85",
    r"jerozolimskie\s+85",
    r"jerozolimskie\s+123",
    r"jerozolimskie\s+142",
    r"mazowiecka\s+11",
    r"hoża\s+86",
    r"nowogrodzka\s+31",
    r"nowogrodzka\s+50",
    r"nowy\s+świat\s+33",
    r"jana\s+pawła\s+ii\s+27",
    r"jana\s+pawła\s+ii\s+43",
    r"jana\s+pawła\s+ii\s+61",
    r"grzybowska\s+87",
    r"grzybowska\s+2",
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
    r"wronia\s+31",
    r"towarowa\s+28",
    r"piękna\s+20",
    r"tamka\s+16",
    # Kraków
    r"mogilska\s+43",
    r"mogilska\s+65",
    r"wielicka\s+28",
    r"pawia\s+9",
    r"szlak\s+77",
    r"karmelicka\s+9",
    r"rynek\s+główny\s+28",
    r"św\.\s*filipa\s+23",
    r"starowiślna\s+1",
    r"kalwaryjska\s+69",
    # Wrocław
    r"ruska\s+61",
    r"ruska\s+51",
    r"św\.\s*mikołaja\s+8",
    r"piłsudskiego\s+74",
    r"legnicka\s+52",
    r"powstańców\s+śląskich\s+9",
    r"powstańców\s+śląskich\s+5",
    r"sucha\s+3",
    r"rynek\s+60",
    # Poznań
    r"półwiejska\s+42",
    r"towarowa\s+35",
    r"św\.\s*marcin\s+29",
    r"roosevelta\s+22",
    r"matyi\s+8",
    r"marcelińska\s+90",
    # Gdańsk / Gdynia / Sopot (Trójmiasto)
    r"grunwaldzka\s+411",
    r"grunwaldzka\s+472",
    r"lęborska\s+3",
    r"al\.\s*zwycięstwa\s+241",
    r"świętojańska\s+43",
    r"śląska\s+35",
    # Katowice / Śląsk
    r"sokolska\s+65",
    r"korfantego\s+2",
    r"francuska\s+34",
    r"mikołowska\s+100",
    # Łódź
    r"piotrkowska\s+115",
    r"piotrkowska\s+173",
    r"kościuszki\s+103",
    r"narutowicza\s+40",
    # Szczecin, Lublin, Rzeszów
    r"niepodległości\s+22",
    r"lipowa\s+18",
    r"krakowska\s+15",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in KNOWN_MASS_REGISTRATION_PATTERNS]


def detect_virtual_office(adres: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Dokonuje detekcji wirtualnego biura lub adresu masowej rejestracji."""
    if not adres or not adres.strip():
        return False, None

    normalized = " ".join(adres.lower().replace(",", " ").replace(".", " ").split())

    # 1. Słowa kluczowe
    for kw in VIRTUAL_OFFICE_KEYWORDS:
        if kw in normalized:
            return True, f"Oznaczenie wirtualnego biura / coworkingu w adresie: '{kw}'"

    # 2. Wzorce masowej rejestracji
    for pat in COMPILED_PATTERNS:
        if pat.search(normalized):
            matched = pat.pattern.replace("\\s+", " ").replace("\\.", ".")
            return True, f"Znany adres masowej rejestracji spółek / centrum biurowe ({matched})"

    return False, None
