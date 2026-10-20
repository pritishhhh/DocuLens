from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.llm import ProviderError

client = TestClient(app)


def test_home_health_and_assets():
    assert client.get("/health").json() == {"status": "ok"}
    assert "Read between" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200


def test_catalog_lists_coverage_without_content(corpus):
    data = client.get("/corpus").json()
    assert data["tickers"][0]["ticker"] == "EXM"
    assert len(data["tickers"][0]["filings"]) == 2
    assert "content" not in str(data)


@pytest.mark.parametrize("payload", [
    {"ticker": "../../secret", "question": "What was revenue?"},
    {"ticker": "NVDA", "question": "   "},
    {"ticker": "NVDA", "question": "x" * 2001},
    {"ticker": "NVDA", "question": "What was revenue?", "form": "8-K"},
    {"ticker": "NVDA", "question": "What was revenue?", "filing_date": "2025-02-31"},
    {"ticker": "NVDA", "question": "What was revenue?", "extra": True}
])
def test_invalid_requests_are_rejected(payload):
    assert client.post("/query", json=payload).status_code == 422


def test_missing_index_is_actionable():
    response = client.post("/query", json={"ticker": "NVDA", "question": "What was revenue?"})
    assert response.status_code == 404
    assert "Build its index" in response.json()["detail"]


def test_vercel_requires_explicit_access_choice(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("DOCULENS_PUBLIC_DEMO", "false")
    assert client.post("/query", json={"ticker": "NVDA", "question": "What was revenue?"}).status_code == 503


def test_api_token_is_enforced(monkeypatch):
    monkeypatch.setenv("DOCULENS_API_TOKEN", "test-token")
    payload = {"ticker": "NVDA", "question": "What was revenue?"}
    assert client.post("/query", json=payload).status_code == 401
    assert client.post("/query", json=payload, headers={"Authorization": "Bearer wrong"}).status_code == 401
    with patch("app.main.ask", return_value={"status": "insufficient_evidence"}):
        assert client.post("/query", json=payload, headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_quota_response_is_not_an_internal_error():
    with patch("app.main.ask", side_effect=ProviderError("Quota exhausted", 429)):
        response = client.post("/query", json={"ticker": "NVDA", "question": "What was revenue?"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
