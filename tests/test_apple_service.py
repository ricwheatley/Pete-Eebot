from datetime import date

from fastapi.testclient import TestClient

from pete_e.core import apple_service


def _set_token(monkeypatch, token: str | None) -> None:
    monkeypatch.setattr(apple_service.settings, "APPLE_WEBHOOK_TOKEN", token)


def test_receive_summary_rejects_missing_token_config(monkeypatch) -> None:
    _set_token(monkeypatch, None)
    client = TestClient(apple_service.app)

    response = client.post("/summary", json={"date": "2024-01-01"})

    assert response.status_code == 500


def test_receive_summary_rejects_request_without_token(monkeypatch) -> None:
    _set_token(monkeypatch, "expected-token")
    client = TestClient(apple_service.app)

    response = client.post("/summary", json={"date": "2024-01-02"})

    assert response.status_code == 401


def test_receive_summary_accepts_valid_token(monkeypatch) -> None:
    captured = {}

    class DummyDal:
        def save_apple_daily(self, day: date, metrics: dict) -> None:
            captured["day"] = day
            captured["metrics"] = metrics

    monkeypatch.setattr(apple_service, "PostgresDal", lambda: DummyDal())
    _set_token(monkeypatch, "expected-token")
    client = TestClient(apple_service.app)

    response = client.post(
        "/summary",
        json={"date": "2024-01-03"},
        headers={"X-Apple-Webhook-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert captured["day"].isoformat() == "2024-01-03"
    assert captured["metrics"]["date"] == "2024-01-03"
