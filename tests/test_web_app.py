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

