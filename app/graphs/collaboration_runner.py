from __future__ import annotations

from typing import Any

from app.graphs.studio_graphs import collaboration_graph


COLLABORATION_NODES = [
    ("planner", "Planner"),
    ("project_analyzer", "Project Analyzer"),
    ("code_reviewer", "Code Reviewer"),
    ("rag_processor", "RAG Processor"),
    ("supervisor", "Supervisor"),
    ("human_review", "Human Review"),
    ("reporter", "Reporter"),
]


def run_collaboration_task(input_state: dict[str, Any]) -> dict[str, Any]:
    graph_state = {
        "goal": input_state.get("goal") or input_state.get("input_text") or "",
        "project_path": input_state.get("project_path"),
        "max_files": input_state.get("max_files", 500),
        "require_human_review": input_state.get("require_human_review", True),
        "task_id": input_state.get("task_id"),
        "events": [],
    }
    result = collaboration_graph.invoke(graph_state)["result"]
    public_result = {
        **result,
        "workflow_name": "multi_agent_collaboration",
        "mermaid": build_collaboration_mermaid(),
        "suggestions": _collaboration_suggestions(result),
        "suggestion_records": _collaboration_suggestion_records(result),
        "tool_calls": [],
        "agent_outputs": _agent_outputs(result),
        **_collaboration_governance(result),
        "workflow_events": _enrich_events(result.get("events", [])),
    }
    return {
        "result": public_result,
        "events": public_result["workflow_events"],
        "final_report": result.get("final_report"),
    }


def build_collaboration_mermaid() -> str:
    lines = ["flowchart LR"]
    for node_id, label in COLLABORATION_NODES:
        lines.append(f"  {node_id}[{label}]")
    for index, (source, _) in enumerate(COLLABORATION_NODES[:-1]):
        target = COLLABORATION_NODES[index + 1][0]
        lines.append(f"  {source} --> {target}")
    return "\n".join(lines)


def _agent_outputs(result: dict[str, Any]) -> list[dict[str, str]]:
    outputs: list[dict[str, str]] = []
    plan = result.get("plan") or []
    if plan:
        outputs.append(
            {
                "node_id": "planner",
                "node_name": "Planner",
                "agent": "planner",
                "content": "\n".join(f"- {item}" for item in plan),
            }
        )
    for item in result.get("worker_results", []):
        agent = str(item.get("agent") or "agent")
        outputs.append(
            {
                "node_id": agent,
                "node_name": _label_for(agent),
                "agent": agent,
                "content": str(item.get("result") or ""),
            }
        )
    notes = result.get("supervisor_notes") or []
    if notes:
        outputs.append(
            {
                "node_id": "supervisor",
                "node_name": "Supervisor",
                "agent": "supervisor",
                "content": "\n".join(f"- {item}" for item in notes),
            }
        )
    if result.get("human_review_packet"):
        outputs.append(
            {
                "node_id": "human_review",
                "node_name": "Human Review",
                "agent": "human_reviewer",
                "content": "Human review packet generated.",
            }
        )
    if result.get("final_report"):
        outputs.append(
            {
                "node_id": "reporter",
                "node_name": "Reporter",
                "agent": "reporter",
                "content": str(result.get("final_report")),
            }
        )
    return outputs


def _collaboration_suggestions(result: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    suggestions.extend(str(item) for item in result.get("supervisor_notes", []))
    project_analysis = result.get("project_analysis") or {}
    code_review = result.get("code_review") or {}
    rag_result = result.get("rag_result") or {}
    suggestions.extend(str(item) for item in project_analysis.get("suggestions", [])[:3])
    suggestions.extend(str(item) for item in code_review.get("suggestions", [])[:3])
    if rag_result.get("chunk_count", 0) > 0:
        suggestions.append("Persist RAG chunks into a vector store for semantic retrieval.")
    return suggestions


def _collaboration_suggestion_records(result: dict[str, Any]) -> list[dict[str, Any]]:
    code_review = result.get("code_review") or {}
    records = code_review.get("suggestion_records") or []
    return [item for item in records if isinstance(item, dict)]


def _collaboration_governance(result: dict[str, Any]) -> dict[str, Any]:
    records = _collaboration_suggestion_records(result)
    code_review = result.get("code_review") or {}
    review_required = bool(result.get("human_review_required")) or any(record.get("review_required") for record in records)
    risk_level = _highest_risk([record.get("risk_level") for record in records])
    score = code_review.get("score")
    if isinstance(score, int) and score < 70 and risk_level == "low":
        risk_level = "high"
    next_actions = _collect_next_actions(records, _collaboration_suggestions(result))
    return {
        "risk_level": risk_level,
        "review_required": review_required,
        "next_actions": next_actions,
        "governance": {
            "risk_level": risk_level,
            "review_required": review_required,
            "next_actions": next_actions,
            "suggestion_record_count": len(records),
        },
    }


def _highest_risk(values: list[Any]) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    level = "low"
    for value in values:
        key = str(value or "low")
        if order.get(key, 0) > order[level]:
            level = key
    return level


def _collect_next_actions(records: list[dict[str, Any]], suggestions: list[str]) -> list[str]:
    actions: list[str] = []
    for record in records:
        for action in record.get("next_actions", [])[:2]:
            if action not in actions:
                actions.append(str(action))
    for suggestion in suggestions[:5]:
        if suggestion not in actions:
            actions.append(suggestion)
    return actions[:6] or ["Review supervisor notes.", "Save stable conclusions to project-memory."]


def _enrich_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched = []
    for event in events:
        node_id = str(event.get("node") or event.get("agent") or "collaboration")
        item = dict(event)
        item["data"] = {
            **(item.get("data") or {}),
            "node_id": node_id,
            "node_type": "collaboration",
            "node_name": _label_for(node_id),
        }
        enriched.append(item)
    return enriched


def _label_for(node_id: str) -> str:
    labels = dict(COLLABORATION_NODES)
    aliases = {
        "project_analyzer": "Project Analyzer",
        "code_reviewer": "Code Reviewer",
        "rag_processor": "RAG Processor",
    }
    return labels.get(node_id) or aliases.get(node_id) or node_id.replace("_", " ").title()
