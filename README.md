# CompanyVerificator — AML & Compliance Engine

> Webowa aplikacja do weryfikacji kontrahentów w ramach procedury **Należytej Staranności**
> (AML / KYB / Compliance) zgodnej z ustawą o przeciwdziałaniu praniu pieniędzy i finansowaniu terroryzmu.

---

## Funkcje

| Moduł | Opis |
|---|---|
| **Biała Lista MF** | Weryfikacja VAT-czynny + rachunki bankowe zgłoszone do MF |
| **KRS / CEIDG** | Pobieranie danych rejestrowych, formy prawnej, zarządu, PKD |
| **CRBR** | Beneficjenci rzeczywiści — porównanie z danymi KRS |
| **VIES** | Walidacja numerów VAT-UE dla podmiotów zagranicznych |
| **Listy sankcyjne** | MSWiA + EU Sanctions List — deterministyczny matcher NIP/KRS/nazwy/osób |
| **Silnik ryzyka** | 10 kodów ryzyka AML, ocena punktowa, decyzja współpracy |
| **Raporty** | PDF A4, Markdown, JSON, CSV — z podpisem SHA-256 |
| **Weryfikacja wsadowa** | CSV / XLSX / tekst — do 100 podmiotów równolegle |
| **Ścieżka audytu** | Decyzje analityka (Akceptacja / Odrzucenie / Eskalacja) z archiwum |

---

## Szybki start

### 1. Wymagania

- Python 3.10+
- `python3-virtualenv` lub `virtualenv` (pip)
- Opcjonalnie: czcionki DejaVu (`/usr/share/fonts/truetype/dejavu/`) dla PDF z polskimi znakami

### 2. Środowisko wirtualne i zależności

```bash
# Utwórz venv
python3 -m virtualenv .venv
# lub: python3 -m venv .venv

# Zainstaluj zależności
.venv/bin/pip install -r requirements.txt
```

### 3. Konfiguracja

```bash
cp .env.example .env
# Edytuj .env — dodaj tokeny API (opcjonalne dla testów offline)
```

Klucze środowiskowe (wszystkie opcjonalne):

| Zmienna | Opis |
|---|---|
| `CEIDG_API_TOKEN` | Token API CEIDG v2 (rząd.gov.pl) |
| `APP_SECRET_KEY` | Klucz CSRF — generowany losowo przy braku |
| `APP_TOKEN` | Bearer token do autoryzacji API (puste = wyłączone) |
| `LOG_LEVEL` | `info` / `debug` / `warning` |

### 4. Uruchomienie

```bash
chmod +x run_web.sh
./run_web.sh
```

Aplikacja dostępna pod: **http://127.0.0.1:8000**

### 5. Uruchomienie testów

```bash
.venv/bin/pytest tests/ -v
```

---

## Architektura

```
src/
├── config.py               # Centralna konfiguracja
├── main.py                 # FastAPI app + middleware
├── core/
│   ├── database.py         # SQLite WAL (5 tabel)
│   ├── validators.py       # NIP / REGON / KRS / IBAN
│   ├── security.py         # CSRF, rate limiting
│   └── io.py               # Atomic file I/O
├── domain/
│   ├── enums.py            # PoziomRyzyka, Decyzja, Status
│   ├── models.py           # VerificationCard, RiskFactor, SanctionHit
│   └── risk_engine.py      # Deterministyczny silnik ryzyka AML
├── providers/
│   ├── mf_white_list.py    # Biała Lista MF API
│   ├── krs_client.py       # KRS API
│   ├── crbr_client.py      # CRBR API
│   ├── ceidg_client.py     # CEIDG v2 API
│   ├── vies_client.py      # VIES EU VAT API
│   └── sanctions/
│       ├── matcher.py      # Deterministyczny matcher sankcyjny
│       └── sync_service.py # Synchronizacja list MSWiA + EU
├── reports/
│   ├── pdf_generator.py    # PDF A4 (ReportLab)
│   ├── markdown_generator.py
│   └── hash_utils.py       # SHA-256 integralność karty
├── services/
│   ├── verification_service.py  # Główny orkiestrator
│   ├── batch_service.py         # Weryfikacja wsadowa
│   └── audit_service.py         # Decyzje analityka + ścieżka audytu
└── web/
    ├── routers/            # FastAPI routers (verify, batch, history, sanctions)
    ├── templates/          # Jinja2 + TailwindCSS + HTMX
    └── static/             # CSS, JS (htmx.min.js, alpine.min.js)
```

---

## API (REST)

Wszystkie endpointy zwracają HTML lub przekierowanie. Dane maszynowe dostępne przez:

- `GET /karta/{id}/json` — pełna karta w JSON
- `GET /karta/{id}/pdf` — raport PDF
- `GET /karta/{id}/md` — raport Markdown
- `GET /wsadowa/{batch_id}/csv` — wyniki wsadowe CSV
- `GET /wsadowa/{batch_id}/status` — status weryfikacji wsadowej (HTMX polling)

---

## Bezpieczeństwo

- **CSRF**: weryfikacja nagłówka `Origin`/`Referer` dla wszystkich żądań POST (middleware)
- **XSS**: Jinja2 auto-escape, nazwy firm zawsze przez `{{ nazwa | e }}`
- **Open Redirect**: `is_safe_redirect_url()` whitelist przed każdym przekierowaniem
- **Rate limiting**: 10 prób logowania / 15 min na IP
- **SHA-256**: każda karta ma hash dowodowy (pola evidence-only, bez decyzji analityka)
- **Token auth**: opcjonalny Bearer token (`APP_TOKEN`) dla wszystkich tras `/api/*`

---

## Wymagania prawne

Aplikacja implementuje procedury należytej staranności zgodnie z:
- Ustawa z dnia 1 marca 2018 r. o przeciwdziałaniu praniu pieniędzy i finansowaniu terroryzmu
- Dyrektywa AML IV/V/VI UE
- Ustawa z dnia 11.03.2004 o podatku od towarów i usług (Biała Lista)
- Ustawa z dnia 13.04.2022 o szczególnych rozwiązaniach w zakresie sankcji (MSWiA)
