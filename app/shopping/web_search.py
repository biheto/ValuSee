from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class WebSearchError(RuntimeError):
    """A sanitized web-search error that is safe to return as source status."""


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    provider: str
    published_at: str = ""
    score: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "url": self.url,
            "domain": urlparse(self.url).hostname or "",
            "snippet": self.snippet,
            "provider": self.provider,
            "published_at": self.published_at,
            "fetched_at": datetime.now(UTC).isoformat(),
            "score": self.score,
        }


def search_web(query: str, limit: int = 6) -> tuple[list[dict[str, object]], dict[str, object]]:
    provider, api_key = _configured_provider()
    if not provider:
        return [], {
            "source_type": "web",
            "provider": "web",
            "status": "not_configured",
            "count": 0,
            "message": "未配置网页搜索服务，请设置 TAVILY_API_KEY、BOCHA_API_KEY 或 SERPER_API_KEY。",
        }
    try:
        if provider == "tavily":
            results = _search_tavily(api_key, query, limit)
        elif provider == "bocha":
            results = _search_bocha(api_key, query, limit)
        else:
            results = _search_serper(api_key, query, limit)
        return [item.as_dict() for item in results], {
            "source_type": "web",
            "provider": provider,
            "status": "ok" if results else "empty",
            "count": len(results),
        }
    except WebSearchError as exc:
        return [], {
            "source_type": "web",
            "provider": provider,
            "status": "error",
            "count": 0,
            "error": str(exc)[:220],
        }
    except Exception as exc:  # noqa: BLE001 - isolate malformed third-party responses
        return [], {
            "source_type": "web",
            "provider": provider,
            "status": "error",
            "count": 0,
            "error": f"搜索结果处理失败：{type(exc).__name__}",
        }


def _configured_provider() -> tuple[str, str]:
    preferred = _env_value("VALUSee_WEB_SEARCH_PROVIDER").strip().lower()
    keys = {
        "tavily": _env_value("TAVILY_API_KEY").strip(),
        "bocha": _env_value("BOCHA_API_KEY").strip(),
        "serper": _env_value("SERPER_API_KEY").strip(),
    }
    if keys.get(preferred):
        return preferred, keys[preferred]
    for provider in ("tavily", "bocha", "serper"):
        if keys[provider]:
            return provider, keys[provider]
    return "", ""


def _env_value(name: str) -> str:
    process_value = os.getenv(name, "")
    if process_value:
        return process_value
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return ""
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def _post_json(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "ValuSee/0.1 web-search", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read(2 * 1024 * 1024)
        parsed = json.loads(body.decode("utf-8", errors="replace"))
    except HTTPError as exc:
        raise WebSearchError(f"搜索服务返回 HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise WebSearchError(f"搜索服务暂不可用：{type(exc).__name__}") from exc
    if not isinstance(parsed, dict):
        raise WebSearchError("搜索服务返回了无效数据")
    return parsed


def _search_tavily(api_key: str, query: str, limit: int) -> list[WebSearchResult]:
    payload = _post_json(
        "https://api.tavily.com/search",
        {"api_key": api_key, "query": query, "search_depth": "advanced", "include_answer": False, "max_results": limit},
        {},
    )
    return _normalize_results(payload.get("results"), "tavily", "url", "title", "content", "published_date")[:limit]


def _search_bocha(api_key: str, query: str, limit: int) -> list[WebSearchResult]:
    payload = _post_json(
        "https://api.bochaai.com/v1/web-search",
        {"query": query, "count": limit, "summary": True},
        {"Authorization": f"Bearer {api_key}"},
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    pages = data.get("webPages") if isinstance(data.get("webPages"), dict) else {}
    return _normalize_results(pages.get("value"), "bocha", "url", "name", "summary", "datePublished", fallback_snippet="snippet")[:limit]


def _search_serper(api_key: str, query: str, limit: int) -> list[WebSearchResult]:
    payload = _post_json(
        "https://google.serper.dev/search",
        {"q": query, "num": limit},
        {"X-API-KEY": api_key},
    )
    return _normalize_results(payload.get("organic"), "serper", "link", "title", "snippet", "date", score_from_position=True)[:limit]


def _normalize_results(
    raw: object,
    provider: str,
    url_key: str,
    title_key: str,
    snippet_key: str,
    date_key: str,
    *,
    fallback_snippet: str = "",
    score_from_position: bool = False,
) -> list[WebSearchResult]:
    if not isinstance(raw, list):
        return []
    results: list[WebSearchResult] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        url = str(item.get(url_key) or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or url in seen:
            continue
        seen.add(url)
        snippet = str(item.get(snippet_key) or (item.get(fallback_snippet) if fallback_snippet else "") or "").strip()
        raw_score = 1 / (index + 1) if score_from_position else item.get("score", 0)
        try:
            score = float(raw_score or 0)
        except (TypeError, ValueError):
            score = 0.0
        results.append(
            WebSearchResult(
                title=str(item.get(title_key) or parsed.hostname).strip()[:240],
                url=url[:2000],
                snippet=snippet[:1200],
                provider=provider,
                published_at=str(item.get(date_key) or "").strip()[:80],
                score=round(score, 6),
            )
        )
    return results
