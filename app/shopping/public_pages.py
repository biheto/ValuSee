from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CACHE_TTL_SECONDS = 300
ALLOWED_DOMAINS = {
    "jd.com": "京东",
    "3.cn": "京东",
    "taobao.com": "淘宝",
    "tmall.com": "天猫",
    "tb.cn": "淘宝",
    "pinduoduo.com": "拼多多",
    "yangkeduo.com": "拼多多",
}
BLOCK_MARKERS = ("验证码", "登录后查看", "访问过于频繁", "安全验证", "captcha", "verify you are human")
GENERIC_TITLES = (
    "淘宝网",
    "淘宝",
    "天猫",
    "京东",
    "拼多多",
    "登录",
    "安全验证",
    "页面不存在",
    "商品详情",
    "商品页面",
    "item details",
)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
PRODUCT_QUERY_KEYS = {"id", "item_id", "sku", "skuid", "goods_id", "goodsid"}


class ProductPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self._in_title = False
        self._in_json_ld = False
        self._buffer: list[str] = []
        self.visible_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (values.get("property") or values.get("name") or values.get("itemprop") or "").lower()
            if key and values.get("content"):
                self.meta[key] = values["content"].strip()
        elif tag == "script" and "ld+json" in values.get("type", "").lower():
            self._in_json_ld = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self.json_ld.append("".join(self._buffer))
            self._buffer = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title:
            self.title += value
        if self._in_json_ld:
            self._buffer.append(data)
        elif len(self.visible_text) < 400:
            self.visible_text.append(value)


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urljoin(req.full_url, newurl)
        validate_public_product_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def platform_for_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return next((name for domain, name in ALLOWED_DOMAINS.items() if host == domain or host.endswith(f".{domain}")), "")


def validate_public_product_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("请输入有效的 HTTP(S) 商品链接")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("商品链接使用了不受支持的网络端口")
    if not platform_for_url(url):
        raise ValueError("当前仅支持用户主动提交的京东、淘宝、天猫和拼多多商品链接")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("商品域名暂时无法解析") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("商品链接不能指向本地或私有网络")


def canonical_product_url(url: str) -> str:
    parsed = urlparse(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parsed.query) if key.lower() in PRODUCT_QUERY_KEYS])
    host = (parsed.hostname or "").lower()
    port = f":{parsed.port}" if parsed.port and parsed.port not in {80, 443} else ""
    return urlunparse((parsed.scheme.lower(), f"{host}{port}", parsed.path or "/", "", query, ""))


def parse_product_html(content: str, url: str) -> dict[str, Any]:
    parser = ProductPageParser()
    parser.feed(content)
    product_data = _find_product_json(parser.json_ld)
    offers = product_data.get("offers") if isinstance(product_data.get("offers"), dict) else {}
    brand_value = product_data.get("brand")
    brand = brand_value.get("name", "") if isinstance(brand_value, dict) else str(brand_value or "")
    image_value = product_data.get("image") or parser.meta.get("og:image", "")
    image_url = str(image_value[0] if isinstance(image_value, list) and image_value else image_value or "")
    embedded_title = _embedded_string(content, ("itemTitle", "rawTitle", "shortTitle", "productTitle", "skuName", "goodsName", "goods_name"))
    embedded_brand = _embedded_string(content, ("brandName", "brand"))
    embedded_model = _embedded_string(content, ("model", "productModel"))
    embedded_sku = _embedded_string(content, ("skuId", "skuCode", "goodsId", "goods_id"))
    price = _number(
        offers.get("price")
        or offers.get("lowPrice")
        or product_data.get("price")
        or parser.meta.get("product:price:amount")
        or parser.meta.get("og:price:amount")
        or _embedded_price(content, ("priceText", "salePrice", "promotionPrice", "jdPrice", "minGroupPrice", "minNormalPrice"))
    )
    title = str(product_data.get("name") or parser.meta.get("og:title") or embedded_title or parser.title).strip()
    if not _meaningful_title(title):
        title = ""
    description = str(product_data.get("description") or parser.meta.get("og:description") or "").strip()
    specs = _additional_properties(product_data.get("additionalProperty"))
    item_id = _product_identity(url)
    if item_id and "商品ID" not in specs:
        specs["商品ID"] = item_id
    page_text = f"{' '.join(parser.visible_text)} {parser.title}".lower()
    blocked = any(marker.lower() in page_text for marker in BLOCK_MARKERS)
    has_product_fields = bool(title or price or brand or embedded_brand or embedded_model or embedded_sku)
    status = "blocked" if blocked and not has_product_fields else "parsed" if title and (price or product_data) else "public_partial"
    return {
        "title": html.unescape(title)[:200] or f"来自 {platform_for_url(url)} 的商品（待确认）",
        "category": "unknown",
        "platform": platform_for_url(url),
        "url": url,
        "brand": str(brand or embedded_brand)[:80],
        "model": str(product_data.get("model") or product_data.get("mpn") or embedded_model)[:100],
        "sku": str(product_data.get("sku") or embedded_sku)[:100],
        "specs": specs,
        "price": price,
        "coupon": 0.0,
        "platform_discount": 0.0,
        "member_discount": 0.0,
        "subsidy": 0.0,
        "pay_discount": 0.0,
        "shipping": 0.0,
        "gift_value": 0.0,
        "condition": "new",
        "official_store": False,
        "return_days": 7,
        "warranty_months": 12,
        "store_name": str((offers.get("seller") or {}).get("name", ""))[:100] if isinstance(offers.get("seller"), dict) else "",
        "image_url": image_url[:1000],
        "selected_variant": "",
        "region": "unknown",
        "membership": "unknown",
        "observation_status": "requires_confirmation",
        "evidence": {"type": "public_html", "url": url, "description": description[:500]},
        "notes": "公开页面按需解析结果，请确认当前 SKU、地区、会员条件、优惠和最终价格。",
        "fetch_status": status,
    }


def fetch_public_product(url: str) -> dict[str, Any]:
    validate_public_product_url(url)
    submitted_url = url
    url = canonical_product_url(url)
    cached = _cache.get(url)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return {**cached[1], "cached": True}
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        },
    )
    try:
        with build_opener(SafeRedirectHandler()).open(request, timeout=8) as response:
            final_url = canonical_product_url(response.geturl())
            validate_public_product_url(final_url)
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise ValueError("商品链接没有返回可解析的网页")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("商品页面内容过大，已停止读取")
            charset = response.headers.get_content_charset() or "utf-8"
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return _unavailable_result(url, type(exc).__name__)
    result = parse_product_html(body.decode(charset, errors="replace"), final_url)
    result["evidence"]["submitted_url"] = submitted_url
    result["cached"] = False
    _cache[url] = (time.monotonic(), result)
    if len(_cache) > 256:
        oldest = min(_cache, key=lambda key: _cache[key][0])
        _cache.pop(oldest, None)
    return result


def _unavailable_result(url: str, reason: str) -> dict[str, Any]:
    return {
        **parse_product_html("", url),
        "fetch_status": "unavailable",
        "fetch_error": reason,
        "notes": "公开页面暂时无法读取，请使用浏览器扩展、截图 OCR 或手动补充信息。",
        "cached": False,
    }


def _find_product_json(documents: list[str]) -> dict[str, Any]:
    def visit(value: Any) -> dict[str, Any] | None:
        if isinstance(value, list):
            return next((found for item in value if (found := visit(item))), None)
        if not isinstance(value, dict):
            return None
        kind = value.get("@type")
        if kind == "Product" or isinstance(kind, list) and "Product" in kind:
            return value
        graph = value.get("@graph")
        return visit(graph) if graph else None

    for document in documents:
        try:
            found = visit(json.loads(document))
        except (json.JSONDecodeError, TypeError):
            continue
        if found:
            return found
    return {}


def _additional_properties(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for item in value[:20]:
        if isinstance(item, dict) and item.get("name") and item.get("value") is not None:
            result[str(item["name"])[:80]] = str(item["value"])[:200]
    return result


def _number(value: Any) -> float:
    match = re.search(r"\d+(?:\.\d{1,2})?", str(value or "").replace(",", ""))
    return float(match.group(0)) if match else 0.0


def _embedded_string(content: str, keys: tuple[str, ...]) -> str:
    if not content:
        return ""
    alternatives = "|".join(re.escape(key) for key in keys)
    match = re.search(
        rf'["\'](?:{alternatives})["\']\s*:\s*["\']((?:\\.|[^"\'\\]){{1,500}})["\']',
        content,
        flags=re.IGNORECASE,
    )
    if match:
        value = match.group(1)
    else:
        scalar = re.search(
            rf'["\'](?:{alternatives})["\']\s*:\s*(\d{{1,100}})(?=\s*[,}}])',
            content,
            flags=re.IGNORECASE,
        )
        if not scalar:
            return ""
        value = scalar.group(1)
    try:
        value = json.loads(f'"{value}"')
    except (json.JSONDecodeError, TypeError):
        value = value.replace(r"\/", "/")
    return html.unescape(str(value)).strip()


def _embedded_price(content: str, keys: tuple[str, ...]) -> float:
    if not content:
        return 0.0
    for key in keys:
        match = re.search(
            rf'["\']{re.escape(key)}["\']\s*:\s*["\']?(\d+(?:\.\d{{1,2}})?)["\']?',
            content,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        value = float(match.group(1))
        if key.lower() in {"mingroupprice", "minnormalprice"} and value >= 1000:
            return value / 100
        return value
    return 0.0


def _meaningful_title(value: str) -> bool:
    normalized = " ".join(html.unescape(value).split()).strip(" -_|·")
    if len(normalized) < 4:
        return False
    lowered = normalized.lower()
    return not any(lowered == item.lower() or lowered.startswith(f"{item.lower()} -") for item in GENERIC_TITLES)


def _product_identity(url: str) -> str:
    parsed = urlparse(url)
    query = {key.lower(): value for key, value in parse_qsl(parsed.query)}
    for key in ("id", "item_id", "goods_id", "goodsid"):
        if query.get(key):
            return query[key][:100]
    if platform_for_url(url) == "京东":
        match = re.search(r"/(\d{5,})(?:\.html)?$", parsed.path)
        if match:
            return match.group(1)
    return ""
