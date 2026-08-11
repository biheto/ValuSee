from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import app
from app.shopping.public_pages import canonical_product_url, parse_product_html, validate_public_product_url
from app.shopping.store import ShoppingStore


PRODUCT_HTML = """
<!doctype html><html><head>
<meta property="og:title" content="fallback title">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Dell U2723QE 4K 显示器",
 "sku":"U2723QE-CN","model":"U2723QE","brand":{"@type":"Brand","name":"Dell"},
 "image":["https://img.example/product.jpg"],
 "additionalProperty":[{"@type":"PropertyValue","name":"分辨率","value":"3840x2160"}],
 "offers":{"@type":"Offer","price":"3499.00","seller":{"name":"官方旗舰店"}}}
</script></head><body><h1>商品详情</h1></body></html>
"""


def product(price: float = 3499) -> dict[str, object]:
    return {
        "title": "Dell U2723QE 4K 显示器",
        "platform": "京东",
        "url": "https://item.jd.com/100012345.html",
        "brand": "Dell",
        "model": "U2723QE",
        "sku": "U2723QE-CN",
        "specs": {"分辨率": "3840x2160"},
        "price": price,
        "coupon": 100,
        "selected_variant": "黑色 / 国行",
        "region": "北京",
        "membership": "PLUS 会员价",
        "observation_status": "requires_confirmation",
        "evidence": {"type": "browser_visible_page", "url": "https://item.jd.com/100012345.html"},
    }


def test_structured_public_product_page_is_normalized() -> None:
    result = parse_product_html(PRODUCT_HTML, "https://item.jd.com/100012345.html")

    assert result["fetch_status"] == "parsed"
    assert result["platform"] == "京东"
    assert result["title"] == "Dell U2723QE 4K 显示器"
    assert result["sku"] == "U2723QE-CN"
    assert result["price"] == 3499
    assert result["specs"]["分辨率"] == "3840x2160"
    assert result["observation_status"] == "requires_confirmation"


def test_embedded_commerce_state_is_used_when_json_ld_is_missing() -> None:
    content = """
    <html><head><title>淘宝商品详情</title></head><body>
    <script>window.__ITEM_DATA__ = {
      "itemTitle":"Sony WH-1000XM5 无线降噪耳机",
      "brandName":"Sony","productModel":"WH-1000XM5",
      "skuId":"XM5-BLACK","priceText":"2499.00"
    };</script><div>商品详情</div></body></html>
    """

    result = parse_product_html(content, "https://item.taobao.com/item.htm?id=778899")

    assert result["fetch_status"] == "parsed"
    assert result["title"] == "Sony WH-1000XM5 无线降噪耳机"
    assert result["brand"] == "Sony"
    assert result["model"] == "WH-1000XM5"
    assert result["sku"] == "XM5-BLACK"
    assert result["price"] == 2499
    assert result["specs"]["商品ID"] == "778899"


def test_jd_page_config_is_used_when_product_dom_is_rendered_later() -> None:
    content = """
    <html><head><title>京东商品详情</title></head><body>
    <script>window.pageConfig = {"product":{"skuid":100092233, "skuName":"联想 ThinkBook 14+ 笔记本电脑", "brandName":"Lenovo", "jdPrice":"5299.00"}};</script>
    </body></html>
    """

    result = parse_product_html(content, "https://item.jd.com/100092233.html")

    assert result["fetch_status"] == "parsed"
    assert result["title"] == "联想 ThinkBook 14+ 笔记本电脑"
    assert result["sku"] == "100092233"
    assert result["price"] == 5299


def test_pinduoduo_raw_data_cent_price_is_normalized() -> None:
    content = """
    <html><head><title>拼多多</title></head><body>
    <script>window.rawData={"goods":{"goodsName":"石头扫地机器人 P20 Pro", "goodsId":66889900, "minGroupPrice":259900}};</script>
    </body></html>
    """

    result = parse_product_html(content, "https://mobile.yangkeduo.com/goods.html?goods_id=66889900")

    assert result["fetch_status"] == "parsed"
    assert result["title"] == "石头扫地机器人 P20 Pro"
    assert result["sku"] == "66889900"
    assert result["price"] == 2599


def test_generic_platform_shell_is_not_reported_as_a_parsed_product() -> None:
    result = parse_product_html(
        "<html><head><title>淘宝网 - 淘！我喜欢</title></head><body>登录后查看</body></html>",
        "https://item.taobao.com/item.htm?id=778899",
    )

    assert result["fetch_status"] == "blocked"
    assert result["title"] == "来自 淘宝 的商品（待确认）"
    assert result["price"] == 0


def test_product_url_allowlist_rejects_credentials_and_lookalike_hosts() -> None:
    with pytest.raises(ValueError):
        validate_public_product_url("https://jd.com@127.0.0.1/private")
    with pytest.raises(ValueError):
        validate_public_product_url("https://eviljd.com/item/1")
    with pytest.raises(ValueError):
        validate_public_product_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        validate_public_product_url("https://item.jd.com:8443/10001.html")


def test_product_url_canonicalization_removes_tracking_but_keeps_item_identity() -> None:
    assert canonical_product_url("https://item.taobao.com/item.htm?id=123&spm=tracking&token=secret#detail") == "https://item.taobao.com/item.htm?id=123"


def test_browser_extension_download_contains_installable_manifest() -> None:
    response = TestClient(app).get("/api/v1/downloads/browser-extension")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "valuesee-browser-extension.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert {"manifest.json", "background.js", "content.js", "popup.html", "popup.js", "popup.css"} <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["manifest_version"] == 3
        assert manifest["version"] == "0.3.0"
        assert "scripting" in manifest["permissions"]
        assert "https://api.valusee.com/*" in manifest["host_permissions"]
        assert "https://*.yangkeduo.com/*" in manifest["host_permissions"]
        popup = archive.read("popup.js").decode("utf-8")
        content = archive.read("content.js").decode("utf-8")
        assert "/api/v1/auth/me" in popup
        assert "chrome.scripting.executeScript" in popup
        assert "VALUSee_COLLECT_PRODUCT_V2" in popup
        assert "VALUSee_COLLECT_PRODUCT_V2" in content


def test_extension_price_is_persisted_only_after_final_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    with TemporaryDirectory() as tmp:
        store = ShoppingStore(Path(tmp) / "capture.db")
        monkeypatch.setattr(routes, "shopping_store", store)
        monkeypatch.setattr(routes, "publish_monitor_event", lambda _event: True)
        client = TestClient(app)

        created = client.post(
            "/api/v1/shopping/extension/captures",
            json={"product": product(), "source": "browser_extension_visible_page"},
        )
        assert created.status_code == 200
        capture = created.json()
        assert capture["status"] == "pending_confirmation"
        assert store.price_history(str(product()["url"]), user_id="local-user")["count"] == 0

        corrected = product(3299)
        confirmed = client.post(
            f"/api/v1/shopping/extension/captures/{capture['capture_id']}/confirm",
            json={"product": corrected},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["product"]["observation_status"] == "confirmed"
        history = store.price_history(str(corrected["url"]), user_id="local-user")
        assert history["count"] == 1
        assert history["points"][0]["region"] == "北京"
        assert history["points"][0]["membership"] == "PLUS 会员价"
        assert history["points"][0]["conditions"]["confirmation_status"] == "confirmed"
        assert history["points"][0]["conditions"]["sku"] == "U2723QE-CN"

        repeated = client.post(f"/api/v1/shopping/extension/captures/{capture['capture_id']}/confirm", json={})
        assert repeated.status_code == 200
        assert repeated.json()["confirmed_now"] is False
        assert store.price_history(str(corrected["url"]), user_id="local-user")["count"] == 1
