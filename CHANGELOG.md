# CHANGELOG — CompanyVerificator

Wszystkie istotne zmiany, poprawki i nowości w projekcie dokumentowane są w tym pliku.

Format wzorowany na [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/).

---

## [0.2.0] — 2026-11-26

### Dodano (Added)
- **Ochrona hasłem strony WWW (`WEB_PASSWORD`):**
  - Obsługa parametru `WEB_PASSWORD` w pliku `.env`. Jeśli parametr jest ustawiony, strona wymaga podania hasła. Gdy brak parametru – aplikacja działa od razu bez ekranu logowania.
  - Zabezpieczenie przed atakami brute-force: po 5 nieudanych próbach logowania z danego adresu IP następuje automatyczna blokada na 5 godzin (parametr `LOGIN_LOCKOUT_HOURS`, domyślnie 5h, kod HTTP 429).
- **Plik dziennika zdarzeń (`companyVerificator.log`):**
  - Nowy moduł `src/core/logging_config.py` zapisujący każde zdarzenie, błąd sieciowy oraz wynik weryfikacji i operacje analityka do pliku `companyVerificator.log`.
- **Zarządzanie historią weryfikacji:**
  - Możliwość usunięcia pojedynczych wpisów z historii (przycisk `✕`) oraz wyczyszczenia całej historii (`/historia/wyczysc`) w widoku głównym oraz w pełnym rejestrze.
  - Metody bazy danych `delete_verification()` oraz `delete_all_verifications()` wraz z kaskadowym usuwaniem zdarzeń audytowych.
- **Modal podglądu podmiotów sankcyjnych:**
  - Klikalne kafelki z liczbą wpisów na stronie `/rejestry` (`LOCAL_SEED`, `MSWIA`, `EU`) otwierające modal z tabelą szczegółów (nazwy, aliasy, NIP/KRS, podstawa prawna).
  - Nowy endpoint `GET /rejestry/entries/{source}`.
- **Wydzielone pliki zależności:**
  - `requirements-prod.txt` – tylko paczki niezbędne do uruchomienia na hostingu (bez pytest, ruff, mypy, respx).
  - `requirements-dev.txt` – pełne środowisko deweloperskie i testowe.

### Zmieniono (Changed)
- **Formularz weryfikacji (`verify.html`):**
  - Wyłączono autouzupełnianie pól (`autocomplete="off"` dla NIP, nazwy, konta, kwoty).
  - Dodano dopisek `(opcjonalnie)` przy polu numeru konta i kwoty transakcji.
  - Zastąpiono płaski opis rejestrów zestawem estetycznych etykiet (badges) ze wskaźnikami statusu (Biała Lista MF, KRS, CEIDG, CRBR, VIES, MSWiA, UE).
  - Zaktualizowano etykiety i dodano dymki pomocy (tooltips) dla checkboxów "Status PEP" oraz "Pomiń cache 24h".
- **Obsługa przerw serwisowych Ministerstwa Finansów:**
  - Wykrywanie błędu MF `WL-196` / `WL-002` (aktualizacja bazy) z automatycznym retry i statusem `MF_NIEDOSTEPNY_CHWILOWO`.
  - Nowy status konta bankowego `BLAD_POLACZENIA_MF` zapobiegający fałszywemu uznawaniu subkont masowych (np. Alior Bank 2490) za brakujące na Białej Liście w trakcie awarii serwisu MF.
- **Stopka strony (`base.html`):**
  - Usunięto zbędny slogan *"Silnik: Deterministyczny (Zero-Hallucination) • Retencja dowodowa: 5 lat"*.

---

## [0.1.0] — 2026-11-25

### Dodano (Added)
- Wstępna wersja aplikacji CompanyVerificator (AML / Compliance / Należyta Staranność).
- Obsługa Białej Listy MF, KRS, CRBR, CEIDG v2, VIES.
- Deterministyczny silnik oceny ryzyka bazujący na 10 regułach prawno-podatkowych.
- Generowanie raportów PDF A4, Markdown i JSON z podpisem SHA-256.
- Weryfikacja wsadowa CSV/XLSX.
