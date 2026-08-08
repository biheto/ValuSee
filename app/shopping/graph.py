from __future__ import annotations

import math
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.harness.events import utc_now_iso


class ShoppingState(TypedDict, total=False):
    goal: str
    products: list[dict[str, Any]]
    profile: dict[str, Any]
    task_id: str
    events: list[dict[str, Any]]
    normalized_products: list[dict[str, Any]]
    same_item_matches: list[dict[str, Any]]
    price_breakdowns: list[dict[str, Any]]
    risk_reports: list[dict[str, Any]]
    comparison_rows: list[dict[str, Any]]
    best_index: int | None
    recommendation: str
    recommendation_reason: str
    summary: str
    report_markdown: str
    final_report: str
    result: dict[str, Any]


_MODEL_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def shopping_decision_graph_runner(state: dict[str, Any]) -> dict[str, Any]:
    graph = _build_graph()
    return graph.invoke(state)


def _build_graph():
    graph = StateGraph(ShoppingState)
    graph.add_node("understand", _understand_products)
    graph.add_node("match", _match_same_item)
    graph.add_node("price", _calculate_prices)
    graph.add_node("risk", _analyze_risks)
    graph.add_node("recommend", _recommend)
    graph.add_node("report", _report)
    graph.set_entry_point("understand")
    graph.add_edge("understand", "match")
    graph.add_edge("match", "price")
    graph.add_edge("price", "risk")
    graph.add_edge("risk", "recommend")
    graph.add_edge("recommend", "report")
    graph.add_edge("report", END)
    return graph.compile()


def _emit_event(state: ShoppingState, node: str, content: str, *, status: str = "completed", data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    events = list(state.get("events", []))
    events.append(
        {
            "task_id": state.get("task_id"),
            "event_id": f"evt_{state.get('task_id', 'shopping')}_{node}_{len(events) + 1}",
            "node": node,
            "agent": node,
            "type": "agent_step",
            "status": status,
            "content": content,
            "timestamp": utc_now_iso(),
            "data": data or {},
        }
    )
    return events


def _understand_products(state: ShoppingState) -> ShoppingState:
    normalized = []
    for index, product in enumerate(state.get("products", [])):
        normalized.append(_normalize_product(product, index))
    return {
        **state,
        "normalized_products": normalized,
        "events": _emit_event(state, "intent", "商品信息识别完成", data={"product_count": len(normalized)}),
    }


def _match_same_item(state: ShoppingState) -> ShoppingState:
    normalized = state.get("normalized_products", [])
    matches = []
    if not normalized:
        return {**state, "same_item_matches": matches, "events": _emit_event(state, "sku_match", "未提供商品候选")}

    anchor = normalized[0]
    for item in normalized:
        relation, confidence, reasons = _same_item_relation(anchor, item)
        matches.append(
            {
                "product_index": item["index"],
                "relation": relation,
                "confidence": confidence,
                "reasons": reasons,
            }
        )
    return {
        **state,
        "same_item_matches": matches,
        "events": _emit_event(state, "sku_match", "同款与规格匹配完成", data={"match_count": len(matches)}),
    }


def _calculate_prices(state: ShoppingState) -> ShoppingState:
    breakdowns = []
    for item in state.get("normalized_products", []):
        page_price = float(item.get("price") or 0.0)
        coupon = float(item.get("coupon") or 0.0)
        platform_discount = float(item.get("platform_discount") or 0.0)
        member_discount = float(item.get("member_discount") or 0.0)
        subsidy = float(item.get("subsidy") or 0.0)
        pay_discount = float(item.get("pay_discount") or 0.0)
        shipping = float(item.get("shipping") or 0.0)
        gift_value = float(item.get("gift_value") or 0.0)
        final_price = max(0.0, page_price - coupon - platform_discount - member_discount - subsidy - pay_discount + shipping - gift_value)
        breakdowns.append(
            {
                "page_price": page_price,
                "coupon": coupon,
                "platform_discount": platform_discount,
                "member_discount": member_discount,
                "subsidy": subsidy,
                "pay_discount": pay_discount,
                "shipping": shipping,
                "gift_value": gift_value,
                "final_price": round(final_price, 2),
            }
        )
    return {
        **state,
        "price_breakdowns": breakdowns,
        "events": _emit_event(state, "price", "真实到手价计算完成", data={"breakdown_count": len(breakdowns)}),
    }


def _analyze_risks(state: ShoppingState) -> ShoppingState:
    profile = state.get("profile", {})
    budget = float(profile.get("budget") or 0.0)
    risks = []
    for index, item in enumerate(state.get("normalized_products", [])):
        breakdown = state.get("price_breakdowns", [{}])[index]
        final_price = float(breakdown.get("final_price") or 0.0)
        price_level = "low"
        if budget > 0 and final_price > budget * 1.15:
            price_level = "high"
        elif budget > 0 and final_price > budget:
            price_level = "medium"

        spec_level = "low"
        reasons = []
        specs = item.get("specs", {})
        title = f"{item.get('title', '')} {item.get('model', '')}".lower()
        if any(token in title for token in ["翻新", "二手", "拆封", "海外", "水货"]):
            spec_level = "high"
            reasons.append("标题中包含翻新/二手/拆封/海外等风险信号")
        if item.get("condition") and item["condition"] not in {"new", "全新"}:
            spec_level = "medium"
            reasons.append(f"成色状态为 {item['condition']}")
        if not item.get("official_store") and item.get("return_days", 7) < 7:
            reasons.append("非官方店铺且退货期偏短")

        store_level = "low" if item.get("official_store") else "medium"
        if not item.get("official_store"):
            reasons.append("非官方店铺")
        if item.get("return_days", 7) <= 3:
            store_level = "high"
            reasons.append("退货期限过短")
        warranty_months = int(item.get("warranty_months") or 0)
        after_sales_level = "low" if warranty_months >= 12 else "medium"
        if warranty_months < 12:
            reasons.append("保修期短于 12 个月")

        overall = _max_level(price_level, spec_level, store_level, after_sales_level)
        if specs:
            reasons.append("已提取到结构化规格信息")
        risks.append(
            {
                "price_risk": price_level,
                "spec_risk": spec_level,
                "store_risk": store_level,
                "after_sales_risk": after_sales_level,
                "overall_risk": overall,
                "reasons": reasons,
            }
        )
    return {
        **state,
        "risk_reports": risks,
        "events": _emit_event(state, "risk", "商品风险分析完成", data={"risk_count": len(risks)}),
    }


def _recommend(state: ShoppingState) -> ShoppingState:
    profile = state.get("profile", {})
    budget = float(profile.get("budget") or 0.0)
    acceptable_risk = str(profile.get("acceptable_risk") or "medium")
    normalized = state.get("normalized_products", [])
    price_breakdowns = state.get("price_breakdowns", [])
    risk_reports = state.get("risk_reports", [])
    matches = state.get("same_item_matches", [])

    rows = []
    best_index = None
    best_score = -1.0
    for index, item in enumerate(normalized):
        breakdown = price_breakdowns[index] if index < len(price_breakdowns) else {}
        risk = risk_reports[index] if index < len(risk_reports) else {}
        match = matches[index] if index < len(matches) else {}
        final_price = float(breakdown.get("final_price") or 0.0)
        relation = str(match.get("relation") or "uncertain")
        confidence = float(match.get("confidence") or 0.0)
        same_item_bonus = 15 if relation == "same" else 0
        risk_penalty = {"low": 0, "medium": 15, "high": 30}.get(str(risk.get("overall_risk") or "medium"), 15)
        budget_bonus = 0
        if budget > 0:
            if final_price <= budget:
                budget_bonus = 20
            elif final_price <= budget * 1.1:
                budget_bonus = 8
        preference_bonus = _preference_bonus(profile, item)
        use_case_bonus = _use_case_bonus(profile, item)
        score = round(100.0 - final_price / 40.0 + same_item_bonus + confidence * 20 + budget_bonus + preference_bonus + use_case_bonus - risk_penalty, 2)
        suitable = _risk_level_order(str(risk.get("overall_risk") or "medium")) <= _risk_level_order(acceptable_risk) and (budget <= 0 or final_price <= budget * 1.15)
        rows.append(
            {
                "index": index,
                "title": item.get("title", ""),
                "platform": item.get("platform", ""),
                "model": item.get("model", ""),
                "same_item_relation": relation,
                "same_item_confidence": round(confidence, 2),
                "final_price": round(final_price, 2),
                "value_score": score,
                "risk_level": str(risk.get("overall_risk") or "medium"),
                "suitable_for_user": suitable,
            }
        )
        if score > best_score:
            best_score = score
            best_index = index

    if best_index is None and rows:
        best_index = 0
    if rows:
        best = rows[best_index]
        if budget > 0 and best["final_price"] <= budget:
            recommendation = "recommend_buy"
            recommendation_reason = "价格和风险均在可接受范围内，适合优先考虑"
        elif best["risk_level"] == "high":
            recommendation = "wait"
            recommendation_reason = "风险偏高，建议继续观察或补充信息"
        else:
            recommendation = "compare_more"
            recommendation_reason = "当前候选可对比，但仍建议结合偏好再确认"
    else:
        recommendation = "need_input"
        recommendation_reason = "未收到有效商品候选"

    summary = _build_summary(best_index, rows, profile)
    return {
        **state,
        "comparison_rows": rows,
        "best_index": best_index,
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
        "summary": summary,
        "events": _emit_event(state, "recommend", "购买建议生成完成", data={"best_index": best_index}),
    }


def _report(state: ShoppingState) -> ShoppingState:
    report = _build_report(state)
    result = {
        "best_index": state.get("best_index"),
        "recommendation": state.get("recommendation"),
        "recommendation_reason": state.get("recommendation_reason"),
        "comparison_rows": state.get("comparison_rows", []),
        "price_breakdowns": state.get("price_breakdowns", []),
        "same_item_matches": state.get("same_item_matches", []),
        "risk_reports": state.get("risk_reports", []),
        "summary": state.get("summary", ""),
        "report_markdown": report,
        "final_report": report,
    }
    return {
        **state,
        "report_markdown": report,
        "final_report": report,
        "result": result,
        "events": _emit_event(state, "report", "购买决策报告生成完成"),
    }


def _normalize_product(product: dict[str, Any], index: int) -> dict[str, Any]:
    title = str(product.get("title") or "").strip()
    brand = str(product.get("brand") or "").strip()
    model = str(product.get("model") or "").strip()
    sku = str(product.get("sku") or "").strip()
    specs = product.get("specs") or {}
    normalized_specs = {str(k).strip().lower(): str(v).strip() for k, v in specs.items()} if isinstance(specs, dict) else {}
    return {
        "index": index,
        "title": title,
        "platform": str(product.get("platform") or "").strip(),
        "url": str(product.get("url") or "").strip(),
        "brand": brand,
        "model": model,
        "sku": sku,
        "specs": normalized_specs,
        "price": float(product.get("price") or 0.0),
        "coupon": float(product.get("coupon") or 0.0),
        "platform_discount": float(product.get("platform_discount") or 0.0),
        "member_discount": float(product.get("member_discount") or 0.0),
        "subsidy": float(product.get("subsidy") or 0.0),
        "pay_discount": float(product.get("pay_discount") or 0.0),
        "shipping": float(product.get("shipping") or 0.0),
        "gift_value": float(product.get("gift_value") or 0.0),
        "condition": str(product.get("condition") or "").strip(),
        "official_store": bool(product.get("official_store", False)),
        "return_days": int(product.get("return_days") or 7),
        "warranty_months": int(product.get("warranty_months") or 12),
        "notes": str(product.get("notes") or "").strip(),
        "signature": _signature(brand, model, sku, normalized_specs),
    }


def _signature(brand: str, model: str, sku: str, specs: dict[str, str]) -> str:
    values = [brand, model, sku]
    for key in sorted(specs):
        if key in {"capacity", "size", "color", "version", "generation", "ram", "storage", "interface"}:
            values.append(f"{key}:{specs[key]}")
    signature = " ".join(part for part in values if part)
    return _normalize_text(signature)


def _same_item_relation(anchor: dict[str, Any], item: dict[str, Any]) -> tuple[str, float, list[str]]:
    if anchor["index"] == item["index"]:
        return "same", 1.0, ["同一候选项"]
    reasons = []
    if _has_conflicting_variant(anchor, item):
        return "different", 0.12, ["接口/版本/成色存在明显冲突"]
    if anchor["signature"] == item["signature"] and anchor["signature"]:
        return "same", 0.98, ["品牌、型号和关键规格一致"]

    score = 0.0
    if anchor["brand"] and anchor["brand"] == item["brand"]:
        score += 0.25
        reasons.append("品牌一致")
    if anchor["model"] and anchor["model"] == item["model"]:
        score += 0.4
        reasons.append("标准型号一致")
    if anchor["sku"] and anchor["sku"] == item["sku"]:
        score += 0.3
        reasons.append("SKU 一致")

    anchor_tokens = _tokens(anchor["title"] + " " + anchor["model"])
    item_tokens = _tokens(item["title"] + " " + item["model"])
    if anchor_tokens and item_tokens:
        overlap = len(anchor_tokens & item_tokens) / max(len(anchor_tokens | item_tokens), 1)
        score += overlap * 0.35
        if overlap > 0:
            reasons.append(f"标题/型号重合度 {overlap:.2f}")

    if _specs_overlap(anchor.get("specs", {}), item.get("specs", {})):
        score += 0.15
        reasons.append("关键规格存在交集")

    if any(token in item["title"] for token in ["翻新", "二手", "拆封", "海外"]) or any(token in anchor["title"] for token in ["翻新", "二手", "拆封", "海外"]):
        reasons.append("存在不同版本或成色信号")
        score -= 0.2

    confidence = max(0.05, min(0.98, round(score, 2)))
    if confidence >= 0.75:
        relation = "same"
    elif confidence >= 0.45:
        relation = "similar"
    else:
        relation = "different"
    return relation, confidence, reasons or ["仅部分信息重合"]


def _has_conflicting_variant(anchor: dict[str, Any], item: dict[str, Any]) -> bool:
    a_text = _normalize_text(f"{anchor.get('title', '')} {anchor.get('model', '')} {anchor.get('sku', '')}")
    b_text = _normalize_text(f"{item.get('title', '')} {item.get('model', '')} {item.get('sku', '')}")
    conflict_pairs = [
        ("usbc", "lightning"),
        ("typec", "lightning"),
        ("usb c", "lightning"),
        ("usb-c", "lightning"),
    ]
    for left, right in conflict_pairs:
        if left in a_text and right in b_text:
            return True
        if right in a_text and left in b_text:
            return True
    a_specs = anchor.get("specs", {}) or {}
    b_specs = item.get("specs", {}) or {}
    for key in ("version", "interface", "generation", "color", "capacity", "size"):
        a_value = _normalize_text(str(a_specs.get(key) or ""))
        b_value = _normalize_text(str(b_specs.get(key) or ""))
        if a_value and b_value and a_value != b_value and key in {"version", "interface", "generation"}:
            if len(a_value) <= 16 and len(b_value) <= 16:
                return True
    return False


def _specs_overlap(left: dict[str, str], right: dict[str, str]) -> bool:
    keys = {"capacity", "size", "color", "version", "generation", "ram", "storage", "interface"}
    for key in keys:
        if left.get(key) and right.get(key) and left[key] == right[key]:
            return True
    return False


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _MODEL_TOKEN_RE.findall(text) if token}


def _normalize_text(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "", text).lower()


def _risk_level_order(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(level, 1)


def _max_level(*levels: str) -> str:
    ordered = sorted((_risk_level_order(level), level) for level in levels)
    return ordered[-1][1]


def _preference_bonus(profile: dict[str, Any], item: dict[str, Any]) -> int:
    preferences = {str(item).lower() for item in profile.get("brand_preferences", [])}
    if item.get("brand", "").lower() in preferences:
        return 8
    return 0


def _use_case_bonus(profile: dict[str, Any], item: dict[str, Any]) -> int:
    use_case = _normalize_text(str(profile.get("use_case") or ""))
    text = _normalize_text(f"{item.get('title', '')} {item.get('model', '')} {item.get('notes', '')}")
    if not use_case or not text:
        return 0
    overlap = len(set(use_case) & set(text))
    if overlap > 10:
        return 10
    if overlap > 4:
        return 5
    return 0


def _build_summary(best_index: int | None, rows: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    if best_index is None or not rows:
        return "未找到可比较的商品候选。"
    best = rows[best_index]
    budget = float(profile.get("budget") or 0.0)
    budget_text = f"预算 {budget:.0f} 元" if budget > 0 else "未设置预算"
    return (
        f"优先推荐第 {best_index + 1} 个候选：{best['title']}，"
        f"到手价约 {best['final_price']:.0f} 元，"
        f"风险等级 {best['risk_level']}，"
        f"{budget_text}。"
    )


def _build_report(state: ShoppingState) -> str:
    rows = state.get("comparison_rows", [])
    risk_reports = state.get("risk_reports", [])
    lines = [
        "# 购买决策报告",
        "",
        f"- 结论：{state.get('recommendation_reason', '')}",
        f"- 推荐动作：{state.get('recommendation', '')}",
        f"- 总结：{state.get('summary', '')}",
        "",
        "## 候选对比",
    ]
    for row in rows:
        lines.append(
            f"- 第 {row['index'] + 1} 个：{row['title']} / 到手价 {row['final_price']:.0f} / "
            f"同款判断 {row['same_item_relation']} / 风险 {row['risk_level']} / 适合用户 {row['suitable_for_user']}"
        )
    lines.append("")
    lines.append("## 风险说明")
    for index, risk in enumerate(risk_reports):
        lines.append(
            f"- 第 {index + 1} 个：价格 {risk['price_risk']}，规格 {risk['spec_risk']}，店铺 {risk['store_risk']}，售后 {risk['after_sales_risk']}"
        )
    lines.append("")
    lines.append("## 价格明细")
    for index, breakdown in enumerate(state.get("price_breakdowns", [])):
        lines.append(
            f"- 第 {index + 1} 个：标价 {breakdown['page_price']:.0f}，券后 {breakdown['coupon']:.0f}，平台补贴 {breakdown['platform_discount']:.0f}，"
            f"会员 {breakdown['member_discount']:.0f}，国补 {breakdown['subsidy']:.0f}，支付优惠 {breakdown['pay_discount']:.0f}，运费 {breakdown['shipping']:.0f}，赠品折算 {breakdown['gift_value']:.0f}，到手价 {breakdown['final_price']:.0f}"
        )
    return "\n".join(lines).strip()
