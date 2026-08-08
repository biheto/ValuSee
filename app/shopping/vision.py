from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.object_storage import persist_upload

ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def inspect_product_image(content: bytes, content_type: str, original_name: str) -> dict[str, Any]:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("仅支持 JPG、PNG 和 WebP 商品图片")
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能为空且大小不能超过 8 MB")
    digest = hashlib.sha256(content).hexdigest()
    upload_dir = Path.cwd() / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"img_{uuid4().hex}{ALLOWED_IMAGE_TYPES[content_type]}"
    stored_path = upload_dir / stored_name
    stored_path.write_bytes(content)
    storage = persist_upload(stored_path, content_type)
    text, provider, warning = _extract_text(stored_path)
    product = normalize_product_text(text, original_name)
    return {
        "asset_id": stored_name.rsplit(".", 1)[0], "file_name": stored_name,
        "content_type": content_type, "size": len(content), "sha256": digest,
        "storage": storage, "ocr_provider": provider, "ocr_text": text,
        "product": product,
        "requires_confirmation": not bool(text.strip()) or not bool(product["model"] or product["brand"]),
        "warning": warning,
    }


def normalize_product_text(text: str, fallback_title: str = "") -> dict[str, Any]:
    clean = " ".join(text.replace("\u3000", " ").split())
    price_match = re.search(r"(?:(?:￥|¥|RMB)\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*元)", clean, re.IGNORECASE)
    model_match = re.search(r"\b((?:AirPods\s+Pro\s+\d+)|(?:[A-Z]{1,8}[- ]?\d{2,}[A-Z0-9-]*))\b", clean, re.IGNORECASE)
    brands = ("Apple", "华为", "小米", "荣耀", "联想", "戴尔", "三星", "索尼", "美的", "海尔", "科沃斯")
    brand = next((item for item in brands if item.lower() in clean.lower()), "")
    category = _detect_category(clean)
    specs: dict[str, Any] = {}
    for label, pattern in {
        "screen_size_inch": r"(\d{2}(?:\.\d)?)\s*(?:英寸|寸)",
        "memory_gb": r"(\d{1,3})\s*GB\s*(?:内存|RAM)?",
        "storage_gb": r"(\d{3,5})\s*GB\s*(?:存储|硬盘|SSD)?",
        "battery_mah": r"(\d{3,5})\s*mAh",
    }.items():
        match = re.search(pattern, clean, re.IGNORECASE)
        if match:
            specs[label] = float(match.group(1)) if "." in match.group(1) else int(match.group(1))
    for token, value in (("USB-C", "USB-C"), ("Lightning", "Lightning"), ("65W", "65W"), ("4K", "4K"), ("国行", "中国大陆版"), ("翻新", "翻新"), ("拆封", "拆封")):
        if token.lower() in clean.lower():
            specs.setdefault("detected", []).append(value)
    title = clean[:120] if clean else Path(fallback_title).stem[:120]
    return {
        "title": title or "截图商品（待确认）", "category": category, "platform": "", "url": "",
        "brand": brand, "model": model_match.group(1) if model_match else "", "sku": "", "specs": specs,
        "price": float(price_match.group(1) or price_match.group(2)) if price_match else 0.0,
        "coupon": 0.0, "platform_discount": 0.0, "member_discount": 0.0, "subsidy": 0.0,
        "pay_discount": 0.0, "shipping": 0.0, "gift_value": 0.0, "condition": "new",
        "official_store": False, "return_days": 7, "warranty_months": 12,
        "notes": "由截图 OCR 生成，请核对型号、规格与价格后再分析。",
    }


def _detect_category(text: str) -> str:
    categories = {
        "phone": ("手机", "iphone", "mate", "pura"),
        "laptop": ("笔记本", "macbook", "thinkpad", "电脑"),
        "monitor": ("显示器", "英寸", "4k", "144hz"),
        "headphone": ("耳机", "airpods", "buds", "降噪"),
        "keyboard": ("键盘", "机械轴", "keycap"),
        "router": ("路由器", "wifi", "wi-fi"),
        "robot_vacuum": ("扫地机器人", "扫拖", "基站"),
        "coffee_machine": ("咖啡机", "浓缩", "磨豆"),
    }
    lowered = text.lower()
    return next((name for name, terms in categories.items() if any(term.lower() in lowered for term in terms)), "unknown")


def _extract_text(path: Path) -> tuple[str, str, str]:
    if not importlib.util.find_spec("PIL") or not importlib.util.find_spec("pytesseract"):
        return "", "unavailable", "本地 OCR 依赖未安装，图片已安全保存，请人工确认商品信息。"
    try:
        from PIL import Image
        import pytesseract

        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            text = pytesseract.image_to_string(image, lang="chi_sim+eng", config="--psm 6")
        return text.strip(), "tesseract", ""
    except Exception as exc:
        return "", "tesseract_error", f"OCR 识别失败，已降级为人工确认：{type(exc).__name__}"
