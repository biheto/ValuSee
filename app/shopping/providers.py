from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CommerceProvider:
    name: str
    base_url: str
    token: str
    kind: str = "official_or_affiliate"

    def lookup(self, product_url: str) -> dict[str, object]:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" and os.getenv("APP_ENV", "dev").lower() in {"prod", "production"}:
            raise ValueError("生产环境的平台适配器必须使用 HTTPS")
        endpoint = self.base_url.rstrip("/") + "/v1/products/lookup"
        body = json.dumps({"url": product_url}).encode("utf-8")
        request = Request(endpoint, data=body, method="POST", headers={
            "Accept": "application/json", "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        })
        with urlopen(request, timeout=8) as response:
            if response.status >= 400:
                raise RuntimeError(f"commerce provider returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or not payload.get("title"):
            raise ValueError("平台适配器返回的数据缺少商品标题")
        return {"provider": self.name, "kind": self.kind, "product": payload}


def configured_providers() -> dict[str, CommerceProvider]:
    raw = os.getenv("VALUSee_COMMERCE_PROVIDERS", "[]")
    try:
        configs = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("VALUSee_COMMERCE_PROVIDERS 必须是 JSON 数组") from exc
    providers = {}
    for item in configs:
        if not isinstance(item, dict) or not item.get("name") or not item.get("base_url") or not item.get("token"):
            continue
        provider = CommerceProvider(
            name=str(item["name"]), base_url=str(item["base_url"]), token=str(item["token"]),
            kind=str(item.get("kind") or "official_or_affiliate"),
        )
        providers[provider.name] = provider
    return providers
