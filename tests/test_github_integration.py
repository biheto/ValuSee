import hashlib
import hmac
import json

import pytest

from app.integrations.github import parse_pull_request_url, verify_webhook_signature


def test_parse_github_pull_request_url():
    pull = parse_pull_request_url("https://github.com/biheto/DevAgent-Studio/pull/42")
    assert pull.owner == "biheto"
    assert pull.repo == "DevAgent-Studio"
    assert pull.number == 42


def test_reject_non_github_pull_request_url():
    with pytest.raises(ValueError):
        parse_pull_request_url("https://example.com/owner/repo/pull/42")


def test_verify_github_webhook_signature():
    body = json.dumps({"action": "opened"}).encode()
    secret = "test-secret"
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, f"sha256={digest}", secret)
    assert not verify_webhook_signature(body, "sha256=bad", secret)
