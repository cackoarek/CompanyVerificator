"""Modele domenowe kart weryfikacji, czynników ryzyka i raportów zbiorczych."""

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from src.config import APP_TIMEZONE
from src.domain.enums import (
    AnalystStatus,
    DecyzjaWspolpracy,
    KanalRelacji,
    PoziomRyzykaAML,
    ProfilRyzykaKyc,
    StatusRachunkuBankowego,
)


def get_app_tz() -> ZoneInfo:
    """Zwraca strefę czasową aplikacji (domyślnie Europe/Warsaw)."""
    try:
        return ZoneInfo(APP_TIMEZONE)
    except Exception:
        return ZoneInfo("Europe/Warsaw")


def get_app_now() -> datetime:
    """Zwraca bieżący czas lokalny w strefie czasowej aplikacji."""
    return datetime.now(get_app_tz())



@dataclass
class KycScorecard:
    """Karta punktacji czynników ryzyka klienta (KYC) zgodna z wytycznymi GIIF i Krajowej Oceny Ryzyka."""

    staz_punkty: int = 0
    staz_opis: str = ""

    siedziba_punkty: int = 0
    siedziba_opis: str = ""

    ubo_punkty: int = 0
    ubo_opis: str = ""

    branza_punkty: int = 0
    branza_opis: str = ""

    kanal_punkty: int = 0
    kanal_opis: str = ""

    suma_punktow: int = 0
    profil_ryzyka: ProfilRyzykaKyc = ProfilRyzykaKyc.NISKIE
    podsumowanie: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "staz_punkty": self.staz_punkty,
            "staz_opis": self.staz_opis,
            "siedziba_punkty": self.siedziba_punkty,
            "siedziba_opis": self.siedziba_opis,
            "ubo_punkty": self.ubo_punkty,
            "ubo_opis": self.ubo_opis,
            "branza_punkty": self.branza_punkty,
            "branza_opis": self.branza_opis,
            "kanal_punkty": self.kanal_punkty,
            "kanal_opis": self.kanal_opis,
            "suma_punktow": self.suma_punktow,
            "profil_ryzyka": self.profil_ryzyka.value,
            "podsumowanie": self.podsumowanie,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KycScorecard":
        payload = dict(data)
        if "profil_ryzyka" in payload:
            payload["profil_ryzyka"] = ProfilRyzykaKyc(payload["profil_ryzyka"])
        return cls(**payload)


@dataclass
class RiskFactor:
    """Pojedynczy deterministyczny czynnik ryzyka wykryty w procedurze należytej staranności."""

    code: str
    title: str
    severity: PoziomRyzykaAML
    points: int
    legal_basis: str
    recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity.value,
            "points": self.points,
            "legal_basis": self.legal_basis,
            "recommendation": self.recommendation,
        }


@dataclass
class SanctionHit:
    """Trafienie na liście sankcyjnej lub liście ostrzeżeń."""

    source: str
    match_type: str  # NIP | KRS | COMPANY_NAME | PERSON
    matched_value: str
    sanctioned_name: str
    confidence: str  # EXACT | HIGH | POSSIBLE
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationCard:
    """Kompletna Karta Weryfikacji Kontrahenta (AML / Compliance / Biała Lista / KRS / CRBR / VIES)."""

    identifier: str
    identifier_kind: str  # NIP | KRS | EU_VAT | FOREIGN_TAX_ID | INVALID
    nazwa: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    nip: Optional[str] = None
    krs: Optional[str] = None
    regon: Optional[str] = None
    vat_ue: Optional[str] = None
    adres: Optional[str] = None
    kraj: str = "PL"
    forma_prawna: str = "NIEZNANA"
    data_rozpoczecia: Optional[str] = None
    data_wpisu_rejestru: Optional[str] = None
    kody_pkd: List[str] = field(default_factory=list)
    pkd_glowny: Optional[str] = None

    data_weryfikacji: str = field(
        default_factory=lambda: get_app_now().isoformat()
    )
    data_weryfikacji_tekst: str = field(
        default_factory=lambda: get_app_now().strftime("%d.%m.%Y, %H:%M")
    )
    osoba_weryfikujaca: str = "CompanyVerificator – AML & Compliance Engine"

    # 1. Rejestry podstawowe (KRS / CEIDG / MF / VIES)
    status_rejestru: str = "AKTYWNY"
    zrodlo_rejestru: str = "Biała Lista MF"
    reprezentacja: List[str] = field(default_factory=list)
    wspolnicy: List[str] = field(default_factory=list)
    upadlosc_lub_likwidacja: bool = False
    krz_status: str = "CZYSTY"  # CZYSTY | POSTEPOWANIE_UPADLOSCIOWE | RESTRUKTURYZACJA | LIKWIDACJA | BEZSKUTECZNA_EGZEKUCJA | NIE_DOTYCZY_ZAGRANICZNA | BLAD_POLACZENIA
    krz_wpisy: List[Dict[str, Any]] = field(default_factory=list)
    krz_szczegoly: List[str] = field(default_factory=list)

    # 2. Beneficjenci rzeczywiści (CRBR)
    crbr_status: str = "NIE_DOTYCZY"  # ZGODNY | ROZBIEZNOSCI | BRAK_WPISU | NIE_DOTYCZY | NIE_DOTYCZY_ZAGRANICZNA | BLAD_POLACZENIA
    beneficjenci_rzeczywisci: List[str] = field(default_factory=list)

    # 3. Listy sankcyjne i ostrzeżenia publiczne (MSWiA / UE / KNF)
    sankcje_mswia: bool = False
    sankcje_ue: bool = False
    sankcje_knf: bool = False
    sankcje_inne: bool = False
    sankcje_trafienia: List[SanctionHit] = field(default_factory=list)
    sankcje_szczegoly: List[str] = field(default_factory=list)

    # 4. Podatki i rachunki bankowe
    status_vat: str = "Niezweryfikowany"
    platnik_vat_czynny: bool = False
    vies_valid: Optional[bool] = None
    zweryfikowany_rachunek: Optional[str] = None
    status_rachunku: StatusRachunkuBankowego = StatusRachunkuBankowego.NIE_PODANO
    rachunki_zgloszone_mf: List[str] = field(default_factory=list)
    kwota_transakcji: Optional[str] = None
    wymagany_mpp: bool = False
    mf_request_id: Optional[str] = None

    # 5. Ocena ryzyka i decyzja
    status_pep: bool = False
    kanal_relacji: KanalRelacji = KanalRelacji.ZDALNIE
    kyc_scorecard: Optional[KycScorecard] = None
    risk_score: int = 0
    risk_factors: List[RiskFactor] = field(default_factory=list)
    poziom_ryzyka: PoziomRyzykaAML = PoziomRyzykaAML.NISKIE
    decyzja: DecyzjaWspolpracy = DecyzjaWspolpracy.AKCEPTACJA
    analyst_status: AnalystStatus = AnalystStatus.AUTO
    uzasadnienie_decyzji: str = ""
    uwagi_dodatkowe: Optional[str] = None

    # 6. Stan sieci i audyt
    blad_polaczenia: bool = False
    niekompletne_zrodla: List[str] = field(default_factory=list)
    komunikat_bledu: Optional[str] = None
    raw_evidence: Dict[str, Any] = field(default_factory=dict)
    sha256_hash: str = ""

    # 7. Metadane wsadowe i audyt sieciowy (opcjonalne)
    batch_id: Optional[str] = None
    client_ip: Optional[str] = None

    @property
    def is_recently_registered(self) -> bool:
        """Zwraca True, jeśli wpis w rejestrze nastąpił mniej niż 180 dni (6 miesięcy) temu."""
        date_str = self.data_wpisu_rejestru or self.data_rozpoczecia
        if not date_str:
            return False
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(date_str[:10], fmt[: len(date_str[:10])] if "T" not in fmt else fmt)
                days = (datetime.now(timezone.utc).replace(tzinfo=None) - dt).days
                return 0 <= days < 180
            except ValueError:
                continue
        return False

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["poziom_ryzyka"] = self.poziom_ryzyka.value
        data["decyzja"] = self.decyzja.value
        data["status_rachunku"] = self.status_rachunku.value
        data["analyst_status"] = self.analyst_status.value
        data["kanal_relacji"] = self.kanal_relacji.value if isinstance(self.kanal_relacji, KanalRelacji) else str(self.kanal_relacji)
        data["kyc_scorecard"] = self.kyc_scorecard.to_dict() if self.kyc_scorecard else None
        data["risk_factors"] = [rf.to_dict() for rf in self.risk_factors]
        data["sankcje_trafienia"] = [sh.to_dict() for sh in self.sankcje_trafienia]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VerificationCard":
        payload = dict(data)
        payload["poziom_ryzyka"] = PoziomRyzykaAML(payload.get("poziom_ryzyka", PoziomRyzykaAML.SREDNIE.value))
        payload["decyzja"] = DecyzjaWspolpracy(payload.get("decyzja", DecyzjaWspolpracy.WYMAGA_WYJASNIENIA.value))
        payload["status_rachunku"] = StatusRachunkuBankowego(
            payload.get("status_rachunku", StatusRachunkuBankowego.NIE_PODANO.value)
        )
        payload["analyst_status"] = AnalystStatus(payload.get("analyst_status", AnalystStatus.AUTO.value))
        if "kanal_relacji" in payload:
            try:
                payload["kanal_relacji"] = KanalRelacji(payload["kanal_relacji"])
            except ValueError:
                payload["kanal_relacji"] = KanalRelacji.ZDALNIE
        if payload.get("kyc_scorecard"):
            payload["kyc_scorecard"] = KycScorecard.from_dict(payload["kyc_scorecard"])
        payload["risk_factors"] = [
            RiskFactor(
                code=rf["code"],
                title=rf["title"],
                severity=PoziomRyzykaAML(rf["severity"]),
                points=int(rf["points"]),
                legal_basis=rf["legal_basis"],
                recommendation=rf["recommendation"],
            )
            for rf in (payload.get("risk_factors") or [])
        ]
        payload["sankcje_trafienia"] = [
            SanctionHit(**sh) for sh in (payload.get("sankcje_trafienia") or [])
        ]
        return cls(**payload)


@dataclass
class BatchSummary:
    """Podsumowanie weryfikacji wsadowej."""

    batch_id: str
    filename: str
    cards: List[VerificationCard] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def total(self) -> int:
        return len(self.cards)

    @property
    def low_risk(self) -> int:
        return sum(1 for c in self.cards if c.poziom_ryzyka == PoziomRyzykaAML.NISKIE and not c.blad_polaczenia)

    @property
    def medium_risk(self) -> int:
        return sum(1 for c in self.cards if c.poziom_ryzyka == PoziomRyzykaAML.SREDNIE and not c.blad_polaczenia)

    @property
    def high_risk(self) -> int:
        return sum(1 for c in self.cards if c.poziom_ryzyka == PoziomRyzykaAML.WYSOKIE)

    @property
    def critical_stop(self) -> int:
        return sum(1 for c in self.cards if c.poziom_ryzyka == PoziomRyzykaAML.KRYTYCZNE_STOP)

    @property
    def offline_errors(self) -> int:
        return sum(1 for c in self.cards if c.blad_polaczenia)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "filename": self.filename,
            "created_at": self.created_at,
            "stats": {
                "total": self.total,
                "low_risk": self.low_risk,
                "medium_risk": self.medium_risk,
                "high_risk": self.high_risk,
                "critical_stop": self.critical_stop,
                "offline_errors": self.offline_errors,
            },
            "cards": [c.to_dict() for c in self.cards],
        }
