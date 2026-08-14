from __future__ import annotations

import json
from typing import Self
from urllib.parse import parse_qs

import pytest

from app.api import routes
from app.schemas.shopping import ShoppingParseUrlRequest
from app.shopping import providers
from app.shopping.providers import PinduoduoProvider, ProviderError


class FakeResponse:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def goods_fixture() -> dict[str, object]:
    return {
        "goods_search_response": {
            "total_count": 1,
            "goods_list": [
                {
                    "goods_id": 123456,
                    "goods_sign": "goods-sign-1",
                    "goods_name": "测试降噪耳机",
                    "brand_name": "TestAudio",
                    "mall_name": "测试官方旗舰店",
                    "opt_name": "耳机",
                    "min_group_price": 159900,
                    "min_normal_price": 169900,
                    "has_coupon": True,
                    "coupon_discount": 10000,
                    "coupon_min_order_amount": 150000,
                    "goods_thumbnail_url": "https://img.example.test/item.jpg",
                    "sales_tip": "已拼10万件",
                }
            ],
        }
    }


def test_pdd_signature_is_sorted_uppercase_and_does_not_send_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers.time, "time", lambda: 1_700_000_000)
    provider = PinduoduoProvider(client_id="client", client_secret="secret")

    params = provider._signed_params("pdd.ddk.goods.search", {"page_size": 10, "keyword": "耳机"})

    assert params == {
        "type": "pdd.ddk.goods.search",
        "client_id": "client",
        "timestamp": "1700000000",
        "data_type": "JSON",
        "page_size": "10",
        "keyword": "耳机",
        "sign": "E4D9AFEBF15A4211D3345C351BF838C0",
    }
    assert "secret" not in "".join(params.values())


def test_pdd_search_maps_official_goods_to_valuesee_product(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        assert timeout == 10
        captured.update({key: values[0] for key, values in parse_qs(request.data.decode("utf-8")).items()})
        return FakeResponse(goods_fixture())

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = PinduoduoProvider(client_id="client", client_secret="secret")

    result = provider.search("降噪耳机", limit=12)

    assert captured["type"] == "pdd.ddk.goods.search"
    assert captured["keyword"] == "降噪耳机"
    assert captured["page_size"] == "12"
    assert len(result) == 1
    product = result[0]["product"]
    assert product["title"] == "测试降噪耳机"
    assert product["platform"] == "拼多多"
    assert product["price"] == 1599
    assert product["coupon"] == 100
    assert product["store_name"] == "测试官方旗舰店"
    assert product["url"] == "https://mobile.yangkeduo.com/goods.html?goods_id=123456"
    assert product["evidence"]["source_api"] == "pdd.ddk.goods.search"
    assert product["evidence"]["affiliate_link"] is False


def test_pdd_search_uses_disclosed_promotion_link_when_pid_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        del timeout
        params = {key: values[0] for key, values in parse_qs(request.data.decode("utf-8")).items()}
        calls.append(params["type"])
        if params["type"] == "pdd.ddk.goods.promotion.url.generate":
            assert params["p_id"] == "pid-1"
            assert json.loads(params["goods_sign_list"]) == ["goods-sign-1"]
            return FakeResponse(
                {
                    "goods_promotion_url_generate_response": {
                        "goods_promotion_url_list": [{"mobile_short_url": "https://p.pinduoduo.com/test"}]
                    }
                }
            )
        assert params["page_size"] == "10"
        return FakeResponse(goods_fixture())

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = PinduoduoProvider(client_id="client", client_secret="secret", pid="pid-1")

    product = provider.search("耳机", limit=1)[0]["product"]

    assert calls == ["pdd.ddk.goods.search", "pdd.ddk.goods.promotion.url.generate"]
    assert product["url"] == "https://p.pinduoduo.com/test"
    assert product["evidence"]["affiliate_link"] is True
    assert "推广链接" in product["notes"]


def test_pdd_api_error_is_sanitized_and_never_contains_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        providers,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            {"error_response": {"error_code": 10000, "sub_code": "access.denied", "sub_msg": "接口无权限"}}
        ),
    )
    provider = PinduoduoProvider(client_id="client", client_secret="top-secret")

    with pytest.raises(ProviderError) as error:
        provider.search("耳机")

    assert "access.denied" in str(error.value)
    assert "接口无权限" in str(error.value)
    assert "top-secret" not in str(error.value)


def test_pdd_lookup_rejects_untrusted_hosts() -> None:
    provider = PinduoduoProvider(client_id="client", client_secret="secret")

    with pytest.raises(ValueError, match="只支持拼多多"):
        provider.lookup("https://notpinduoduo.com/goods.html?goods_id=123456")


def test_pdd_lookup_and_health_use_platform_minimum_page_size(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, str]] = []

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        del timeout
        params = {key: values[0] for key, values in parse_qs(request.data.decode("utf-8")).items()}
        calls.append(params)
        return FakeResponse(goods_fixture())

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = PinduoduoProvider(client_id="client", client_secret="secret")

    lookup = provider.lookup("https://mobile.yangkeduo.com/goods.html?goods_id=123456")
    health = provider.health_check()

    assert lookup["product"]["title"] == "测试降噪耳机"
    assert health["status"] == "healthy"
    assert [call["page_size"] for call in calls] == ["10", "10"]


def test_configured_providers_enables_pdd_only_with_complete_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALUSee_COMMERCE_PROVIDERS", "[]")
    monkeypatch.setenv("PDD_CLIENT_ID", "client")
    monkeypatch.delenv("PDD_CLIENT_SECRET", raising=False)
    assert "pdd" not in providers.configured_providers()

    monkeypatch.setenv("PDD_CLIENT_SECRET", "secret")
    monkeypatch.setenv("PDD_PID", "pid-1")
    configured = providers.configured_providers()
    assert isinstance(configured["pdd"], PinduoduoProvider)
    assert configured["pdd"].pid == "pid-1"


def test_pdd_product_link_uses_official_provider_before_public_page(monkeypatch: pytest.MonkeyPatch) -> None:
    class OfficialProvider:
        def lookup(self, product_url: str) -> dict[str, object]:
            assert product_url == "https://mobile.yangkeduo.com/goods.html?goods_id=123456"
            return {
                "provider": "pdd",
                "kind": "official_affiliate",
                "product": {
                    "title": "官方接口商品",
                    "platform": "拼多多",
                    "url": product_url,
                    "sku": "goods-sign-1",
                    "price": 199,
                    "coupon": 20,
                    "evidence": {"source": "pinduoduo_official_ddk_api"},
                },
            }

    monkeypatch.setattr(routes, "_request_user", lambda _authorization: "user-1")
    monkeypatch.setattr(routes, "configured_providers", lambda: {"pdd": OfficialProvider()})
    monkeypatch.setattr(routes, "fetch_public_product", lambda _url: pytest.fail("public parser should not run"))

    response = routes.parse_shopping_url(
        ShoppingParseUrlRequest(url="https://mobile.yangkeduo.com/goods.html?goods_id=123456"),
        authorization="Bearer token",
    )

    assert response.fetch_status == "parsed"
    assert response.source == "pinduoduo_official_ddk_api"
    assert response.product.title == "官方接口商品"
    assert response.product.price == 199


def test_admin_provider_health_exposes_sanitized_platform_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class RejectedProvider:
        name = "pdd"

        def health_check(self) -> dict[str, object]:
            raise ProviderError("Pinduoduo API rejected the request (access.denied): 接口无权限")

    monkeypatch.setattr(routes, "_require_admin", lambda _authorization: "admin-1")
    monkeypatch.setattr(routes, "configured_providers", lambda: {"pdd": RejectedProvider()})

    result = routes.admin_provider_health("pdd", authorization="Bearer token")

    assert result["status"] == "unhealthy"
    assert result["error_type"] == "ProviderError"
    assert "access.denied" in str(result["error"])
    assert "接口无权限" in str(result["error"])
