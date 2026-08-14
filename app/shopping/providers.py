from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """A sanitized commerce provider error that is safe to expose to logs and health views."""


class ProviderLike(Protocol):
    name: str
    kind: str

    def lookup(self, product_url: str) -> dict[str, object]: ...

    def health_check(self) -> dict[str, object]: ...

    def search(self, query: str, category: str = "", limit: int = 12) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class CommerceProvider:
    """ValuSee-compatible external adapter kept for JD, Taobao, and custom sources."""

    name: str
    base_url: str
    token: str
    kind: str = "official_or_affiliate"

    def _validate_url(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" and os.getenv("APP_ENV", "dev").lower() in {"prod", "production"}:
            raise ValueError("生产环境的平台适配器必须使用 HTTPS")

    def lookup(self, product_url: str) -> dict[str, object]:
        self._validate_url()
        endpoint = self.base_url.rstrip("/") + "/v1/products/lookup"
        body = json.dumps({"url": product_url}).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        with urlopen(request, timeout=8) as response:
            if response.status >= 400:
                raise ProviderError(f"commerce provider returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict) or not payload.get("title"):
            raise ValueError("平台适配器返回的数据缺少商品标题")
        return {"provider": self.name, "kind": self.kind, "product": payload}

    def health_check(self) -> dict[str, object]:
        self._validate_url()
        endpoint = self.base_url.rstrip("/") + "/health"
        request = Request(
            endpoint,
            method="GET",
            headers={"Accept": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        with urlopen(request, timeout=8) as response:
            return {
                "provider": self.name,
                "status": "healthy" if 200 <= response.status < 300 else "unhealthy",
                "http_status": response.status,
            }

    def search(self, query: str, category: str = "", limit: int = 12) -> list[dict[str, object]]:
        self._validate_url()
        endpoint = self.base_url.rstrip("/") + "/v1/products/search"
        body = json.dumps({"query": query, "category": category, "limit": limit}).encode("utf-8")
        request = Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        with urlopen(request, timeout=8) as response:
            if response.status >= 400:
                raise ProviderError(f"commerce provider returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
        items = payload.get("products", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise TypeError("平台搜索适配器返回格式无效")
        return [
            {"provider": self.name, "kind": self.kind, "product": item}
            for item in items[:limit]
            if isinstance(item, dict)
            and item.get("title")
            and str(item.get("url", "")).startswith(("http://", "https://"))
        ]


@dataclass
class PinduoduoProvider:
    """Direct adapter for the official Pinduoduo Duoduo Jinbao gateway."""

    client_id: str
    client_secret: str
    pid: str = ""
    custom_parameters: str = ""
    endpoint: str = "https://gw-api.pinduoduo.com/api/router"
    name: str = "pdd"
    kind: str = "official_affiliate"
    cache_ttl_seconds: int = 120
    _cache: dict[str, tuple[float, object]] = field(default_factory=dict, init=False, repr=False)
    _cache_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @staticmethod
    def _wire_value(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return str(value)

    def _signed_params(self, api_type: str, params: dict[str, object] | None = None) -> dict[str, str]:
        values: dict[str, str] = {
            "type": api_type,
            "client_id": self.client_id,
            "timestamp": str(int(time.time())),
            "data_type": "JSON",
        }
        for key, value in (params or {}).items():
            if value is not None and value != "":
                values[key] = self._wire_value(value)
        canonical = self.client_secret + "".join(f"{key}{values[key]}" for key in sorted(values)) + self.client_secret
        values["sign"] = hashlib.md5(canonical.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
        return values

    def _cached(self, key: str) -> object | None:
        with self._cache_lock:
            cached = self._cache.get(key)
            if not cached or time.monotonic() - cached[0] >= self.cache_ttl_seconds:
                if cached:
                    self._cache.pop(key, None)
                return None
            return cached[1]

    def _save_cache(self, key: str, value: object) -> None:
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), value)
            if len(self._cache) > 256:
                oldest = min(self._cache, key=lambda item: self._cache[item][0])
                self._cache.pop(oldest, None)

    def _promotion_identity(self) -> dict[str, str]:
        if not self.pid or not self.custom_parameters:
            raise ProviderError(
                "拼多多商品搜索需要已授权备案的推广身份：请同时配置 PDD_PID 与 "
                "PDD_CUSTOM_PARAMETERS，并确保两项与备案参数完全一致"
            )
        return {"pid": self.pid, "custom_parameters": self.custom_parameters}

    def _call(self, api_type: str, params: dict[str, object] | None = None, *, cache: bool = True) -> dict[str, object]:
        cache_key = f"{api_type}:{json.dumps(params or {}, ensure_ascii=False, sort_keys=True, default=str)}"
        if cache:
            cached = self._cached(cache_key)
            if isinstance(cached, dict):
                return cached
        body = urlencode(self._signed_params(api_type, params)).encode("utf-8")
        request = Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": "ValuSee/0.1 (+https://valusee.com)",
            },
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"Pinduoduo gateway unavailable: {type(exc).__name__}") from exc
        if not isinstance(payload, dict):
            raise ProviderError("Pinduoduo gateway returned invalid JSON")
        error = payload.get("error_response")
        if isinstance(error, dict):
            code = str(error.get("sub_code") or error.get("error_code") or "unknown")
            message = str(error.get("sub_msg") or error.get("error_msg") or "request rejected")
            if code == "60001":
                raise ProviderError(
                    "拼多多未认可当前推广身份（60001）：请确认 PDD_PID 与 "
                    "PDD_CUSTOM_PARAMETERS 均已在多多进宝授权备案，并与备案时的参数完全一致"
                )
            raise ProviderError(f"Pinduoduo API rejected the request ({code}): {message[:180]}")
        if cache:
            self._save_cache(cache_key, payload)
        return payload

    @staticmethod
    def _goods(payload: dict[str, object], response_key: str, list_key: str) -> list[dict[str, object]]:
        response = payload.get(response_key)
        if not isinstance(response, dict):
            raise ProviderError(f"Pinduoduo response is missing {response_key}")
        items = response.get(list_key, [])
        if not isinstance(items, list):
            raise ProviderError(f"Pinduoduo response field {list_key} is invalid")
        return [item for item in items if isinstance(item, dict)]

    @staticmethod
    def _money(value: object) -> float:
        try:
            return round(max(0, int(value or 0)) / 100, 2)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _product_url(goods_id: object) -> str:
        return f"https://mobile.yangkeduo.com/goods.html?goods_id={goods_id}"

    def _normalize(self, item: dict[str, object], affiliate_url: str = "") -> dict[str, object]:
        goods_id = str(item.get("goods_id") or "")
        goods_sign = str(item.get("goods_sign") or "")
        category = str(item.get("opt_name") or item.get("category_name") or "")
        price = self._money(item.get("min_group_price") or item.get("min_normal_price"))
        coupon = self._money(item.get("coupon_discount")) if bool(item.get("has_coupon")) else 0.0
        source_url = self._product_url(goods_id) if goods_id else "https://mobile.yangkeduo.com"
        observed_at = datetime.now(UTC).isoformat()
        specs = {"商品ID": goods_id}
        if category:
            specs["类目"] = category
        if item.get("sales_tip"):
            specs["销量"] = str(item["sales_tip"])
        if item.get("coupon_min_order_amount"):
            specs["优惠券门槛"] = f"¥{self._money(item['coupon_min_order_amount']):g}"
        return {
            "title": str(item.get("goods_name") or item.get("goods_desc") or "拼多多商品"),
            "category": category or "unknown",
            "platform": "拼多多",
            "url": affiliate_url or source_url,
            "brand": str(item.get("brand_name") or ""),
            "model": "",
            "sku": goods_sign or goods_id,
            "specs": specs,
            "price": price,
            "coupon": coupon,
            "platform_discount": 0.0,
            "member_discount": 0.0,
            "subsidy": 0.0,
            "pay_discount": 0.0,
            "shipping": 0.0,
            "gift_value": 0.0,
            "condition": "新品",
            "official_store": False,
            "return_days": 7,
            "warranty_months": 0,
            "store_name": str(item.get("mall_name") or ""),
            "image_url": str(item.get("goods_image_url") or item.get("goods_thumbnail_url") or ""),
            "selected_variant": "",
            "region": "平台公开价格",
            "membership": "未包含个性化会员价格",
            "observation_status": "official_api",
            "evidence": {
                "source": "pinduoduo_official_ddk_api",
                "source_api": "pdd.ddk.goods.search",
                "observed_at": observed_at,
                "goods_id": goods_id,
                "goods_sign": goods_sign,
                "affiliate_link": bool(affiliate_url),
                "price_unit": "CNY",
                "price_scope": "public_affiliate_price",
            },
            "notes": "价格来自拼多多官方多多进宝接口；下单前请在原平台核对当前 SKU、地区价与优惠条件。"
            + (" 当前跳转链接属于推广链接。" if affiliate_url else ""),
        }

    def _promotion_urls(self, goods_signs: list[str]) -> list[str]:
        if not self.pid or not goods_signs:
            return []
        payload = self._call(
            "pdd.ddk.goods.promotion.url.generate",
            {
                "p_id": self.pid,
                "custom_parameters": self.custom_parameters,
                "goods_sign_list": goods_signs,
                "generate_short_url": True,
            },
            cache=False,
        )
        response = payload.get("goods_promotion_url_generate_response")
        items = response.get("goods_promotion_url_list", []) if isinstance(response, dict) else []
        if not isinstance(items, list):
            return []
        return [
            str(item.get("mobile_short_url") or item.get("short_url") or item.get("mobile_url") or item.get("url") or "")
            for item in items
            if isinstance(item, dict)
        ]

    def search(self, query: str, category: str = "", limit: int = 12) -> list[dict[str, object]]:
        params: dict[str, object] = {
            "keyword": query.strip(),
            "page": 1,
            "page_size": max(10, min(limit, 50)),
            **self._promotion_identity(),
        }
        if category.strip().isdigit():
            params["opt_id"] = int(category.strip())
        payload = self._call("pdd.ddk.goods.search", params)
        items = self._goods(payload, "goods_search_response", "goods_list")[:limit]
        signs = [str(item.get("goods_sign") or "") for item in items if item.get("goods_sign")]
        urls: list[str] = []
        if self.pid and signs:
            try:
                urls = self._promotion_urls(signs)
            except ProviderError:
                urls = []
        normalized = [self._normalize(item, urls[index] if index < len(urls) else "") for index, item in enumerate(items)]
        return [{"provider": self.name, "kind": self.kind, "product": item} for item in normalized]

    def lookup(self, product_url: str) -> dict[str, object]:
        parsed = urlparse(product_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if not any(host == domain or host.endswith(f".{domain}") for domain in ("pinduoduo.com", "yangkeduo.com")):
            raise ValueError("只支持拼多多商品链接")
        goods_id = (parse_qs(parsed.query).get("goods_id") or [""])[0]
        if not goods_id.isdigit():
            raise ValueError("链接中没有可识别的拼多多 goods_id，请使用浏览器扩展采集短链接")
        params: dict[str, object] = {
            "goods_id_list": [int(goods_id)],
            "page": 1,
            "page_size": 10,
            **self._promotion_identity(),
        }
        payload = self._call("pdd.ddk.goods.search", params)
        items = self._goods(payload, "goods_search_response", "goods_list")
        if not items:
            raise ProviderError("拼多多官方接口未返回该商品，商品可能已下架或不在推广库")
        product = self._normalize(items[0])
        return {"provider": self.name, "kind": self.kind, "product": product}

    def health_check(self) -> dict[str, object]:
        started = time.perf_counter()
        payload = self._call(
            "pdd.ddk.goods.search",
            {
                "keyword": os.getenv("PDD_HEALTH_QUERY", "耳机"),
                "page": 1,
                "page_size": 10,
                **self._promotion_identity(),
            },
            cache=False,
        )
        items = self._goods(payload, "goods_search_response", "goods_list")
        return {
            "provider": self.name,
            "status": "healthy",
            "api": "pdd.ddk.goods.search",
            "sample_count": len(items),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "pid_configured": bool(self.pid),
            "custom_parameters_configured": bool(self.custom_parameters),
        }


@lru_cache(maxsize=8)
def _pdd_provider(client_id: str, client_secret: str, pid: str, custom_parameters: str) -> PinduoduoProvider:
    return PinduoduoProvider(
        client_id=client_id,
        client_secret=client_secret,
        pid=pid,
        custom_parameters=custom_parameters,
    )


def commerce_provider_statuses() -> list[dict[str, object]]:
    """Return sanitized provider readiness for the operations console."""
    active = configured_providers()
    statuses = [
        {"name": item.name, "kind": item.kind, "status": "ready", "missing": []}
        for item in active.values()
        if item.name != "pdd"
    ]
    pdd_values = {
        "PDD_CLIENT_ID": os.getenv("PDD_CLIENT_ID", "").strip(),
        "PDD_CLIENT_SECRET": os.getenv("PDD_CLIENT_SECRET", "").strip(),
        "PDD_PID": os.getenv("PDD_PID", "").strip(),
        "PDD_CUSTOM_PARAMETERS": os.getenv("PDD_CUSTOM_PARAMETERS", "").strip(),
    }
    missing = [name for name, value in pdd_values.items() if not value]
    if len(missing) < len(pdd_values):
        statuses.append(
            {
                "name": "pdd",
                "kind": "official_affiliate",
                "status": "ready" if not missing else "configuration_required",
                "missing": missing,
            }
        )
    return statuses


def configured_providers() -> dict[str, ProviderLike]:
    providers: dict[str, ProviderLike] = {}

    pdd_client_id = os.getenv("PDD_CLIENT_ID", "").strip()
    pdd_client_secret = os.getenv("PDD_CLIENT_SECRET", "").strip()
    pdd_pid = os.getenv("PDD_PID", "").strip()
    pdd_custom_parameters = os.getenv("PDD_CUSTOM_PARAMETERS", "").strip()
    if pdd_client_id and pdd_client_secret and pdd_pid and pdd_custom_parameters:
        providers["pdd"] = _pdd_provider(
            pdd_client_id,
            pdd_client_secret,
            pdd_pid,
            pdd_custom_parameters,
        )

    raw = os.getenv("VALUSee_COMMERCE_PROVIDERS", "[]")
    try:
        configs = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("VALUSee_COMMERCE_PROVIDERS 必须是 JSON 数组") from exc
    if not isinstance(configs, list):
        raise TypeError("VALUSee_COMMERCE_PROVIDERS 必须是 JSON 数组")
    for item in configs:
        if not isinstance(item, dict) or not item.get("name") or not item.get("base_url") or not item.get("token"):
            continue
        provider = CommerceProvider(
            name=str(item["name"]),
            base_url=str(item["base_url"]),
            token=str(item["token"]),
            kind=str(item.get("kind") or "official_or_affiliate"),
        )
        providers[provider.name] = provider
    return providers
