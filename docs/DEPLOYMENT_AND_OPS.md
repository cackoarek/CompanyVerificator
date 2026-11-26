# 🚢 Wdrożenie Produkcyjne, Konfiguracja i Utrzymanie (Ops)

Niniejszy przewodnik opisuje procedury instalacji, konfiguracji zmiennych środowiskowych, uruchamiania w trybie ciągłym (daemona) oraz zarządzania procesem produkcyjnym aplikacji **CompanyVerificator**.

---

## ⚙️ Konfiguracja Środowiska (.env)

Aplikacja ładuje parametry konfiguracyjne z pliku `.env` znajdującego się w katalogu głównym projektu.

Wzór pliku znajduje się w [`.env.example`](file:///home/acacko/PycharmProjects/CompanyVerificator/.env.example):

```bash
cp .env.example .env
```

### Katalog Zmiennych Środowiskowych:

| Zmienna | Typ | Domyślnie | Opis |
| :--- | :---: | :---: | :--- |
| `CV_HOST` | string | `127.0.0.1` | Interfejs sieciowy, na którym nasłuchuje Uvicorn (użyj `0.0.0.0` dla dockera/dostępu zewnętrznego). |
| `CV_PORT` | int | `8000` | Port HTTP serwera webowego. |
| `CV_DEBUG` | bool | `false` | Tryb deweloperski (włącza auto-reload kodu w Uvicornie). Na produkcji zawsze `false`. |
| `CV_TIMEZONE` | string | `Europe/Warsaw` | Strefa czasowa dla dat weryfikacji, raportów i tabeli historii (CET/CEST). |
| `WEB_PASSWORD` | string | *(puste)* | Hasło dostępowe do panelu webowego. Jeśli puste, panel jest otwarty bez konieczności logowania. |
| `LOGIN_LOCKOUT_HOURS` | int | `5` | Czas trwania blokady adresu IP po 5 nieudanych próbach logowania (w godzinach). |
| `CV_ACCESS_TOKEN` | string | *(puste)* | Opcjonalny stały token dostępowy API (`Authorization: Bearer <token>`). |
| `CV_DATA_DIR` | string | `data` | Ścieżka do katalogu na bazę SQLite i pliki audytowe (względna lub bezwzględna). |
| `CV_CACHE_TTL_HOURS` | int | `24` | Czas życia pamięci podręcznej dla pobranych odpisów kontrahentów. |
| `CV_HTTP_TIMEOUT_SECONDS` | float | `8.0` | Limit czasu oczekiwania na odpowiedź zewnętrznych API rejestrowych. |
| `CV_BATCH_CONCURRENCY` | int | `4` | Maksymalna liczba równolegle badanych podmiotów w zadaniach wsadowych. |
| `CV_PAYMENT_THRESHOLD_PLN`| float | `15000.00` | Próg kwotowy art. 19 Prawa przedsiębiorców wymagający rachunku z Białej Listy. |
| `CV_ALLOW_DELETION` | bool | `true` | Zezwolenie na manualne usuwanie pojedynczych wpisów lub czyszczenie historii. |
| `CEIDG_API_TOKEN` | string | *(puste)* | Opcjonalny bezpłatny klucz API Hurtowni Danych CEIDG v2 ([dane.biznes.gov.pl](https://dane.biznes.gov.pl)). |
| `GUS_ENABLED` | bool | `true` | Włączenie integracji z Bazą Internetową REGON (BIR 1.1). |
| `GUS_USER_KEY` | string | `abcde12345...` | Klucz użytkownika GUS (domyślnie publiczny klucz środowiska testowego GUS). |

---

## 🚀 Uruchomienie i Skrypty Operacyjne

### 1. Skrypt Startowy `run_web.sh`
W katalogu głównym znajduje się zoptymalizowany skrypt uruchomieniowy:
```bash
./run_web.sh
```
Skrypt ten:
- Sprawdza i aktywuje środowisko wirtualne `.venv`,
- Uruchamia serwer Uvicorn z konfiguracją wczytaną z `.env`,
- Konfiguruje logowanie do `companyVerificator.log`.

### 2. Narzędzie Automatycznego Deploymentu (`analysis/deploy.sh`)
W repozytorium znajduje się dedykowany skrypt automatyzujący wdrożenie na zdalny serwer hostingowy:
```bash
./analysis/deploy.sh
```
**Procedura wykonywana przez skrypt:**
1. Zalogowanie przez SSH do serwera docelowego,
2. Wykrycie i bezpieczne zamknięcie istniejącego procesu aplikacji (`SIGTERM`),
3. Pobranie najnowszych zmian z repozytorium (`git pull origin master`),
4. Weryfikacja i instalacja zależności produkcyjnych (`pip install -r requirements-prod.txt`),
5. Uruchomienie procesu w tle (`nohup ./run_web.sh &`),
6. Sprawdzenie przypisanego numeru PID i test odpowiedzi portu.

---

## 🌐 Przykładowa Konfiguracja Nginx (Reverse Proxy)

Zalecana konfiguracja produkcyjna z wykorzystaniem serwera Nginx i certyfikatu SSL (Let's Encrypt):

```nginx
server {
    listen 80;
    server_name company-verificator.twojadomena.pl;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name company-verificator.twojadomena.pl;

    ssl_certificate /etc/letsencrypt/live/company-verificator.twojadomena.pl/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/company-verificator.twojadomena.pl/privkey.pem;

    client_max_body_size 16M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 90s;
    }

    location /static/ {
        alias /home/app/CompanyVerificator/src/web/static/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }
}
```

---

## 💾 Zarządzanie Bazą Danych i Kopia Zapasowa (Backup)

1. **Struktura bazy SQLite:**
   - Baza danych znajduje się w `data/company_verificator.db`.
   - Zastosowano tryb **WAL (Write-Ahead Logging)**, co umożliwia bezkonfliktowy, współbieżny odczyt i zapis nawet podczas masowych zadań wsadowych.
2. **Kopia zapasowa (Backup Online):**
   - Dzięki trybowi WAL kopię zapasową bazy można bezpiecznie wykonać w trakcie działania aplikacji za pomocą polecenia `sqlite3`:
     ```bash
     sqlite3 data/company_verificator.db ".backup 'data/backup_$(date +%Y%m%d_%H%M%S).db'"
     ```
3. **Archiwum Dowodowe:**
   - Katalog `data/audits/` zawiera pliki PDF, Markdown oraz surowe zrzuty JSON z dowodami. Zaleca się cykliczny backup tego katalogu (np. przez `rsync` lub do chmury S3).
