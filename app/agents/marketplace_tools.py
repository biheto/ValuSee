from __future__ import annotations

from typing import Any

TOOLS: list[dict[str, Any]] = [
    {"code": "file_scan", "name": "文件扫描", "category": "filesystem", "transport": "native", "risk": "low"},
    {"code": "code_review", "name": "代码规则审查", "category": "analysis", "transport": "native", "risk": "low"},
    {"code": "rag_chunk", "name": "知识切片", "category": "rag", "transport": "native", "risk": "low"},
    {"code": "vector_search", "name": "向量检索", "category": "rag", "transport": "mcp/remote", "risk": "medium"},
    {"code": "git_read", "name": "Git 仓库读取", "category": "git", "transport": "mcp", "risk": "medium"},
    {"code": "shell_exec", "name": "命令执行", "category": "system", "transport": "mcp", "risk": "high"},
    {"code": "http_api", "name": "HTTP API 调用", "category": "integration", "transport": "mcp", "risk": "medium"},
]

AGENT_TOOL_ALLOWLIST: dict[str, set[str]] = {
    "project_analyzer": {"file_scan", "git_read"},
    "code_reviewer": {"file_scan", "code_review", "git_read"},
    "rag_processor": {"file_scan", "rag_chunk", "vector_search"},
    "learning_coach": {"rag_chunk"},
    "workflow_runner": {"file_scan", "http_api", "rag_chunk"},
}


def list_tools() -> list[dict[str, Any]]:
    return TOOLS


def check_permission(agent_code: str, tool_code: str) -> dict[str, Any]:
    allowed = tool_code in AGENT_TOOL_ALLOWLIST.get(agent_code, set())
    risk = next((item["risk"] for item in TOOLS if item["code"] == tool_code), "unknown")
    reason = "工具在该 Agent 的允许列表中。" if allowed else "工具未授权给该 Agent，需管理员审批。"
    if risk == "high" and allowed:
        reason += " 该工具风险较高，建议启用人工确认。"
    return {"agent_code": agent_code, "tool_code": tool_code, "allowed": allowed, "reason": reason}
