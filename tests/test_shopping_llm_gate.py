from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.service import AuthStore
from app.main import app
from app.shopping.store import ShoppingStore


def _decision_payload() -> dict[str, object]:
    return {
        "goal": "比较显示器",
        "products": [{"title": "测试显示器", "platform": "JD", "model": "M27", "price": 1999}],
        "profile": {"budget": 2500},
    }


def test_shopping_decision_requires_tested_user_llm_config(monkeypatch, tmp_path) -> None:
    database = tmp_path / "shopping-user-key-gate.db"
    auth = AuthStore(database)
    shopping = ShoppingStore(database)
    user = auth.register("buyer@example.com", "strong-password", "Buyer")
    token = auth.create_session(user["user_id"])
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr("app.api.routes.auth_store", auth)
    monkeypatch.setattr("app.auth.service.auth_store", auth)
    monkeypatch.setattr("app.api.routes.shopping_store", shopping)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-platform-must-not-be-used")
    client = TestClient(app)

    missing = client.post("/api/v1/shopping/decide", headers=headers, json=_decision_payload())
    assert missing.status_code == 428
    assert "你自己的 LLM API Key" in missing.json()["detail"]

    shopping.save_llm_config(user["user_id"], {
        "api_key": "sk-user-key",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5",
        "vision_model": "gpt-5",
        "wire_api": "responses",
    })
    untested = client.post("/api/v1/shopping/decide", headers=headers, json=_decision_payload())
    assert untested.status_code == 428
    assert "测试连接" in untested.json()["detail"]
