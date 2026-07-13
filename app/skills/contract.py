from __future__ import annotations

import re
from typing import Any


ALLOWED_EXECUTION_TYPES = {"agent", "prompt", "rule", "python"}
ALLOWED_SCHEMA_TYPES = {"string", "number", "integer", "boolean", "object", "array", "null"}
ALLOWED_DEPENDENCY_TYPES = {"mcp_tool", "rag_collection", "prompt_version", "llm_model", "skill"}

PERMISSION_LEVELS: dict[str, dict[str, Any]] = {
    "safe": {"rank": 0, "label": "Safe", "description": "No external side effects."},
    "project-read": {"rank": 1, "label": "Project read", "description": "Reads project files or metadata."},
    "llm": {"rank": 2, "label": "LLM", "description": "Calls a configured language model."},
    "workflow-write": {"rank": 3, "label": "Workflow write", "description": "Can create or modify workflow definitions."},
    "network": {"rank": 4, "label": "Network", "description": "May access network resources."},
    "filesystem": {"rank": 5, "label": "Filesystem", "description": "May write files or run local filesystem operations."},
}

PERMISSION_ALIASES = {
    "llm.call": "llm",
    "project.read": "project-read",
    "project.file.read": "project-read",
    "filesystem.read": "project-read",
    "filesystem.write": "filesystem",
    "network.call": "network",
    "workflow.write": "workflow-write",
}


def normalize_permission_level(permission: str) -> str:
    value = permission.strip().lower()
    if value in PERMISSION_LEVELS:
        return value
    return PERMISSION_ALIASES.get(value, "safe")


def permission_levels(permissions: list[str]) -> list[str]:
    levels = {normalize_permission_level(str(permission)) for permission in permissions}
    return sorted(levels, key=lambda item: PERMISSION_LEVELS[item]["rank"])


def risk_level_for_permissions(permissions: list[str], execution_type: str) -> str:
    levels = permission_levels(permissions)
    max_rank = max((PERMISSION_LEVELS[level]["rank"] for level in levels), default=0)
    if execution_type == "python":
        max_rank = max(max_rank, PERMISSION_LEVELS["filesystem"]["rank"])
    if max_rank >= 5:
        return "critical"
    if max_rank >= 4:
        return "high"
    if max_rank >= 2:
        return "medium"
    return "low"


def validate_skill_contract(skill: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    code = str(skill.get("code") or "").strip()
    execution_type = str(skill.get("execution_type") or "prompt").strip()
    permissions = skill.get("permissions") if isinstance(skill.get("permissions"), list) else []
    input_schema = skill.get("input_schema")
    output_schema = skill.get("output_schema")
    dependencies = skill.get("dependencies") if isinstance(skill.get("dependencies"), list) else []
    tests = skill.get("tests") if isinstance(skill.get("tests"), list) else []

    if not code:
        errors.append("skill.code is required")
    elif not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{1,127}$", code):
        errors.append("skill.code must use letters, numbers, dot, underscore, colon or dash")
    if execution_type not in ALLOWED_EXECUTION_TYPES:
        errors.append(f"Unsupported execution_type: {execution_type}")
    if not isinstance(input_schema, dict):
        errors.append("input_schema must be an object")
    else:
        _validate_schema("input_schema", input_schema, errors, warnings)
    if not isinstance(output_schema, dict):
        errors.append("output_schema must be an object")
    else:
        _validate_schema("output_schema", output_schema, errors, warnings)
    if not isinstance(permissions, list) or any(not isinstance(item, str) for item in permissions):
        errors.append("permissions must be a string array")
    if dependencies:
        _validate_dependencies(dependencies, errors)
    if tests:
        _validate_tests(tests, errors)
    if execution_type == "python":
        default_input = skill.get("default_input") if isinstance(skill.get("default_input"), dict) else {}
        if not skill.get("entrypoint") and not default_input.get("_entrypoint_path"):
            errors.append("python skill requires entrypoint or default_input._entrypoint_path")
        if not any(normalize_permission_level(str(item)) in {"filesystem", "project-read"} for item in permissions):
            warnings.append("python skill should declare project-read or filesystem permission")

    levels = permission_levels([str(item) for item in permissions])
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "permission_levels": levels,
        "risk_level": risk_level_for_permissions([str(item) for item in permissions], execution_type),
    }


def _validate_schema(name: str, schema: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    if not schema:
        warnings.append(f"{name} is empty")
        return
    for key, value in schema.items():
        if not isinstance(key, str) or not key:
            errors.append(f"{name} contains an empty key")
        if isinstance(value, str):
            if value not in ALLOWED_SCHEMA_TYPES:
                warnings.append(f"{name}.{key} uses non-standard type `{value}`")
        elif isinstance(value, dict):
            declared_type = value.get("type")
            if declared_type and declared_type not in ALLOWED_SCHEMA_TYPES:
                warnings.append(f"{name}.{key} uses non-standard type `{declared_type}`")
        else:
            errors.append(f"{name}.{key} must be a string type or schema object")


def _validate_dependencies(dependencies: list[Any], errors: list[str]) -> None:
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            errors.append(f"dependencies[{index}] must be an object")
            continue
        dep_type = str(dependency.get("type") or "")
        dep_ref = str(dependency.get("ref") or dependency.get("name") or "")
        if dep_type not in ALLOWED_DEPENDENCY_TYPES:
            errors.append(f"dependencies[{index}].type is unsupported: {dep_type}")
        if not dep_ref:
            errors.append(f"dependencies[{index}] requires ref or name")


def _validate_tests(tests: list[Any], errors: list[str]) -> None:
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            errors.append(f"tests[{index}] must be an object")
            continue
        if not str(test.get("name") or test.get("case_id") or "").strip():
            errors.append(f"tests[{index}] requires name or case_id")
        if not isinstance(test.get("input") or {}, dict):
            errors.append(f"tests[{index}].input must be an object")
