from __future__ import annotations

from collections import Counter
from typing import Any


ISSUE_GROUPS = {
    "质量与故障": ("损坏", "故障", "失灵", "开裂", "漏液", "死机", "断连"),
    "续航与发热": ("续航", "电池", "发热", "过热", "耗电"),
    "性能与体验": ("卡顿", "延迟", "噪音", "异响", "模糊", "色差"),
    "规格与描述": ("不符", "缩水", "型号", "配置", "翻新", "拆封", "二手"),
    "物流与售后": ("物流", "包装", "客服", "退货", "保修", "售后"),
}


def analyze_reviews(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [
        item
        for item in reviews
        if str(item.get("content", "")).strip() and str(item.get("source", "")).strip()
    ]
    if not usable:
        return {
            "risk_level": "unknown",
            "confidence": 0.0,
            "summary": "评论证据不足，暂不判断商品口碑风险。",
            "issue_groups": [],
            "sample_size": 0,
            "verified_ratio": 0.0,
            "average_rating": 0.0,
            "negative_ratio": 0.0,
        }

    total_weight = 0.0
    negative_weight = 0.0
    issues: Counter[str] = Counter()
    ratings: list[float] = []
    verified = 0
    evidence: dict[str, list[str]] = {key: [] for key in ISSUE_GROUPS}

    for review in usable:
        content = str(review.get("content", "")).strip()
        rating = max(1.0, min(5.0, float(review.get("rating", 3) or 3)))
        weight = 1.35 if review.get("verified_purchase") else 1.0
        verified += int(bool(review.get("verified_purchase")))
        ratings.append(rating)
        total_weight += weight
        if rating <= 2:
            negative_weight += weight
        for group, keywords in ISSUE_GROUPS.items():
            if any(keyword in content for keyword in keywords):
                issues[group] += weight
                if len(evidence[group]) < 3:
                    evidence[group].append(content[:180])

    negative_ratio = negative_weight / total_weight if total_weight else 0.0
    confidence = min(0.95, 0.25 + len(usable) / 50 + verified / len(usable) * 0.25)
    risk = "high" if negative_ratio >= 0.35 else "medium" if negative_ratio >= 0.16 else "low"
    groups = [
        {
            "name": name,
            "weighted_mentions": round(score, 2),
            "ratio": round(score / total_weight, 3),
            "evidence": evidence[name],
        }
        for name, score in issues.most_common()
    ]
    top = groups[0]["name"] if groups else "未发现集中缺陷"
    return {
        "risk_level": risk,
        "confidence": round(confidence, 3),
        "sample_size": len(usable),
        "verified_ratio": round(verified / len(usable), 3),
        "average_rating": round(sum(ratings) / len(ratings), 2),
        "negative_ratio": round(negative_ratio, 3),
        "issue_groups": groups,
        "summary": f"分析 {len(usable)} 条有来源评论，主要风险方向：{top}。结论置信度 {confidence:.0%}。",
    }
