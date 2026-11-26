# 🧠 Silnik Ryzyka AML & Scoring Należytej Staranności

Dokument przedstawia metodykę oceny ryzyka, strukturę scoringu punktowego, katalog reguł prawno-podatkowych oraz zasady automatycznego podejmowania decyzji w module [`src/domain/risk_engine.py`](file:///home/acacko/PycharmProjects/CompanyVerificator/src/domain/risk_engine.py).

---

## 🎯 Cel i Podstawa Metodyczna

Silnik ryzyka realizuje wymagania:
- **Art. 34–43 ustawy z dnia 1 marca 2018 r. o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu (AML)**,
- **Krajowej Oceny Ryzyka Prania Pieniędzy (KOR)** opracowanej przez Generalnego Inspektora Informacji Finansowej (GIIF),
- **Wytycznych Ministerstwa Finansów w sprawie dochowania Należytej Staranności przez nabywców towarów w transakcjach krajowych**.

Ocena ma charakter deterministyczny i audytowalny — każda decyzja posiada przypisaną listę zidentyfikowanych czynników ryzyka wraz z podstawą prawną i rekomendacją postępowania dla analityka.

---

## 🚦 Klasyfikacja Poziomów Ryzyka i Matryca Decyzyjna

Łączny wynik punktowy (`risk_score`) podmiotu determinuje poziom ryzyka oraz wstępną rekomendację systemową:

| Poziom Ryzyka | Zakres Punktowy | Rekomendacja Systemowa | Kolor w UI | Wymagane Działania |
| :--- | :---: | :---: | :---: | :--- |
| 🟢 **NISKIE** | **0 – 14 pkt** | **AKCEPTACJA** | Zielony | Kontrahent spełnia standardowe kryteria bezpieczeństwa. Dopuszczalna procedura Standardowej Należytej Staranności (SDD). |
| 🟡 **ŚREDNIE** | **15 – 39 pkt** | **WYMAGA WYJAŚNIENIA** | Żółty | Wykryto umiarkowane czynniki (np. branża wrażliwa, krótki staż). Wymaga standardowego monitoringu transakcji. |
| 🟠 **WYSOKIE** | **40 – 99 pkt** | **WARUNKOWO / WYJAŚNIENIE** | Pomarańczowy | Wykryto istotne przesłanki ryzyka (np. brak czynnego VAT, brak CRBR, wirtualne biuro). Wymagana procedura Wzmożonej Należytej Staranności (EDD). |
| 🛑 **KRYTYCZNE (STOP)** | **≥ 100 pkt** | **ODMOWA WSPÓŁPRACY (STOP)** | Czerwony | Bezwzględny zakaz nawiązywania relacji i realizacji płatności (obecność na liście sankcyjnej MSWiA/UE). |

---

## 📊 Matryca Czynników Ryzyka (Risk Factors Catalog)

Poniższa tabela przedstawia reguły weryfikowane przez silnik:

| Kod Reguły | Nazwa / Przesłanka Ryzyka | Waga Punktowa | Poziom | Podstawa Prawna / Metodyka |
| :--- | :--- | :---: | :---: | :--- |
| `SANCTIONS_HIT` | **Figurowanie na liście sankcyjnej (MSWiA / UE)** | **+100 pkt** | KRYTYCZNE | Ustawa z dnia 13.04.2022 r. o szczególnych rozwiązaniach... / Rozporządzenia UE |
| `REGISTRY_INACTIVE` | **Brak wpisu w rejestrze (KRS/CEIDG) lub status NIEZNALEZIONY** | **+60 pkt** | WYSOKIE | Art. 96b / 86 ustawy o VAT |
| `INSOLVENCY_OR_LIQUIDATION` | **Podmiot w stanie likwidacji, upadłości lub restrukturyzacji** | **+60 pkt** | WYSOKIE | Metodyka Należytej Staranności MF |
| `VAT_NOT_ACTIVE` | **Brak statusu czynnego podatnika VAT (Biała Lista)** | **+25 pkt** | ŚREDNIE | Art. 88 ust. 3a oraz art. 96b ustawy o VAT |
| `BANK_ACCOUNT_NOT_ON_WHITELIST` | **Rachunek bankowy niewidoczny na Białej Liście (dla kwot > 15 000 zł)** | **+40 pkt** | WYSOKIE | Art. 19 Prawa przedsiębiorców / art. 22p ustawy o PIT |
| `CRBR_MISSING` | **Brak wymaganego wpisu w rejestrze UBO (CRBR)** | **+30 pkt** | WYSOKIE | Art. 58-61 ustawy AML (obowiązek zgłoszenia beneficjenta) |
| `CRBR_DISCREPANCY` | **Rozbieżność pomiędzy UBO w CRBR a reprezentacją w KRS** | **+20 pkt** | ŚREDNIE | Art. 68 ustawy AML (zgłaszanie rozbieżności) |
| `COMPANY_AGE_CRITICAL` | **Bardzo młody staż rynkowy (< 6 miesięcy)** | **+25 pkt** | ŚREDNIE | Wytyczne GIIF i KOR (ryzyko podmiotu fasadowego) |
| `COMPANY_AGE_MODERATE` | **Młody staż rynkowy (6 – 12 miesięcy)** | **+15 pkt** | ŚREDNIE | Wytyczne GIIF i KOR |
| `SENSITIVE_INDUSTRY_VAT` | **Branża wrażliwa podatkowo (Załącznik nr 15 do VAT / KOR GIIF)** | **+15 – 25 pkt** | ŚREDNIE | Paliwa, elektronika, stal, surowce wtórne, nieruchomości |
| `VIRTUAL_OFFICE_ADDRESS` | **Adres siedziby pod adresem biura wirtualnego / masowego** | **+20 pkt** | ŚREDNIE | Wskaźniki ryzyka transakcyjnego GIIF |
| `PEP_STATUS_DETECTED` | **Osoba w organach lub UBO posiadająca status PEP** | **+30 pkt** | WYSOKIE | Art. 46 ustawy AML (wzmożone środki bezpieczeństwa) |
| `RELATION_CHANNEL_REMOTE` | **Nawiązanie relacji gospodarczej na odległość (kanał zdalny)** | **+3 pkt** | NISKIE | Wytyczne KYC GIIF (kryterium kanału dystrybucji) |

---

## 🏢 Specjalne Ścieżki Proceduralne (Exemptions & SDD)

Aplikacja implementuje automatyczne ścieżki łagodzące i zwalniające zgodnie z polskim prawem:

### 1. Spółki Publiczne notowane na GPW i NewConnect
- **Zwolnienie z CRBR:** Zgodnie z **art. 58 ustawy AML**, spółki publiczne podlegające wymogom ujawniania informacji zgodnie z przepisami prawa UE nie podlegają obowiązkowi zgłaszania UBO do CRBR.
- **SDD (Uproszczona Należyta Staranność):** Zgodnie z **art. 42 ust. 1 pkt 1 ustawy AML**, spółka giełdowa otrzymuje automatycznie status `PUBLIC_COMPANY_GPW`. Silnik wyłącza penalizację za brak wpisu w CRBR, a poziom ryzyka bazowego wynosi `0 pkt (🟢 NISKIE)`.

### 2. Członkowie Grup VAT
- Podmioty wchodzące w skład zarejestrowanej Grupy VAT (zgodnie z **art. 96 ust. 7ba ustawy o VAT**) posiadają status `Członek Grupy VAT`.
- Silnik identyfikuje adnotację Białej Listy i nie traktuje podmiotu jako niezarejestrowanego podatnika VAT.

### 3. Organizacje Pozarządowe i Fundacje (NGO)
- Podmioty realizujące działalność statutową zwolnioną podmiotowo z VAT (np. WOŚP, fundacje charytatywne) ze statusem `Zwolniony` nie są penalizowane jak podmioty wykreślone z rejestru.

---

## 📝 Ścieżka Nadpisań Analityka (Analyst Overrides)

Aplikacja gwarantuje pełną rozliczalność decyzji zgodnie z wymaganiami KNF i audytu:
1. **Domyślny stan:** Każda karta jest generowana ze statusem `AUTO`.
2. **Manualne zatwierdzenie:** Analityk może zmienić decyzję na `AKCEPTACJA`, `WARUNKOWO` lub `ODMOWA_WSPOLPRACY_STOP`, podając uzasadnienie tekstowe w formularzu.
3. **Bezwzględna blokada (Hard Stop):**
   - Jeśli podmiot figuruje na liście sankcyjnej (`sankcje_hit = True`), system rzuca błąd `400 Bad Request` i uniemożliwia manualne zatwierdzenie kontrahenta.
   - Jeśli w trakcie weryfikacji wystąpił błąd krytyczny sieci (`blad_polaczenia = True`), zatwierdzenie jest zablokowane do czasu ponowienia badania.
4. **Audit Trail:** Każda zmiana jest rejestrowana w tabeli `audit_events` wraz ze znacznikiem czasu, adresem IP, starą i nową decyzją oraz notatką.
