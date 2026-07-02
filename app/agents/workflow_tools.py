from __future__ import annotations

from typing import Any


def run_workflow(workflow_name: str, input_text: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    if not nodes:
        nodes = [
            {"id": "plan", "type": "planner", "name": "任务规划", "config": {}},
            {"id": "execute", "type": "executor", "name": "任务执行", "config": {}},
            {"id": "report", "type": "reporter", "name": "结果汇总", "config": {}},
        ]

    events = []
    current = input_text
    for index, node in enumerate(nodes, 1):
        node_type = node.get("type", "unknown")
        name = node.get("name") or node.get("id") or f"node_{index}"
        current = execute_workflow_node(node_type, name, current, node.get("config", {}))
        events.append(
            {
                "step": index,
                "node_id": node.get("id"),
                "node_type": node_type,
                "name": name,
                "status": _status_for_node(node_type),
                "output": current,
            }
        )

    return {"workflow_name": workflow_name, "events": events, "output": current}


def execute_workflow_node(node_type: str, name: str, current: str, config: dict[str, Any]) -> str:
    goal = str(config.get("goal") or current or "未提供目标")
    if node_type == "planner":
        return f"已规划任务：{goal}"
    if node_type == "executor":
        return f"已执行：{current}"
    if node_type == "agent":
        agent_type = config.get("agent_type") or name
        return f"{agent_type} 已处理：{current}"
    if node_type == "rag":
        collection = config.get("collection") or "default"
        return f"已检索知识库 {collection}：{current}"
    if node_type == "mcp_tool":
        tool_name = config.get("tool_name") or "filesystem"
        return f"已调用 MCP 工具 {tool_name}：{current}"
    if node_type == "supervisor":
        return f"质量检查通过：{current}"
    if node_type == "reporter":
        return f"最终报告：{current}"
    if node_type == "human_review":
        return f"等待人工审核：{current}"
    return f"{name} 处理完成：{current}"


def _status_for_node(node_type: str) -> str:
    if node_type == "human_review":
        return "waiting_review"
    return "completed"
