# 1

Pola formularzy NIP, Nazwa, Nr. konta, kwota transakcji - powoduje że potem przeglądarka proponuje poprzednie wpisy. Nie jest mi potrzebne to. Niech pole będzie takie że nie dostanę propozycji starszych wpisów podczas wpisywania.

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- W pliku `src/web/templates/pages/verify.html` dodano atrybut `autocomplete="off"` na poziomie całego elementu `<form>`, jak również bezpośrednio na polach wejściowych `<input>` dla identyfikatora (NIP/KRS/VAT-UE), nazwy, numeru rachunku bankowego oraz kwoty transakcji. Dzięki temu przeglądarka nie wyświetla podpowiedzi z historii wcześniejszych wpisów.

---

## 2

Nr. konta i kwota transakcji - rozumiem że powinny być opisane jako "Opcjonalne"

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- W pliku `src/web/templates/pages/verify.html` zaktualizowano etykiety pól:
  - `Rachunek bankowy NRB / IBAN (opcjonalnie)`
  - `Kwota transakcji brutto (PLN) (opcjonalnie)`
- Jedynym polem wymaganym weryfikacji pozostaje identyfikator (NIP / KRS / VAT-UE), oznaczony czerwoną gwiazdką `*`.

---

## 3

Wpis: "Zero-Hallucination" na stronie chyba nie jest potrzebne. Tutaj nie ma AI przecież. Usuń

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- Usunięto frazę "Zero-Hallucination" z górnego banera w `src/web/templates/pages/verify.html` i zastąpiono ją profesjonalnym, neutralnym opisem: *"Elektroniczna weryfikacja kontrahenta • Ścieżka audytu SHA-256"*.

---

## 4

Tekst: "Automatyczne badanie podmiotów w rejestrach: Biała Lista VAT MF (z kontami wirtualnymi i requestId), KRS, CRBR, CEIDG, VIES oraz na listach sankcyjnych MSWiA i UE." proponuję jakoś zaprezentować ładniej. Wymyśl jak ładnie zaprezentować zbiory w których aplikacja testuje aby prezentowało się lepiej.

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- Zamiast płaskiego ciągu tekstu wdrożono zestaw estetycznych, interaktywnych etykiet (badges) w nagłówku strony głównej (`src/web/templates/pages/verify.html`):
  - 🟢 **Biała Lista MF** (status VAT, rachunki wirtualne, identyfikator `requestId`)
  - 🔵 **KRS** (Odpis Aktualny, skład zarządu, stan prawny)
  - 🔷 **CEIDG** (dane jednoosobowych działalności, kody PKD, data startu)
  - 🟣 **CRBR (UBO)** (Centralny Rejestr Beneficjentów Rzeczywistych)
  - 🟡 **VIES (VAT-UE)** (europejski rejestr podatników VAT)
  - 🔴 **Sankcje MSWiA** (polska lista sankcyjna)
  - 🟣 **Sankcje UE** (unijna baza FSF)
- Każda z etykiet posiada wskaźnik statusu oraz szczegółowy tooltip wyjaśniający zakres badania.

---

## 5

Dla Firmy: NIP: 5322030067, Nazwa: Smart IT Solutions Arkadiusz Cacko, Numer konta: 74 2490 0005 0000 4530 7931 2255 skrypt zgłasza błąd dla: 🚫 Brak na Białej Liście MF. Chyba coś nie tak. Popraw albo wyjaśnij dlaczego nie działa.
Powtórnie sprawdznie ostatecznie przeszło - czyli poprzednie wykonania pewnie zwracały jakieś błędy ale nie zostało to prawidłowo zaprezentowane dla użytkownika testowego. Warto to jednak odnotować i zaprezentować aby nie dawać fałszywego werdyktu.

**Status:** ZREALIZOWANE
**Szczegóły realizacji i wyjaśnienie:**
- **Przyczyna problemu:** 
  1. Podany numer konta (prefix Alior Banku: `2490`) to subkonto masowe/wirtualne. Takie rachunki nie znajdują się na ogólnej liście rachunków zwracanej przez endpoint wyszukiwania (`/api/search/nip/`), lecz wymagają odpytania dedykowanego endpointu sprawdzającego powiązanie pary NIP + rachunek (`/api/check/nip/.../bank-account/...`).
  2. W momencie pierwszego testu serwery Ministerstwa Finansów przeprowadzały przerwę serwisową i zwracały status HTTP 400 z kodem `WL-196` (*"Trwa aktualizacja bazy danych. Spróbuj ponownie później."*). Wcześniejsza wersja kodu przy awarii API MF uznawała listę rachunków za pustą, co fałszywie klasyfikowało konto jako `BRAK_NA_BIALEJ_LISCIE` (czerwony werdykt), mimo że to usługa MF była niedostępna.
- **Wdrożone poprawki:**
  - W `src/providers/mf_white_list.py` dodano detekcję błędu `WL-196` oraz automatyczny retry. W razie trwającej niedostępności zwracany jest jasny status `MF_NIEDOSTEPNY_CHWILOWO`.
  - W `src/domain/enums.py` i `src/services/verification_service.py` wprowadzono dedykowany stan rachunku: `BLAD_POLACZENIA_MF` ("⚠️ Nie zweryfikowano — MF chwilowo niedostępny"), prezentowany na żółto, bez niesłusznego obniżania oceny kontrahenta i bez fałszywego przypisywania mu braku rejestracji konta.
  - Zaktualizowano reguły silnika ryzyka `src/domain/risk_engine.py` o kod `BANK_VERIFICATION_FAILED_MF`, który informuje analityka o konieczności ponowienia testu po zakończeniu okna serwisowego MF, zamiast karać kontrahenta sankcją podatkową.

---

## 6

W dziale "Ostatnie transakcje" daj możliwość skasowania "Wszystkich" albo poszczególnych sprawdzeń z historii.

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- W `src/core/database.py` zaimplementowano metody `delete_verification(verification_id)` oraz `delete_all_verifications()`, które usuwają wpisy z tabeli weryfikacji wraz z powiązanymi wpisami w tabeli audytowej `audit_events`.
- W routerze `src/web/routers/history.py` dodano endpointy:
  - `DELETE /historia/{verification_id}` – usuwa pojedynczy wpis z bazy i natychmiast odświeża tabelę przez HTMX.
  - `POST /historia/wyczysc` – usuwa całą historię weryfikacji.
- W szablonie `src/web/templates/partials/history_table.html` dodano przycisk `✕` przy każdym wierszu z monitem potwierdzenia usunięcia wpisu.
- W widoku głównym `src/web/templates/pages/verify.html` dodano przycisk *"Wyczyść wszystkie"* w nagłówku sekcji *"Ostatnie weryfikacje"*.
- W widoku rejestru `src/web/templates/pages/history.html` dodano przycisk *"🗑️ Wyczyść całą historię"*.

---

## 7

Dorób plik companyVerificator.log gdzie odłożyć logi z każdej czynności w aplikacji. Każde zdarzenie, każdy wynik i w szczególności momenty gdy coś się nie udało.

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- Utworzono moduł `src/core/logging_config.py` definiujący centralny logger `company_verificator`, zapisujący zdarzenia z sygnaturą czasową, poziomem logowania oraz modułem źródłowym do pliku `companyVerificator.log` w głównym katalogu projektu oraz równolegle na konsolę.
- W `src/config.py` zdefiniowano stałą `LOG_FILE_PATH = PROJECT_ROOT / "companyVerificator.log"`.
- Zintegrowano logowanie w:
  - `src/main.py` – zdarzenia uwierzytelniania, próby logowania, blokady adresów IP, wylogowania.
  - `src/services/verification_service.py` – start weryfikacji każdego podmiotu, trafienia w cache, wykrycie błędów formalnych identyfikatorów, wywołania rejestrów państwowych, wyniki punktowe AML i decyzje oraz błędy połączeń.

---

## 8

Chciałbym aby strona był chroniona hasłem jesli istnieje w .env pole WEB_PASSWORD. Jeśli istnieje, niech aplikacja wyświetla stronę logowania wymającą logowania tym hasłem.
Wdróż też zabezpieczenie 5-krotnego złego logowania z danego IP. Wtedy kolejna próba za 5h (5h to wartość parametru też z .env, dodaj go).
Przy braku WEB_PASSWORD strona nie zgłasza strony logowania, działa od razu bez przekierowania do logowania.

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- W `src/config.py` oraz `.env.example` dodano parametry:
  - `WEB_PASSWORD` – hasło dostępowe do panelu WWW (jeśli puste, logowanie jest wyłączone i strona otwiera się od razu).
  - `LOGIN_LOCKOUT_HOURS` – czas trwania blokady po 5 nieudanych próbach (domyślnie 5 godzin).
- W `src/core/security.py` wdrożono mechanizm `is_ip_locked_out(client_ip)` oraz `record_failed_login_attempt(client_ip)` bazujący na przesuwnym oknie czasowym definiowanym przez `LOGIN_LOCKOUT_HOURS`.
- W `src/main.py` zmodyfikowano middleware `optional_token_auth_middleware` oraz endpoint `/login`:
  - Gdy `WEB_PASSWORD` jest ustawione i użytkownik nie posiada ciasteczka autoryzacyjnego, renderowany jest formularz logowania hasłem.
  - W przypadku 5 błędnych prób logowania adres IP zostaje natychmiast zablokowany na zadany czas (5h). Przy kolejnych żądaniach serwer zwraca kod HTTP 429 z komunikatem o blokadzie.
  - Przy braku `WEB_PASSWORD` w `.env` aplikacja działa całkowicie bez logowania.

---

## 9

na stronie /rejestry na dole jest "Bazy sankcyjne załadowane lokalnie (SQLite)" oraz informacja że w "LOCAL_SEED" jest 26 podmiotów. Chciałbym kliknąć w owe 26 i zobaczyć w modalu listę. Tak samo jak w przypadku "Polska lista MSWiA" oraz "Unijna lista UE (FSF)". Co ciekawe te dwie ostatnie listy są puste. Tak powinno być?

**Status:** ZREALIZOWANE
**Szczegóły realizacji i wyjaśnienie:**
- **Dlaczego listy MSWiA i UE były puste:**
  - Tak, domyślnie po świeżej instalacji/starcie bazy lokalnej załadowany jest jedynie pakiet startowy `LOCAL_SEED` (25 podmiotów referencyjnych dla natychmiastowego działania offline). 
  - Oficjalne bazy rządowe MSWiA oraz Unii Europejskiej (FSF) są pobierane na żądanie z serwerów zewnętrznych po naciśnięciu przycisku *"🔄 Synchronizuj listy sankcyjne MSWiA & UE"*. Ponieważ pobranie pełnej unijnej bazy XML i rejestru MSWiA wymaga połączenia sieciowego i chwilę trwa, nie jest ono wymuszane przy każdym zwykłym starcie serwera.
- **Wdrożenie podglądu w modalu:**
  - Utworzono szablon `src/web/templates/partials/sanction_entries_modal.html` prezentujący tabelę wpisów sankcyjnych (typ, nazwa, aliasy, NIP/KRS, podstawa prawna).
  - W `src/web/routers/sanctions.py` dodano endpoint `GET /rejestry/entries/{source}` zwracający modal przez HTMX.
  - W `src/web/templates/partials/sanctions_sync_status.html` kafelki z liczbą wpisów (`LOCAL_SEED`, `MSWIA`, `EU`) zostały przekształcone w klikalne elementy ładujące modal z wpisami danego rejestru.
  - W `src/core/database.py` dodano obsługę stronicowania i limitów dla metody `list_sanction_entries`.

---

## 10

W stopce widzę "Silnik: Deterministyczny (Zero-Hallucination) • Retencja dowodowa: 5 lat" - skasuj to.

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- W pliku `src/web/templates/base.html` usunięto frazę *"Silnik: Deterministyczny (Zero-Hallucination) • Retencja dowodowa: 5 lat"* i zastąpiono ją prostym podpisem: *"Procedura Należytej Staranności (AML & Compliance)"*.

---

## 11

W formularzu jest dostępne pole wyboru "Status PEP (osoba na eksponowanym stanowisku politycznym)" - trochę nie rozumiem co to oznacza. To użytkownik ma tą informację dostarczyć? Nie da się tego jakoś sprawdzić? Opisz mi analizę na ten temat.

**Status:** ZREALIZOWANE
**Szczegóły analizy prawnej i technicznej:**
1. **Czym jest status PEP:** Zgodnie z art. 2 ust. 2 pkt 11 ustawy z dnia 1 marca 2018 r. o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu (AML), PEP (*Politically Exposed Person*) to osoby zajmujące eksponowane stanowiska polityczne (posłowie, senatorowie, ministrowie, sędziowie sądów najwyższych, członkowie zarządów spółek Skarbu Państwa) oraz członkowie ich rodzin i bliscy współpracownicy.
2. **Czy użytkownik musi dostarczyć tę informację i czy da się to sprawdzić automatycznie:**
   - **Brak otwartego państwowego API:** W Polsce ani w Unii Europejskiej **nie istnieje darmowe, publicznie otwarte API** pozwalające na automatyczne odpytanie o status PEP po numerze PESEL czy nazwisku. Rejestry oświadczeń majątkowych są rozproszone (BIP Sejmu, sądów, urzędów).
   - **Komercyjne bazy danych:** Instytucje finansowe (banki, domy maklerskie) korzystają z drogich, komercyjnych baz subskrypcyjnych (np. Dow Jones Risk & Compliance, Refinitiv World-Check, LexisNexis), których licencje kosztują dziesiątki tysięcy złotych rocznie.
   - **Standardowa praktyka MŚP:** Zgodnie z wytycznymi GIIF, w przypadku podmiotów niebędących bankami, badanie PEP opiera się na **oświadczeniu pisemnym kontrahenta** (ankiecie KYB/AML) pobieranej podczas onboardingu klienta/dostawcy.
   - **Rola checkboxa w aplikacji:** Checkbox służy analitykowi do zaznaczenia: *"Wiem z oświadczenia kontrahenta, że w zarządzie lub strukturze właścicielskiej występuje osoba PEP"*. Silnik CompanyVerificator automatycznie przypisuje wówczas właściwą wagę ryzyka (30 pkt, wymóg zgody wyższego szczebla zgodnie z art. 46 ustawy AML).
3. **Wdrożona zmiana w UI:**
   - Przy polu wyboru dodano ikonę `ⓘ` oraz czytelny tooltip wyjaśniający, że jest to opcja manualna oparta na oświadczeniu kontrahenta z uwagi na brak darmowego API rejestru PEP.

---

## 12

Co oznacza checkbox "Wymuś odpytanie rejestrów na żywo (pomiń cache)"? Wyjaśnij mi działanie. Boję się że użytkownik który zaloguje się do tej usługi może nie wiedzieć co ma wybierać.

**Status:** ZREALIZOWANE
**Szczegóły i wyjaśnienie działania:**
1. **Jak działa cache:**
   - Aby zapobiec blokowaniu zapytań przez limity serwerów rządowych (np. Biała Lista MF posiada limity zapytań na dobę per IP), CompanyVerificator zapisuje wyniki każdej weryfikacji w lokalnej bazie danych SQLite z okresem ważności 24 godzin (`CV_CACHE_TTL_HOURS=24`).
   - Gdy użytkownik wpisuje NIP podmiotu, który był sprawdzany np. 2 godziny temu, system błyskawicznie zwraca zachowany wynik bez ponownego obciążania serwerów MF/KRS/VIES.
2. **Kiedy potrzebne jest wymuszenie na żywo:**
   - Przydaje się wyłącznie wtedy, gdy wiemy, że kontrahent dosłownie przed chwilą dokonał zmiany w rejestrze (np. zarejestrował się do VAT, zmienił zarząd w KRS lub zgłosił nowy rachunek do urzędu skarbowego) i chcemy natychmiast zweryfikować świeży stan ignorując zapis z ostatnich 24h.
3. **Wdrożona zmiana w UI:**
   - Domyślnie pole jest odznaczone (użytkownik nie musi go dotykać ani zmieniać).
   - Zmieniono etykietę na bardziej intuicyjną: *"Odpytaj rejestry na żywo (pomiń cache 24h)"* oraz dodano dymek pomocy `ⓘ` wyjaśniający, kiedy warto z tej opcji skorzystać.

---

## 13

czy możesz utworzyć requirements tylko dla uruchomienia projektu? tak aby nie ściagać zależności które nie są potrzebne do uruchomienia na hostingu

**Status:** ZREALIZOWANE
**Szczegóły realizacji:**
- Utworzono plik `requirements-prod.txt` zawierający wyłącznie pakiety niezbędne do uruchomienia aplikacji w środowisku produkcyjnym:
  - `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`, `pydantic`, `python-dotenv`, `httpx`, `reportlab`, `openpyxl`.
  - Wykluczono pakiety testowe i deweloperskie (`pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`).
- Przygotowano plik `requirements-dev.txt` dla środowiska deweloperskiego.
- Zaktualizowano instrukcję instalacji w `README.md`.
