from __future__ import annotations

from typing import Any, Optional


def collaborate(goal: str, project_path: Optional[str], require_human_review: bool) -> dict[str, Any]:
    plan = [
        "Planner 解析目标并拆分任务",
        "Project Analyzer 分析项目结构",
        "Code Reviewer 检查风险",
        "RAG Processor 整理知识材料",
        "Supervisor 汇总质量意见",
    ]
    worker_results = [
        {"agent": "planner", "result": f"目标已拆解：{goal}"},
        {"agent": "project_analyzer", "result": f"分析对象：{project_path or '未绑定项目路径'}"},
        {"agent": "code_reviewer", "result": "建议执行规则审查和测试覆盖检查。"},
        {"agent": "rag_processor", "result": "建议将 README、SQL、接口文档纳入知识库。"},
    ]
    supervisor_notes = [
        "当前结果适合作为自动化初稿。",
        "涉及文件修改、命令执行、外部 API 调用时应触发人工审核。",
    ]
    review_packet = None
    if require_human_review:
        review_packet = {
            "status": "pending",
            "question": "是否允许 Agent 继续执行可能影响项目文件或外部系统的动作？",
            "options": ["approve", "reject", "revise"],
        }
    final_report = _report(goal, plan, worker_results, supervisor_notes, require_human_review)
    return {
        "goal": goal,
        "plan": plan,
        "worker_results": worker_results,
        "supervisor_notes": supervisor_notes,
        "human_review_required": require_human_review,
        "human_review_packet": review_packet,
        "final_report": final_report,
    }


def _report(goal: str, plan: list[str], worker_results: list[dict[str, str]], notes: list[str], review: bool) -> str:
    plan_text = "\n".join(f"- {item}" for item in plan)
    result_text = "\n".join(f"- {item['agent']}: {item['result']}" for item in worker_results)
    note_text = "\n".join(f"- {item}" for item in notes)
    review_text = "需要人工审核" if review else "无需人工审核"
    return f"""# 多 Agent 协作报告

## 目标

{goal}

## 执行计划

{plan_text}

## Agent 结果

{result_text}

## Supervisor 意见

{note_text}

## 人工审核

{review_text}
"""
