from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path
from typing import Any
from uuid import uuid4


ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
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

    text, provider, warning = _extract_text(stored_path)
    product = normalize_product_text(text, original_name)
    return {
        "asset_id": stored_name.rsplit(".", 1)[0],
        "file_name": stored_name,
        "content_type": content_type,
        "size": len(content),
        "sha256": digest,
        "ocr_provider": provider,
        "ocr_text": text,
        "product": product,
        "requires_confirmation": not bool(text.strip()) or not bool(product["model"] or product["brand"]),
        "warning": warning,
    }


def normalize_product_text(text: str, fallback_title: str = "") -> dict[str, Any]:
    clean = " ".join(text.replace("\u3000", " ").split())
    price_match = re.search(r"(?:¥|￥|RMB\s*)\s*(\d+(?:\.\d{1,2})?)", clean, re.IGNORECASE)
    model_match = re.search(r"\b([A-Z]{1,6}[- ]?\d{2,}[A-Z0-9-]*)\b", clean, re.IGNORECASE)
    brands = ("Apple", "华为", "小米", "荣耀", "联想", "戴尔", "三星", "索尼", "美的", "海尔", "科沃斯")
    brand = next((item for item in brands if item.lower() in clean.lower()), "")
    title = clean[:120] if clean else Path(fallback_title).stem[:120]
    return {
        "title": title or "截图商品（待确认）",
        "platform": "",
        "url": "",
        "brand": brand,
        "model": model_match.group(1) if model_match else "",
        "sku": "",
        "specs": {},
        "price": float(price_match.group(1)) if price_match else 0.0,
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
        "notes": "由截图 OCR 生成，请核对商品型号、规格和价格。",
    }


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

