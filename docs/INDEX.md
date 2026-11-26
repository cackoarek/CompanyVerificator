# 📚 Dokumentacja CompanyVerificator

Witaj w oficjalnej dokumentacji systemu **CompanyVerificator** — zaawansowanego silnika weryfikacji kontrahentów (KYC / KYB / AML / Due Diligence) dla polskich i unijnych przedsiębiorstw.

Aplikacja automatyzuje procedury **Należytej Staranności** w transakcjach gospodarczych, bada powiązania z listami sankcyjnymi, weryfikuje statusy podatkowe na Białej Liście Ministerstwa Finansów oraz tworzy kryptograficznie zabezpieczone karty dowodowe SHA-256 chroniące przed sankcjami KAS i odpowiedzialnością karnoskarbową.

---

## 🧭 Struktura dokumentacji

Dokumentacja została podzielona na moduły tematyczne:

```
docs/
├── INDEX.md               # Strona główna dokumentacji (jesteś tutaj)
├── ARCHITECTURE.md        # Architektura techniczna, wzorce projektowe i przepływ danych
├── AML_RISK_ENGINE.md     # Metodyka oceny ryzyka AML, punktacja KYC, matryca decyzyjna
├── REGISTRIES_AND_DATA.md # Rejestry publiczne, algorytmy dopasowania i heurystyka
├── API_AND_EXPORTS.md     # Interfejsy API, integracje wsadowe (Batch) i formaty raportów
├── SECURITY_AND_AUTH.md   # Model bezpieczeństwa, ochrona kryptograficzna, tokeny i sesje
└── DEPLOYMENT_AND_OPS.md  # Wdrożenie produkcyjne, konfiguracja środowiska (.env), utrzymanie
```

---

## 🚀 Szybki przegląd dokumentacji

| Dział | Opis zawartości | Kluczowe zagadnienia |
| :--- | :--- | :--- |
| [**1. Architektura systemu**](ARCHITECTURE.md) | Opis budowy aplikacji, warstwy Domain-Driven Design, przepływ danych i komponenty. | FastAPI, HTMX, SQLite WAL, ReportLab, Providers, Services |
| [**2. Silnik Ryzyka AML & Scoring**](AML_RISK_ENGINE.md) | Szczegółowa specyfikacja algorytmów oceny ryzyka, kryteria GIIF, wagi punktowe i matryca decyzyjna. | KOR GIIF, wirtualne biura, spółki publiczne, procedury SDD/EDD |
| [**3. Rejestry Publiczne i Sankcje**](REGISTRIES_AND_DATA.md) | Charakterystyka integrowanych źródeł, odporność na okna serwisowe i silnik dopasowań sankcyjnych. | Biała Lista MF, KRS, CRBR, CEIDG, VIES, MSWiA, UE, GUS BIR |
| [**4. API, Eksporty i Zadania Wsadowe**](API_AND_EXPORTS.md) | Specyfikacja endpointów, formaty kart dowodowych, przetwarzanie plików CSV/XLSX. | Raporty PDF A4, Markdown, JSON raw_evidence, Batch Jobs |
| [**5. Bezpieczeństwo i Sesje**](SECURITY_AND_AUTH.md) | Kryptografia SHA-256, podpisywane ciasteczka HMAC-SHA256, ochrona CSRF/brute-force. | Pieczęć dowodowa, tokeny sesyjne 12h, rate limiting, HSTS |
| [**6. Wdrożenie i Operacje (Ops)**](DEPLOYMENT_AND_OPS.md) | Instrukcja uruchomienia lokalnego i na serwerach produkcyjnych, konfiguracja `.env`, strefy czasowe. | `run_web.sh`, systemd, Nginx, certyfikaty SSL, `CV_TIMEZONE` |

---

## ⚖️ Zgodność regulacyjna i normy prawne

System CompanyVerificator realizuje wymagania nałożone przez:
- **Ustawę z dnia 1 marca 2018 r. o przeciwdziałaniu praniu pieniędzy oraz finansowaniu terroryzmu** (Dz.U. z 2023 r. poz. 1124 ze zm.) — procedury identyfikacji i weryfikacji klienta (CDD/KYC), identyfikacja beneficjentów rzeczywistych (CRBR), badanie statusu PEP, prawo do stosowania uproszczonych środków (SDD) dla spółek giełdowych (art. 42 i art. 58).
- **Ustawę z dnia 11 marca 2004 r. o podatku od towarów i usług** — badanie statusu na Białej Liście Podatników VAT (art. 96b), weryfikacja rachunków rozliczeniowych i subkont wirtualnych pod kątem sankcji art. 19 Prawa przedsiębiorców oraz art. 22p ustawy o PIT (próg 15 000 PLN).
- **Ustawę z dnia 13 kwietnia 2022 r. o szczególnych rozwiązaniach w zakresie przeciwdziałania wspieraniu agresji na Ukrainę** (Dz.U. poz. 835) — bezwzględna blokada transakcji z podmiotami z listy MSWiA pod rygorem kar finansowych do 20 mln PLN i odpowiedzialności karnej.
- **Rozporządzenia Rady (UE)** (m.in. 269/2014, 833/2014) dotyczące sankcji sektorowych i osobowych Unii Europejskiej.
- **Metodykę Ministerstwa Finansów w zakresie oceny dochowania należytej staranności przez nabywców towarów w obrocie krajowym**.
