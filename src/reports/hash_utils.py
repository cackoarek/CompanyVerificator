"""Kanoniczne obliczanie skrótu SHA-256 całego pakietu dowodowego weryfikacji."""

import hashlib
import json
from typing import Any, Dict

from src.domain.models import VerificationCard


def compute_card_sha256(card: VerificationCard) -> str:
    """
    Oblicza deterministyczny skrót SHA-256 ze wszystkich danych merytorycznych karty
    oraz surowych odpowiedzi rejestrów (z wyłączeniem samego pola sha256_hash i statusu analityka).
    """
    payload: Dict[str, Any] = card.to_dict()
    payload.pop("sha256_hash", None)
    payload.pop("analyst_status", None)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
