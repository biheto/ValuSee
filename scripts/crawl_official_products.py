from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


USER_AGENT = "ValuSeeEvaluationResearch/0.1 (public product-page sampling)"
OUTPUT = Path("data/evaluation/official_products.jsonl")
PAGE_URLS = [
    ("gaming_console", "https://www.nintendo.com/us/gaming-systems/switch/oled-model/"),
    ("gaming_console", "https://www.nintendo.com/us/gaming-systems/switch/lite/"),
    ("furniture", "https://www.ikea.com/us/en/p/billy-bookcase-white-00263850/"),
    ("computer_mouse", "https://www.logitech.com/en-us/products/mice/mx-master-3s.html"),
    ("computer_keyboard", "https://www.logitech.com/en-us/products/keyboards/mx-keys-s.html"),
    ("gaming_console", "https://www.playstation.com/en-us/ps5/"),
    ("audio", "https://www.apple.com/airpods-pro/specs/"),
    ("apparel", "https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111"),
    ("skincare", "https://www.cerave.com/skincare/cleansers/foaming-facial-cleanser"),
    ("skincare", "https://theordinary.com/en-us/niacinamide-10-zinc-1-serum-100436.html"),
    ("packaged_food", "https://www.lays.com/products/lays-classic-potato-chips"),
]


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._in_title = False
        self._in_json_ld = False
        self._json_parts: list[str] = []
        self.json_ld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self._in_title = True
        if tag == "meta" and values.get("name", "").lower() == "description":
            self.description = values.get("content") or ""
        if tag == "script" and "ld+json" in (values.get("type") or "").lower():
            self._in_json_ld = True
            self._json_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_json_ld:
            self.json_ld.append("".join(self._json_parts))
            self._json_parts = []
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_json_ld:
            self._json_parts.append(data)


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _robots_allowed(url: str, cache: dict[str, urllib.robotparser.RobotFileParser]) -> bool:
    origin = urllib.parse.urlsplit(url)
    robots_url = f"{origin.scheme}://{origin.netloc}/robots.txt"
    parser = cache.get(robots_url)
    if parser is None:
        parser = urllib.robotparser.RobotFileParser(robots_url)
        request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                parser.parse(response.read().decode("utf-8", errors="replace").splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                parser.parse([])
            else:
                parser.parse(["User-agent: *", "Disallow: /"])
        except (OSError, TimeoutError, urllib.error.URLError):
            parser.parse(["User-agent: *", "Disallow: /"])
        cache[robots_url] = parser
    return parser.can_fetch(USER_AGENT, url)


def _fetch(url: str) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.status, response.read(), response.headers.get_content_type()


def _product_record(url: str, category: str, status: int, body: bytes, content_type: str) -> dict[str, Any]:
    html = body.decode("utf-8", errors="replace")
    parser = PageParser()
    parser.feed(html)

    products: list[dict[str, Any]] = []
    for block in parser.json_ld:
        try:
            decoded = json.loads(block)
        except json.JSONDecodeError:
            continue
        products.extend(
            item
            for item in _walk_json(decoded)
            if "product" in str(item.get("@type", "")).lower()
        )

    product = products[0] if products else {}
    brand = product.get("brand") or {}
    if isinstance(brand, dict):
        brand = brand.get("name", "")
    description = str(product.get("description") or parser.description or "").strip()
    raw_model = product.get("model")
    model = raw_model.strip() if isinstance(raw_model, str) else ""
    raw_variants = raw_model if isinstance(raw_model, list) else product.get("hasVariant", [])
    if isinstance(raw_variants, dict):
        raw_variants = [raw_variants]
    variants = []
    for variant in raw_variants if isinstance(raw_variants, list) else []:
        if not isinstance(variant, dict):
            continue
        variant_offer = variant.get("offers") or {}
        if isinstance(variant_offer, list):
            variant_offer = variant_offer[0] if variant_offer else {}
        variants.append(
            {
                "name": str(variant.get("name") or "").strip(),
                "color": str(variant.get("color") or "").strip(),
                "sku": str(variant.get("sku") or "").strip(),
                "mpn": str(variant.get("mpn") or "").strip(),
                "price": variant_offer.get("price") if isinstance(variant_offer, dict) else None,
                "price_currency": variant_offer.get("priceCurrency", "") if isinstance(variant_offer, dict) else "",
                "availability": variant_offer.get("availability", "") if isinstance(variant_offer, dict) else "",
            }
        )
    offer = product.get("offers") or {}
    if isinstance(offer, list):
        offer = offer[0] if offer else {}
    if not isinstance(offer, dict):
        offer = {}
    specs = []
    raw_specs = product.get("additionalProperty", [])
    if isinstance(raw_specs, dict):
        raw_specs = [raw_specs]
    for spec in raw_specs if isinstance(raw_specs, list) else []:
        if isinstance(spec, dict):
            specs.append(
                {
                    "name": str(spec.get("name") or "").strip(),
                    "value": str(spec.get("value") or "").strip(),
                }
            )
    return {
        "source_url": url,
        "category": category,
        "market": "US English page",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "http_status": status,
        "content_type": content_type,
        "page_title": " ".join(parser.title.split()),
        "product_name": str(product.get("name") or parser.title).strip(),
        "brand": str(brand).strip(),
        "model": model or str(product.get("mpn") or "").strip(),
        "sku": str(product.get("sku") or "").strip(),
        "gtin": str(product.get("gtin13") or product.get("gtin14") or product.get("gtin") or "").strip(),
        "description_excerpt": description[:500],
        "observed_offer": {
            "price": offer.get("price"),
            "price_currency": offer.get("priceCurrency", ""),
            "availability": offer.get("availability", ""),
        },
        "specifications": specs,
        "variants": variants,
        "structured_product_data": bool(product),
        "raw_product_schema_fields": sorted(product.keys()),
        "annotation_status": "source_captured_needs_human_review" if product else "page_only_needs_human_extraction",
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
    records: list[dict[str, Any]] = []
    for index, (category, url) in enumerate(PAGE_URLS):
        if index:
            time.sleep(1.5)
        if not _robots_allowed(url, robots_cache):
            records.append({"source_url": url, "annotation_status": "skipped_robots_disallow"})
            continue
        try:
            status, body, content_type = _fetch(url)
            if "html" not in content_type:
                records.append({"source_url": url, "http_status": status, "annotation_status": "skipped_non_html"})
                continue
            records.append(_product_record(url, category, status, body, content_type))
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            try:
                time.sleep(2.5)
                status, body, content_type = _fetch(url)
                records.append(_product_record(url, category, status, body, content_type))
            except (OSError, TimeoutError, urllib.error.URLError):
                records.append({"source_url": url, "annotation_status": "fetch_failed", "error": str(exc)[:240]})

    OUTPUT.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )
    successful = sum(item.get("http_status") == 200 for item in records)
    structured = sum(bool(item.get("structured_product_data")) for item in records)
    print(f"wrote {len(records)} rows to {OUTPUT}; HTTP 200: {successful}; Product JSON-LD: {structured}")


if __name__ == "__main__":
    main()
