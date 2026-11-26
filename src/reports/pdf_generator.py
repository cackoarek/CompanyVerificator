"""Generatory dokumentów PDF (A4 Karta Kontrahenta oraz A4 Pejzaż Raport Zbiorczy)."""

import hashlib
import html
import os
from pathlib import Path
from typing import Tuple, Union

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from src.domain.enums import DecyzjaWspolpracy, PoziomRyzykaAML, StatusRachunkuBankowego
from src.domain.models import BatchSummary, VerificationCard


def _esc(val: object) -> str:
    return html.escape(str(val or ""), quote=True)


def register_pdf_fonts() -> Tuple[str, str]:
    """Rejestruje czcionki TrueType obsługujące polskie znaki."""
    registered = pdfmetrics.getRegisteredFontNames()
    if "DejaVuSans" in registered and "DejaVuSans-Bold" in registered:
        return "DejaVuSans", "DejaVuSans-Bold"

    candidate_pairs = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    for reg_path, bold_path in candidate_pairs:
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont("DejaVuSans", reg_path))
                pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold_path))
                return "DejaVuSans", "DejaVuSans-Bold"
            except Exception:
                pass
    return "Helvetica", "Helvetica-Bold"


def _section_bar(title: str, sec_hdr: ParagraphStyle, width: int = 525) -> Table:
    bar = Table([[Paragraph(_esc(title), sec_hdr)]], colWidths=[width])
    bar.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                ("LINELEFT", (0, 0), (-1, -1), 3, colors.HexColor("#2563EB")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return bar


def generate_card_pdf(card: VerificationCard, output_path: Union[str, Path]) -> Path:
    """Generuje oficjalną Kartę Weryfikacji Kontrahenta (PDF A4)."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    font_reg, font_bold = register_pdf_fonts()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=35, rightMargin=35, topMargin=28, bottomMargin=28)

    hdr_brand = ParagraphStyle("HdrBrand", fontName=font_bold, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#38BDF8"))
    hdr_title = ParagraphStyle("HdrTitle", fontName=font_bold, fontSize=12.5, leading=15, textColor=colors.white)
    hdr_sub = ParagraphStyle("HdrSub", fontName=font_reg, fontSize=7, leading=9, textColor=colors.HexColor("#CBD5E1"))
    hdr_right = ParagraphStyle("HdrRight", fontName=font_bold, fontSize=8, leading=10, textColor=colors.HexColor("#F8FAFC"), alignment=2)
    hdr_right_sub = ParagraphStyle("HdrRightSub", fontName=font_reg, fontSize=6.5, leading=8.5, textColor=colors.HexColor("#94A3B8"), alignment=2)
    sec_hdr = ParagraphStyle("SecHdr", fontName=font_bold, fontSize=8.5, leading=11, textColor=colors.HexColor("#0F172A"))
    cell_bold = ParagraphStyle("CellB", fontName=font_bold, fontSize=7.5, leading=10, textColor=colors.HexColor("#334155"))
    cell_norm = ParagraphStyle("CellN", fontName=font_reg, fontSize=7.5, leading=10, textColor=colors.HexColor("#0F172A"))
    footer_style = ParagraphStyle("FooterS", fontName=font_reg, fontSize=6.5, leading=8.5, textColor=colors.HexColor("#64748B"))

    elements = []

    # 1. Nagłówek Corporate Navy
    header_table = Table(
        [
            [
                Paragraph("COMPANYVERIFICATOR • COMPLIANCE & NALEŻYTA STARANNOŚĆ", hdr_brand),
                Paragraph("URZĘDOWY DOWÓD WERYFIKACJI", hdr_right),
            ],
            [
                Paragraph("KARTA WERYFIKACJI KONTRAHENTA (AML / VAT)", hdr_title),
                Paragraph(f"{_esc(card.identifier_kind)}: <b>{_esc(card.identifier)}</b>", hdr_right),
            ],
            [
                Paragraph("Podstawa: art. 34 ustawy AML • art. 22p PIT • art. 96b i 108a ustawy o VAT", hdr_sub),
                Paragraph(f"Audyt: {_esc(card.data_weryfikacji_tekst)} • IP: {_esc(card.client_ip or 'nieznane')}", hdr_right_sub),
            ],
        ],
        colWidths=[360, 165],
    )
    header_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.extend([header_table, Spacer(1, 8)])

    # 2. Karta decyzji
    if card.blad_polaczenia:
        dec_bg, dec_border = colors.HexColor("#FEF2F2"), colors.HexColor("#DC2626")
        dec_title = '<font color="#991B1B" size="9.5"><b>[!] STATUS: WERYFIKACJA NIEKOMPLETNA – BŁĄD POŁĄCZENIA</b></font>'
        dec_sub = f'<font color="#7F1D1D" size="7.5">Niedostępne źródła: {_esc(", ".join(card.niekompletne_zrodla))}. Nie zatwierdzaj płatności przed ponowieniem.</font>'
    elif card.decyzja == DecyzjaWspolpracy.AKCEPTACJA:
        dec_bg, dec_border = colors.HexColor("#F0FDF4"), colors.HexColor("#16A34A")
        dec_title = '<font color="#15803D" size="9.5"><b>✓ STATUS: AKCEPTACJA WSPÓŁPRACY I PŁATNOŚCI</b></font>'
        dec_sub = '<font color="#166534" size="7.5">Brak trafień sankcyjnych, status rejestrowy i podatkowy zweryfikowany pozytywnie.</font>'
    elif card.decyzja == DecyzjaWspolpracy.WYMAGA_WYJASNIENIA:
        dec_bg, dec_border = colors.HexColor("#FFFBEB"), colors.HexColor("#D97706")
        dec_title = '<font color="#B45309" size="9.5"><b>[!] STATUS: WYMAGA WYJAŚNIENIA / ZGODY COMPLIANCE</b></font>'
        dec_sub = f'<font color="#92400E" size="7.5">{_esc(card.uzasadnienie_decyzji)}</font>'
    else:
        dec_bg, dec_border = colors.HexColor("#FEF2F2"), colors.HexColor("#DC2626")
        dec_title = '<font color="#991B1B" size="9.5"><b>[✗] STATUS: BEZWZGLĘDNA BLOKADA TRANSAKCJI (SANKCJE)</b></font>'
        dec_sub = '<font color="#7F1D1D" size="7.5">Podmiot lub osoba powiązana figuruje na liście sankcyjnej – zakaz udostępniania środków.</font>'

    ryzyko_badge = {
        PoziomRyzykaAML.NISKIE: '<font color="#15803D"><b>[NISKIE]</b></font>',
        PoziomRyzykaAML.SREDNIE: '<font color="#B45309"><b>[ŚREDNIE]</b></font>',
        PoziomRyzykaAML.WYSOKIE: '<font color="#C2410C"><b>[WYSOKIE]</b></font>',
        PoziomRyzykaAML.KRYTYCZNE_STOP: '<font color="#DC2626"><b>[KRYTYCZNE – STOP]</b></font>',
    }.get(card.poziom_ryzyka, _esc(card.poziom_ryzyka.value))

    decision_card = Table(
        [
            [
                Paragraph(f"{dec_title}<br/>{dec_sub}", cell_norm),
                Paragraph(
                    f"<b>Ryzyko:</b> {ryzyko_badge} ({card.risk_score}/100 pkt)<br/>"
                    f"<b>Decyzja analityka:</b> {_esc(card.analyst_status.value)}<br/>"
                    f"<b>System:</b> {_esc(card.osoba_weryfikujaca)}",
                    cell_norm,
                ),
            ]
        ],
        colWidths=[335, 190],
    )
    decision_card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), dec_bg),
                ("BOX", (0, 0), (-1, -1), 1, dec_border),
                ("LINELEFT", (0, 0), (0, -1), 4, dec_border),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.extend([decision_card, Spacer(1, 8)])

    # 3. Sekcja 1: Dane identyfikacyjne
    elements.extend([_section_bar("1. DANE IDENTYFIKACYJNE PODMIOTU", sec_hdr), Spacer(1, 3)])
    t1 = Table(
        [
            [Paragraph("Pełna nazwa:", cell_bold), Paragraph(f"<b>{_esc(card.nazwa)}</b>", cell_norm)],
            [Paragraph("NIP / REGON / KRS:", cell_bold), Paragraph(f"NIP: <b>{_esc(card.nip or 'Brak')}</b> • REGON: {_esc(card.regon or 'Brak')} • KRS: {_esc(card.krs or 'Brak')}", cell_norm)],
            [Paragraph("Adres siedziby:", cell_bold), Paragraph(_esc(card.adres or "Brak danych adresowych"), cell_norm)],
            [Paragraph("Forma prawna / PKD:", cell_bold), Paragraph(f"{_esc(card.forma_prawna)} • PKD: {_esc(card.pkd_glowny or 'Brak')} • Start: {_esc(card.data_rozpoczecia or 'Brak')}", cell_norm)],
        ],
        colWidths=[140, 385],
    )
    t1.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.extend([t1, Spacer(1, 8)])

    # 4. Sekcja 2: Rejestry i sankcje
    elements.extend([_section_bar("2. WYNIKI WERYFIKACJI W REJESTRACH PUBLICZNYCH I SANKCYJNYCH", sec_hdr), Spacer(1, 3)])

    rep_txt = ", ".join(card.reprezentacja[:6]) if card.reprezentacja else "Brak danych reprezentacji"
    ubo_txt = ", ".join(card.beneficjenci_rzeczywisci[:6]) if card.beneficjenci_rzeczywisci else "Brak wpisu / nie dotyczy"
    if card.status_rachunku == StatusRachunkuBankowego.NIE_PODANO:
        if card.rachunki_zgloszone_mf:
            acc_previews = ", ".join(f"<code>{a[:2]} {a[2:6]}...{a[-4:]}</code>" for a in card.rachunki_zgloszone_mf[:3])
            more = f" (+{len(card.rachunki_zgloszone_mf)-3})" if len(card.rachunki_zgloszone_mf) > 3 else ""
            rach_txt = f'<font color="#15803D"><b>Wykaz MF ({len(card.rachunki_zgloszone_mf)}):</b></font> {acc_previews}{more}'
        elif card.platnik_vat_czynny:
            rach_txt = '<font color="#D97706"><b>[!] BRAK zarejestrowanych kont na Białej Liście MF</b></font>'
        else:
            rach_txt = '<font color="#64748B">Nie wskazano rachunku do badania</font>'
    else:
        rach_txt = {
            StatusRachunkuBankowego.ZGODNY_BIALA_LISTA: f'<font color="#15803D"><b>✓ Zgodny z Białą Listą MF</b></font> ({_esc(card.zweryfikowany_rachunek)})',
            StatusRachunkuBankowego.BRAK_NA_BIALEJ_LISCIE: f'<font color="#D97706"><b>[!] BRAK na Białej Liście MF</b></font> ({_esc(card.zweryfikowany_rachunek)})',
            StatusRachunkuBankowego.NIE_DOTYCZY_ZAGRANICZNY: f'<font color="#2563EB">Rachunek zagraniczny</font> ({_esc(card.zweryfikowany_rachunek or "brak")})',
        }.get(card.status_rachunku, _esc(card.status_rachunku.value))

    mswia_txt = '<font color="#DC2626"><b>[✗] WPIS NA LIŚCIE MSWiA</b></font>' if card.sankcje_mswia else '<font color="#15803D">✓ Czysty (MSWiA)</font>'
    ue_txt = '<font color="#DC2626"><b>[✗] WPIS NA LIŚCIE UE</b></font>' if card.sankcje_ue else '<font color="#15803D">✓ Czysty (UE)</font>'

    t2 = Table(
        [
            [Paragraph("Rejestr podstawowy:", cell_bold), Paragraph(f"<b>{_esc(card.status_rejestru)}</b> ({_esc(card.zrodlo_rejestru)})", cell_norm)],
            [Paragraph("Reprezentacja (KRS):", cell_bold), Paragraph(_esc(rep_txt), cell_norm)],
            [Paragraph("CRBR / UBO:", cell_bold), Paragraph(f"<b>{_esc(card.crbr_status)}</b> • {_esc(ubo_txt)}", cell_norm)],
            [Paragraph("Status VAT / VIES:", cell_bold), Paragraph(f"{_esc(card.status_vat)} • MF Request ID: <code>{_esc(card.mf_request_id or 'Brak')}</code>", cell_norm)],
            [Paragraph("Rachunek bankowy:", cell_bold), Paragraph(rach_txt, cell_norm)],
            [Paragraph("Listy sankcyjne:", cell_bold), Paragraph(f"{mswia_txt} &nbsp;|&nbsp; {ue_txt}", cell_norm)],
            [Paragraph("Status PEP:", cell_bold), Paragraph("TAK (Wymagane wzmożone środki)" if card.status_pep else "NIE", cell_norm)],
        ],
        colWidths=[140, 385],
    )
    t2.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    elements.extend([t2, Spacer(1, 8)])

    # 5. Sekcja 3: Czynniki ryzyka
    if card.risk_factors:
        elements.extend([_section_bar("3. WYKRYTE CZYNNIKI RYZYKA I ZALECENIA", sec_hdr), Spacer(1, 3)])
        rf_rows = [[Paragraph("Czynnik", cell_bold), Paragraph("Pkt", cell_bold), Paragraph("Zalecenie / Podstawa", cell_bold)]]
        for rf in card.risk_factors:
            rf_rows.append(
                [
                    Paragraph(_esc(rf.title), cell_norm),
                    Paragraph(f"+{rf.points}", cell_norm),
                    Paragraph(f"{_esc(rf.recommendation)} <i>({_esc(rf.legal_basis)})</i>", cell_norm),
                ]
            )
        t3 = Table(rf_rows, colWidths=[195, 35, 295])
        t3.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        elements.extend([t3, Spacer(1, 8)])

    # 6. Pieczęć SHA-256
    audit_seal = Table(
        [
            [
                Paragraph(
                    f"<b>KRYPTOGRAFICZNA PIECZĘĆ AUDYTOWA (SHA-256):</b><br/>"
                    f"<code>{_esc(card.sha256_hash)}</code><br/>"
                    f"Wymóg retencji dowodów: minimum 5 lat od końca roku obrotowego (art. 34 ustawy AML / art. 86 OP).",
                    footer_style,
                )
            ]
        ],
        colWidths=[525],
    )
    audit_seal.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(audit_seal)

    doc.build(elements)
    return path


def generate_batch_pdf(summary: BatchSummary, output_path: Union[str, Path]) -> Path:
    """Generuje zbiorczy raport weryfikacji wsadowej w formacie PDF (A4 pejzaż)."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    font_reg, font_bold = register_pdf_fonts()

    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=28, rightMargin=28, topMargin=22, bottomMargin=22)

    hdr_title = ParagraphStyle("RptTitle", fontName=font_bold, fontSize=11, leading=14, textColor=colors.white)
    hdr_right = ParagraphStyle("RptRight", fontName=font_bold, fontSize=8, leading=10, textColor=colors.HexColor("#F8FAFC"), alignment=2)
    tbl_hdr = ParagraphStyle("RptTblHdr", fontName=font_bold, fontSize=7, leading=9, textColor=colors.white)
    tbl_hdr_c = ParagraphStyle("RptTblHdrC", fontName=font_bold, fontSize=7, leading=9, textColor=colors.white, alignment=1)
    cell_n = ParagraphStyle("RptCN", fontName=font_reg, fontSize=7, leading=9, textColor=colors.HexColor("#334155"))
    cell_c = ParagraphStyle("RptCC", fontName=font_reg, fontSize=7, leading=9, textColor=colors.HexColor("#334155"), alignment=1)
    footer_s = ParagraphStyle("RptFS", fontName=font_reg, fontSize=6.5, leading=8.5, textColor=colors.HexColor("#64748B"))

    t_header = Table(
        [
            [
                Paragraph(
                    f"<b>COMPANYVERIFICATOR • RAPORT NALEŻYTEJ STARANNOŚCI</b><br/>"
                    f"Zadanie: <b>{_esc(summary.batch_id)}</b> • Źródło: <b>{_esc(summary.filename)}</b>",
                    hdr_title,
                ),
                Paragraph(
                    f"Podmiotów: <b>{summary.total}</b><br/>Retencja dowodowa: <b>5 LAT</b>",
                    hdr_right,
                ),
            ]
        ],
        colWidths=[560, 226],
    )
    t_header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0F172A")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements = [t_header, Spacer(1, 8)]

    headers = [
        Paragraph("LP", tbl_hdr_c),
        Paragraph("KONTRAHENT", tbl_hdr),
        Paragraph("IDENTYFIKATOR", tbl_hdr),
        Paragraph("REJESTR", tbl_hdr_c),
        Paragraph("STATUS VAT", tbl_hdr_c),
        Paragraph("RACHUNEK", tbl_hdr),
        Paragraph("SANKCJE", tbl_hdr_c),
        Paragraph("RYZYKO", tbl_hdr_c),
        Paragraph("DECYZJA", tbl_hdr_c),
    ]
    rows = [headers]
    for idx, c in enumerate(summary.cards, start=1):
        sankcje = "STOP" if (c.sankcje_mswia or c.sankcje_ue or c.sankcje_inne) else "Czysty"
        vat = "Błąd sieci" if c.blad_polaczenia else ("Czynny" if c.platnik_vat_czynny else c.status_vat)
        rows.append(
            [
                Paragraph(str(idx), cell_c),
                Paragraph(f"<b>{_esc(c.nazwa)}</b>", cell_n),
                Paragraph(_esc(c.identifier), cell_n),
                Paragraph(_esc(c.status_rejestru), cell_c),
                Paragraph(_esc(vat), cell_c),
                Paragraph(_esc(c.status_rachunku.value), cell_n),
                Paragraph(_esc(sankcje), cell_c),
                Paragraph(f"{_esc(c.poziom_ryzyka.value)} ({c.risk_score})", cell_c),
                Paragraph(_esc(c.decyzja.value), cell_c),
            ]
        )

    t_reg = Table(rows, colWidths=[22, 175, 80, 68, 75, 130, 65, 80, 91], repeatRows=1)
    t_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            t_style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC")))
    t_reg.setStyle(TableStyle(t_style))
    elements.extend([t_reg, Spacer(1, 8)])

    sha_sig = hashlib.sha256(f"{summary.batch_id}:{summary.total}:{summary.created_at}".encode("utf-8")).hexdigest()
    seal = Table(
        [[Paragraph(f"<b>PIECZĘĆ RAPORTU (SHA-256):</b> <code>{sha_sig}</code>", footer_s)]],
        colWidths=[786],
    )
    seal.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    elements.append(seal)
    doc.build(elements)
    return path
