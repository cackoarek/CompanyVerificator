# Plan pracy – Projekt `CompanyVerificator` (Moduł Compliance, AML & Należyta Staranność)

Dokument powstał na podstawie analizy modułu **Compliance & AML** w projekcie `TaxPilot_AI` (`/home/acacko/PycharmProjects/TaxPilot_AI`) i stanowi plan budowy dedykowanej, samodzielnej aplikacji webowej w Pythonie do weryfikacji firm w procedurze należytej staranności.

---

## 1. Analiza modułu „Compliance & AML” w `TaxPilot_AI`

### 1.1. Architektura i kluczowe komponenty źródłowe
Moduł w `TaxPilot_AI` jest rozdzielony między logikę domenową, integrację z rejestrami i warstwę webową:
- **`src/skills/aml_tools.py`** – deterministyczny silnik weryfikacji (`AMLVerificationEngine`), obsługa list sankcyjnych (`check_sanctions`), model danych karty (`KartaWeryfikacjiKontrahenta`), raport miesięczny (`MiesiecznyRaportWeryfikacji`) oraz orkiestrator wsadowy (`VerificationService`).
- **`src/level_1_ingestion/company_fetcher.py`** – klient HTTP (`CompanyFetcher`) dla Białej Listy Podatników VAT MF (`/api/search/nip` oraz `/api/check/nip/{nip}/bank-account/{acc}` dla rachunków wirtualnych) i Hurtowni Danych CEIDG v2.
- **`src/core/validators.py`** – deterministyczne algorytmy sum kontrolnych (`validate_nip`, `validate_regon`, `validate_nrb`).
- **`src/core/io.py`** – atomowe zapisy na dysk i blokady plikowe (`atomic_write_text`, `atomic_write_json`, `file_lock`).
- **`src/web/routers/aml.py` + `src/web/templates/`** – interfejs FastAPI + Jinja2 + HTMX + Alpine.js + TailwindCSS (`pages/aml.html`, `partials/aml_card_result.html`, `partials/aml_table_rows.html`) z eksportem kart i raportów do PDF (ReportLab) oraz Markdown.
- **`src/web/app.py` i `src/web/utils/security.py`** – mechanizmy bezpieczeństwa warstwy web (nagłówki HTTP/CSP, ochrona CSRF po `Origin`/`Referer`, opcjonalny token dostępowy z rate-limitingiem i stałoczasowym porównaniem).

### 1.2. Rozwiązania warte przeniesienia do `CompanyVerificator`
1. **Zasada Zero-Hallucination** – cała logika oceny ryzyka, walidacji identyfikatorów i obliczeń kwotowych (`Decimal`) realizowana deterministycznie w Pythonie, bez udziału LLM w podejmowaniu decyzji compliance.
2. **Obsługa rachunków wirtualnych (subkont masowych płatności)** – dwuetapowe sprawdzanie rachunku: najpierw lista rachunków z `search/nip`, a przy braku trafienia dedykowany endpoint MF `check/nip/{nip}/bank-account/{acc}`.
3. **Jawne rozróżnienie błędów sieci od negatywnego statusu w rejestrze** – flaga `blad_polaczenia` uniemożliwia błędne oznaczenie firmy jako nieistniejącej podczas awarii API oraz chroni cache przed „zatruciem” niekompletnymi wynikami.
4. **Dwupoziomowy cache z opcją wymuszenia (`force`)** – pamięć sesji + trwałe archiwum na dysku, bez powielania zapytań do API dla tego samego podmiotu.
5. **Urzędowa dokumentacja dowodowa (Audit Trail)** – generowanie indywidualnej Karty Weryfikacji Kontrahenta (PDF A4 + Markdown + JSON) oraz raportu zbiorczego (PDF A4 landscape) z kryptograficzną sumą kontrolną SHA-256 i wymogiem 5-letniej retencji (art. 34 ustawy AML, art. 86 Ordynacji podatkowej, art. 22p PIT, art. 117ba Ordynacji podatkowej).
6. **Lekki, szybki stos Server-Driven UI** – FastAPI + Jinja2 + HTMX + Alpine.js, brak ciężkiego frontendowego builda SPA, wygodne partiale HTMX.

### 1.3. Zidentyfikowane luki i ograniczenia w `TaxPilot_AI` (do naprawy w nowym projekcie)
1. **Statyczne (hardcoded) listy sankcyjne** – `KNOWN_SANCTIONS_NIPS`, `KNOWN_SANCTIONS_NAMES`, `KNOWN_SANCTIONS_PERSONS` zawierają jedynie kilkanaście wpisów przykładowych. Brak automatycznej synchronizacji oficjalnych list MSWiA, EU Consolidated Financial Sanctions oraz OFAC/KNF.
2. **Brak realnych integracji z KRS i CRBR** – dla spółek handlowych silnik wstawia obecnie stałe komunikaty opisowe (`"ZGODNY"`, `"Zarząd zgodnie z odpisem KRS"`), bez odpytywania otwartego API KRS (`api-krs.ms.gov.pl`) oraz rejestru beneficjentów rzeczywistych (CRBR).
3. **Brak weryfikacji VIES dla kontrahentów z UE** – podmioty zagraniczne są oznaczane optymistycznie jako aktywni podatnicy VAT-UE bez odpytania systemu VIES Komisji Europejskiej.
4. **Nieużywane pole `status_pep` oraz gubiony `requestId` MF** – pole PEP nie ma mechanizmu deklaracji/weryfikacji, a `CompanyFetcher.check_bank_account_mf` zwraca `request_id` MF, który nie jest utrwalany w karcie dowodowej (a stanowi istotny dowód w kontroli KAS).
5. **Brak pełnej walidacji sum kontrolnych przed wywołaniem API** – `AMLVerificationEngine` sprawdza jedynie długość/cyfry NIP zamiast wywoływać `validate_nip` i `validate_nrb`.
6. **Hash SHA-256 liczony tylko z 5 pól nagłówkowych** – nie obejmuje surowych odpowiedzi rejestrów, statusu VAT ani numeru rachunku, przez co nie chroni integralności całego dowodu audytowego.
7. **Synchroniczne `requests.get` wewnątrz tras `async def` FastAPI** – blokuje pętlę zdarzeń przy wolnych odpowiedziach API rządowych.
8. **Silne powiązanie z kontekstem faktur JDG (`CompanyProfile` / katalog `firmy/`)** – brak niezależnej bazy historii weryfikacji, filtrowania, kolejki zadań wsadowych oraz workflow akceptacji/wyjaśnienia przez użytkownika (notatka compliance, decyzja ręczna po wyjaśnieniu).
9. **Brak atomowego zapisu w `aml_tools.py`** – pliki raportów i kart zapisywane standardowym `open()` mimo istnienia `src/core/io.py`.

---

## 2. Architektura docelowa `CompanyVerificator`

### 2.1. Stos technologiczny
- **Backend & Web**: Python 3.11+, FastAPI, Uvicorn, Pydantic v2, Jinja2, HTMX 2.x, Alpine.js 3.x, TailwindCSS (lokalny build CSS lub spakietowany asset bez twardej zależności od CDN).
- **Klient HTTP**: `httpx.AsyncClient` (asynchroniczne, równoległe odpytywanie rejestrów z timeoutami, retry/backoff i rate-limitingiem).
- **Persystencja i audyt**:
  - **SQLite** (np. SQLAlchemy 2.0 / SQLModel) – rejestr firm, historia weryfikacji, kolejki wsadowe, decyzje analityka, metadane synchronizacji list sankcyjnych.
  - **Archiwum dowodowe na dysku** (z `atomic_write_*`) – surowe odpowiedzi JSON z API (z `requestId`), karty PDF/MD oraz raporty zbiorcze dla 5-letniej retencji.
- **Generowanie dokumentów**: ReportLab (PDF A4 z polskimi czcionkami DejaVu/Liberation), eksport JSON / Markdown / CSV.
- **Jakość i testy**: `pytest`, `pytest-asyncio`, `respx` (hermetyczne mockowanie `httpx`), `ruff`, `mypy`.

### 2.2. Proponowana struktura katalogów
```text
CompanyVerificator/
├── pyproject.toml
├── .env.example
├── workplan.md
├── Dockerfile
├── docker-compose.yml
├── src/
│   ├── main.py                     # Punkt wejścia FastAPI + lifespan
│   ├── config.py                   # Konfiguracja (ścieżki, tokeny API, limity, retencja)
│   ├── core/
│   │   ├── validators.py           # NIP, REGON, KRS, NRB/IBAN, VAT-UE
│   │   ├── io.py                   # Atomowy zapis i blokady plikowe
│   │   ├── security.py             # CSRF, nagłówki, auth token, sanityzacja uploadów
│   │   └── database.py             # Połączenie SQLite i schemat tabel
│   ├── domain/
│   │   ├── enums.py                # PoziomRyzykaAML, DecyzjaWspolpracy, StatusRejestru...
│   │   ├── models.py               # VerificationCard, BatchReport, RiskFactor, AuditEvent
│   │   └── risk_engine.py          # Deterministyczna matryca ryzyka i reguły należytej staranności
│   ├── providers/
│   │   ├── base.py                 # Wspólny interfejs i obsługa błędów/timeoutów
│   │   ├── mf_white_list.py        # Biała Lista MF (search + check bank account + requestId)
│   │   ├── krs_client.py           # Otwarte API KRS (odpis aktualny, zarząd, upadłość/likwidacja)
│   │   ├── crbr_client.py          # Integracja CRBR (beneficjenci rzeczywiści + porównanie z KRS)
│   │   ├── ceidg_client.py         # Hurtownia Danych CEIDG v2 (status JDG, PKD)
│   │   ├── vies_client.py          # Weryfikacja VAT-UE (VIES)
│   │   └── sanctions/
│   │       ├── sync_service.py     # Pobieranie i parsowanie list MSWiA, EU Sanctions, OFAC/KNF
│   │       └── matcher.py          # Normalizacja nazw, tokenizacja i deterministyczne dopasowanie
│   ├── services/
│   │   ├── verification_service.py # Orkiestracja równoległego sprawdzenia 1 podmiotu
│   │   ├── batch_service.py        # Weryfikacja wsadowa (CSV/XLSX/lista NIP) + śledzenie postępu
│   │   └── audit_service.py        # Zarządzanie decyzjami użytkownika, historią i retencją
│   ├── reports/
│   │   ├── markdown_generator.py   # Karty i raporty Markdown
│   │   ├── pdf_generator.py        # Karty indywidualne i raporty zbiorcze PDF (ReportLab)
│   │   └── hash_utils.py           # Kanoniczny hash SHA-256 całego pakietu dowodowego
│   └── web/
│       ├── routers/                # dashboard, verify, batch, history, sanctions, settings
│       ├── templates/              # base.html, pages/*, partials/*, components/*
│       └── static/                 # css, js (htmx, alpine), ikony, czcionki
└── tests/
    ├── unit/                       # Walidatory, matcher sankcji, risk_engine, hash_utils
    ├── providers/                  # Hermetyczne testy parserów (respx / fixtures JSON/XML)
    ├── integration/                # End-to-end service + DB + generowanie PDF
    └── web/                        # TestClient FastAPI, HTMX, CSRF, XSS, auth
```

---

## 3. Etapy realizacji (Plan pracy)

### Etap 0: Inicjalizacja projektu i fundament techniczny
- [ ] Utworzenie `pyproject.toml` z zależnościami (`fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `httpx`, `pydantic`, `sqlalchemy`/`sqlite`, `reportlab`, `openpyxl` do XLSX, oraz `pytest`, `respx`, `ruff`, `mypy`).
- [ ] Skonfigurowanie zmiennych środowiskowych (`.env.example`, `src/config.py`) oraz centralnego logowania bez wycieku danych wrażliwych.
- [ ] Przeniesienie i rozszerzenie `core/io.py` (atomowe operacje dyskowe) oraz `core/security.py` (CSP, CSRF Origin check, rate limiting, opcjonalny token dostępu).
- [ ] Zaprojektowanie i utworzenie bazy SQLite (tabele: `verifications`, `batch_jobs`, `audit_events`, `sanction_entries`, `sanction_sync_log`).

### Etap 1: Rdzeń walidacji i model oceny ryzyka (Zero-Hallucination)
- [ ] Rozszerzenie `core/validators.py` o:
  - ścisłą walidację NIP (z kontrolą sumy kontrolnej i flagą dla trybu deweloperskiego),
  - walidację KRS (10 cyfr), REGON (9/14), NRB/IBAN PL (modulo 97-10) oraz formatów zagranicznych VAT-UE,
  - detekcję i klasyfikację identyfikatora wejściowego (NIP / KRS / VAT-UE).
- [ ] Zdefiniowanie modeli domenowych (`VerificationCard`, `RiskFactor`, `ProviderResult`, `BatchSummary`) oraz statusów procedury należytej staranności.
- [ ] Implementacja deterministycznego silnika ryzyka (`risk_engine.py`) z jawną listą czynników ryzyka (waga + podstawa prawna + zalecenie), obejmującego:
  - trafienia sankcyjne (MSWiA / UE / OFAC) -> natychmiastowe `KRYTYCZNE_STOP`,
  - błędy sieci / niekompletność rejestrów -> blokada zatwierdzenia (`NIEKOMPLETNA`),
  - status w rejestrze (wykreślony, zawieszony, w upadłości/likwidacji, brak wpisu),
  - wiek podmiotu (krótki staż działalności – sygnał ostrzegawczy należytej staranności VAT),
  - status VAT (czynny, zwolniony, wykreślony z rejestru VAT),
  - rachunek bankowy na Białej Liście MF vs próg 15 000 PLN (art. 22p PIT / art. 117ba OP) i wskazanie Split Payment (MPP),
  - spójność reprezentacji i UBO (KRS vs CRBR),
  - kody PKD wysokiego ryzyka AML oraz status PEP.
- [ ] Kanoniczne obliczanie SHA-256 z pełnego zrzutu JSON dowodu (`hash_utils.py`).

### Etap 2: Integracje z rejestrami publicznymi i listami sankcyjnymi (Async)
- [ ] **Biała Lista VAT MF (`mf_white_list.py`)**: asynchroniczne `search/nip` oraz `check/nip/{nip}/bank-account/{acc}` z zapisem `requestId` MF i rozróżnieniem kodów HTTP (200 / 404 / 429 / 5xx / timeout).
- [ ] **KRS API (`krs_client.py`)**: pobieranie odpisu aktualnego (`api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P&format=json`), ekstrakcja formy prawnej, daty rejestracji, statusu (upadłość/likwidacja), PKD oraz składu zarządu/prokurentów.
- [ ] **CRBR (`crbr_client.py`)**: integracja wyszukiwania beneficjentów rzeczywistych (UBO) dla spółek oraz automatyczna weryfikacja istnienia wpisu / spójności danych z KRS.
- [ ] **CEIDG v2 (`ceidg_client.py`)**: obsługa klucza `CEIDG_API_TOKEN` dla JDG (data rozpoczęcia, status aktywny/zawieszony/wykreślony, kody PKD).
- [ ] **VIES (`vies_client.py`)**: weryfikacja aktywności zagranicznych numerów VAT-UE (SOAP/REST Komisji Europejskiej) z obsługą niedostępności usługi krajowej.
- [ ] **Moduł list sankcyjnych (`providers/sanctions/`)**:
  - parser i synchronizator oficjalnych źródeł (polska lista MSWiA, unijna lista EU Consolidated Financial Sanctions, opcjonalnie OFAC SDN / lista ostrzeżeń publicznych KNF) zapisywanych w SQLite z datą ostatniej aktualizacji,
  - deterministyczny silnik dopasowania po NIP, KRS, znormalizowanej nazwie firmy oraz osobach z zarządu/UBO pobranych z KRS/CRBR (z podziałem na pewne trafienie vs potencjalna zbieżność do weryfikacji analityka).

### Etap 3: Orkiestracja weryfikacji i obsługa procesów wsadowych
- [ ] **`VerificationService`**: równoległe odpytywanie właściwych rejestrów dla typu podmiotu (`asyncio.gather`), obsługa cache (in-memory + SQLite/dysk z TTL i flagą `force`), zachowanie pełnych surowych odpowiedzi API.
- [ ] **`BatchService`**: import listy podmiotów z CSV / XLSX / tekstu (kolumny: NIP/VAT-UE, opcjonalnie nazwa, rachunek bankowy, kwota transakcji), deduplikacja po NIP, kontrola współbieżności (`asyncio.Semaphore`, respektowanie limitów API MF), śledzenie postępu zadania.
- [ ] **`AuditService`**: rejestrowanie zdarzeń audytowych (kto, kiedy, z jakiego powodu zmienił decyzję po uzyskaniu wyjaśnień od kontrahenta), obsługa załączania notatki compliance do teczki kontrahenta.

### Etap 4: Raportowanie i dowody audytowe
- [ ] Przeniesienie i rozbudowa generatora **Kart Weryfikacji Kontrahenta (PDF A4)** oraz **Zbiorczych Raportów Weryfikacji (PDF A4 pejzaż)** w ReportLab:
  - dodanie sekcji: `requestId` z API MF, szczegółowe wyniki KRS i CRBR (zarząd, UBO), lista wykrytych czynników ryzyka (Risk Matrix), deklaracja PEP oraz historia decyzji analityka.
- [ ] Generowanie eksportów **Markdown**, **JSON** (z pełnym zrzutem dowodowym i SHA-256) oraz **CSV** (dla raportów wsadowych).
- [ ] Zapisywanie paczek dowodowych w ustrukturyzowanym archiwum (np. `data/audits/{ROK}/{MIESIAC}/{NIP}/`) za pomocą atomowych operacji I/O.

### Etap 5: Interfejs Web (FastAPI + Jinja2 + HTMX + Alpine.js)
- [ ] **Layout bazowy i nawigacja**: przejrzysty dashboard dla zespołu compliance/księgowości, wskaźnik aktualności baz sankcyjnych, brak twardych zależności uniemożliwiających pracę lokalną.
- [ ] **Widok 1 – Weryfikacja pojedynczej firmy (`/`)**:
  - formularz: NIP / KRS / VAT-UE, opcjonalnie rachunek bankowy, kwota brutto PLN, checkbox deklaracji PEP / transakcji podwyższonego ryzyka, checkbox `Wymuś odpytanie na żywo`,
  - walidacja sum kontrolnych w locie, prezentacja wyniku przez HTMX wraz z rozbiciem na rejestry (MF, KRS, CRBR, CEIDG, VIES, Sankcje), matrycą ryzyk, `requestId`, hash SHA-256 i przyciskami pobrania PDF/MD/JSON.
- [ ] **Widok 2 – Weryfikacja wsadowa (`/wsadowa`)**:
  - upload pliku CSV/XLSX lub wklejenie listy NIP-ów,
  - pasek postępu w czasie rzeczywistym (HTMX polling), tabela wyników z podświetleniem ryzyk krytycznych/średnich, pobieranie zbiorczego raportu PDF/CSV oraz paczki kart.
- [ ] **Widok 3 – Rejestr i historia weryfikacji (`/historia`)**:
  - wyszukiwarka po NIP/nazwie, filtry (poziom ryzyka, status decyzji, tryb offline, zakres dat),
  - podgląd szczegółów karty, przycisk ponownej weryfikacji na żywo, formularz decyzji compliance (np. oznaczenie jako „Wyjaśniono – ZAW-NR złożony” z zapisem w Audit Trail).
- [ ] **Widok 4 – Źródła danych i listy sankcyjne (`/rejestry`)**:
  - status połączenia z MF / KRS / CRBR / VIES / CEIDG,
  - liczba wpisów na listach sankcyjnych, data ostatniej synchronizacji, przycisk ręcznej aktualizacji list oraz konfiguracja parametrów (np. klucz CEIDG, progi ostrzeżeń).

### Etap 6: Testy, hardening bezpieczeństwa i wdrożenie
- [ ] Testy jednostkowe walidatorów, silnika ryzyka, dopasowania sankcji i sum SHA-256.
- [ ] Hermetyczne testy providerów (`respx` z realistycznymi fixture'ami odpowiedzi MF, KRS, CRBR, CEIDG, VIES, list sankcyjnych XML/CSV) – w tym scenariusze 404, 429, 500 i timeoutów.
- [ ] Testy integracyjne `VerificationService` i `BatchService` z bazą SQLite i generowaniem PDF.
- [ ] Testy warstwy Web (`TestClient`): endpointy HTML/HTMX, pobieranie PDF/MD/JSON, testy bezpieczeństwa (CSRF, XSS w danych firm z rejestrów, autoryzacja tokenem, walidacja plików CSV/XLSX).
- [ ] Przygotowanie `Dockerfile`, `docker-compose.yml` (z wolumenem dla bazy SQLite i 5-letniego archiwum dowodów) oraz `README.md` z instrukcją uruchomienia.

---

## 4. Kryteria akceptacji (Definition of Done)
1. Każda weryfikacja firmy jest w 100% deterministyczna, odtwarzalna i opatrzona kompletem dowodów (`requestId` z MF, zrzut danych rejestrowych, znacznik czasu UTC, SHA-256).
2. Żaden błąd sieciowy lub niedostępność API nie skutkuje fałszywie pozytywnym wynikiem („NISKIE RYZYKO”) ani nie zatruwa cache.
3. Spółki prawa handlowego mają realnie weryfikowaną reprezentację (KRS), beneficjentów rzeczywistych (CRBR) oraz powiązane osoby na listach sankcyjnych.
4. Aplikacja webowa umożliwia zarówno szybkie sprawdzenie ad-hoc przed przelewem, jak i masową weryfikację kontrahentów z pliku wraz z archiwizacją i audytowalną historią decyzji.
5. Zestaw testów automatycznych (`pytest`), lintera (`ruff`) oraz typowania (`mypy`) przechodzi bez błędów.
