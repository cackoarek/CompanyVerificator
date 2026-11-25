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
