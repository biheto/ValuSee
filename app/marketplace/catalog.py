from __future__ import annotations

from copy import deepcopy
from typing import Any


BUILTIN_MARKETPLACE_MANIFESTS: dict[str, dict[str, Any]] = {
    "security-governance-skill-pack": {
        "package_id": "security-governance-skill-pack",
        "name": "Security Governance Skill Pack",
        "version": "1.0.0",
        "package_type": "skill_pack",
        "author": "ValuSee",
        "description": "Declarative security and governance skills for project risk review.",
        "permissions": ["filesystem.read", "llm.call"],
        "skills": [
            {
                "code": "market.security.checklist",
                "name": "Security Checklist",
                "description": "Produce a security checklist for a repository review.",
                "category": "security",
                "execution_type": "prompt",
                "permissions": ["llm.call"],
                "input_schema": {"project_path": "string", "focus": "string"},
                "output_schema": {"report_markdown": "string"},
                "default_input": {"project_path": ".", "focus": "auth, secret, SQL and dependency risk"},
                "prompt_template": "Review {{project_path}} with focus on {{focus}}.",
                "tests": [
                    {
                        "name": "security checklist smoke",
                        "input": {"project_path": ".", "focus": "secret and dependency risk"},
                    }
                ],
            },
            {
                "code": "market.governance.review",
                "name": "Governance Review",
                "description": "Summarize ownership, review gates and next actions.",
                "category": "governance",
                "execution_type": "prompt",
                "permissions": ["llm.call"],
                "input_schema": {"goal": "string"},
                "output_schema": {"report_markdown": "string"},
                "default_input": {"goal": "Assess governance gaps and review gates."},
                "prompt_template": "Create governance actions for: {{goal}}",
                "tests": [
                    {
                        "name": "governance review smoke",
                        "input": {"goal": "Check ownership, review gates and rollback plan."},
                    }
                ],
            },
        ],
    },
    "devagent-rag-knowledge-pack": {
        "package_id": "devagent-rag-knowledge-pack",
        "name": "DevAgent RAG Knowledge Pack",
        "version": "1.0.0",
        "package_type": "rag_pack",
        "author": "ValuSee",
        "description": "Seed project-memory with reusable RAG notes about DevAgent concepts.",
        "permissions": ["rag.write"],
        "rag_notes": [
            {
                "collection": "project-memory",
                "path": "marketplace/skill-plugin-system",
                "content": "Skill plugins are runtime capabilities registered with metadata, permissions, input schema, output schema and execution logs.",
            },
            {
                "collection": "project-memory",
                "path": "marketplace/harness-runtime",
                "content": "Harness Runtime records task context, timeline events, artifacts, human review checkpoints and resume state for governed agent execution.",
            },
        ],
    },
    "filesystem-mcp-pack": {
        "package_id": "filesystem-mcp-pack",
        "name": "Filesystem MCP Pack",
        "version": "1.0.0",
        "package_type": "mcp_pack",
        "author": "ValuSee",
        "description": "Register a stdio filesystem MCP server configuration template.",
        "permissions": ["mcp.configure"],
        "mcp_servers": [
            {
                "server_id": "market_filesystem",
                "name": "Marketplace Filesystem MCP",
                "transport": "stdio",
                "command": ".venv\\Scripts\\python.exe",
                "args": ["scripts/launch_mcp_filesystem.py", "."],
                "env": {},
                "enabled": False,
            }
        ],
    },
    "governance-benchmark-dataset": {
        "package_id": "governance-benchmark-dataset",
        "name": "Governance Benchmark Dataset",
        "version": "1.0.0",
        "package_type": "benchmark_pack",
        "author": "ValuSee",
        "description": "Reusable benchmark cases for LLM, RAG, Workflow and collaboration evaluation.",
        "permissions": ["benchmark.read"],
        "benchmark_cases": [
            {
                "benchmark_type": "llm",
                "case_id": "prompt_governance_summary",
                "arguments": {"agent": "reporter", "user_prompt": "Summarize governance risks.", "fallback": "fallback"},
                "enabled": True,
            },
            {
                "benchmark_type": "rag",
                "case_id": "rag_skill_plugin_question",
                "arguments": {"collection": "project-memory", "question": "What is a skill plugin?", "limit": 5},
                "enabled": True,
            },
        ],
    },
    "review-workflow-template-pack": {
        "package_id": "review-workflow-template-pack",
        "name": "Review Workflow Template Pack",
        "version": "1.0.0",
        "package_type": "workflow_pack",
        "author": "ValuSee",
        "description": "Install a reusable Skill-based review workflow template.",
        "permissions": ["workflow.write"],
        "workflows": [
            {
                "workflow_id": "market_skill_review_workflow",
                "name": "Marketplace Skill Review Workflow",
                "description": "Planner -> Security Scan Skill -> Reporter",
                "nodes": [
                    {"id": "plan", "type": "planner", "name": "Planner", "x": 64, "y": 90, "config": {}},
                    {
                        "id": "security",
                        "type": "skill",
                        "name": "Security Scan",
                        "x": 300,
                        "y": 90,
                        "config": {"skill_code": "security.scan", "agent_code": "skill_console", "input": {}},
                    },
                    {"id": "report", "type": "reporter", "name": "Reporter", "x": 540, "y": 90, "config": {}},
                ],
                "edges": [{"source": "plan", "target": "security"}, {"source": "security", "target": "report"}],
            }
        ],
    },
    "prompt-governance-pack": {
        "package_id": "prompt-governance-pack",
        "name": "Prompt Governance Pack",
        "version": "1.0.0",
        "package_type": "prompt_pack",
        "author": "ValuSee",
        "description": "Install an additional reporter prompt version for evidence-first reports.",
        "permissions": ["prompt.write"],
        "prompts": [
            {
                "agent": "reporter",
                "prompt_family": "reporter",
                "prompt_version": "reporter.marketplace.evidence.v1",
                "title": "Marketplace evidence reporter",
                "description": "Requires evidence, uncertainty and owner-oriented next actions.",
                "system_suffix": "Always include evidence, uncertainty, owner, next action and review gate sections.",
                "is_active": False,
            }
        ],
    },
}


def marketplace_catalog() -> list[dict[str, Any]]:
    items = []
    for manifest in BUILTIN_MARKETPLACE_MANIFESTS.values():
        items.append(
            {
                "package_id": manifest["package_id"],
                "name": manifest["name"],
                "version": manifest.get("version", "1.0.0"),
                "package_type": manifest["package_type"],
                "author": manifest.get("author"),
                "description": manifest.get("description"),
                "permissions": manifest.get("permissions", []),
                "source_url": f"builtin://{manifest['package_id']}",
            }
        )
    return items


def get_builtin_manifest(package_id: str) -> dict[str, Any] | None:
    manifest = BUILTIN_MARKETPLACE_MANIFESTS.get(package_id)
    return deepcopy(manifest) if manifest else None
