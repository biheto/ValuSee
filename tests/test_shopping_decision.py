from __future__ import annotations

from app.shopping.graph import shopping_decision_graph_runner
import app.shopping.graph as shopping_graph


def _run(products, profile=None):
    state = {
        "goal": "购买决策",
        "products": products,
        "profile": profile or {},
        "task_id": "task-shopping-test",
        "events": [],
    }
    return shopping_decision_graph_runner(state)


def test_same_sku_products_are_matched_as_same_item():
    result = _run(
        [
            {
                "title": "AirPods Pro 2 USB-C",
                "platform": "JD",
                "brand": "Apple",
                "model": "AirPods Pro 2",
                "sku": "APP2-USBC",
                "specs": {"version": "USB-C", "generation": "2"},
                "price": 1799,
                "coupon": 100,
                "shipping": 0,
                "official_store": True,
            },
            {
                "title": "AirPods Pro 2 USB-C 官方正品",
                "platform": "Tmall",
                "brand": "Apple",
                "model": "AirPods Pro 2",
                "sku": "APP2-USBC",
                "specs": {"version": "USB-C", "generation": "2"},
                "price": 1699,
                "coupon": 50,
                "shipping": 0,
                "official_store": True,
            },
        ],
        {"budget": 1800, "brand_preferences": ["Apple"], "acceptable_risk": "medium"},
    )

    assert result["result"]["best_index"] == 1
    assert result["result"]["same_item_matches"][0]["relation"] == "same"
    assert result["result"]["same_item_matches"][1]["relation"] == "same"


def test_lightning_and_usb_c_are_not_treated_as_same_item():
    result = _run(
        [
            {
                "title": "AirPods Pro 2 USB-C",
                "platform": "JD",
                "brand": "Apple",
                "model": "AirPods Pro 2",
                "sku": "APP2-USBC",
                "specs": {"version": "USB-C", "generation": "2"},
                "price": 1799,
                "official_store": True,
            },
            {
                "title": "AirPods Pro 2 Lightning",
                "platform": "JD",
                "brand": "Apple",
                "model": "AirPods Pro 2",
                "sku": "APP2-LIGHT",
                "specs": {"version": "Lightning", "generation": "2"},
                "price": 1599,
                "official_store": True,
            },
        ]
    )

    assert result["result"]["same_item_matches"][0]["relation"] == "same"
    assert result["result"]["same_item_matches"][1]["relation"] != "same"
    assert result["result"]["same_item_matches"][1]["confidence"] < 0.75


def test_true_price_is_calculated_from_discount_breakdown():
    result = _run(
        [
            {
                "title": "27寸显示器",
                "platform": "JD",
                "brand": "Dell",
                "model": "U2723",
                "price": 1499,
                "coupon": 100,
                "platform_discount": 50,
                "member_discount": 30,
                "subsidy": 20,
                "pay_discount": 10,
                "shipping": 15,
                "gift_value": 25,
                "official_store": True,
            }
        ]
    )

    breakdown = result["result"]["price_breakdowns"][0]
    assert breakdown["final_price"] == 1279.0


def test_three_candidates_are_all_compared_and_reported():
    products = [
        {"title": f"Monitor {index}", "platform": platform, "brand": "Dell", "model": f"U27{index}", "sku": f"SKU-{index}", "price": 1200 + index * 100, "official_store": True}
        for index, platform in enumerate(("JD", "Tmall", "PDD"), start=1)
    ]
    result = _run(products, {"budget": 1800, "acceptable_risk": "medium"})["result"]

    assert len(result["comparison_rows"]) == 3
    assert len(result["price_breakdowns"]) == 3
    assert len(result["same_item_matches"]) == 3
    assert len(result["risk_reports"]) == 3
    assert [row["index"] for row in result["comparison_rows"]] == [0, 1, 2]
    assert "候选 3" in result["final_report"]


def test_orchestrator_emits_followups_for_blocking_missing_fields():
    result = _run(
        [
            {
                "title": "新商品候选",
                "platform": "JD",
                "price": 0,
                "official_store": True,
            }
        ],
        {"budget": 1800, "acceptable_risk": "medium"},
    )["result"]

    orchestration = result["orchestration"]
    assert orchestration["schema_version"] == "shopping_orchestration.v1"
    assert orchestration["status"] == "needs_input"
    assert any(item["field"] == "price" and item["severity"] == "blocking" for item in orchestration["missing_information"])
    assert any(question["suggested_tool"] == "browser_extension_capture" for question in result["follow_up_questions"])
    assert any(step["tool"] == "browser_extension_capture" for step in result["tool_plan"])
    assert "自治执行计划" in result["final_report"]


def test_orchestrator_can_recommend_real_monitor_action():
    result = _run(
        [
            {
                "title": "Dell U2723QE 显示器",
                "platform": "JD",
                "brand": "Dell",
                "model": "U2723QE",
                "sku": "U2723QE",
                "specs": {"size": "27", "interface": "USB-C"},
                "price": 3199,
                "official_store": True,
                "return_days": 7,
                "warranty_months": 36,
            }
        ],
        {"budget": 2500, "acceptable_risk": "medium"},
    )["result"]

    orchestration = result["orchestration"]
    monitor_actions = [item for item in orchestration["actions"] if item["type"] == "create_price_monitor"]
    assert monitor_actions
    assert monitor_actions[0]["status"] == "ready"
    assert monitor_actions[0]["target_price"] == 2500
    assert orchestration["interface_contracts"]["price_monitor"]["endpoint"] == "POST /api/v1/shopping/monitors"


def test_risk_and_budget_change_recommendation():
    result = _run(
        [
            {
                "title": "翻新版耳机",
                "platform": "unknown",
                "brand": "Apple",
                "model": "AirPods Pro 2",
                "price": 1299,
                "official_store": False,
                "condition": "二手",
                "return_days": 3,
                "warranty_months": 6,
            },
            {
                "title": "官方新款耳机",
                "platform": "JD",
                "brand": "Apple",
                "model": "AirPods Pro 2",
                "price": 1799,
                "coupon": 100,
                "official_store": True,
                "return_days": 7,
                "warranty_months": 12,
            },
        ],
        {"budget": 1700, "acceptable_risk": "medium"},
    )

    assert result["result"]["recommendation"] in {"recommend_buy", "compare_more", "wait"}
    assert result["result"]["risk_reports"][0]["overall_risk"] == "high"
    assert result["result"]["comparison_rows"][0]["suitable_for_user"] is False


def test_agents_cannot_override_rule_facts(monkeypatch):
    def malicious_agent(**_kwargs):
        return ({"best_index": 99, "final_price": 0.01, "overall_risk": "low"}, {
            "answer_source": "llm", "fallback_used": False, "model": "test", "trace_id": "trace-test",
        })

    monkeypatch.setattr(shopping_graph, "_run_shopping_agent", malicious_agent)
    monkeypatch.setattr(shopping_graph.llm_provider, "generate_with_status", lambda *_args, **_kwargs: {
        "text": "# Agent report\n\nUse candidate 99 for 0.01.",
        "answer_source": "llm", "fallback_used": False, "model": "test", "trace_id": "trace-report",
    })
    result = _run([{
        "title": "Dell U2723", "brand": "Dell", "model": "U2723", "price": 1499,
        "coupon": 100, "official_store": True,
    }], {"budget": 1600, "acceptable_risk": "medium"})

    decision = result["result"]
    assert decision["best_index"] == 0
    assert decision["price_breakdowns"][0]["final_price"] == 1399
    assert decision["agent_outputs"]["recommendation"]["best_index"] == 0
    assert "候选 1 规则到手价：1399.00" in decision["final_report"]
    assert decision["rule_facts"]["best_index"] == 0
