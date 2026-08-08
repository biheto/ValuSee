from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.graphs.collaboration_runner import run_collaboration_task
from app.graphs.studio_graphs import code_review_graph
from app.harness.events import utc_now_iso
from app.integrations.github import GitHubClient, GitHubPullRequest, parse_pull_request_url


SCENARIOS = {
    "onboarding": {
        "name": "Project Onboarding",
        "description": "Turn an unfamiliar repository into an architecture tour and learning path.",
    },
    "pr_review": {
        "name": "PR Change Risk Review",
        "description": "Review local Git changes before merge and produce evidence-backed risk actions.",
    },
    "governance": {
        "name": "Architecture Governance",
        "description": "Find architecture drift, technical debt, and the next governance actions.",
    },
}


def run_business_scenario(state: dict[str, Any]) -> dict[str, Any]:
    scenario = str(state.get("business_scenario") or "onboarding")
    if scenario not in SCENARIOS:
        raise ValueError(f"Unsupported business scenario: {scenario}")
    project_path = state.get("project_path")
    if scenario != "pr_review" and not project_path:
        raise ValueError("project_path is required for a business scenario")

    if scenario == "pr_review":
        return _run_pr_review(state)

    goal = state.get("goal") or _default_goal(scenario)
    collaboration = run_collaboration_task({**state, "goal": goal})
    result = dict(collaboration.get("result") or {})
    if scenario == "onboarding":
        result = _onboarding_result(result)
    else:
        result = _governance_result(result)
    result["business_scenario"] = scenario
    result["scenario_name"] = SCENARIOS[scenario]["name"]
    return {"result": result, "events": collaboration.get("events", []), "final_report": result.get("final_report")}


def _run_pr_review(state: dict[str, Any]) -> dict[str, Any]:
    pull: GitHubPullRequest | None = None
    if state.get("pr_url"):
        pull = parse_pull_request_url(str(state["pr_url"]))
        changed_files, diff_text = GitHubClient().get_pull_diff(pull)
        project_path = str(state.get("project_path") or pull.url)
    else:
        if not state.get("project_path"):
            raise ValueError("project_path or pr_url is required for PR review")
        project_path = str(Path(state["project_path"]).expanduser().resolve())
        changed_files, diff_text = _git_diff(project_path, state.get("pr_base"), state.get("pr_head"))
    review = {"findings": [], "risks": []}
    if state.get("project_path"):
        review = code_review_graph.invoke({
            "project_path": project_path,
            "max_files": state.get("max_files", 500),
        })["result"]
    findings = list(review.get("findings", []))
    if diff_text:
        for line_no, line in enumerate(diff_text.splitlines(), 1):
            if "TODO" in line or "FIXME" in line:
                findings.append({"category": "change_risk", "severity": "medium", "file": "git diff", "line": line_no, "message": "Changed code introduces TODO/FIXME; confirm ownership before merge."})
            if any(secret in line.lower() for secret in ("api_key=", "password=", "secret=")):
                findings.append({"category": "security", "severity": "critical", "file": "git diff", "line": line_no, "message": "Changed diff contains a possible credential; block merge and rotate it."})
    risk_level = _risk_level(findings)
    review_required = risk_level in {"high", "critical"} or bool(state.get("require_human_review", True))
    test_recommendations = _test_recommendations(changed_files, findings)
    next_actions = ["确认变更影响范围和回滚方案", *test_recommendations]
    report = _pr_report(project_path, changed_files, risk_level, findings, test_recommendations, next_actions)
    result = {
        "business_scenario": "pr_review",
        "scenario_name": SCENARIOS["pr_review"]["name"],
        "project_path": project_path,
        "changed_files": changed_files,
        "diff_available": bool(diff_text),
        "findings": findings,
        "risks": review.get("risks", []),
        "score": max(0, 100 - min(100, len(findings) * 8)),
        "risk_level": risk_level,
        "review_required": review_required,
        "human_review_required": review_required,
        "human_review_packet": ({
            "status": "pending",
            "question": "是否允许该变更进入合并流程？",
            "options": ["approve", "reject", "revise"],
            "summary": next_actions,
        } if review_required else None),
        "test_recommendations": test_recommendations,
        "next_actions": next_actions,
        "suggestions": next_actions,
        "final_report": report,
        "agent_outputs": [{"node_id": "pr_reviewer", "node_name": "PR Risk Reviewer", "agent": "code_reviewer", "content": report}],
        "tool_calls": [{"tool": "github.pull_request.diff" if pull else "git.diff", "status": "completed", "changed_files": len(changed_files)}],
        "governance": {"risk_level": risk_level, "review_required": review_required, "next_actions": next_actions},
    }
    if pull and state.get("post_comment"):
        try:
            marker = "<!-- devagent-studio-pr-review -->"
            posted = GitHubClient().upsert_pr_comment(pull, _github_comment(result), marker)
            result["github_comment_url"] = posted.get("html_url")
            result["github_comment_status"] = "posted"
        except Exception as exc:
            result["github_comment_status"] = "failed"
            result["github_comment_error"] = str(exc)
    elif pull:
        result["github_comment_status"] = "skipped"
    event = {
        "task_id": state.get("task_id"),
        "node": "pr_reviewer",
        "agent": "code_reviewer",
        "type": "agent_step",
        "status": "completed",
        "content": f"Reviewed {len(changed_files)} changed files.",
        "timestamp": utc_now_iso(),
        "data": {"node_id": "pr_reviewer", "node_name": "PR Risk Reviewer"},
    }
    return {"result": result, "events": [event], "final_report": report}


def _git_diff(root: str, base: str | None, head: str | None) -> tuple[list[str], str]:
    args = ["git", "diff", "--unified=3"]
    if base and head:
        args.append(f"{base}..{head}")
    elif base:
        args.append(str(base))
    proc = subprocess.run(args, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=30)
    if proc.returncode != 0:
        raise ValueError(proc.stderr.strip() or "Unable to read Git diff")
    names = subprocess.run(["git", "diff", "--name-only", *args[2:]], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=30)
    return [line.strip() for line in names.stdout.splitlines() if line.strip()], proc.stdout[:120000]


def _github_comment(result: dict[str, Any]) -> str:
    return "<!-- devagent-studio-pr-review -->\n" + str(result.get("final_report") or "")


def _default_goal(scenario: str) -> str:
    return {"onboarding": "生成项目架构导览、关键模块说明、风险清单和新成员学习路径。", "governance": "检查项目架构漂移、技术债和治理缺口，并给出可执行的优先级建议。"}[scenario]


def _onboarding_result(result: dict[str, Any]) -> dict[str, Any]:
    analysis = result.get("project_analysis") or {}
    result["onboarding_artifacts"] = {"architecture_tour": analysis, "learning_path": ["项目入口与技术栈", "核心模块与调用关系", "风险与治理规则", "选择一个模块完成实践任务"]}
    result["next_actions"] = ["从架构导览选择一个模块进行追问", "为关键模块补充 project-memory 知识笔记", "运行一次 PR 变更风险审查"]
    result["suggestions"] = result["next_actions"]
    return result


def _governance_result(result: dict[str, Any]) -> dict[str, Any]:
    actions = result.get("next_actions") or result.get("suggestions") or []
    result["governance_artifacts"] = {"debt_register": actions, "review_cycle": "每次版本发布前运行一次，并对 high/critical finding 进行人工确认"}
    result["next_actions"] = [*actions[:4], "将已确认架构规则沉淀到 project-memory"]
    result["suggestions"] = result["next_actions"]
    return result


def _risk_level(findings: list[dict[str, Any]]) -> str:
    levels = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    value = max((levels.get(str(item.get("severity") or item.get("risk_level") or "low").lower(), 0) for item in findings), default=0)
    return next(key for key, number in levels.items() if number == value)


def _test_recommendations(files: list[str], findings: list[dict[str, Any]]) -> list[str]:
    recommendations = [f"为 {path} 增加回归测试和边界条件测试" for path in files[:4]]
    if any(item.get("category") == "security" for item in findings):
        recommendations.insert(0, "执行凭证扫描并验证敏感信息未进入提交历史")
    return recommendations or ["补充本次变更的最小回归测试集"]


def _pr_report(project_path: str, files: list[str], risk: str, findings: list[dict[str, Any]], tests: list[str], actions: list[str]) -> str:
    finding_lines = "\n".join(f"- [{item.get('severity', 'low')}] {item.get('file', 'unknown')}: {item.get('message', '')}" for item in findings[:20]) or "- 未发现规则级问题，仍需结合业务语义确认。"
    return f"""# PR 变更风险审查\n\n- 项目：`{project_path}`\n- 变更文件：{len(files)}\n- 风险等级：**{risk}**\n- 是否需要人工审核：**{'是' if risk in {'high', 'critical'} else '建议'}**\n\n## 变更范围\n\n{chr(10).join(f'- `{path}`' for path in files) or '- 当前工作区没有可比较的 Git diff。'}\n\n## Findings\n\n{finding_lines}\n\n## 测试建议\n\n{chr(10).join(f'- {item}' for item in tests)}\n\n## 治理动作\n\n{chr(10).join(f'- {item}' for item in actions)}\n"""
