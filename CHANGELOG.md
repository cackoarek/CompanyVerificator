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
- **Zarządzanie historią weryfikacji i retencja audytowa:**
  - Możliwość usunięcia pojedynczych wpisów z historii (przycisk `✕`) oraz wyczyszczenia całej historii (`/historia/wyczysc`) w widoku głównym oraz w pełnym rejestrze.
  - Usunięcie z interfejsu WWW usuwa wyłącznie wpisy z bazy prezentacyjnej SQLite – **pliki dowodowe na dysku (`data/audits/`) pozostają nienaruszone** na potrzeby ścieżki audytu AML.
  - Rejestrowanie internetowego adresu IP sprawdzającego (`client_ip`) – zapisywany w bazie, w plikach JSON/MD/PDF, w logach oraz prezentowany w tabeli historii.
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
- **Skrypt startowy (`run_web.sh`):**
  - Skrypt ładuje teraz zmienne `CV_HOST`, `CV_PORT`, `CV_DEBUG` bezpośrednio ze wskazanego pliku `.env` (zamiast sztywno wpisanego portu 8000). Umożliwia to prostą zmianę portu w `.env` bez edycji skryptów shellowych.
- **Aktualizacja API Hurtowni Danych CEIDG do wersji v3:**
  - Zaktualizowano endpoint do `https://dane.biznes.gov.pl/api/ceidg/v3/firmy` (wycofana przez MRiT wersja v2 zwracała błąd bramki API `404 No context-path`).
  - Rozszerzono pobieranie danych o adres siedziby, numer REGON oraz kody PKD.
  - Wprowadzono inteligentne wybieranie wpisu aktywnego (`AKTYWNY` / `ZAWIESZONY`) w przypadku przedsiębiorców posiadających wcześniejsze, historycznie wykreślone wpisy w CEIDG pod tym samym NIP.
- **Obsługa przedsiębiorców niebędących podatnikami VAT (np. zwolnionych podmiotowo/przedmiotowo):**
  - Przedsiębiorcy aktywni w CEIDG, którzy nie figurują na Białej Liście MF (ponieważ wykaz MF obejmuje wyłącznie zarejestrowanych podatników VAT), otrzymują teraz właściwy status: `Nie figuruje na Białej Liście (np. zwolniony z VAT / niebędący podatnikiem VAT)`.
  - Zapobieganie fałszywym alarmom podwyższonego ryzyka (brak kary `REGISTRY_INACTIVE` dla aktywnych JDG zwolnionych z VAT).
- **Prezentacja rachunków bankowych z Białej Listy MF:**
  - Gdy użytkownik nie wpisze numeru rachunku w formularzu, w wynikach weryfikacji prezentowana jest pełna lista oficjalnie zarejestrowanych rachunków firmowych w MF wraz z formatowaniem i przyciskiem szybkiego kopiowania (`Kopiuj`).
  - Jeśli czynny podatnik VAT nie ma zarejestrowanego ani jednego rachunku w wykazie MF, system wyświetla widoczne ostrzeżenie oraz nalicza punkt ryzyka `NO_REGISTERED_BANK_ACCOUNTS` (+20 pkt, ryzyko średnie), zapobiegając nieświadomym przelewom na niezgłoszone rachunki.
  - Wykaz kont oraz ewentualny alert o ich braku są również uwzględniane w raportach Markdown i PDF.
- **Obsługa kodu HTTP 204 w CEIDG v3:**
  - Dodano prawidłową interpretację odpowiedzi `204 No Content` z API CEIDG v3 jako brak wpisu w CEIDG (charakterystyczne dla spółek prawa handlowego rejestrowanych wyłącznie w KRS).
- **Ekran logowania:**
  - Ujednolicono teksty na ekranie logowania – zamiast *"Wymagany Token Dostępu"* oraz *"CV_ACCESS_TOKEN"* wyświetlane jest *"🔒 Wymagane hasło dostępu"* i *"Wpisz hasło dostępu"*.

---

## [0.1.0] — 2026-11-25

### Dodano (Added)
- Wstępna wersja aplikacji CompanyVerificator (AML / Compliance / Należyta Staranność).
- Obsługa Białej Listy MF, KRS, CRBR, CEIDG v2, VIES.
- Deterministyczny silnik oceny ryzyka bazujący na 10 regułach prawno-podatkowych.
- Generowanie raportów PDF A4, Markdown i JSON z podpisem SHA-256.
- Weryfikacja wsadowa CSV/XLSX.
