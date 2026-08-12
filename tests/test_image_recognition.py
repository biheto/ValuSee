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


def test_browser_ocr_text_falls_back_when_external_vision_is_unavailable(monkeypatch, tmp_path) -> None:
    prepare_storage(monkeypatch, tmp_path)
    monkeypatch.setattr(vision, "_extract_with_vision", lambda *_args: ({}, "vision_unavailable", "视觉模型不可用。"))
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


def test_browser_ocr_is_fused_with_visual_result(monkeypatch, tmp_path) -> None:
    prepare_storage(monkeypatch, tmp_path)
    captured = {}

    def visual(_content, _content_type, ocr_hint=""):
        captured["ocr_hint"] = ocr_hint
        return ({
            "ocr_text": "券后 ¥83.26",
            "title": "小个子工装牛仔背带裤短裤女宽松慵懒风可爱减龄学生2026新款夏日",
            "price": 83.26,
            "sku": "5807786724999",
            "platform": "淘宝",
            "store_name": "WAN 小婉女装",
            "selected_variant": "牛仔蓝 优质现货",
            "confidence": 0.94,
        }, "vision:gpt-4o-mini", "请核对。")

    monkeypatch.setattr(vision, "_extract_with_vision", visual)
    ocr = "用户评价·400+\n优惠前 ¥98\n券后 ¥83.26\n已选 牛仔蓝 优质现货"
    result = vision.inspect_product_image(png_bytes(), "image/png", "taobao.png", client_ocr_text=ocr)

    assert captured["ocr_hint"] == ocr
    assert result["ocr_provider"] == "vision:gpt-4o-mini+browser:tesseract.js"
    assert result["product"]["price"] == 83.26
    assert result["product"]["title"].startswith("小个子工装牛仔背带裤")
    assert result["product"]["selected_variant"] == "牛仔蓝 优质现货"


def test_ocr_prefers_effective_price_and_rejects_review_title() -> None:
    product = vision.normalize_product_text("""淘宝
用户评价·400+
小个子工装牛仔背带裤短裤女宽松慵懒风可爱减龄学生2026新款夏日
优惠前 ¥98
券后 ¥83.26
店铺：WAN 小婉女装
已选：牛仔蓝 优质现货""")

    assert product["title"].startswith("小个子工装牛仔背带裤")
    assert product["price"] == 83.26
    assert product["store_name"] == "WAN 小婉女装"
    assert product["selected_variant"] == "牛仔蓝 优质现货"


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
    assert provider._vision_endpoints("https://congee.pro", "responses") == [
        "https://congee.pro/v1/responses", "https://congee.pro/responses",
    ]


def test_responses_wire_converts_multimodal_messages_and_reads_output() -> None:
    provider = LLMProvider()
    messages = [
        {"role": "system", "content": "Extract JSON."},
        {"role": "user", "content": [
            {"type": "text", "text": "Read this."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc", "detail": "high"}},
        ]},
    ]

    converted = provider._responses_input(messages)
    assert converted[1]["content"][0] == {"type": "input_text", "text": "Read this."}
    assert converted[1]["content"][1] == {
        "type": "input_image", "image_url": "data:image/png;base64,abc", "detail": "high",
    }
    assert provider._vision_response_text({"output_text": '{"title":"AirPods"}'}) == '{"title":"AirPods"}'
    assert provider._vision_response_text({"output": [{"content": [{"type": "output_text", "text": "ok"}]}]}) == "ok"


def test_vision_provider_errors_are_classified_without_exposing_secrets() -> None:
    provider = LLMProvider()

    assert provider._classify_provider_error("https://example/v1/chat/completions: HTTP 401 {\"error\":\"invalid_api_key\"}") == "auth_failed"
    assert provider._classify_provider_error("HTTP 400 model vision-basic is not supported") == "model_unsupported"
    assert provider._classify_provider_error("vision provider returned no message content") == "invalid_response"
