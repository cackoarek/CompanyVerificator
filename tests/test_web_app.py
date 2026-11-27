"""Testy integracyjne i bezpieczeństwa warstwy webowej FastAPI."""

from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient

from src.core.database import Database
from src.core.security import reset_login_rate_limits
from src.main import app


def _make_client(tmp_path: Path, monkeypatch=None) -> TestClient:
    app.state.db = Database(tmp_path / "web_test.db")
    app.state.audits_dir = tmp_path / "audits"
    if monkeypatch:
        monkeypatch.setattr("src.main.WEB_PASSWORD", "")
        monkeypatch.setattr("src.main.ACCESS_TOKEN", "")
        monkeypatch.delenv("WEB_PASSWORD", raising=False)
        monkeypatch.delenv("CV_ACCESS_TOKEN", raising=False)
    return TestClient(app)


def test_web_home_verify_history_and_exports(tmp_path: Path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)

    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert "CompanyVerificator" in resp_home.text

    with respx.mock(assert_all_called=False) as mock:
        mock.get(url__regex=r"https://wl-api\.mf\.gov\.pl/api/search/nip/5250001090.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "result": {
                        "requestId": "web-mf-1",
                        "subject": {
                            "name": "Test <script>alert(1)</script> Sp. z o.o.",
                            "nip": "5250001090",
                            "statusVat": "Czynny",
                            "regon": "012100784",
                            "workingAddress": "Warszawa",
                            "accountNumbers": ["61109010140000071219812874"],
                        },
                    }
                },
            )
        )
        mock.get(url__regex=r"https://dane\.biznes\.gov\.pl/api/ceidg/.*").mock(
            return_value=httpx.Response(404, json={"firmy": []})
        )
        resp_verify = client.post(
            "/verify",
            data={
                "identifier": "5250001090",
                "rachunek": "61109010140000071219812874",
                "kwota": "18000",
            },
        )
    assert resp_verify.status_code == 200
    # Weryfikacja ochrony przed XSS w nazwie podmiotu
    assert "<script>alert(1)</script>" not in resp_verify.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp_verify.text
    assert "NISKIE RYZYKO" in resp_verify.text

    # Sprawdzenie historii
    resp_hist = client.get("/historia")
    assert resp_hist.status_code == 200
    assert "5250001090" in resp_hist.text

    # Pobranie ID z bazy i test eksportów PDF / MD / JSON
    items = app.state.db.list_verifications(limit=1)
    vid = items[0]["id"]

    assert client.get(f"/karta/{vid}").status_code == 200
    pdf_resp = client.get(f"/karta/{vid}/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert len(pdf_resp.content) > 1000

    md_resp = client.get(f"/karta/{vid}/md")
    assert md_resp.status_code == 200
    assert "KARTA WERYFIKACJI KONTRAHENTA" in md_resp.text

    json_resp = client.get(f"/karta/{vid}/json")
    assert json_resp.status_code == 200
    assert json_resp.json()["mf_request_id"] == "web-mf-1"


def test_web_batch_and_registries_pages(tmp_path: Path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    assert client.get("/wsadowa").status_code == 200
    assert client.get("/rejestry").status_code == 200
    assert client.get("/health").json()["status"] == "ok"


def test_csrf_and_token_auth_hardening(tmp_path: Path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    reset_login_rate_limits()

    # 1. CSRF z obcej domeny -> 403
    csrf_resp = client.post(
        "/verify",
        data={"identifier": "5250001090"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert csrf_resp.status_code == 403

    # 2. Ochrona tokenem CV_ACCESS_TOKEN
    monkeypatch.setattr("src.main.ACCESS_TOKEN", "super-secret-compliance-token-123456")
    monkeypatch.setenv("CV_ACCESS_TOKEN", "super-secret-compliance-token-123456")
    unauth = client.get("/")
    assert unauth.status_code == 401

    # Test bezpośredniego wejścia GET na /login
    login_page = client.get("/login?redirect_url=/karta/123")
    assert login_page.status_code == 200
    assert "Wymagane hasło dostępu" in login_page.text
    assert 'value="/karta/123"' in login_page.text

    login_ok = client.post("/login", data={"token": "super-secret-compliance-token-123456", "redirect_url": "//evil.com"}, follow_redirects=False)
    assert login_ok.status_code == 303
    # Open Redirect prevention -> przekierowanie na '/' zamiast '//evil.com'
    assert login_ok.headers["location"] == "/"


def test_web_password_protection_and_lockout(tmp_path: Path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    reset_login_rate_limits()

    monkeypatch.setattr("src.main.WEB_PASSWORD", "TajneHaslo123!")
    monkeypatch.setenv("WEB_PASSWORD", "TajneHaslo123!")
    monkeypatch.setenv("LOGIN_LOCKOUT_HOURS", "5")

    # Bez logowania -> 401 z formularzem hasła
    resp = client.get("/", headers={"accept": "text/html"})
    assert resp.status_code == 401
    assert "Wymagane hasło dostępu" in resp.text

    # 4 błędne próby -> 401
    for _ in range(4):
        bad_login = client.post("/login", data={"password": "zle-haslo"})
        assert bad_login.status_code == 401

    # 5. błędna próba -> blokada (429)
    fifth_try = client.post("/login", data={"password": "zle-haslo"})
    assert fifth_try.status_code == 429
    assert "zablokowany na 5h" in fifth_try.json()["detail"]

    # Kolejna próba wejścia na stronę z tego IP -> 429
    blocked = client.get("/", headers={"accept": "text/html"})
    assert blocked.status_code == 429
    assert "Dostęp tymczasowo zablokowany" in blocked.text


def test_history_delete_item_and_clear_all(tmp_path: Path, monkeypatch):
    client = _make_client(tmp_path, monkeypatch)
    db = client.app.state.db

    # Dodaj 2 testowe wpisy
    db.save_verification({"id": "v-1", "identifier": "5250001090", "identifier_kind": "NIP", "nazwa": "Firma 1", "poziom_ryzyka": "NISKIE", "decyzja": "AKCEPTACJA", "analyst_status": "AUTO", "status_vat": "Czynny", "status_rachunku": "NIE_PODANO", "blad_polaczenia": False, "sankcje_hit": False, "status_pep": False, "sha256_hash": "a"*64, "card_json": "{}", "created_at": "2026-01-01T10:00:00Z"})
    db.save_verification({"id": "v-2", "identifier": "5250001091", "identifier_kind": "NIP", "nazwa": "Firma 2", "poziom_ryzyka": "NISKIE", "decyzja": "AKCEPTACJA", "analyst_status": "AUTO", "status_vat": "Czynny", "status_rachunku": "NIE_PODANO", "blad_polaczenia": False, "sankcje_hit": False, "status_pep": False, "sha256_hash": "b"*64, "card_json": "{}", "created_at": "2026-01-01T11:00:00Z"})

    assert len(db.list_verifications()) == 2

    # Usuń pojedynczy wpis
    del_resp = client.delete("/historia/v-1")
    assert del_resp.status_code == 200
    assert len(db.list_verifications()) == 1
    assert db.list_verifications()[0]["id"] == "v-2"

    # Wyczyść całą historię
    clear_resp = client.post("/historia/wyczysc")
    assert clear_resp.status_code == 200
    assert len(db.list_verifications()) == 0

    # Test blokady backendowej gdy ALLOW_DELETION jest wyłączone (CV_ALLOW_DELETION=false)
    db.save_verification({"id": "v-3", "identifier": "5250001092", "identifier_kind": "NIP", "nazwa": "Firma 3", "poziom_ryzyka": "NISKIE", "decyzja": "AKCEPTACJA", "analyst_status": "AUTO", "status_vat": "Czynny", "status_rachunku": "NIE_PODANO", "blad_polaczenia": False, "sankcje_hit": False, "status_pep": False, "sha256_hash": "c"*64, "card_json": "{}", "created_at": "2026-01-01T12:00:00Z"})
    monkeypatch.setattr("src.web.routers.history.ALLOW_DELETION", False)
    monkeypatch.setattr("src.web.dependencies.ALLOW_DELETION", False)

    # Próba usunięcia pojedynczego wpisu -> 403
    blocked_del = client.delete("/historia/v-3")
    assert blocked_del.status_code == 403
    assert "Usuwanie wpisów weryfikacji zostało wyłączone" in blocked_del.json()["detail"]
    assert len(db.list_verifications()) == 1

    # Próba wyczyszczenia całości -> 403
    blocked_clear = client.post("/historia/wyczysc")
    assert blocked_clear.status_code == 403
    assert "Czyszczenie historii weryfikacji zostało wyłączone" in blocked_clear.json()["detail"]
    assert len(db.list_verifications()) == 1

    # Przyciski usuwania nie powinny być widoczne w HTML
    hist_html = client.get("/historia")
    assert hist_html.status_code == 200
    assert "Wyczyść całą historię" not in hist_html.text
    assert 'hx-delete="/historia/v-3"' not in hist_html.text


def test_how_it_works_page_publicly_accessible(tmp_path: Path, monkeypatch):
    """Testuje, czy strona /jak-to-dziala jest dostępna również bez logowania przy aktywnym WEB_PASSWORD."""
    reset_login_rate_limits()
    app.state.db = Database(tmp_path / "web_test.db")
    app.state.audits_dir = tmp_path / "audits"
    monkeypatch.setenv("WEB_PASSWORD", "sekretne_haslo")
    monkeypatch.setattr("src.main.WEB_PASSWORD", "sekretne_haslo")

    client = TestClient(app)

    # Strona główna wymaga logowania (401)
    resp_home = client.get("/", headers={"accept": "text/html"})
    assert resp_home.status_code == 401
    assert "Wymagane hasło dostępu" in resp_home.text
    assert "/jak-to-dziala" in resp_home.text

    # Strona /jak-to-dziala jest dostępna publicznie (200)
    resp_guide = client.get("/jak-to-dziala")
    assert resp_guide.status_code == 200
    assert "Jak działa CompanyVerificator?" in resp_guide.text
    assert "Biała Lista Podatników VAT" in resp_guide.text
    assert "Matryca ryzyka" in resp_guide.text
    assert "Firma niedawno założona" in resp_guide.text


def test_signed_session_tokens_and_security_hardening(tmp_path: Path, monkeypatch):
    """Testuje podpis kryptograficzny ciasteczek sesyjnych HMAC, nagłówek HSTS i rate limiting."""
    from src.core.security import (
        create_session_token,
        verify_session_token,
        check_verify_rate_limit,
        reset_verify_rate_limits,
    )

    # 1. Test HMAC session token
    secret = "bardzo_tajne_haslo_123"
    token = create_session_token(secret, max_age=3600)
    assert verify_session_token(token, secret, max_age=3600) is True
    # Zły sekret
    assert verify_session_token(token, "inne_haslo", max_age=3600) is False
    # Sfałszowany token
    parts = token.split(".")
    tampered = f"{parts[0]}.{parts[1]}.badsignature"
    assert verify_session_token(tampered, secret, max_age=3600) is False
    # Przestarzały token (max_age=-1)
    assert verify_session_token(token, secret, max_age=-1) is False

    # 2. Test rate limitera weryfikacji
    reset_verify_rate_limits()
    test_ip = "192.168.1.100"
    for _ in range(5):
        assert check_verify_rate_limit(test_ip, max_requests=5, window_seconds=60) is True
    # 6. żądanie przekracza limit
    assert check_verify_rate_limit(test_ip, max_requests=5, window_seconds=60) is False

    # 3. Test nagłówka HSTS
    client = _make_client(tmp_path, monkeypatch)
    resp = client.get("/health", headers={"x-forwarded-proto": "https"})
    assert resp.status_code == 200
    assert "Strict-Transport-Security" in resp.headers
    assert "max-age=31536000" in resp.headers["Strict-Transport-Security"]


def test_public_audit_reports_access(tmp_path: Path, monkeypatch):
    """Testuje publiczny dostęp (GET /karta/{id}) bez logowania gdy PUBLIC_AUDIT_REPORTS=true."""
    client = _make_client(tmp_path, monkeypatch)
    db = client.app.state.db

    # Zapisz testową kartę
    card_dict = {
        "id": "audit-uuid-12345",
        "identifier": "5260251049",
        "identifier_kind": "NIP",
        "nazwa": "Powszechny Zakład Ubezpieczeń SA",
        "poziom_ryzyka": "NISKIE",
        "decyzja": "AKCEPTACJA",
        "analyst_status": "AUTO",
        "status_vat": "Czynny",
        "status_rachunku": "NIE_PODANO",
        "blad_polaczenia": False,
        "sankcje_hit": False,
        "status_pep": False,
        "sha256_hash": "c"*64,
        "card_json": '{"id": "audit-uuid-12345", "identifier": "5260251049", "identifier_kind": "NIP", "nazwa": "Powszechny Zakład Ubezpieczeń SA", "nip": "5260251049", "poziom_ryzyka": "NISKIE", "decyzja": "AKCEPTACJA", "analyst_status": "AUTO", "uzasadnienie_decyzji": "OK", "data_weryfikacji": "2026-11-27T20:00:00Z"}',
        "created_at": "2026-11-27T20:00:00Z",
    }
    db.save_verification(card_dict)

    # Ustaw hasło WEB_PASSWORD
    monkeypatch.setattr("src.main.WEB_PASSWORD", "Tajne123")
    monkeypatch.setenv("WEB_PASSWORD", "Tajne123")

    # 1. Gdy PUBLIC_AUDIT_REPORTS=false -> /karta/audit-uuid-12345 wymaga hasła (401)
    monkeypatch.setenv("PUBLIC_AUDIT_REPORTS", "false")
    monkeypatch.setattr("src.main.PUBLIC_AUDIT_REPORTS", False)
    resp = client.get("/karta/audit-uuid-12345", headers={"accept": "text/html"})
    assert resp.status_code == 401

    # 2. Gdy PUBLIC_AUDIT_REPORTS=true -> /karta/audit-uuid-12345 jest dostępny publicznie (200)
    monkeypatch.setenv("PUBLIC_AUDIT_REPORTS", "true")
    monkeypatch.setattr("src.main.PUBLIC_AUDIT_REPORTS", True)
    resp_pub = client.get("/karta/audit-uuid-12345", headers={"accept": "text/html"})
    assert resp_pub.status_code == 200
    assert "Powszechny Zakład Ubezpieczeń SA" in resp_pub.text
    # Sprawdź, czy formularz decyzji jest zablokowany (tryb read-only)
    assert "Podgląd tylko do odczytu" in resp_pub.text
    assert "Zmiana statusu decyzji i dodawanie notatek audytowych wymaga logowania" in resp_pub.text

    # 3. Zapis decyzji (POST /karta/.../decision) nadal wymaga logowania (401)
    resp_post = client.post("/karta/audit-uuid-12345/decision", data={"analyst_status": "REJECTED"})
    assert resp_post.status_code == 401

    # 4. Inne strony (np. /, /historia, /wsadowa) nadal wymagają logowania (401)
    assert client.get("/", headers={"accept": "text/html"}).status_code == 401
    assert client.get("/historia", headers={"accept": "text/html"}).status_code == 401


