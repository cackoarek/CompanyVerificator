"""Wyliczenia domenowe dla procedury należytej staranności AML i Compliance."""

from enum import Enum


class PoziomRyzykaAML(str, Enum):
    NISKIE = "NISKIE"
    SREDNIE = "SREDNIE"
    WYSOKIE = "WYSOKIE"
    KRYTYCZNE_STOP = "KRYTYCZNE_STOP"

    @property
    def label(self) -> str:
        mapping = {
            PoziomRyzykaAML.NISKIE: "Niskie",
            PoziomRyzykaAML.SREDNIE: "Średnie",
            PoziomRyzykaAML.WYSOKIE: "Wysokie",
            PoziomRyzykaAML.KRYTYCZNE_STOP: "Krytyczne (STOP)",
        }
        return mapping.get(self, self.value)


class DecyzjaWspolpracy(str, Enum):
    AKCEPTACJA = "AKCEPTACJA"
    WYMAGA_WYJASNIENIA = "WYMAGA_WYJASNIENIA"
    ODMOWA_WSPOLPRACY_STOP = "ODMOWA_WSPOLPRACY_STOP"

    @property
    def label(self) -> str:
        mapping = {
            DecyzjaWspolpracy.AKCEPTACJA: "Akceptacja",
            DecyzjaWspolpracy.WYMAGA_WYJASNIENIA: "Wymaga wyjaśnienia",
            DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP: "Odmowa współpracy (STOP)",
        }
        return mapping.get(self, self.value)


class StatusRachunkuBankowego(str, Enum):
    ZGODNY_BIALA_LISTA = "ZGODNY_BIALA_LISTA"
    BRAK_NA_BIALEJ_LISCIE = "BRAK_NA_BIALEJ_LISCIE"
    BLAD_POLACZENIA_MF = "BLAD_POLACZENIA_MF"      # MF API niedostępne — nie można zweryfikować
    NIE_PODANO = "NIE_PODANO"
    NIE_DOTYCZY_ZAGRANICZNY = "NIE_DOTYCZY_ZAGRANICZNY"

    @property
    def label(self) -> str:
        mapping = {
            StatusRachunkuBankowego.ZGODNY_BIALA_LISTA: "Zgodny z Białą Listą",
            StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE: "Brak na Białej Liście",
            StatusRachunkuBankowego.BLAD_POLACZENIA_MF: "Błąd połączenia z MF",
            StatusRachunkuBankowego.NIE_PODANO: "Nie podano",
            StatusRachunkuBankowego.NIE_DOTYCZY_ZAGRANICZNY: "Nie dotyczy (zagraniczny)",
        }
        return mapping.get(self, self.value)


class AnalystStatus(str, Enum):
    AUTO = "AUTO"
    PENDING_EXPLANATION = "PENDING_EXPLANATION"
    APPROVED_AFTER_REVIEW = "APPROVED_AFTER_REVIEW"
    REJECTED = "REJECTED"

    @property
    def label(self) -> str:
        mapping = {
            AnalystStatus.AUTO: "Weryfikacja automatyczna",
            AnalystStatus.PENDING_EXPLANATION: "Oczekuje na wyjaśnienie",
            AnalystStatus.APPROVED_AFTER_REVIEW: "Zatwierdzono po wyjaśnieniu",
            AnalystStatus.REJECTED: "Odrzucono / Blokada",
        }
        return mapping.get(self, self.value)


class KanalRelacji(str, Enum):
    SPOTKANIE_OSOBISTE = "SPOTKANIE_OSOBISTE"
    ZDALNIE = "ZDALNIE"

    @property
    def label(self) -> str:
        mapping = {
            KanalRelacji.SPOTKANIE_OSOBISTE: "Spotkanie osobiste",
            KanalRelacji.ZDALNIE: "Zdalnie (online)",
        }
        return mapping.get(self, self.value)


class ProfilRyzykaKyc(str, Enum):
    NISKIE = "NISKIE"                  # 0–4 pkt GIIF
    STANDARDOWE = "STANDARDOWE"        # 5–9 pkt GIIF
    PODWYZSZONE_EDD = "PODWYZSZONE_EDD" # 10–14 pkt GIIF (Wzmożone środki bezpieczeństwa)
    WYSOKIE_NIEAKCEPTOWALNE = "WYSOKIE_NIEAKCEPTOWALNE"  # >= 15 pkt GIIF

    @property
    def label(self) -> str:
        mapping = {
            ProfilRyzykaKyc.NISKIE: "Niskie",
            ProfilRyzykaKyc.STANDARDOWE: "Standardowe",
            ProfilRyzykaKyc.PODWYZSZONE_EDD: "Podwyższone (EDD)",
            ProfilRyzykaKyc.WYSOKIE_NIEAKCEPTOWALNE: "Wysokie nieakceptowalne",
        }
        return mapping.get(self, self.value)


