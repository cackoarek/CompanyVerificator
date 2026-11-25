"""Testy integracyjne i bezpieczeństwa warstwy webowej FastAPI."""

from pathlib import Path

import httpx
import respx
from fastapi.testclient import TestClient

from src.core.database import Database
from src.core.security import reset_login_rate_limits
from src.main import app


def _make_client(tmp_path: Path) -> TestClient:
    app.state.db = Database(tmp_path / "web_test.db")
    app.state.audits_dir = tmp_path / "audits"
    return TestClient(app)


def test_web_home_verify_history_and_exports(tmp_path: Path):
    client = _make_client(tmp_path)

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


def test_web_batch_and_registries_pages(tmp_path: Path):
    client = _make_client(tmp_path)
    assert client.get("/wsadowa").status_code == 200
    assert client.get("/rejestry").status_code == 200
    assert client.get("/health").json()["status"] == "ok"


def test_csrf_and_token_auth_hardening(tmp_path: Path, monkeypatch):
    client = _make_client(tmp_path)
    reset_login_rate_limits()

    # 1. CSRF z obcej domeny -> 403
    csrf_resp = client.post(
        "/verify",
        data={"identifier": "5250001090"},
        headers={"Origin": "https://evil.example.com"},
    )
    assert csrf_resp.status_code == 403

    # 2. Ochrona tokenem CV_ACCESS_TOKEN
    monkeypatch.setenv("CV_ACCESS_TOKEN", "super-secret-compliance-token-123456")
    unauth = client.get("/")
    assert unauth.status_code == 401

    login_ok = client.post("/login", data={"token": "super-secret-compliance-token-123456", "redirect_url": "//evil.com"}, follow_redirects=False)
    assert login_ok.status_code == 303
    # Open Redirect prevention -> przekierowanie na '/' zamiast '//evil.com'
    assert login_ok.headers["location"] == "/"
