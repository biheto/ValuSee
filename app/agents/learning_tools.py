from __future__ import annotations

from typing import Any, Optional


def build_learning_plan(topic: str, level: str, days: int, goal: Optional[str]) -> dict[str, Any]:
    phases = _phases(level)
    plan = []
    for day in range(1, days + 1):
        phase = phases[min(len(phases) - 1, (day - 1) * len(phases) // days)]
        plan.append(
            {
                "day": day,
                "theme": f"{topic} - {phase}",
                "tasks": [
                    f"阅读并整理 {topic} 的 {phase} 核心概念",
                    "完成一个 30-60 分钟的小练习",
                    "记录 3 个不理解的问题并让 Agent 复盘",
                ],
                "output": "学习笔记 + 可运行示例 + 当日自测",
            }
        )
    quiz = [
        {"question": f"{topic} 最核心的应用场景是什么？", "answer": "用自己的项目场景解释，而不是背定义。"},
        {"question": f"你会如何验证 {topic} 的学习成果？", "answer": "用一个可运行 demo、测试结果和复盘报告验证。"},
        {"question": "遇到报错时如何定位？", "answer": "先读日志，再缩小复现范围，最后沉淀排障笔记。"},
    ]
    report = _report(topic, level, days, goal, plan, quiz)
    return {"plan": plan, "quiz": quiz, "report_markdown": report}


def _phases(level: str) -> list[str]:
    if level == "advanced":
        return ["架构原理", "工程治理", "性能优化", "生产落地"]
    if level == "intermediate":
        return ["核心概念", "项目实战", "调试排障", "最佳实践"]
    return ["基础入门", "最小 demo", "案例练习", "总结复盘"]


def _report(topic: str, level: str, days: int, goal: Optional[str], plan: list[dict[str, Any]], quiz: list[dict[str, str]]) -> str:
    goal_text = goal or "掌握基础能力并能完成一个小型项目"
    plan_text = "\n".join(
        f"- Day {item['day']}: {item['theme']}，产出：{item['output']}" for item in plan
    )
    quiz_text = "\n".join(f"- {item['question']}" for item in quiz)
    return f"""# {topic} 学习陪练计划

- 当前水平：{level}
- 学习周期：{days} 天
- 目标：{goal_text}

## 每日计划

{plan_text}

## 自测题

{quiz_text}
"""
