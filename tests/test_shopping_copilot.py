from __future__ import annotations

import json
from typing import Self

import pytest

from app.shopping import copilot, web_search


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


class FakeCommerceProvider:
    name = "jd"

    def search(self, query: str, category: str, limit: int) -> list[dict[str, object]]:
        assert query and category == "" and limit > 0
        return [{
            "provider": self.name,
            "kind": "official",
            "product": {
                "title": "测试显示器",
                "url": "https://item.example.com/monitor",
                "platform": "京东",
                "store_name": "官方自营",
                "model": "M27",
                "price": 1999,
            },
        }]


def test_tavily_search_normalizes_traceable_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.delenv("VALUSee_WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setattr(
        web_search,
        "urlopen",
        lambda request, timeout: FakeResponse({
            "results": [
                {
                    "title": "官方规格",
                    "url": "https://brand.example.com/products/m27",
                    "content": "支持 USB-C 供电",
                    "published_date": "2026-09-20",
                    "score": 0.92,
                },
                {"title": "无效地址", "url": "javascript:alert(1)", "content": "ignore"},
            ]
        }),
    )

    results, status = web_search.search_web("M27 显示器", 5)

    assert status == {"source_type": "web", "provider": "tavily", "status": "ok", "count": 1}
    assert results[0]["title"] == "官方规格"
    assert results[0]["domain"] == "brand.example.com"
    assert results[0]["snippet"] == "支持 USB-C 供电"


def test_copilot_returns_sources_and_citations_without_user_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        copilot,
        "search_web",
        lambda query, limit: ([{
            "title": "品牌官方参数",
            "url": "https://brand.example.com/m27",
            "domain": "brand.example.com",
            "snippet": "27 英寸 4K 显示器",
            "provider": "tavily",
            "published_at": "2026-09-20",
            "fetched_at": "2026-09-23T10:00:00Z",
            "score": 0.9,
        }], {"source_type": "web", "provider": "tavily", "status": "ok", "count": 1}),
    )
    monkeypatch.setattr(
        copilot,
        "_search_shopping_rag",
        lambda query, user_id: ([{"chunk_id": "r1", "path": "monitor.md", "content": "选购规则"}], {"source_type": "rag", "provider": "shopping-knowledge", "status": "ok", "count": 1}),
    )

    result = copilot.run_copilot_chat(
        message="推荐一台显示器",
        mode="research",
        history=[],
        product_limit=8,
        web_limit=6,
        user_id="user-1",
        commerce_providers={"jd": FakeCommerceProvider()},
        user_llm_config={},
    )

    assert result["answer_source"] == "evidence_summary"
    assert len(result["results"]) == 1
    assert [item["id"] for item in result["citations"]] == [1, 2]
    assert result["citations"][0]["source_type"] == "web"
    assert result["citations"][1]["source_type"] == "commerce"
    assert any(item["source_type"] == "rag" and item["status"] == "ok" for item in result["sources"])
    assert any(item["source_type"] == "model" and item["status"] == "not_configured" for item in result["sources"])


def test_copilot_removes_model_created_urls_and_invalid_citations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        copilot,
        "search_web",
        lambda query, limit: ([{
            "title": "可信页面",
            "url": "https://trusted.example.com/page",
            "domain": "trusted.example.com",
            "snippet": "可验证信息",
            "provider": "bocha",
        }], {"source_type": "web", "provider": "bocha", "status": "ok", "count": 1}),
    )
    monkeypatch.setattr(
        copilot,
        "_search_shopping_rag",
        lambda query, user_id: ([], {"source_type": "rag", "provider": "shopping-knowledge", "status": "empty", "count": 0}),
    )
    monkeypatch.setattr(
        copilot.llm_provider,
        "generate_with_status",
        lambda *args, **kwargs: {
            "text": "已核验 [1]，错误引用 [99]，伪造网址 https://fake.example.com/a 。",
            "answer_source": "llm",
            "model": "deepseek-chat",
        },
    )

    result = copilot.run_copilot_chat(
        message="这款怎么样",
        mode="guide",
        history=[{"role": "user", "content": "M27 显示器"}],
        product_limit=8,
        web_limit=6,
        user_id="user-1",
        commerce_providers={},
        user_llm_config={
            "configured": True,
            "enabled": True,
            "api_key": "secret",
            "last_test_status": "ok",
            "model": "deepseek-chat",
        },
    )

    assert result["search_query"] == "M27 显示器 这款怎么样"
    assert "[1]" in result["answer"]
    assert "[99]" not in result["answer"]
    assert "fake.example.com" not in result["answer"]
    assert result["answer_source"] == "llm"
    assert any(item["source_type"] == "commerce" and item["status"] == "not_configured" for item in result["sources"])
