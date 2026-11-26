"""Generatory kart i raportów zbiorczych w formacie Markdown oraz CSV."""

import csv
import io
from typing import List

from src.domain.enums import DecyzjaWspolpracy, PoziomRyzykaAML, StatusRachunkuBankowego
from src.domain.models import BatchSummary, VerificationCard


def render_card_markdown(card: VerificationCard) -> str:
    """Generuje oficjalną Kartę Weryfikacji Kontrahenta w formacie Markdown."""
    rejestr_badge = {
        "AKTYWNY": "✅ Aktywny",
        "ZAWIESZONY": "⚠️ Zawieszony",
        "WYKRESLONY": "❌ Wykreślony / Zlikwidowany",
        "NIEZNALEZIONY": "❓ Nieznaleziony w rejestrach",
        "BLAD_POLACZENIA": "⚠️ Błąd połączenia z rejestrem",
    }.get(card.status_rejestru, card.status_rejestru)

    has_sanctions = bool(card.sankcje_mswia or card.sankcje_ue or card.sankcje_inne)
    crbr_badge = {
        "ZGODNY": "⚠️ Zgłoszony w CRBR (WYKRYTO SANKCJE!)" if has_sanctions else "✅ Zgodny z rejestrem CRBR",
        "BRAK_WPISU": "⚠️ Brak wpisu w CRBR",
        "ROZBIEZNOSCI": "⚠️ Wykryto rozbieżności z KRS",
        "NIE_DOTYCZY": "ℹ️ Nie dotyczy (JDG)",
        "NIE_DOTYCZY_ZAGRANICZNA": "ℹ️ Nie dotyczy polskiego CRBR (podmiot zagraniczny)",
        "BLAD_POLACZENIA": "⚠️ Brak połączenia z CRBR (do weryfikacji ręcznej)",
    }.get(card.crbr_status, card.crbr_status)

    mswia_badge = "🚨 FIGURUJE NA LIŚCIE SANKCYJNEJ (STOP!)" if card.sankcje_mswia else "✅ Brak na liście MSWiA"
    ue_badge = "🚨 FIGURUJE NA LIŚCIE SANKCYJNEJ (STOP!)" if card.sankcje_ue else "✅ Brak na liście UE"

    rachunek_badge = {
        StatusRachunkuBankowego.ZGODNY_BIALA_LISTA: "✅ Potwierdzony na Białej Liście VAT (MF)",
        StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE: "⚠️ BRAK na Białej Liście MF (ryzyko art. 22p PIT pow. 15 tys. zł)",
        StatusRachunkuBankowego.NIE_PODANO: "ℹ️ Nie wskazano rachunku do weryfikacji",
        StatusRachunkuBankowego.NIE_DOTYCZY_ZAGRANICZNY: "ℹ️ Rachunek zagraniczny (nie podlega Białej Liście MF)",
    }.get(card.status_rachunku, card.status_rachunku.value)

    ryzyko_badge = {
        PoziomRyzykaAML.NISKIE: "🟢 NISKIE",
        PoziomRyzykaAML.SREDNIE: "🟡 ŚREDNIE",
        PoziomRyzykaAML.WYSOKIE: "🟠 WYSOKIE",
        PoziomRyzykaAML.KRYTYCZNE_STOP: "🔴 KRYTYCZNE – SANKCJE (STOP)",
    }.get(card.poziom_ryzyka, card.poziom_ryzyka.value)

    decyzja_badge = {
        DecyzjaWspolpracy.AKCEPTACJA: "✅ AKCEPTACJA WSPÓŁPRACY",
        DecyzjaWspolpracy.WYMAGA_WYJASNIENIA: "⚠️ WYMAGA WYJAŚNIENIA",
        DecyzjaWspolpracy.ODMOWA_WSPOLPRACY_STOP: "🛑 ODMOWA WSPÓŁPRACY (STOP)",
    }.get(card.decyzja, card.decyzja.value)

    lines: List[str] = [
        "# KARTA WERYFIKACJI KONTRAHENTA (AML / COMPLIANCE / NALEŻYTA STARANNOŚĆ)",
        f"*ID audytu: `{card.id}` | Data: `{card.data_weryfikacji_tekst}` (UTC: `{card.data_weryfikacji}`) | IP badającego: `{card.client_ip or 'nieznane'}`*",
    ]

    if card.blad_polaczenia:
        lines.extend(
            [
                "",
                "> [!WARNING]",
                "> ### ⚠️ WERYFIKACJA NIEKOMPLETNA – BŁĄD POŁĄCZENIA Z REJESTRAMI",
                f"> Niedostępne źródła: **{', '.join(card.niekompletne_zrodla) or 'API rejestrów'}** ({card.komunikat_bledu or 'brak sieci'}).",
                "> **Karta nie stanowi ostatecznego dowodu należytej staranności i nie powinna być zatwierdzana przed ponownym sprawdzeniem.**",
            ]
        )

    lines.extend(
        [
            "",
            "---",
            "## 1. Dane podstawowe podmiotu",
            f"* **Nazwa:** **{card.nazwa}**",
            f"* **Identyfikator wejściowy ({card.identifier_kind}):** `{card.identifier}`",
            f"* **NIP:** `{card.nip or 'Brak'}` | **REGON:** `{card.regon or 'Brak'}` | **KRS:** `{card.krs or 'Brak'}`",
            f"* **Adres:** {card.adres or 'Brak danych adresowych'}",
            f"* **Forma prawna:** {card.forma_prawna}",
            f"* **Data wpisu do rejestru przedsiębiorców:** {card.data_wpisu_rejestru or card.data_rozpoczecia or 'Brak danych'}" if card.krs else f"* **Data rozpoczęcia działalności:** {card.data_rozpoczecia or 'Brak danych'}",
            f"* **PKD główny:** `{card.pkd_glowny or 'Brak'}`",
            "",
            "---",
            "## 2. Wyniki sprawdzenia w rejestrach publicznych",
            f"* **Rejestr ({card.zrodlo_rejestru}):** {rejestr_badge}",
            f"  * **Reprezentacja (KRS / właściciel):** {', '.join(card.reprezentacja) if card.reprezentacja else 'Brak danych'}",
            f"  * **Wspólnicy (KRS):** {', '.join(card.wspolnicy) if card.wspolnicy else 'Brak danych / nie dotyczy'}",
            f"* **Rejestr Beneficjentów Rzeczywistych (CRBR):** {crbr_badge}",
            f"  * **UBO:** {', '.join(card.beneficjenci_rzeczywisci) if card.beneficjenci_rzeczywisci else 'Brak danych'}",
            f"* **Status VAT:** {card.status_vat}",
            f"* **Status rachunku bankowego:** {rachunek_badge}",
            f"  * **Sprawdzany rachunek:** `{card.zweryfikowany_rachunek or 'Nie podano'}`",
            f"  * **MF Request ID:** `{card.mf_request_id or 'Brak'}`",
            f"  * **Zarejestrowane rachunki w MF ({len(card.rachunki_zgloszone_mf)}):**" if card.rachunki_zgloszone_mf else (
                f"  * **Zarejestrowane rachunki w MF:** ⚠️ Brak zgłoszonych rachunków w wykazie MF!" if card.platnik_vat_czynny else f"  * **Zarejestrowane rachunki w MF:** Nie dotyczy"
            ),
        ]
    )

    if card.rachunki_zgloszone_mf:
        for acc in card.rachunki_zgloszone_mf:
            lines.append(f"    * `{acc}`")

    lines.extend(
        [
            f"* **Lista sankcyjna MSWiA:** {mswia_badge}",
            f"* **Lista sankcyjna UE:** {ue_badge}",
        ]
    )

    if card.sankcje_szczegoly:
        lines.append("")
        lines.append("### 🚨 Szczegóły trafień sankcyjnych")
        for s in card.sankcje_szczegoly:
            lines.append(f"* ⚠️ {s}")

    lines.extend(
        [
            "",
            "---",
            "## 3. Ocena ryzyka i decyzja compliance",
            f"* **Status PEP:** {'TAK ⚠️' if card.status_pep else 'NIE'}",
            f"* **Wynik punktowy ryzyka:** `{card.risk_score}/100`",
            f"* **Poziom ryzyka:** **{ryzyko_badge}**",
            f"* **Decyzja automatyczna:** **{decyzja_badge}**",
            f"* **Status analityka:** `{card.analyst_status.value}`",
            f"* **Uzasadnienie:** {card.uzasadnienie_decyzji}",
        ]
    )

    if card.risk_factors:
        lines.append("")
        lines.append("### Wykryte czynniki ryzyka (Risk Matrix)")
        lines.append("| Kod | Czynnik | Waga | Podstawa prawna | Zalecenie |")
        lines.append("| :--- | :--- | :---: | :--- | :--- |")
        for rf in card.risk_factors:
            lines.append(f"| `{rf.code}` | {rf.title} | +{rf.points} | {rf.legal_basis} | {rf.recommendation} |")

    lines.extend(
        [
            "",
            "---",
            "## 4. Ślad audytowy (Audit Trail)",
            f"* **Skrót SHA-256 całego dowodu:** `{card.sha256_hash}`",
            "* **Okres retencji:** Minimum 5 lat od zakończenia roku obrotowego (art. 34 ustawy AML / art. 86 Ordynacji podatkowej).",
            "",
        ]
    )
    return "\n".join(lines)


def render_batch_markdown(summary: BatchSummary) -> str:
    """Generuje zbiorczy raport z weryfikacji wsadowej w formacie Markdown."""
    lines: List[str] = [
        "# ZBIORCZY RAPORT WERYFIKACJI KONTRAHENTÓW (AML / COMPLIANCE)",
        f"**ID zadania:** `{summary.batch_id}` | **Źródło:** `{summary.filename}` | **Data (UTC):** `{summary.created_at}`",
        "",
        "## 1. Podsumowanie",
        f"* **Łącznie podmiotów:** {summary.total}",
        f"* **🟢 Niskie ryzyko:** {summary.low_risk}",
        f"* **🟡 Średnie ryzyko:** {summary.medium_risk}",
        f"* **🟠 Wysokie ryzyko:** {summary.high_risk}",
        f"* **🔴 Krytyczne (STOP / Sankcje):** {summary.critical_stop}",
        f"* **⚠️ Błędy sieci / niekompletne:** {summary.offline_errors}",
        "",
        "## 2. Wykaz zweryfikowanych podmiotów",
        "| Lp. | Identyfikator | Nazwa | Status VAT | Rachunek MF | Sankcje | Ryzyko | Decyzja | SHA-256 (skrót) |",
        "| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for idx, c in enumerate(summary.cards, start=1):
        sankcje = "STOP" if (c.sankcje_mswia or c.sankcje_ue or c.sankcje_inne) else "Czysty"
        vat = "Błąd sieci" if c.blad_polaczenia else ("Czynny" if c.platnik_vat_czynny else c.status_vat)
        lines.append(
            f"| {idx} | `{c.identifier}` | **{c.nazwa}** | {vat} | {c.status_rachunku.value} | {sankcje} | {c.poziom_ryzyka.value} | {c.decyzja.value} | `{c.sha256_hash[:12]}` |"
        )
    return "\n".join(lines)


def render_batch_csv(summary: BatchSummary) -> str:
    """Generuje raport wsadowy w formacie CSV (UTF-8 z BOM dla Excela)."""
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "ID",
            "Identyfikator",
            "Typ",
            "NIP",
            "KRS",
            "Nazwa",
            "Forma prawna",
            "Status rejestru",
            "Status VAT",
            "Status rachunku",
            "MF Request ID",
            "Sankcje",
            "Punkty ryzyka",
            "Poziom ryzyka",
            "Decyzja",
            "Status analityka",
            "Blad polaczenia",
            "SHA-256",
        ]
    )
    for c in summary.cards:
        writer.writerow(
            [
                c.id,
                c.identifier,
                c.identifier_kind,
                c.nip or "",
                c.krs or "",
                c.nazwa,
                c.forma_prawna,
                c.status_rejestru,
                c.status_vat,
                c.status_rachunku.value,
                c.mf_request_id or "",
                "TAK" if (c.sankcje_mswia or c.sankcje_ue or c.sankcje_inne) else "NIE",
                c.risk_score,
                c.poziom_ryzyka.value,
                c.decyzja.value,
                c.analyst_status.value,
                "TAK" if c.blad_polaczenia else "NIE",
                c.sha256_hash,
            ]
        )
    return "\ufeff" + buf.getvalue()
