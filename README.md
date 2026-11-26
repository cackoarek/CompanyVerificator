# CompanyVerificator — AML & Compliance Engine

> Webowa aplikacja do weryfikacji kontrahentów w ramach procedury **Należytej Staranności**
> (AML / KYB / Compliance) zgodnej z polską ustawą o przeciwdziałaniu praniu pieniędzy oraz wytycznymi Ministerstwa Finansów.

---

## Spis treści
- [Funkcje](#funkcje)
- [Wymagania i instalacja](#wymagania-i-instalacja)
- [Konfiguracja środowiska (.env)](#konfiguracja-środowiska-env)
- [Uruchomienie](#uruchomienie)
- [Testy i jakość kodu](#testy-i-jakość-kodu)
- [Architektura projektu](#architektura-projektu)
- [Rejestry, błędy przejściowe i kody odpowiedzi](#rejestry-błędy-przejściowe-i-kody-odpowiedzi)
- [Endpointy i eksport danych](#endpointy-i-eksport-danych)
- [Bezpieczeństwo i integralność danych](#bezpieczeństwo-i-integralność-danych)
- [Podstawa prawna](#podstawa-prawna)

---

## Funkcje

| Moduł | Zakres weryfikacji |
|---|---|
| **Biała Lista MF** | Status VAT (czynny / zwolniony / niezarejestrowany), identyfikator zapytania `requestId`, sprawdzanie kont bankowych zgłoszonych do MF oraz subkont masowych/wirtualnych. Obsługa retry dla okien serwisowych MF (`WL-196`). |
| **KRS / CEIDG** | Pobieranie danych rejestrowych, formy prawnej, reprezentacji (zarząd, prokurenci), kodów PKD (w tym PKD przeważającego) oraz daty rozpoczęcia działalności / rejestracji. |
| **CRBR** | Centralny Rejestr Beneficjentów Rzeczywistych — identyfikacja UBO i porównanie ze składem reprezentacji KRS. |
| **VIES** | Walidacja numerów VAT-UE dla kontrahentów z Unii Europejskiej. |
| **Listy sankcyjne** | Listy sankcyjne MSWiA oraz Unii Europejskiej (EU Sanctions Map) z deterministycznym dopasowywaniem po NIP, KRS, nazwie podmiotu oraz nazwiskach członków zarządu i UBO. |
| **Silnik ryzyka (AML)** | Deterministyczny scoring bazujący na 10 regułach prawno-podatkowych, klasyfikacja poziomu ryzyka (NISKIE, ŚREDNIE, WYSOKIE, KRYTYCZNE STOP) oraz rekomendacja decyzyjna. |
| **Raporty i audyt** | Generowanie kart audytowych w formatach PDF (A4), Markdown, JSON oraz zestawień zbiorczych CSV/PDF z pieczęcią kryptograficzną SHA-256. |
| **Weryfikacja wsadowa** | Równoległe przetwarzanie plików CSV, XLSX lub wklejonych list NIP/identyfikatorów (do 100 podmiotów jednocześnie) z podglądem postępu na żywo (HTMX). |
| **Ścieżka audytu analityka** | Możliwość manualnej zmiany decyzji (Akceptacja, Odrzucenie, Wyjaśnienie) z blokadą akceptacji dla podmiotów na listach sankcyjnych lub z błędami połączenia. |

---

## Wymagania i instalacja

### 1. Wymagania systemowe
- **Python 3.10+**
- Narzędzie do środowisk wirtualnych: `virtualenv` lub standardowy moduł `venv`
- *(Opcjonalnie)* Czcionki DejaVu (`/usr/share/fonts/truetype/dejavu/`) w systemie Linux do renderowania polskich znaków diakrytycznych w PDF (w przypadku ich braku ReportLab stosuje fallback do fontów bazowych).

### 2. Przygotowanie środowiska

```bash
# Sklonuj repozytorium i przejdź do katalogu projektu
cd /home/acacko/PycharmProjects/CompanyVerificator

# Utwórz środowisko wirtualne
python3 -m virtualenv .venv
# lub: python3 -m venv .venv
```

### 3. Zależności (do wyboru)

Repozytorium posiada podzielone pliki zależności, co pozwala uniknąć instalowania niepotrzebnych pakietów na serwerze:

- **Tylko uruchomienie (środowisko produkcyjne / minimalne):**
  ```bash
  .venv/bin/pip install -r requirements-prod.txt
  ```
  *(Instaluje wyłącznie: FastAPI, Uvicorn, Jinja2, Pydantic, python-dotenv, python-multipart, HTTPX, ReportLab, openpyxl)*

- **Środowisko deweloperskie (wraz z testami i linterami):**
  ```bash
  .venv/bin/pip install -r requirements-dev.txt
  ```
  *(Zawiera dodatkowo: pytest, pytest-asyncio, respx, ruff, mypy)*

---

## Konfiguracja środowiska (.env)

Skopiuj przykładowy plik konfiguracyjny:
```bash
cp .env.example .env
```

Dostępne parametry:

| Zmienna | Wartość domyślna | Opis |
|---|---|---|
| `CEIDG_API_TOKEN` | *(puste)* | Klucz API do Hurtowni Danych CEIDG v2 ([dane.biznes.gov.pl](https://dane.biznes.gov.pl)). Opcjonalny – w przypadku braku tokenu aplikacja pomija szczegółowe odpytywanie CEIDG bez przerywania procedury. |
| `APP_SECRET_KEY` | *(losowy)* | Klucz do zabezpieczeń sesyjnych i CSRF. |
| `APP_TOKEN` | *(puste)* | Opcjonalny token Bearer do autoryzacji zapytań API (gdy puste, dostęp jest otwarty). |
| `DB_PATH` | `data/verificator.db` | Ścieżka do lokalnej bazy danych SQLite (tryb WAL). |
| `AUDITS_DIR` | `data/audits` | Ścieżka archiwizacji wygenerowanych kart (JSON, MD, PDF). |
| `HTTP_TIMEOUT_SECONDS`| `8.0` | Timeout dla zewnętrznych zapytań do rejestrów publicznych. |
| `LOG_LEVEL` | `info` | Poziom logowania (`debug`, `info`, `warning`, `error`). |

---

## Uruchomienie

### Skrypt automatyczny
Najprostszym sposobem uruchomienia jest gotowy skrypt startowy:
```bash
chmod +x run_web.sh
./run_web.sh
```

### Uruchomienie ręczne przez Uvicorn
```bash
.venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
```

Po uruchomieniu interfejs graficzny dostępny jest pod adresem: **http://127.0.0.1:8000**

---

## Testy i jakość kodu

Aplikacja posiada pełny zestaw testów jednostkowych, integracyjnych oraz testów warstwy webowej (mockujących zewnętrzne rejestry za pomocą biblioteki `respx`):

```bash
# Uruchomienie wszystkich testów
.venv/bin/pytest tests/ -v

# Szybkie sprawdzenie linterem
.venv/bin/ruff check src/

# Sprawdzenie typów
.venv/bin/mypy src/
```

---

## Architektura projektu

Kod zorganizowany jest w warstwy odpowiedzialności (Domain-Driven / Clean Architecture):

```
CompanyVerificator/
├── src/
│   ├── config.py               # Ustawienia aplikacji, ścieżki, limity i tokeny
│   ├── main.py                 # Inicjalizacja FastAPI, middleware (CSRF, CORS, security headers)
│   ├── core/                   # Warstwa bazowa
│   │   ├── database.py         # SQLite WAL: obsługa kart, zdarzeń audytowych, sankcji i zadań wsadowych
│   │   ├── validators.py       # Algorytmy sum kontrolnych NIP, REGON, KRS, IBAN/NRB
│   │   ├── security.py         # Weryfikacja Origin/CSRF, bezpieczne przekierowania, ochrona przed brute-force
│   │   └── io.py               # Atomowe operacje zapisu plików i blokady
│   ├── domain/                 # Warstwa domenowa (czysta logika biznesowa)
│   │   ├── enums.py            # Wyliczenia: poziomy ryzyka, decyzje, statusy rejestrów i kont
│   │   ├── models.py           # Struktury danych: VerificationCard, RiskFactor, SanctionHit, BatchSummary
│   │   └── risk_engine.py      # Deterministyczny silnik oceny ryzyka AML i procedury należytej staranności
│   ├── providers/              # Klienci zewnętrznych API rejestrowych
│   │   ├── base.py             # Mechanizm retry z exponential backoff dla zapytań HTTP
│   │   ├── mf_white_list.py    # Biała Lista Podatników VAT (wyszukiwanie NIP + weryfikacja konta)
│   │   ├── krs_client.py       # API Ministerstwa Sprawiedliwości (odpis aktualny KRS: rejestr P i S)
│   │   ├── crbr_client.py      # Centralny Rejestr Beneficjentów Rzeczywistych
│   │   ├── ceidg_client.py     # API Hurtowni Danych CEIDG v2
│   │   ├── vies_client.py      # Komisja Europejska – VIES REST API
│   │   └── sanctions/          # Moduł sankcyjny (parsowanie XML/HTML + silnik dopasowań)
│   ├── reports/                # Generowanie artefaktów dowodowych
│   │   ├── hash_utils.py       # Kanoniczne hashowanie karty SHA-256 (wykluczające decyzje analityka)
│   │   ├── markdown_generator.py
│   │   └── pdf_generator.py    # ReportLab: Karta weryfikacji A4 (pion) i raporty wsadowe (poziom)
│   ├── services/               # Orkiestracja procesów biznesowych
│   │   ├── verification_service.py # Główny proces weryfikacji pojedynczego kontrahenta
│   │   ├── batch_service.py        # Współbieżna weryfikacja wsadowa (CSV/XLSX) z semaforem
│   │   └── audit_service.py        # Zarządzanie decyzjami analityka i historią zmian
│   └── web/                    # Warstwa prezentacji (FastAPI + Jinja2 + HTMX)
│       ├── routers/            # Trasy: / (verify), /wsadowa, /historia, /rejestry
│       ├── templates/          # Szablony HTML oparte o TailwindCSS
│       └── static/             # Zasoby frontendowe: CSS, JS (htmx.min.js, alpine.min.js)
├── tests/                      # Zestaw testów automatycznych
├── requirements-prod.txt       # Zależności produkcyjne (minimalne)
├── requirements-dev.txt        # Zależności deweloperskie i testowe
├── run_web.sh                  # Skrypt uruchomieniowy
└── workplan.md                 # Szczegółowy plan techniczny wdrożenia
```

---

## Rejestry, błędy przejściowe i kody odpowiedzi

Aplikacja została wyposażona w mechanizmy odporności na typowe zakłócenia w działaniu systemów państwowych:

1. **Aktualizacje bazy MF (błąd `WL-196`):**
   - Ministerstwo Finansów w godzinach nocnych lub serwisowych zwraca kod HTTP 400 z ciałem `{"code": "WL-196", "message": "Trwa aktualizacja bazy danych..."}`.
   - Provider automatycznie ponawia próbę po krótkim odstępie czasu, a w razie trwającej niedostępności oznacza stan jako `MF_NIEDOSTEPNY_CHWILOWO`, nie traktując tego jako błąd kontrahenta.
2. **Konta wirtualne i subkonta masowe:**
   - W przypadku braku konta na głównej liście Białej Listy, system automatycznie odpytuje endpoint `/api/check/nip/{nip}/bank-account/{acc}`, co pozwala na potwierdzenie rachunków powiązanych (np. Alior Bank, mBank, itp.).
3. **Graceful degradation dla CEIDG:**
   - Brak tokena API nie powoduje awarii – podmiot JDG jest identyfikowany przez Białą Listę MF, a użytkownik otrzymuje czytelną wskazówkę o opcjonalnej konfiguracji tokena.

---

## Endpointy i eksport danych

Poza interfejsem webowym dane z weryfikacji dostępne są w postaci maszynowej:

| Ścieżka | Format | Opis |
|---|---|---|
| `GET /karta/{id}` | HTML | Szczegółowy widok karty z historią decyzji analityka. |
| `GET /karta/{id}/pdf` | PDF | Oficjalny raport weryfikacyjny z pieczęcią SHA-256 gotowy do archiwizacji. |
| `GET /karta/{id}/md` | Markdown | Tekstowy raport z podsumowaniem i czynnikami ryzyka. |
| `GET /karta/{id}/json` | JSON | Pełny zrzut danych domenowych i dowodowych (`raw_evidence`). |
| `POST /karta/{id}/decision` | Formularz | Zapis decyzji analityka (Akceptacja, Odrzucenie, Wyjaśnienie). |
| `GET /wsadowa/{batch_id}/status` | HTML | Fragment HTMX do monitorowania postępu weryfikacji zbiorczej. |
| `GET /wsadowa/{batch_id}/csv` | CSV | Zbiorcze zestawienie wyników dla przetworzonego pliku wsadowego. |
| `GET /wsadowa/{batch_id}/pdf` | PDF | Zbiorczy raport tabelaryczny w formacie A4 landscape. |

---

## Bezpieczeństwo i integralność danych

- **Kryptograficzny stempel SHA-256:** Każda karta weryfikacyjna posiada unikalny hash wyliczany z kanonicznego zrzutu danych dowodowych pobranych z rejestrów. Hash ten nie ulega unieważnieniu po dopisaniu notatki analityka.
- **CSRF & Origin Protection:** Middleware sprawdza nagłówki `Origin` i `Referer` dla metod modyfikujących stan (`POST`).
- **Ochrona przed Open Redirect:** Parametry przekierowań są walidowane pod kątem ścieżek relatywnych należących wyłącznie do bieżącej domeny.
- **Zabezpieczenie przed XSS:** Wszystkie dane wejściowe i odpowiedzi rejestrów w szablonach Jinja2 są automatycznie sanitowane.
- **Blokada zatwierdzania podmiotów zablokowanych:** Silnik uniemożliwia zatwierdzenie kontrahenta, na którym ciążą sankcje międzynarodowe lub dla którego nie udało się pobrać danych (ochrona przed ominięciem procedury).

---

## Podstawa prawna

Procedury i wagi ryzyka zaimplementowane w silniku aplikacji odpowiadają polskim i europejskim wymogom prawnym:
- **Ustawa z dnia 1 marca 2018 r. o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu** (Dz.U. z 2023 r. poz. 1124 ze zm.) – procedury identyfikacji klienta, weryfikacji tożsamości, badania beneficjentów rzeczywistych (UBO) i statusu PEP.
- **Ustawa z dnia 11 marca 2004 r. o podatku od towarów i usług** (Biała Lista Podatników VAT, art. 96b) oraz mechanizm podzielonej płatności (MPP / Split Payment).
- **Ustawa z dnia 13 kwietnia 2022 r. o szczególnych rozwiązaniach w zakresie przeciwdziałania wspieraniu agresji na Ukrainę** (Dz.U. poz. 835) – krajowa lista sankcyjna MSWiA.
- **Rozporządzenia Rady (UE)** w sprawie środków ograniczających w związku z działaniami destabilizującymi sytuację na Ukrainie (reżim sankcyjny UE).
- **Wytyczne Ministerstwa Finansów** dotyczące dochowania należytej staranności przez nabywców towarów w transakcjach krajowych.
