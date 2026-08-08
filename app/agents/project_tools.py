from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.providers.llm_provider import llm_provider

EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "node_modules",
    "target",
    "build",
    "dist",
    "__pycache__",
}

KEY_FILE_NAMES = {
    "README.md",
    "pom.xml",
    "build.gradle",
    "settings.gradle",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Dockerfile",
    "docker-compose.yml",
    "application.yml",
    "application.yaml",
    "application.properties",
    "tsconfig.json",
    "vite.config.ts",
    "rsbuild.config.ts",
}


def scan_project(project_path: str, max_files: int) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Project path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {root}")

    files: list[dict[str, Any]] = []
    directories: set[str] = set()
    key_files: list[str] = []

    for path in root.rglob("*"):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            directories.add(rel)
            continue
        if len(files) >= max_files:
            break
        suffix = path.suffix.lower()
        item = {
            "path": rel,
            "name": path.name,
            "suffix": suffix,
            "size": path.stat().st_size,
        }
        files.append(item)
        if path.name in KEY_FILE_NAMES or path.name.lower().startswith("readme"):
            key_files.append(rel)

    return {
        "root": root.as_posix(),
        "project_name": root.name,
        "files": files,
        "directories": sorted(directories),
        "key_files": sorted(key_files),
    }


def identify_tech_stack(scan: dict[str, Any]) -> list[str]:
    paths = {file["path"] for file in scan["files"]}
    names = {file["name"] for file in scan["files"]}
    suffixes = {file["suffix"] for file in scan["files"]}
    stack: set[str] = set()

    if "pom.xml" in names:
        stack.update({"Java", "Maven"})
    if "build.gradle" in names or "settings.gradle" in names:
        stack.update({"Java", "Gradle"})
    if any(path.endswith("Application.java") for path in paths):
        stack.add("Spring Boot")
    if any("mybatis" in path.lower() for path in paths):
        stack.add("MyBatis")
    if "package.json" in names:
        stack.update({"Node.js", "Frontend"})
    if "tsconfig.json" in names or ".tsx" in suffixes or ".ts" in suffixes:
        stack.add("TypeScript")
    if ".tsx" in suffixes or any("react" in path.lower() for path in paths):
        stack.add("React")
    if "pyproject.toml" in names or "requirements.txt" in names:
        stack.add("Python")
    if any(path.endswith("main.py") for path in paths):
        stack.add("FastAPI/Python Service")
    if "Dockerfile" in names or "docker-compose.yml" in names:
        stack.add("Docker")
    if any(path.endswith(".sql") for path in paths):
        stack.add("SQL")
    if any("mcp" in path.lower() for path in paths):
        stack.add("MCP")
    if any("rag" in path.lower() for path in paths):
        stack.add("RAG")

    return sorted(stack)


def analyze_modules(scan: dict[str, Any]) -> list[str]:
    directories = scan["directories"]
    modules: list[str] = []

    top_level = sorted({directory.split("/")[0] for directory in directories if "/" not in directory})
    for name in top_level[:20]:
        modules.append(name)

    maven_modules = [
        directory
        for directory in directories
        if directory.count("/") <= 1 and any(
            file["path"] == f"{directory}/pom.xml" for file in scan["files"]
        )
    ]
    for module in maven_modules:
        if module not in modules:
            modules.append(module)

    return modules[:30]


def extract_api_hints(scan: dict[str, Any]) -> list[str]:
    hints: list[str] = []
    controller_files = [file["path"] for file in scan["files"] if "controller" in file["path"].lower()]
    for path in controller_files[:20]:
        hints.append(path)
    return hints


def generate_findings(scan: dict[str, Any], tech_stack: list[str], modules: list[str]) -> tuple[list[str], list[str]]:
    risks: list[str] = []
    suggestions: list[str] = []
    key_files = set(scan["key_files"])
    file_count = len(scan["files"])

    if not any(path.lower().startswith("readme") or path.lower().endswith("/readme.md") for path in key_files):
        risks.append("未发现 README 文档，项目上手成本可能较高。")
        suggestions.append("补充 README，说明项目定位、启动方式、核心模块和常用命令。")

    if "Docker" not in tech_stack:
        suggestions.append("可以补充 Dockerfile 或 docker-compose，降低环境搭建成本。")

    if file_count >= 500:
        suggestions.append("项目文件较多，建议增加模块说明和架构图，方便新人理解。")

    if "Java" in tech_stack and "Maven" in tech_stack and not modules:
        risks.append("检测到 Maven/Java，但模块边界不明显，可能需要进一步梳理分层。")

    if "SQL" in tech_stack:
        suggestions.append("建议把数据库表结构和核心业务实体建立映射说明。")

    if "MCP" in tech_stack:
        suggestions.append("建议为 MCP 工具增加权限边界、调用日志和失败重试策略。")

    if not risks:
        risks.append("未发现明显结构性风险，后续可接入更深入的代码质量分析。")
    if not suggestions:
        suggestions.append("建议进入第二阶段：加入代码审查 Agent 和 LLM 语义分析。")

    return risks, suggestions


def quality_score(scan: dict[str, Any], tech_stack: list[str], risks: list[str]) -> int:
    score = 70
    if scan["key_files"]:
        score += 10
    if tech_stack:
        score += 10
    if len(scan["directories"]) > 3:
        score += 5
    score -= max(0, len(risks) - 1) * 5
    return max(0, min(100, score))


def generate_report(
    scan: dict[str, Any],
    tech_stack: list[str],
    modules: list[str],
    api_hints: list[str],
    risks: list[str],
    suggestions: list[str],
    score: int,
) -> str:
    stack_text = ", ".join(tech_stack) if tech_stack else "暂未识别"
    key_files = "\n".join(f"- `{item}`" for item in scan["key_files"][:30]) or "- 暂未发现"
    module_text = "\n".join(f"- `{item}`" for item in modules) or "- 暂未识别明显模块"
    api_text = "\n".join(f"- `{item}`" for item in api_hints) or "- 暂未发现 Controller/API 线索"
    risk_text = "\n".join(f"- {item}" for item in risks)
    suggestion_text = "\n".join(f"- {item}" for item in suggestions)
    mermaid_nodes = "\n".join(
        f"    A --> M{index}[{_safe_mermaid_label(module)}]" for index, module in enumerate(modules[:8], 1)
    ) or "    A --> B[待进一步分析]"

    fallback = f"""# {scan['project_name']} 项目分析报告

## 项目概览

- 项目路径：`{scan['root']}`
- 文件数量：{len(scan['files'])}
- 目录数量：{len(scan['directories'])}
- 识别技术栈：{stack_text}
- 初步质量评分：{score}/100

## 关键文件

{key_files}

## 模块结构

{module_text}

## API / 入口线索

{api_text}

## 架构草图

```mermaid
graph TD
    A[{_safe_mermaid_label(scan['project_name'])}]
{mermaid_nodes}
```

## 风险提示

{risk_text}

## 优化建议

{suggestion_text}

## 下一步建议

- 接入代码审查 Agent，分析异常处理、重复代码、安全风险和 SQL 风险。
- 接入 RAG 知识加工 Agent，把 README、接口文档、SQL 和部署文档沉淀为可检索知识库。
- 接入 LangGraph Checkpoint，把任务执行过程保存为可回放的时间线。
"""
    architecture = llm_provider.generate(
        "你是 ValuSee 的项目架构讲解 Agent。请基于扫描事实解释项目结构、阅读路径和治理建议，不要编造不存在的文件。",
        (
            "请输出中文 Markdown，包含：项目定位、架构理解、关键模块阅读顺序、风险理解、学习路径。"
            "只基于给定事实。\n"
            f"项目：{scan['project_name']}\n"
            f"技术栈：{tech_stack}\n"
            f"模块：{modules}\n"
            f"关键文件：{scan.get('key_files', [])[:30]}\n"
            f"API 线索：{api_hints}\n"
            f"风险：{risks}\n"
            f"建议：{suggestions}"
        ),
        "",
        agent="project_analyzer",
        prompt_version="project_analyzer.architecture.v1",
    )
    if architecture:
        return f"{fallback}\n\n## LLM 架构理解\n\n{architecture}\n"
    return fallback


def _safe_mermaid_label(value: str) -> str:
    return re.sub(r"[\[\]{}()<>|]", " ", value).strip() or "Project"
