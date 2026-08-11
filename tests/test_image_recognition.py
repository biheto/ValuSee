from __future__ import annotations

import base64

import app.shopping.vision as vision
from app.providers.llm_provider import LLMProvider


def png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def prepare_storage(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(vision, "runtime_data_dir", lambda _name: tmp_path)
    monkeypatch.setattr(vision, "persist_upload", lambda path, _content_type: {"backend": "test", "key": path.name})


def test_unavailable_ocr_never_uses_upload_filename_as_product_title(monkeypatch, tmp_path) -> None:
    prepare_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(vision, "_extract_with_vision", lambda *_args: ({}, "vision_unavailable", "视觉模型不可用。"))
    monkeypatch.setattr(vision, "_extract_with_tesseract", lambda _path: ("", "tesseract_error", "OCR 不可用。"))

    result = vision.inspect_product_image(png_bytes(), "image/png", "iPhone-16-Pro-5999元.png")

    assert result["recognition_status"] == "unavailable"
    assert result["product"]["title"] == "截图商品（待确认）"
    assert "iPhone" not in result["product"]["title"]
    assert result["missing_fields"] == ["商品标题", "当前价格", "型号/SKU/已选规格"]


def test_multimodal_result_becomes_an_editable_structured_product(monkeypatch, tmp_path) -> None:
    prepare_storage(monkeypatch, tmp_path)
    payload = {
        "ocr_text": "Apple AirPods Pro 2 USB-C 到手价 ¥1499",
        "title": "Apple AirPods Pro 2 USB-C",
        "brand": "Apple",
        "model": "AirPods Pro 2",
        "sku": "MTJV3CH/A",
        "platform": "京东",
        "category": "headphone",
        "price": 1499,
        "coupon": 100,
        "store_name": "Apple 产品京东自营旗舰店",
        "selected_variant": "USB-C / 国行",
        "official_store": True,
        "specs": {"接口": "USB-C"},
        "confidence": 0.93,
    }
    monkeypatch.setattr(vision, "_extract_with_vision", lambda *_args: (payload, "vision:gpt-4o-mini", "请核对。"))

    result = vision.inspect_product_image(png_bytes(), "image/png", "screenshot.png")

    assert result["recognition_status"] == "recognized"
    assert result["confidence"] == 0.93
    assert result["ocr_provider"] == "vision:gpt-4o-mini"
    assert result["product"]["title"] == "Apple AirPods Pro 2 USB-C"
    assert result["product"]["price"] == 1499
    assert result["product"]["sku"] == "MTJV3CH/A"
    assert result["product"]["selected_variant"] == "USB-C / 国行"
    assert result["missing_fields"] == []


def test_browser_ocr_text_skips_external_vision_and_extracts_product(monkeypatch, tmp_path) -> None:
    prepare_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(vision, "_extract_with_vision", lambda *_args: (_ for _ in ()).throw(AssertionError("vision should not run")))
    text = """JD Product Detail
Apple AirPods Pro 2 USB-C
SKU: MTJV3CH/A
Apple Official Store
Current price: RMB 1499
Coupon: RMB 100
Selected: White / China Version"""

    result = vision.inspect_product_image(png_bytes(), "image/png", "anything.png", client_ocr_text=text)

    assert result["ocr_provider"] == "browser:tesseract.js"
    assert result["product"]["title"] == "Apple AirPods Pro 2 USB-C"
    assert result["product"]["platform"] == "京东"
    assert result["product"]["price"] == 1499
    assert result["product"]["coupon"] == 100
    assert result["product"]["sku"] == "MTJV3CH/A"
    assert result["product"]["selected_variant"] == "White / China Version"
    assert result["recognition_status"] == "recognized"


def test_ocr_extracts_slash_sku_when_its_chinese_label_is_noisy() -> None:
    product = vision.normalize_product_text("Apple AirPods Pro 2 USB-C\n商品编亏 MTJV3CH/A\n当前价格 ¥1499")

    assert product["sku"] == "MTJV3CH/A"
    assert product["price"] == 1499


def test_json_fence_from_vision_provider_is_parsed() -> None:
    result = vision._json_object('```json\n{"title":"Dell U2723QE","price":3499}\n```')

    assert result == {"title": "Dell U2723QE", "price": 3499}


def test_multimodal_provider_sends_image_without_storing_base64_in_trace(monkeypatch) -> None:
    provider = LLMProvider()
    recorded = {}

    monkeypatch.setattr(provider, "_config", lambda _agent=None: {"api_key": "test-key", "model": "vision-test", "base_url": "", "source": "test"})
    def fake_invoke(_config, messages):
        assert messages[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        return {"choices": [{"message": {"content": [{"type": "text", "text": '{"title":"AirPods Pro 2"}'}]}}], "usage": {"input_tokens": 20, "output_tokens": 8}}
    monkeypatch.setattr(provider, "_invoke_vision_http", fake_invoke)
    monkeypatch.setattr(provider, "_save_trace", lambda **values: recorded.update(values))

    result = provider.analyze_image_with_status("system", "user", png_bytes(), "image/png")

    assert result["fallback_used"] is False
    assert result["text"] == '{"title":"AirPods Pro 2"}'
    assert recorded["input_payload"]["image"]["size_bytes"] == len(png_bytes())
    assert "base64" not in str(recorded["input_payload"])


def test_vision_endpoint_normalization_supports_standard_and_gateway_urls() -> None:
    provider = LLMProvider()

    assert provider._vision_endpoints("") == ["https://api.openai.com/v1/chat/completions"]
    assert provider._vision_endpoints("https://gateway.example/v1") == ["https://gateway.example/v1/chat/completions"]
    assert provider._vision_endpoints("https://gateway.example") == [
        "https://gateway.example/v1/chat/completions", "https://gateway.example/chat/completions",
    ]
