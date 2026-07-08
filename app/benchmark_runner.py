from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.harness.events import utc_now_iso
from app.persistence.sqlite_store import task_store
from app.providers.mcp_provider import mcp_provider


def default_mcp_benchmark_cases() -> list[dict[str, Any]]:
    project_path = Path.cwd().as_posix()
    return [
        {
            "case_id": "fs_read_readme",
            "server_id": "real_filesystem",
            "tool_name": "read_text_file",
            "arguments": {"path": f"{project_path}/README.md", "head": 5},
            "enabled": True,
        },
        {
            "case_id": "fs_list_project",
            "server_id": "real_filesystem",
            "tool_name": "list_directory",
            "arguments": {"path": project_path},
            "enabled": True,
        },
        {
            "case_id": "fs_search_mcp",
            "server_id": "real_filesystem",
            "tool_name": "search_files",
            "arguments": {
                "path": project_path,
                "pattern": "**/*mcp*.py",
                "excludePatterns": ["**/.venv/**", "**/node_modules/**", "**/__pycache__/**"],
            },
            "enabled": True,
        },
        {
            "case_id": "memory_search_project",
            "server_id": "real_memory",
            "tool_name": "search_nodes",
            "arguments": {"query": "DevAgent"},
            "enabled": True,
        },
        {
            "case_id": "memory_read_graph",
            "server_id": "real_memory",
            "tool_name": "read_graph",
            "arguments": {},
            "enabled": True,
        },
    ]


def run_mcp_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    cases = [case for case in (payload.get("cases") or default_mcp_benchmark_cases()) if case.get("enabled", True)]
    iterations = max(1, min(20, int(payload.get("iterations") or 3)))
    agent_code = str(payload.get("agent_code") or "benchmark_runner")
    run_id = f"bench_{uuid4().hex}"
    config = {
        "agent_code": agent_code,
        "iterations": iterations,
        "case_count": len(cases),
        "cases": cases,
    }
    task_store.create_benchmark_run(
        run_id=run_id,
        name=str(payload.get("name") or "MCP Tool Benchmark"),
        benchmark_type="mcp",
        config=config,
    )

    results: list[dict[str, Any]] = []
    for case in cases:
        for iteration in range(1, iterations + 1):
            results.append(_run_single_mcp_case(run_id, case, iteration, agent_code))

    summary = _summarize_benchmark(results, cases, iterations)
    status = "completed" if summary["failed"] == 0 else "completed_with_failures"
    return task_store.finish_benchmark_run(run_id, status, summary)


def _run_single_mcp_case(run_id: str, case: dict[str, Any], iteration: int, agent_code: str) -> dict[str, Any]:
    started = time.perf_counter()
    output: dict[str, Any] = {}
    error_message: str | None = None
    status = "completed"
    try:
        output = mcp_provider.call_tool(
            str(case.get("tool_name") or ""),
            dict(case.get("arguments") or {}),
            server_id=case.get("server_id"),
            agent_code=agent_code,
        )
        if output.get("status") == "failed":
            status = "failed"
            error_message = str(output.get("error_message") or "MCP tool returned failed status")
    except Exception as exc:
        status = "failed"
        error_message = str(exc)

    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    result = {
        "run_id": run_id,
        "case_id": str(case.get("case_id") or case.get("tool_name") or "case"),
        "server_id": case.get("server_id"),
        "tool_name": case.get("tool_name"),
        "iteration": iteration,
        "status": status,
        "latency_ms": latency_ms,
        "error_message": error_message,
        "input": dict(case.get("arguments") or {}),
        "output": _compact_json(output),
        "created_at": utc_now_iso(),
    }
    return task_store.append_benchmark_result(result)


def _summarize_benchmark(results: list[dict[str, Any]], cases: list[dict[str, Any]], iterations: int) -> dict[str, Any]:
    total = len(results)
    completed = sum(1 for item in results if item.get("status") == "completed")
    failed = total - completed
    latencies = sorted(int(item.get("latency_ms") or 0) for item in results)
    by_case: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id") or case.get("tool_name") or "case")
        case_results = [item for item in results if item.get("case_id") == case_id]
        case_latencies = sorted(int(item.get("latency_ms") or 0) for item in case_results)
        case_total = len(case_results)
        case_failed = sum(1 for item in case_results if item.get("status") != "completed")
        by_case.append(
            {
                "case_id": case_id,
                "server_id": case.get("server_id"),
                "tool_name": case.get("tool_name"),
                "total": case_total,
                "completed": case_total - case_failed,
                "failed": case_failed,
                "success_rate": _rate(case_total - case_failed, case_total),
                "avg_latency_ms": _avg(case_latencies),
                "p95_latency_ms": _p95(case_latencies),
                "min_latency_ms": case_latencies[0] if case_latencies else 0,
                "max_latency_ms": case_latencies[-1] if case_latencies else 0,
            }
        )
    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "success_rate": _rate(completed, total),
        "avg_latency_ms": _avg(latencies),
        "p95_latency_ms": _p95(latencies),
        "min_latency_ms": latencies[0] if latencies else 0,
        "max_latency_ms": latencies[-1] if latencies else 0,
        "iterations": iterations,
        "case_count": len(cases),
        "by_case": by_case,
    }


def _avg(values: list[int]) -> int:
    return int(sum(values) / len(values)) if values else 0


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    index = max(0, min(len(values) - 1, math.ceil(len(values) * 0.95) - 1))
    return values[index]


def _rate(numerator: int, denominator: int) -> float:
    return round(float(numerator) / float(denominator), 4) if denominator else 0.0


def _compact_json(value: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= 12000:
        return value
    return {"truncated": True, "preview": text[:12000]}
