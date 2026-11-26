"""Wyliczenia domenowe dla procedury należytej staranności AML i Compliance."""

from enum import Enum


class PoziomRyzykaAML(str, Enum):
    NISKIE = "NISKIE"
    SREDNIE = "SREDNIE"
    WYSOKIE = "WYSOKIE"
    KRYTYCZNE_STOP = "KRYTYCZNE_STOP"


class DecyzjaWspolpracy(str, Enum):
    AKCEPTACJA = "AKCEPTACJA"
    WYMAGA_WYJASNIENIA = "WYMAGA_WYJASNIENIA"
    ODMOWA_WSPOLPRACY_STOP = "ODMOWA_WSPOLPRACY_STOP"


class StatusRachunkuBankowego(str, Enum):
    ZGODNY_BIALA_LISTA = "ZGODNY_BIALA_LISTA"
    BRAK_NA_BIALEJ_LISCIE = "BRAK_NA_BIALEJ_LISCIE"
    BLAD_POLACZENIA_MF = "BLAD_POLACZENIA_MF"      # MF API niedostępne — nie można zweryfikować
    NIE_PODANO = "NIE_PODANO"
    NIE_DOTYCZY_ZAGRANICZNY = "NIE_DOTYCZY_ZAGRANICZNY"


class AnalystStatus(str, Enum):
    AUTO = "AUTO"
    PENDING_EXPLANATION = "PENDING_EXPLANATION"
    APPROVED_AFTER_REVIEW = "APPROVED_AFTER_REVIEW"
    REJECTED = "REJECTED"


class KanalRelacji(str, Enum):
    SPOTKANIE_OSOBISTE = "SPOTKANIE_OSOBISTE"
    ZDALNIE = "ZDALNIE"


class ProfilRyzykaKyc(str, Enum):
    NISKIE = "NISKIE"                  # 0–4 pkt GIIF
    STANDARDOWE = "STANDARDOWE"        # 5–9 pkt GIIF
    PODWYZSZONE_EDD = "PODWYZSZONE_EDD" # 10–14 pkt GIIF (Wzmożone środki bezpieczeństwa)
    WYSOKIE_NIEAKCEPTOWALNE = "WYSOKIE_NIEAKCEPTOWALNE"  # >= 15 pkt GIIF

