from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.object_storage import persist_upload
from app.core.paths import runtime_data_dir
from app.providers.llm_provider import llm_provider

ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
VISION_PROMPT = """你是 ValuSee 商品截图识别器。只提取图片中明确可见的信息，不得猜测或补全。
返回一个 JSON 对象，不要 Markdown，不要解释。字段：
ocr_text,title,brand,model,sku,platform,category,price,coupon,platform_discount,member_discount,
subsidy,shipping,store_name,selected_variant,condition,official_store,return_days,warranty_months,
specs,confidence,evidence_notes。
price 和优惠字段使用数字；看不清时使用 0 或空字符串。category 仅使用 phone、laptop、monitor、
headphone、keyboard、router、robot_vacuum、coffee_machine、unknown。confidence 为 0 到 1。
标题应是商品标题，不要把用户评价、销量、页面导航、文件名、订单编号、店铺名或广告语当成标题。
价格必须按视觉标签判断：券后价、到手价或实付价优先作为 price；原价、优惠前价格和划线价不能作为
当前成交价。不要把评价数量、销量、折扣百分比、月销数字或 SKU 数字识别成价格。selected_variant
只填写页面当前明确选中的颜色、尺码、容量或套装。OCR 参考文本可能有错，只可用于辅助定位，最终以
图片的视觉层级、标签和选中状态为准。"""


def inspect_product_image(content: bytes, content_type: str, original_name: str, *, client_ocr_text: str = "", user_config: dict[str, Any] | None = None) -> dict[str, Any]:
    del original_name
    _validate_upload(content, content_type)
    _validate_image_pixels(content)
    digest = hashlib.sha256(content).hexdigest()
    upload_dir = runtime_data_dir("uploads")
    stored_name = f"img_{uuid4().hex}{ALLOWED_IMAGE_TYPES[content_type]}"
    stored_path = upload_dir / stored_name
    stored_path.write_bytes(content)
    storage = persist_upload(stored_path, content_type)

    supplied_text = client_ocr_text.strip()[:30_000]
    vision_payload, provider, warning = _extract_with_vision(content, content_type, supplied_text, user_config=user_config)
    if vision_payload:
        model_text = str(vision_payload.get("ocr_text") or "").strip()
        text = supplied_text or model_text
        fusion_text = "\n".join(dict.fromkeys(value for value in (model_text, supplied_text) if value))
        product = normalize_vision_product({**vision_payload, "ocr_text": fusion_text})
        if supplied_text:
            provider = f"{provider}+browser:tesseract.js"
            warning = _join_warnings(warning, "已使用视觉模型与浏览器 OCR 交叉识别。")
    elif supplied_text:
        provider = "browser:tesseract.js"
        warning = _join_warnings(warning, "视觉模型暂不可用，当前结果仅由浏览器 OCR 推断。")
        text = supplied_text
        product = normalize_product_text(text)
    else:
        text, provider, local_warning = _extract_with_tesseract(stored_path)
        warning = _join_warnings(warning, local_warning)
        product = normalize_product_text(text)

    missing_fields = _missing_product_fields(product)
    recognized = _has_product_evidence(product, text)
    recognition_status = "recognized" if recognized and len(missing_fields) <= 1 else "partial" if recognized else "unavailable"
    if recognition_status == "unavailable":
        warning = _join_warnings(warning, "图片中未识别到可确认的商品信息，请换用清晰完整截图或手动补充。")
    confidence = _bounded_number(vision_payload.get("confidence") if vision_payload else 0.0)
    return {
        "asset_id": stored_name.rsplit(".", 1)[0], "file_name": stored_name,
        "content_type": content_type, "size": len(content), "sha256": digest,
        "storage": storage, "ocr_provider": provider, "ocr_text": text,
        "product": product, "requires_confirmation": True, "warning": warning,
        "recognition_status": recognition_status, "confidence": confidence,
        "missing_fields": missing_fields,
    }


def _validate_upload(content: bytes, content_type: str) -> None:
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("仅支持 JPG、PNG 和 WebP 商品图片")
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能为空且大小不能超过 8 MB")
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": content.startswith(b"RIFF") and content[8:12] == b"WEBP",
    }
    if not signatures[content_type]:
        raise ValueError("图片内容与声明类型不一致")


def _validate_image_pixels(content: bytes) -> None:
    if importlib.util.find_spec("PIL") is None:
        return
    from PIL import Image

    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError("图片像素尺寸过大")
            image.verify()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("图片文件已损坏或格式无效") from exc


def _extract_with_vision(content: bytes, content_type: str, ocr_hint: str = "", *, user_config: dict[str, Any] | None = None) -> tuple[dict[str, Any], str, str]:
    if not user_config or not user_config.get("enabled") or not user_config.get("api_key"):
        return {}, "vision_unavailable", "在线图片识别需要配置你自己的视觉模型 API Key，已尝试本地 OCR。"
    image_content, image_type = _prepare_vision_image(content, content_type)
    user_prompt = "识别这张用户主动上传的电商商品截图，优先读取当前选中规格、当前成交价、店铺和优惠。"
    if ocr_hint:
        user_prompt += f"\n以下是本地 OCR 参考文本，可能存在错字或错序，请与图片核对后再输出：\n{ocr_hint[:8000]}"
    result = llm_provider.analyze_image_with_status(
        VISION_PROMPT,
        user_prompt,
        image_content,
        image_type,
        user_config=user_config,
    )
    if result.get("fallback_used"):
        messages = {
            "not_configured": "在线图片识别尚未配置视觉模型，已尝试本地 OCR。",
            "auth_failed": "在线图片识别的 API 密钥或 Base URL 鉴权失败，已尝试本地 OCR。",
            "model_unsupported": "当前模型不支持图片输入，请在模型服务后台选择支持图片输入的模型，并配置视觉模型名称，已尝试本地 OCR。",
            "invalid_response": "视觉模型返回格式无效，已尝试本地 OCR。",
            "network_error": "视觉模型网络连接失败，已尝试本地 OCR。",
            "provider_unavailable": "在线图片识别暂不可用，已尝试本地 OCR。",
            "all_providers_failed": "主视觉模型和备用视觉模型均不可用，已尝试本地 OCR。",
        }
        code = str(result.get("error_code") or "provider_unavailable")
        provider_name = str(result.get("provider_name") or "primary")
        warning = messages.get(code, messages["provider_unavailable"])
        if provider_name in {"fallback", "fallback_provider"}:
            warning = "主视觉模型不可用，已切换备用视觉模型；请核对识别结果。"
        return {}, "vision_unavailable", warning
    payload = _json_object(str(result.get("text") or ""))
    if not payload:
        return {}, f"vision:{result.get('model') or 'configured'}", "视觉模型未返回有效结构，已尝试本地 OCR。"
    provider_name = str(result.get("provider_name") or "primary")
    provider_label = "备用视觉模型" if provider_name in {"fallback", "fallback_provider"} else "视觉模型"
    return payload, f"vision:{result.get('model') or 'configured'}", f"已使用{provider_label}识别，结果可能存在误差，请核对商品和价格。"


def _prepare_vision_image(content: bytes, content_type: str) -> tuple[bytes, str]:
    if not importlib.util.find_spec("PIL"):
        return content, content_type
    from PIL import Image

    with Image.open(BytesIO(content)) as image:
        if max(image.size) <= 2200 and len(content) <= 4 * 1024 * 1024:
            return content, content_type
        image.thumbnail((2200, 2200))
        converted = image.convert("RGB")
        output = BytesIO()
        converted.save(output, format="JPEG", quality=90, optimize=True)
        return output.getvalue(), "image/jpeg"


def _json_object(value: str) -> dict[str, Any]:
    stripped = value.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_vision_product(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("ocr_text") or "")
    fallback = normalize_product_text(text)
    specs = payload.get("specs") if isinstance(payload.get("specs"), dict) else {}
    category = str(payload.get("category") or fallback["category"])
    allowed_categories = {"phone", "laptop", "monitor", "headphone", "keyboard", "router", "robot_vacuum", "coffee_machine", "unknown"}
    if category not in allowed_categories:
        category = fallback["category"]
    title = _text(payload.get("title"), 200)
    fallback_title = fallback["title"] if fallback["title"] != "截图商品（待确认）" else ""
    return {
        **fallback,
        "title": title or fallback_title or "截图商品（待确认）",
        "category": category,
        "platform": _text(payload.get("platform") or fallback["platform"], 40),
        "brand": _text(payload.get("brand") or fallback["brand"], 80),
        "model": _text(payload.get("model") or fallback["model"], 100),
        "sku": _text(payload.get("sku") or fallback["sku"], 100),
        "specs": {**fallback["specs"], **{str(key)[:80]: str(value)[:300] for key, value in list(specs.items())[:30]}},
        "price": _bounded_number(payload.get("price") or fallback["price"]),
        "coupon": _bounded_number(payload.get("coupon") or fallback["coupon"]),
        "platform_discount": _bounded_number(payload.get("platform_discount") or fallback["platform_discount"]),
        "member_discount": _bounded_number(payload.get("member_discount") or fallback["member_discount"]),
        "subsidy": _bounded_number(payload.get("subsidy") or fallback["subsidy"]),
        "shipping": _bounded_number(payload.get("shipping") or fallback["shipping"]),
        "condition": _text(payload.get("condition"), 40) or "new",
        "official_store": payload.get("official_store") is True,
        "return_days": _bounded_int(payload.get("return_days"), 0, 365, 7),
        "warranty_months": _bounded_int(payload.get("warranty_months"), 0, 240, 12),
        "store_name": _text(payload.get("store_name") or fallback["store_name"], 100),
        "selected_variant": _text(payload.get("selected_variant") or fallback["selected_variant"], 240),
        "evidence": {"type": "user_uploaded_screenshot", "notes": _text(payload.get("evidence_notes"), 500)},
        "notes": "由 AI 截图识别生成，请核对型号、规格、价格和优惠后再分析。",
    }


def normalize_product_text(text: str, fallback_title: str = "") -> dict[str, Any]:
    del fallback_title
    lines = [" ".join(line.split()) for line in text.replace("\u3000", " ").splitlines() if line.strip()]
    clean = " ".join(text.replace("\u3000", " ").split())
    price = _labeled_amount(clean, ("券后价", "券后", "预估到手价", "到手价", "实付价", "成交价", "会员价", "活动价", "促销价", "当前价格", "current price"))
    if not price:
        generic_price = re.search(r"(?:(?:￥|¥|RMB)\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*元)", clean, re.IGNORECASE)
        price = float(generic_price.group(1) or generic_price.group(2)) if generic_price else 0.0
    model_match = re.search(r"\b((?:AirPods\s+Pro\s+\d+)|(?:[A-Z]{1,8}[- ]?\d{2,}[A-Z0-9-]*))\b", clean, re.IGNORECASE)
    sku_match = re.search(r"(?:SKU|商品编号|货号)\s*[:：]?\s*([A-Z0-9][A-Z0-9/_-]{3,})", clean, re.IGNORECASE)
    if not sku_match:
        sku_match = re.search(r"\b([A-Z0-9]{4,}/[A-Z0-9]{1,12})\b", clean, re.IGNORECASE)
    coupon = _labeled_amount(clean, ("优惠券", "领券", "coupon"))
    selected_match = re.search(r"(?:已选中?|当前选择|selected)\s*[:：]?\s*([^\n]{2,160})", text, re.IGNORECASE)
    store_match = re.search(r"(?:店铺|商家)\s*[:：]\s*([^\n]{2,100})", text, re.IGNORECASE)
    brands = ("Apple", "华为", "小米", "荣耀", "联想", "戴尔", "三星", "索尼", "美的", "海尔", "科沃斯", "石头", "OPPO", "vivo")
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
    return {
        "title": _title_from_ocr(lines) or "截图商品（待确认）", "category": category, "platform": _platform_from_text(clean), "url": "",
        "brand": brand, "model": model_match.group(1) if model_match else "", "sku": sku_match.group(1) if sku_match else "", "specs": specs,
        "price": price,
        "coupon": coupon, "platform_discount": 0.0, "member_discount": 0.0, "subsidy": 0.0,
        "pay_discount": 0.0, "shipping": 0.0, "gift_value": 0.0, "condition": "new",
        "official_store": bool(re.search(r"官方旗舰|官方店|自营|official store", clean, re.IGNORECASE)), "return_days": 7, "warranty_months": 12,
        "store_name": store_match.group(1).strip() if store_match else "", "image_url": "", "selected_variant": selected_match.group(1).strip() if selected_match else "", "region": "unknown", "membership": "unknown",
        "observation_status": "requires_confirmation", "evidence": {"type": "local_ocr"},
        "notes": "由截图 OCR 生成，请核对型号、规格与价格后再分析。",
    }


def _detect_category(text: str) -> str:
    categories = {
        "phone": ("手机", "iphone", "mate", "pura"), "laptop": ("笔记本", "macbook", "thinkpad", "电脑"),
        "monitor": ("显示器", "英寸", "4k", "144hz"), "headphone": ("耳机", "airpods", "buds", "降噪"),
        "keyboard": ("键盘", "机械轴", "keycap"), "router": ("路由器", "wifi", "wi-fi"),
        "robot_vacuum": ("扫地机器人", "扫拖", "基站"), "coffee_machine": ("咖啡机", "浓缩", "磨豆"),
    }
    lowered = text.lower()
    return next((name for name, terms in categories.items() if any(term.lower() in lowered for term in terms)), "unknown")


def _title_from_ocr(lines: list[str]) -> str:
    ignored = re.compile(r"(?:用户评价|宝贝评价|累计评价|全部评价|月销|已售|人付款|加购|购物车|收藏|客服|好评率|优惠前|原价|划线价|券后|到手价|当前价格|价格|优惠券|领券|优惠|满减|补贴|sku|商品编号|货号|selected|已选|店铺|official store|current price)", re.IGNORECASE)
    product_terms = ("手机", "笔记本", "显示器", "耳机", "键盘", "路由器", "扫地机器人", "咖啡机", "iphone", "macbook", "airpods", "thinkpad", "monitor")
    brand_terms = ("apple", "华为", "小米", "荣耀", "联想", "戴尔", "dell", "三星", "索尼", "sony", "美的", "海尔", "科沃斯", "石头", "oppo", "vivo")
    candidates = []
    for index, line in enumerate(lines[:80]):
        value = line.strip(" -_|·")[:200]
        if len(value) < 4 or ignored.search(value) or re.fullmatch(r"[￥¥$]?\s*[\d,.]+(?:\s*元)?", value):
            continue
        lowered = value.lower()
        score = min(len(value), 80) / 20 - index * 0.03
        score += 5 if any(term in lowered for term in product_terms) else 0
        score += 4 if any(term in lowered for term in brand_terms) else 0
        score += 2 if re.search(r"[A-Za-z]+[- ]?\d{2,}", value) else 0
        candidates.append((score, value))
    return max(candidates, default=(0, ""))[1][:120]


def _labeled_amount(text: str, labels: tuple[str, ...]) -> float:
    normalized = text.replace(",", "")
    for label in labels:
        match = re.search(
            rf"{re.escape(label)}\s*(?:约|低至|后|为)?\s*[:：]?\s*(?:￥|¥|RMB)?\s*(\d+(?:\.\d{{1,2}})?)",
            normalized,
            re.IGNORECASE,
        )
        if match:
            return float(match.group(1))
    return 0.0


def _platform_from_text(text: str) -> str:
    lowered = text.lower()
    for platform, terms in {
        "京东": ("京东", "jd.com", "jd product"), "淘宝": ("淘宝", "taobao"),
        "天猫": ("天猫", "tmall"), "拼多多": ("拼多多", "pinduoduo"),
    }.items():
        if any(term.lower() in lowered for term in terms):
            return platform
    return ""


def _extract_with_tesseract(path: Path) -> tuple[str, str, str]:
    if not importlib.util.find_spec("PIL") or not importlib.util.find_spec("pytesseract"):
        return "", "unavailable", "本地 OCR 依赖未安装。"
    try:
        from PIL import Image, ImageEnhance, ImageOps
        import pytesseract

        with Image.open(path) as image:
            prepared = ImageOps.grayscale(image)
            prepared = ImageEnhance.Contrast(prepared).enhance(1.6)
            text = pytesseract.image_to_string(prepared, lang="chi_sim+eng", config="--oem 3 --psm 6")
        return text.strip(), "tesseract", ""
    except Exception as exc:
        return "", "tesseract_error", f"本地 OCR 识别失败：{type(exc).__name__}"


def _missing_product_fields(product: dict[str, Any]) -> list[str]:
    missing = []
    if product.get("title") in {"", "截图商品（待确认）"}:
        missing.append("商品标题")
    if not product.get("price"):
        missing.append("当前价格")
    if not product.get("model") and not product.get("sku") and not product.get("selected_variant"):
        missing.append("型号/SKU/已选规格")
    return missing


def _has_product_evidence(product: dict[str, Any], text: str) -> bool:
    meaningful_title = product.get("title") not in {"", "截图商品（待确认）"}
    return bool(meaningful_title or product.get("price") or product.get("brand") or product.get("model") or product.get("sku") or product.get("specs") or text.strip())


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _bounded_number(value: Any) -> float:
    try:
        return max(0.0, min(float(value or 0), 100_000_000.0))
    except (TypeError, ValueError):
        return 0.0


def _bounded_int(value: Any, minimum: int, maximum: int, default: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _join_warnings(*values: str) -> str:
    return " ".join(dict.fromkeys(value.strip() for value in values if value and value.strip()))
