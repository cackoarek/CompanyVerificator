"""Deterministyczny silnik dopasowania podmiotów i osób do list sankcyjnych."""

import re
from typing import Any, Dict, List, Optional, Sequence

from src.core.validators import clean_krs, clean_nip
from src.domain.models import SanctionHit

_DIACRITICS = {
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "ä": "a", "ö": "o", "ü": "u", "ß": "ss", "à": "a", "é": "e", "è": "e", "ê": "e",
}

_STOP_WORDS = {
    "sp", "z", "o", "sa", "spolka", "akcyjna", "komandytowa", "jawna", "partnerska",
    "ograniczona", "odpowiedzialnoscia", "llc", "gmbh", "corp", "inc", "ltd", "limited",
    "sarl", "pao", "oao", "zao", "ao", "ooo", "jsc", "pjsc", "group", "polska", "eu",
}


def strip_diacritics(text: str) -> str:
    s = (text or "").lower()
    for k, v in _DIACRITICS.items():
        s = s.replace(k, v)
    return s


def normalize_name(name: str) -> str:
    """Normalizuje nazwę firmy lub osoby na potrzeby porównań sankcyjnych."""
    if not name:
        return ""
    s = strip_diacritics(name)
    s = re.sub(
        r"\b(sp\.?\s*z\s*o\.?\s*o\.?|spolka\s+z\s+ograniczona\s+odpowiedzialnoscia|s\.?a\.?|spolka\s+akcyjna|sp\.?\s*k\.?|gmbh|llc|inc|corp|ltd|limited|pao|oao|zao|ooo|pjsc)\b",
        "",
        s,
    )
    return re.sub(r"[^a-z0-9]", "", s).strip()


def tokenize_name(name: str) -> List[str]:
    """Zwraca listę znormalizowanych słów kluczowych bez form prawnych."""
    if not name:
        return []
    s = strip_diacritics(re.sub(r"\(.*?\)|\[.*?\]", " ", name))
    words = re.findall(r"[a-z0-9]{2,}", s)
    return [w for w in words if w not in _STOP_WORDS]


def match_sanctions(
    *,
    nip: Optional[str],
    krs: Optional[str],
    company_name: str,
    persons: Sequence[str],
    entries: List[Dict[str, Any]],
) -> List[SanctionHit]:
    """
    Dopasowuje NIP, KRS, nazwę podmiotu oraz osoby (zarząd, UBO) do wpisów sankcyjnych z bazy.
    """
    hits: List[SanctionHit] = []
    seen_keys: set[tuple[str, str, str]] = set()

    norm_nip = clean_nip(nip)
    norm_krs = clean_krs(krs)
    norm_comp = normalize_name(company_name)
    comp_tokens = set(tokenize_name(company_name))

    def _add_hit(hit: SanctionHit) -> None:
        key = (hit.source, hit.match_type, hit.sanctioned_name)
        if key not in seen_keys:
            seen_keys.add(key)
            hits.append(hit)

    for entry in entries:
        source = entry.get("source", "UNKNOWN")
        entry_type = entry.get("entry_type", "ENTITY")
        s_name = entry.get("name", "")
        s_nip = clean_nip(entry.get("nip"))
        s_krs = clean_krs(entry.get("krs"))
        reason = entry.get("reason", "")
        listed_at = entry.get("listed_at", "")
        date_suffix = f", wpis z dnia {listed_at}" if listed_at else ""
        aliases = entry.get("aliases") or []
        candidate_names = [s_name] + [a for a in aliases if a]

        # 1. Identyfikatory rejestrowe (EXACT)
        if norm_nip and len(norm_nip) == 10 and s_nip and norm_nip == s_nip:
            hit_reason = f"Identyfikator NIP {norm_nip} figuruje w wykazie sankcyjnym podmiotu '{s_name}'"
            if reason:
                hit_reason += f" ({reason}{date_suffix})"
            elif date_suffix:
                hit_reason += f" ({date_suffix.lstrip(', ')})"
            _add_hit(
                SanctionHit(
                    source=source,
                    match_type="NIP",
                    matched_value=norm_nip,
                    sanctioned_name=s_name,
                    confidence="EXACT",
                    reason=hit_reason,
                )
            )
            continue

        if norm_krs and len(norm_krs) == 10 and s_krs and norm_krs == s_krs:
            hit_reason = f"Numer KRS {norm_krs} figuruje w wykazie sankcyjnym podmiotu '{s_name}'"
            if reason:
                hit_reason += f" ({reason}{date_suffix})"
            elif date_suffix:
                hit_reason += f" ({date_suffix.lstrip(', ')})"
            _add_hit(
                SanctionHit(
                    source=source,
                    match_type="KRS",
                    matched_value=norm_krs,
                    sanctioned_name=s_name,
                    confidence="EXACT",
                    reason=hit_reason,
                )
            )
            continue

        # 2. Dopasowanie po nazwie firmy
        if entry_type == "ENTITY" and norm_comp:
            matched_entity = False
            for cname in candidate_names:
                c_norm = normalize_name(cname)
                c_tokens = set(tokenize_name(cname))
                if not c_norm or len(c_norm) < 4:
                    continue
                if c_norm == norm_comp or (c_tokens and c_tokens == comp_tokens):
                    hit_reason = f"Nazwa podmiotu '{company_name}' jest tożsama z podmiotem sankcjonowanym '{s_name}'"
                    if reason:
                        hit_reason += f" ({reason}{date_suffix})"
                    elif date_suffix:
                        hit_reason += f" ({date_suffix.lstrip(', ')})"
                    _add_hit(
                        SanctionHit(
                            source=source,
                            match_type="COMPANY_NAME",
                            matched_value=company_name,
                            sanctioned_name=s_name,
                            confidence="HIGH",
                            reason=hit_reason,
                        )
                    )
                    matched_entity = True
                    break
                # Warunek częściowej zbieżności:
                # Zapobiega fałszywym trafieniom na pojedynczych pospolitych słowach (np. 'bank', 'invest', 'poland')
                is_distinctive_match = False
                if len(c_tokens) >= 2 and c_tokens.issubset(comp_tokens):
                    is_distinctive_match = True
                elif len(c_tokens) == 1 and (len(c_norm) >= 8 and c_norm in norm_comp):
                    is_distinctive_match = True

                if is_distinctive_match:
                    hit_reason = f"Zbieżność nazwy '{company_name}' z podmiotem sankcjonowanym '{s_name}'"
                    if reason:
                        hit_reason += f" ({reason}{date_suffix})"
                    elif date_suffix:
                        hit_reason += f" ({date_suffix.lstrip(', ')})"
                    _add_hit(
                        SanctionHit(
                            source=source,
                            match_type="COMPANY_NAME",
                            matched_value=company_name,
                            sanctioned_name=s_name,
                            confidence="HIGH" if len(c_tokens) >= 2 or len(c_norm) >= 10 else "POSSIBLE",
                            reason=hit_reason,
                        )
                    )
                    matched_entity = True
                    break
            if matched_entity:
                continue

        # 3. Dopasowanie po osobach (Zarząd / Prokurent / UBO)
        if entry_type == "PERSON":
            for person in persons:
                p_tokens = set(tokenize_name(person))
                if not p_tokens:
                    continue
                for cname in candidate_names:
                    c_tokens = set(tokenize_name(cname))
                    if not c_tokens:
                        continue
                    # p_tokens subset of c_tokens: "Ivan Testov" ⊂ "Ivan Petrovich Testov"
                    if len(p_tokens) >= 2 and p_tokens.issubset(c_tokens):
                        hit_reason = f"Osoba powiązana/zarządzająca '{person}' figuruje na liście sankcyjnej jako '{s_name}'"
                        if reason:
                            hit_reason += f" ({reason}{date_suffix})"
                        elif date_suffix:
                            hit_reason += f" ({date_suffix.lstrip(', ')})"
                        _add_hit(
                            SanctionHit(
                                source=source,
                                match_type="PERSON",
                                matched_value=person,
                                sanctioned_name=s_name,
                                confidence="HIGH",
                                reason=hit_reason,
                            )
                        )
                        break
                    # c_tokens subset of p_tokens: "Ivan Petrovich Testov" ⊃ "Ivan Testov"
                    if len(c_tokens) >= 2 and c_tokens.issubset(p_tokens):
                        hit_reason = f"Osoba powiązana/zarządzająca '{person}' figuruje na liście sankcyjnej jako '{s_name}'"
                        if reason:
                            hit_reason += f" ({reason}{date_suffix})"
                        elif date_suffix:
                            hit_reason += f" ({date_suffix.lstrip(', ')})"
                        _add_hit(
                            SanctionHit(
                                source=source,
                                match_type="PERSON",
                                matched_value=person,
                                sanctioned_name=s_name,
                                confidence="HIGH",
                                reason=hit_reason,
                            )
                        )
                        break
                    if len(c_tokens) == 1:
                        single = next(iter(c_tokens))
                        if len(single) >= 5 and single in p_tokens:
                            hit_reason = f"Potencjalna zbieżność nazwiska osoby powiązanej '{person}' z wpisem sankcyjnym '{s_name}'"
                            if reason:
                                hit_reason += f" ({reason}{date_suffix})"
                            elif date_suffix:
                                hit_reason += f" ({date_suffix.lstrip(', ')})"
                            _add_hit(
                                SanctionHit(
                                    source=source,
                                    match_type="PERSON",
                                    matched_value=person,
                                    sanctioned_name=s_name,
                                    confidence="POSSIBLE",
                                    reason=hit_reason,
                                )
                            )
                            break

    return hits
