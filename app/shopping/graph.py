from __future__ import annotations

import json
import math
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.harness.events import utc_now_iso
from app.providers.llm_provider import llm_provider


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
    intent_analysis: dict[str, Any]
    product_insights: list[dict[str, Any]]
    matching_explanations: list[dict[str, Any]]
    review_analysis: dict[str, Any]
    risk_explanations: list[dict[str, Any]]
    agent_recommendation: dict[str, Any]
    supervisor_review: dict[str, Any]
    agent_status: dict[str, dict[str, Any]]


_MODEL_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def shopping_decision_graph_runner(state: dict[str, Any]) -> dict[str, Any]:
    graph = _build_graph()
    return graph.invoke(state)


def _build_graph():
    graph = StateGraph(ShoppingState)
    graph.add_node("intent_agent", _intent_agent)
    graph.add_node("understand", _understand_products)
    graph.add_node("product_agent", _product_agent)
    graph.add_node("match", _match_same_item)
    graph.add_node("sku_agent", _sku_agent)
    graph.add_node("price", _calculate_prices)
    graph.add_node("risk", _analyze_risks)
    graph.add_node("review_agent", _review_agent)
    graph.add_node("risk_agent", _risk_agent)
    graph.add_node("recommend", _recommend)
    graph.add_node("recommendation_agent", _recommendation_agent)
    graph.add_node("supervisor_agent", _supervisor_agent)
    graph.add_node("report", _report)
    graph.set_entry_point("intent_agent")
    graph.add_edge("intent_agent", "understand")
    graph.add_edge("understand", "product_agent")
    graph.add_edge("product_agent", "match")
    graph.add_edge("match", "sku_agent")
    graph.add_edge("sku_agent", "price")
    graph.add_edge("price", "risk")
    graph.add_edge("risk", "review_agent")
    graph.add_edge("review_agent", "risk_agent")
    graph.add_edge("risk_agent", "recommend")
    graph.add_edge("recommend", "recommendation_agent")
    graph.add_edge("recommendation_agent", "supervisor_agent")
    graph.add_edge("supervisor_agent", "report")
    graph.add_edge("report", END)
    return graph.compile()


def _emit_event(state: ShoppingState, node: str, content: str, *, status: str = "completed", data: dict[str, Any] | None = None, agent: str | None = None) -> list[dict[str, Any]]:
    events = list(state.get("events", []))
    events.append(
        {
            "task_id": state.get("task_id"),
            "event_id": f"evt_{state.get('task_id', 'shopping')}_{node}_{len(events) + 1}",
            "node": node,
            "agent": agent or node,
            "type": "agent_step",
            "status": status,
            "content": content,
            "timestamp": utc_now_iso(),
            "data": data or {},
        }
    )
    return events


def _agent_event_data(result: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "answer_source": result.get("answer_source", "fallback"),
        "fallback_used": bool(result.get("fallback_used", True)),
        "model": result.get("model"),
        "trace_id": result.get("trace_id"),
        **extra,
    }


def _parse_json_object(text: str) -> dict[str, Any]:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        match = re.search(r"\{.*\}", value, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _run_shopping_agent(
    *,
    agent: str,
    system_prompt: str,
    user_prompt: str,
    fallback: dict[str, Any],
    prompt_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = llm_provider.generate_with_status(
        system_prompt,
        user_prompt,
        json.dumps(fallback, ensure_ascii=False),
        agent=agent,
        prompt_version=prompt_version,
    )
    payload = _parse_json_object(str(result.get("text") or "")) or fallback
    return payload, result


def _intent_agent(state: ShoppingState) -> ShoppingState:
    profile = state.get("profile", {})
    fallback = {
        "goal": state.get("goal", ""),
        "constraints": [key for key in ("budget", "use_case", "acceptable_risk") if profile.get(key)],
        "missing_information": [],
        "priority": "适配度优先，其次是到手价和风险",
    }
    payload, result = _run_shopping_agent(
        agent="shopping_intent",
        prompt_version="shopping_intent.v1",
        system_prompt="你是 ValuSee 的购物意图 Agent。只基于用户目标和档案提取预算、场景、偏好、风险边界和缺失信息。返回 JSON，不要编造商品事实。",
        user_prompt=json.dumps({"goal": state.get("goal", ""), "profile": profile}, ensure_ascii=False),
        fallback=fallback,
    )
    statuses = {**state.get("agent_status", {}), "shopping_intent": _agent_event_data(result)}
    return {**state, "intent_analysis": payload, "agent_status": statuses, "events": _emit_event(state, "intent_agent", "购物意图 Agent 完成", data=_agent_event_data(result), agent="shopping_intent")}


def _understand_products(state: ShoppingState) -> ShoppingState:
    normalized = []
    for index, product in enumerate(state.get("products", [])):
        normalized.append(_normalize_product(product, index))
    return {
        **state,
        "normalized_products": normalized,
        "events": _emit_event(state, "intent", "商品信息识别完成", data={"product_count": len(normalized)}),
    }


def _product_agent(state: ShoppingState) -> ShoppingState:
    products = state.get("normalized_products", [])
    fallback = {
        "products": [
            {"index": item.get("index"), "identity": item.get("model") or item.get("title"), "uncertainties": []}
            for item in products
        ]
    }
    payload, result = _run_shopping_agent(
        agent="shopping_product",
        prompt_version="shopping_product.v1",
        system_prompt="你是商品理解 Agent。基于已提取的商品字段，指出标准型号、规格、套装、版本和仍需确认的字段。不得修改输入字段，不得猜测价格。返回 JSON。",
        user_prompt=json.dumps({"products": products, "intent": state.get("intent_analysis", {})}, ensure_ascii=False),
        fallback=fallback,
    )
    statuses = {**state.get("agent_status", {}), "shopping_product": _agent_event_data(result)}
    return {**state, "product_insights": payload.get("products", fallback["products"]), "agent_status": statuses, "events": _emit_event(state, "product_agent", "商品理解 Agent 完成", data=_agent_event_data(result, product_count=len(products)), agent="shopping_product")}


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


def _sku_agent(state: ShoppingState) -> ShoppingState:
    fallback = {"matches": state.get("same_item_matches", []), "summary": "同款结论以 SKU、型号和规则校验为准。"}
    payload, result = _run_shopping_agent(
        agent="shopping_sku_matching",
        prompt_version="shopping_sku_matching.v1",
        system_prompt="你是 SKU 同款匹配 Agent。规则匹配结果是不可修改的事实。只解释每个候选为什么同款、相似或不同，并指出需要用户确认的差异。返回 JSON，不要改 confidence 或 relation。",
        user_prompt=json.dumps({"products": state.get("normalized_products", []), "rule_matches": state.get("same_item_matches", [])}, ensure_ascii=False),
        fallback=fallback,
    )
    statuses = {**state.get("agent_status", {}), "shopping_sku_matching": _agent_event_data(result)}
    return {**state, "matching_explanations": payload.get("matches", fallback["matches"]), "agent_status": statuses, "events": _emit_event(state, "sku_agent", "SKU 同款 Agent 完成（规则结论锁定）", data=_agent_event_data(result), agent="shopping_sku_matching")}


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
    from app.shopping.store import shopping_store

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

        governed_matches = shopping_store.evaluate_risk_rules(item)
        for match in governed_matches:
            reasons.append(f"命中风控规则：{match['name']}")
            spec_level = _max_level(spec_level, str(match["severity"]))

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


def _review_agent(state: ShoppingState) -> ShoppingState:
    products = state.get("normalized_products", [])
    evidence = [
        {
            "index": item.get("index"),
            "title": item.get("title"),
            "notes": item.get("notes"),
            "evidence": item.get("evidence", {}),
        }
        for item in products
    ]
    fallback = {
        "risk_level": "unknown",
        "confidence": 0.0,
        "summary": "当前候选没有提供带来源的评论证据，暂不推断评论风险。",
        "issue_groups": [],
        "evidence_gaps": ["未提供带来源评论"],
    }
    payload, result = _run_shopping_agent(
        agent="shopping_review",
        prompt_version="shopping_review.v1",
        system_prompt="你是商品评论分析 Agent。只能基于用户提供的带来源评论或明确证据总结高频问题。没有评论就返回 unknown，不得凭常识编造缺陷。返回 JSON。",
        user_prompt=json.dumps({"products": evidence, "reviews": state.get("reviews", [])}, ensure_ascii=False),
        fallback=fallback,
    )
    statuses = {**state.get("agent_status", {}), "shopping_review": _agent_event_data(result)}
    return {**state, "review_analysis": payload, "agent_status": statuses, "events": _emit_event(state, "review_agent", "评论分析 Agent 完成（证据不足不推断）", data=_agent_event_data(result), agent="shopping_review")}


def _risk_agent(state: ShoppingState) -> ShoppingState:
    fallback = {
        "explanations": [
            {"index": index, "explanation": "风险等级由规则校验结果确定，请结合证据核对。"}
            for index, _ in enumerate(state.get("risk_reports", []))
        ],
        "evidence_gaps": [],
    }
    payload, result = _run_shopping_agent(
        agent="shopping_risk",
        prompt_version="shopping_risk.v1",
        system_prompt="你是购物风险 Agent。规则层输出的 price/spec/store/after_sales/overall 风险等级不可修改。你只能解释触发原因、列出证据缺口和建议的人工确认项，不得自行增加未经证实的风险。返回 JSON。",
        user_prompt=json.dumps({"products": state.get("normalized_products", []), "rule_risks": state.get("risk_reports", []), "review_analysis": state.get("review_analysis", {})}, ensure_ascii=False),
        fallback=fallback,
    )
    statuses = {**state.get("agent_status", {}), "shopping_risk": _agent_event_data(result)}
    return {**state, "risk_explanations": payload.get("explanations", fallback["explanations"]), "agent_status": statuses, "events": _emit_event(state, "risk_agent", "风险 Agent 完成（规则等级锁定）", data=_agent_event_data(result), agent="shopping_risk")}


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


def _recommendation_agent(state: ShoppingState) -> ShoppingState:
    fallback = {
        "recommendation": state.get("recommendation", "need_input"),
        "reason": state.get("recommendation_reason", ""),
        "best_index": state.get("best_index"),
        "tradeoffs": [],
        "next_action": "确认商品规格、价格和风险证据后再决定。",
    }
    payload, result = _run_shopping_agent(
        agent="shopping_recommendation",
        prompt_version="shopping_recommendation.v1",
        system_prompt="你是个性化购物推荐 Agent。规则层已经锁定候选评分、价格、风险和 best_index，你只能基于这些事实解释取舍、适配用户场景并提出下一步，不能改写价格、风险等级或 best_index。返回 JSON。",
        user_prompt=json.dumps({"intent": state.get("intent_analysis", {}), "profile": state.get("profile", {}), "comparison": state.get("comparison_rows", []), "recommendation": fallback, "risk_explanations": state.get("risk_explanations", [])}, ensure_ascii=False),
        fallback=fallback,
    )
    payload["best_index"] = state.get("best_index")
    payload["recommendation"] = state.get("recommendation", "need_input")
    statuses = {**state.get("agent_status", {}), "shopping_recommendation": _agent_event_data(result)}
    return {**state, "agent_recommendation": payload, "agent_status": statuses, "events": _emit_event(state, "recommendation_agent", "个性化推荐 Agent 完成（规则结论锁定）", data=_agent_event_data(result, best_index=state.get("best_index")), agent="shopping_recommendation")}


def _supervisor_agent(state: ShoppingState) -> ShoppingState:
    fallback = {
        "approved": True,
        "issues": [],
        "evidence_gaps": [],
        "summary": "规则价格、同款和风险结论已完成一致性校验。",
    }
    payload, result = _run_shopping_agent(
        agent="shopping_supervisor",
        prompt_version="shopping_supervisor.v1",
        system_prompt="你是购物决策 Supervisor。检查 Agent 输出是否引用了输入事实，检查是否越权修改价格、风险、匹配关系或推荐索引。发现越权时列出 issues；不得自行改变规则事实。返回 JSON。",
        user_prompt=json.dumps({"rule_facts": {"matches": state.get("same_item_matches", []), "prices": state.get("price_breakdowns", []), "risks": state.get("risk_reports", []), "best_index": state.get("best_index"), "recommendation": state.get("recommendation")}, "agent_outputs": {"intent": state.get("intent_analysis", {}), "product": state.get("product_insights", []), "sku": state.get("matching_explanations", []), "review": state.get("review_analysis", {}), "risk": state.get("risk_explanations", []), "recommendation": state.get("agent_recommendation", {})}}, ensure_ascii=False),
        fallback=fallback,
    )
    statuses = {**state.get("agent_status", {}), "shopping_supervisor": _agent_event_data(result)}
    return {**state, "supervisor_review": payload, "agent_status": statuses, "events": _emit_event(state, "supervisor_agent", "购物 Supervisor 完成（事实一致性校验）", data=_agent_event_data(result), agent="shopping_supervisor")}


def _report(state: ShoppingState) -> ShoppingState:
    fallback_report = _build_report(state)
    report_result = llm_provider.generate_with_status(
        "你是 ValuSee 购物 Reporter Agent。基于规则事实和各 Agent 解释生成中文购买决策报告。价格、风险等级、同款关系和推荐索引必须原样保留；缺少证据时明确说明，不得编造。输出 Markdown。",
        json.dumps({
            "rule_facts": {
                "matches": state.get("same_item_matches", []),
                "prices": state.get("price_breakdowns", []),
                "risks": state.get("risk_reports", []),
                "comparison": state.get("comparison_rows", []),
                "best_index": state.get("best_index"),
                "recommendation": state.get("recommendation"),
            },
            "agent_explanations": {
                "intent": state.get("intent_analysis", {}),
                "product": state.get("product_insights", []),
                "sku": state.get("matching_explanations", []),
                "review": state.get("review_analysis", {}),
                "risk": state.get("risk_explanations", []),
                "recommendation": state.get("agent_recommendation", {}),
                "supervisor": state.get("supervisor_review", {}),
            },
        }, ensure_ascii=False),
        fallback_report,
        agent="shopping_reporter",
        prompt_version="shopping_reporter.v1",
    )
    report = str(report_result.get("text") or fallback_report)
    report = f"{report.rstrip()}\n\n---\n\n{_build_rule_fact_sheet(state)}"
    statuses = {**state.get("agent_status", {}), "shopping_reporter": _agent_event_data(report_result)}
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
        "agent_status": statuses,
        "rule_facts": {
            "same_item_matches": state.get("same_item_matches", []),
            "price_breakdowns": state.get("price_breakdowns", []),
            "risk_reports": state.get("risk_reports", []),
            "best_index": state.get("best_index"),
            "recommendation": state.get("recommendation"),
        },
        "agent_outputs": {
            "intent": state.get("intent_analysis", {}),
            "product": state.get("product_insights", []),
            "sku": state.get("matching_explanations", []),
            "review": state.get("review_analysis", {}),
            "risk": state.get("risk_explanations", []),
            "recommendation": state.get("agent_recommendation", {}),
            "supervisor": state.get("supervisor_review", {}),
        },
    }
    return {
        **state,
        "report_markdown": report,
        "final_report": report,
        "result": result,
        "events": _emit_event(state, "report", "购买决策 Reporter Agent 完成", data=_agent_event_data(report_result), agent="shopping_reporter"),
    }


def _build_rule_fact_sheet(state: ShoppingState) -> str:
    """Append immutable rule facts after the narrative Agent report."""
    lines = ["## 规则校验事实（不可由 Agent 修改）", ""]
    lines.append(f"- 推荐候选索引：{state.get('best_index')}")
    lines.append(f"- 规则推荐结论：{state.get('recommendation', 'need_input')}")
    for index, breakdown in enumerate(state.get("price_breakdowns", [])):
        lines.append(f"- 候选 {index + 1} 规则到手价：{float(breakdown.get('final_price') or 0):.2f}")
    for index, match in enumerate(state.get("same_item_matches", [])):
        lines.append(f"- 候选 {index + 1} 同款关系：{match.get('relation')}（置信度 {float(match.get('confidence') or 0):.2f}）")
    for index, risk in enumerate(state.get("risk_reports", [])):
        lines.append(f"- 候选 {index + 1} 规则风险：{risk.get('overall_risk')}（价格 {risk.get('price_risk')} / 规格 {risk.get('spec_risk')} / 店铺 {risk.get('store_risk')} / 售后 {risk.get('after_sales_risk')}）")
    return "\n".join(lines)


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
