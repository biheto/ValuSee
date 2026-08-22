from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.auth.service import AuthStore
from app.shopping.store import ShoppingStore


def test_campaign_publication_window_and_crud():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "operations.db")
        draft = store.save_campaign({"name": "Draft", "title": "Internal", "status": "draft"})
        live = store.save_campaign({"name": "Launch", "title": "Visible", "summary": "Source-aware", "status": "published", "starts_at": "2020-01-01T00:00:00+00:00", "ends_at": "2099-01-01T00:00:00+00:00"})
        ended = store.save_campaign({"name": "Ended", "title": "Old", "status": "published", "ends_at": "2020-01-01T00:00:00+00:00"})
        assert [item["campaign_id"] for item in store.list_campaigns(public_only=True)] == [live["campaign_id"]]
        assert store.delete_campaign(draft["campaign_id"]) is True
        assert store.delete_campaign(ended["campaign_id"]) is True
        try:
            store.save_campaign({"name": "Unsafe", "title": "Unsafe", "target_url": "javascript:alert(1)"})
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe campaign protocols must be rejected")


def test_governed_risk_rules_match_fields_and_are_audited():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "operations.db")
        rule = store.save_risk_rule({"code": "refurbished", "name": "翻新风险", "field_name": "title", "pattern": "翻新", "severity": "high", "action": "block"})
        snapshot = store.risk_rule_snapshot_status()
        assert snapshot["strategy"] == "double_buffer_atomic_snapshot"
        assert snapshot["rule_count"] == 1
        matches = store.evaluate_risk_rules({"title": "官方翻新耳机"})
        assert matches and matches[0]["severity"] == "high" and matches[0]["action"] == "block"
        store.list_risk_rules = lambda: (_ for _ in ()).throw(AssertionError("read path should use the active snapshot"))  # type: ignore[method-assign]
        assert store.evaluate_risk_rules({"title": "官方翻新耳机"})[0]["code"] == "refurbished"
        audit = store.record_admin_audit("admin", "risk_rule.save", "risk_rule", rule["rule_id"], {"enabled": True})
        assert store.list_admin_audits()[0]["audit_id"] == audit["audit_id"]
        assert store.delete_risk_rule(rule["rule_id"]) is True
        assert store.evaluate_risk_rules({"title": "官方翻新耳机"}) == []


def test_suspending_user_revokes_all_sessions_and_upgrade_is_governed():
    with TemporaryDirectory() as tmp:
        store = AuthStore(Path(tmp) / "operations.db")
        user = store.register("operations@example.com", "strong-password", "Operations")
        token = store.create_session(user["user_id"])
        session = store.list_sessions(user["user_id"])[0]
        upgrade = store.request_upgrade(user["user_id"], "pro")
        assert store.update_upgrade_request(upgrade["request_id"], "contacted")["status"] == "contacted"
        assert store.update_user_status(user["user_id"], "suspended")["status"] == "suspended"
        assert store.validate_session(session["session_id"], token) is False


def test_experiment_assignment_is_stable_and_inactive_falls_back():
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "operations.db")
        experiment = store.save_experiment({"code": "hero-copy", "name": "Hero copy", "variants": ["control", "value"], "status": "running"})
        first = store.assign_experiment("u1", "hero-copy")
        second = store.assign_experiment("u1", "hero-copy")
        assert first and second and first["variant"] == second["variant"]
        store.save_experiment({"code": "hero-copy", "name": "Hero copy", "variants": ["control", "value"], "status": "paused"}, experiment["experiment_id"])
        assert store.assign_experiment("u2", "hero-copy") is None


def test_metrics_are_exposed_in_development_and_protected_in_production(monkeypatch):
    client = TestClient(app)
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "valuesee_http_requests_total" in response.text
    assert "valuesee_http_request_duration_seconds_bucket" in response.text
    assert "valuesee_dependency_up" in response.text

    monkeypatch.setattr("app.main.settings.app_env", "production")
    monkeypatch.setenv("VALUSee_METRICS_TOKEN", "metrics-secret")
    assert client.get("/metrics").status_code == 403
    assert client.get("/metrics", headers={"X-Metrics-Token": "metrics-secret"}).status_code == 200


def test_request_id_is_generated_or_preserved_without_echoing_unsafe_values():
    client = TestClient(app)
    generated = client.get("/health")
    assert len(generated.headers["X-Request-ID"]) == 32
    preserved = client.get("/health", headers={"X-Request-ID": "release-check-123"})
    assert preserved.headers["X-Request-ID"] == "release-check-123"
    unsafe = client.get("/health", headers={"X-Request-ID": "bad value"})
    assert unsafe.headers["X-Request-ID"] != "bad value"


def test_prometheus_alert_rules_are_parseable_and_cover_core_failures():
    document = yaml.safe_load(Path("ops/prometheus-alerts.yml").read_text(encoding="utf-8"))
    alerts = {rule["alert"] for group in document["groups"] for rule in group["rules"]}
    assert {"ValuSeeApiHighErrorRate", "ValuSeeApiP95LatencyHigh", "ValuSeeDependencyUnavailable", "ValuSeeDeadLetterQueueNotEmpty"} <= alerts


def test_event_metadata_is_allowlisted(monkeypatch):
    captured: list[dict] = []

    def record(_user_id, event_type, reference_id, metadata, idempotency_key):
        captured.append({"event_type": event_type, "reference_id": reference_id, "metadata": metadata, "idempotency_key": idempotency_key})
        return captured[-1]

    monkeypatch.setattr("app.api.routes.shopping_store.record_business_event", record)
    response = TestClient(app).post(
        "/api/v1/shopping/events",
        json={
            "event_type": "page_view",
            "reference_id": "discover",
            "idempotency_key": "view-1",
            "metadata": {"view": "discover", "variant": "compact", "email": "must-not-be-collected"},
        },
    )
    assert response.status_code == 200
    assert captured[0]["metadata"] == {"view": "discover", "variant": "compact"}


def test_shared_page_escapes_dynamic_title(monkeypatch):
    monkeypatch.setattr("app.main.shopping_store.get_share", lambda _token: {"title": '<script>alert("x")</script>'})
    response = TestClient(app).get("/share/test-token")
    assert response.status_code == 200
    assert "<script>alert" not in response.text
    assert "&lt;script&gt;alert" in response.text
