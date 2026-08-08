from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.agents.project_tools import EXCLUDED_DIRS, scan_project
from app.providers.llm_provider import llm_provider

SOURCE_SUFFIXES = {".java", ".py", ".ts", ".tsx", ".js", ".jsx", ".xml", ".yml", ".yaml", ".sql"}
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"(?i)Bearer\s+[a-z0-9._\-]{20,}"),
]


def review_project(project_path: str, max_files: int) -> dict[str, Any]:
    scan = scan_project(project_path, max_files)
    root = Path(scan["root"])
    findings: list[dict[str, Any]] = []

    for file in scan["files"]:
        if file["suffix"] not in SOURCE_SUFFIXES:
            continue
        path = root / file["path"]
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        text = _safe_read(path)
        if not text:
            continue
        findings.extend(_review_file(file["path"], text))

    risks = _build_risks(findings, scan)
    suggestions = _build_suggestions(findings, scan)
    suggestion_records = _build_suggestion_records(findings, suggestions, scan)
    score = _score(findings, scan)
    report = _report(scan, findings, risks, suggestions, score)
    return {
        "scan": scan,
        "findings": findings,
        "risks": risks,
        "suggestions": suggestions,
        "suggestion_records": suggestion_records,
        "score": score,
        "report_markdown": report,
    }


def review_single_file(project_path: str, file_path: str, max_chars: int = 20000) -> dict[str, Any]:
    root = Path(project_path).expanduser().resolve()
    target = (root / file_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError("Refusing to review outside project root")
    if not target.is_file():
        raise FileNotFoundError(str(target))
    rel_path = target.relative_to(root).as_posix()
    text = _safe_read_limited(target, max_chars)
    lines = text.splitlines()
    suffix = target.suffix.lower()
    findings = _review_file(rel_path, text)
    responsibilities = _infer_responsibilities(rel_path, text)
    dependencies = _extract_dependencies(text, suffix)
    api_surface = _extract_api_surface(text, suffix)
    call_chain = _build_call_chain_context(root, rel_path, text, suffix)
    testability = _assess_testability(text, suffix, findings)
    risks = _build_file_risks(findings, text, dependencies, testability)
    suggestions = _build_file_suggestions(rel_path, findings, dependencies, testability)
    semantic_review = _semantic_file_review(
        rel_path=rel_path,
        text=text,
        responsibilities=responsibilities,
        dependencies=dependencies,
        api_surface=api_surface,
        call_chain=call_chain,
        findings=findings,
        risks=risks,
        testability=testability,
    )
    report = _file_report(
        rel_path=rel_path,
        line_count=len(lines),
        suffix=suffix or "unknown",
        responsibilities=responsibilities,
        dependencies=dependencies,
        api_surface=api_surface,
        call_chain=call_chain,
        findings=findings,
        risks=risks,
        testability=testability,
        semantic_review=semantic_review,
        suggestions=suggestions,
    )
    return {
        "project_path": root.as_posix(),
        "file_path": rel_path,
        "line_count": len(lines),
        "suffix": suffix,
        "responsibilities": responsibilities,
        "dependencies": dependencies,
        "api_surface": api_surface,
        "call_chain": call_chain,
        "findings": findings,
        "risks": risks,
        "testability": testability,
        "semantic_review": semantic_review,
        "suggestions": suggestions,
        "report_markdown": report,
    }


def _safe_read(path: Path) -> str:
    try:
        if path.stat().st_size > 300_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _safe_read_limited(path: Path, max_chars: int) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def _review_file(rel_path: str, text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = text.splitlines()

    for index, line in enumerate(lines, 1):
        stripped = line.strip()
        if "TODO" in stripped or "FIXME" in stripped:
            findings.append(_finding("maintainability", "medium", rel_path, index, "存在 TODO/FIXME，需要跟踪处理。"))
        if "printStackTrace()" in stripped:
            findings.append(_finding("reliability", "high", rel_path, index, "直接 printStackTrace，建议使用统一日志和异常处理。"))
        if re.search(r"catch\s*\(\s*Exception\s+\w+\s*\)", stripped):
            findings.append(_finding("reliability", "medium", rel_path, index, "捕获通用 Exception，建议收敛异常类型。"))
        if "SELECT *" in stripped.upper():
            findings.append(_finding("database", "medium", rel_path, index, "SQL 使用 SELECT *，建议显式字段。"))
        if re.search(r"sql\s*\+=", stripped, re.IGNORECASE) or re.search(r"query\s*\+=", stripped, re.IGNORECASE):
            findings.append(_finding("security", "high", rel_path, index, "疑似字符串拼接 SQL，需检查注入风险。"))
        for pattern in SECRET_PATTERNS:
            if pattern.search(stripped):
                findings.append(_finding("security", "critical", rel_path, index, "疑似硬编码密钥或敏感凭证。"))

    if len(lines) > 500:
        findings.append(_finding("maintainability", "medium", rel_path, 1, "单文件行数超过 500，建议拆分职责。"))

    return findings


def _infer_responsibilities(rel_path: str, text: str) -> list[str]:
    lower_path = rel_path.lower()
    signals: list[str] = []
    path_roles = [
        ("route", "定义 HTTP/API 路由或请求入口"),
        ("controller", "处理控制器入口和请求编排"),
        ("service", "承载业务服务或应用用例"),
        ("repository", "封装数据访问或持久化逻辑"),
        ("store", "管理本地状态或持久化存储"),
        ("schema", "定义数据模型、请求响应结构或校验规则"),
        ("component", "实现前端 UI 组件"),
        ("test", "验证功能行为或回归场景"),
        ("graph", "编排 LangGraph/工作流节点"),
        ("agent", "实现 Agent 能力或工具封装"),
    ]
    for keyword, role in path_roles:
        if keyword in lower_path:
            signals.append(role)
    if re.search(r"@\w+\.(get|post|put|patch|delete)\(", text):
        signals.append("暴露 FastAPI 风格接口")
    if re.search(r"class\s+\w+", text):
        signals.append("定义类/对象边界")
    if re.search(r"def\s+\w+\(", text):
        signals.append("提供函数级能力单元")
    if re.search(r"export\s+(function|const|type)|function\s+[A-Z]\w+\(", text):
        signals.append("提供前端组件、类型或交互函数")
    if not signals:
        signals.append("承担通用代码逻辑，需结合调用方确认职责边界")
    return _unique(signals)[:8]


def _extract_dependencies(text: str, suffix: str) -> list[str]:
    dependencies: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if suffix == ".py":
            match = re.match(r"(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", stripped)
            if match:
                dependencies.append(match.group(1) or match.group(2))
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            match = re.search(r"from\s+['\"]([^'\"]+)['\"]|import\(['\"]([^'\"]+)['\"]\)", stripped)
            if match:
                dependencies.append(match.group(1) or match.group(2))
        elif suffix in {".java"}:
            match = re.match(r"import\s+([\w.*]+);", stripped)
            if match:
                dependencies.append(match.group(1))
        elif suffix in {".xml", ".yml", ".yaml"}:
            if ":" in stripped and not stripped.startswith("#"):
                dependencies.append(stripped.split(":", 1)[0])
    return _unique(dependencies)[:20]


def _extract_api_surface(text: str, suffix: str) -> list[str]:
    surface: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if suffix == ".py":
            match = re.match(r"(?:async\s+)?def\s+(\w+)\(", stripped)
            if match:
                surface.append(f"function {match.group(1)}")
            route = re.search(r"@\w+\.(get|post|put|patch|delete)\(([^)]*)\)", stripped)
            if route:
                surface.append(f"HTTP {route.group(1).upper()} {route.group(2)[:80]}")
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            match = re.match(r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\(", stripped)
            if match:
                surface.append(f"function {match.group(1)}")
            const_match = re.match(r"export\s+const\s+(\w+)", stripped)
            if const_match:
                surface.append(f"export const {const_match.group(1)}")
        elif suffix == ".java":
            match = re.search(r"(public|private|protected)\s+[\w<>\[\]]+\s+(\w+)\(", stripped)
            if match:
                surface.append(f"method {match.group(2)}")
    return _unique(surface)[:30]


def _build_call_chain_context(root: Path, rel_path: str, text: str, suffix: str) -> dict[str, Any]:
    symbols = _extract_local_symbols(text, suffix)
    inbound = _find_inbound_references(root, rel_path, symbols)
    outbound = _extract_outbound_calls(text, suffix)
    return {
        "symbols": symbols[:30],
        "inbound_references": inbound[:30],
        "outbound_calls": outbound[:30],
        "summary": _call_chain_summary(symbols, inbound, outbound),
    }


def _extract_local_symbols(text: str, suffix: str) -> list[str]:
    symbols: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if suffix == ".py":
            for pattern in [r"class\s+(\w+)", r"(?:async\s+)?def\s+(\w+)\("]:
                match = re.match(pattern, stripped)
                if match:
                    symbols.append(match.group(1))
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            for pattern in [
                r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\(",
                r"(?:export\s+)?const\s+(\w+)\s*=",
                r"type\s+(\w+)\s*=",
                r"interface\s+(\w+)",
            ]:
                match = re.match(pattern, stripped)
                if match:
                    symbols.append(match.group(1))
        elif suffix == ".java":
            for pattern in [r"class\s+(\w+)", r"(?:public|private|protected)\s+[\w<>\[\]]+\s+(\w+)\("]:
                match = re.search(pattern, stripped)
                if match:
                    symbols.append(match.group(1))
    return _unique(symbols)


def _find_inbound_references(root: Path, rel_path: str, symbols: list[str]) -> list[dict[str, Any]]:
    if not symbols:
        return []
    symbol_set = set(symbols[:20])
    references: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if len(references) >= 60:
            break
        if path.is_dir() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            path.relative_to(root)
        except ValueError:
            continue
        relative = path.relative_to(root).as_posix()
        if relative == rel_path or any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        content = _safe_read_limited(path, 60000)
        if not content:
            continue
        for symbol in symbol_set:
            if re.search(rf"\b{re.escape(symbol)}\b", content):
                references.append({"path": relative, "symbol": symbol})
                break
    return references


def _extract_outbound_calls(text: str, suffix: str) -> list[str]:
    calls: list[str] = []
    if suffix == ".py":
        for match in re.finditer(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\(", text):
            name = match.group(1)
            if name not in {"if", "for", "while", "return", "len", "str", "int", "dict", "list", "set"}:
                calls.append(name)
    elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
        for match in re.finditer(r"\b([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\(", text):
            name = match.group(1)
            if name not in {"if", "for", "while", "switch", "map", "filter", "reduce"}:
                calls.append(name)
    elif suffix == ".java":
        for match in re.finditer(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\(", text):
            calls.append(match.group(1))
    return _unique(calls)[:40]


def _call_chain_summary(symbols: list[str], inbound: list[dict[str, Any]], outbound: list[str]) -> list[str]:
    summary = [
        f"识别到 {len(symbols)} 个本地符号、{len(inbound)} 条入站引用、{len(outbound)} 个出站调用线索。",
    ]
    if inbound:
        touched = ", ".join(item["path"] for item in inbound[:5])
        summary.append(f"可能被这些文件调用：{touched}")
    else:
        summary.append("未在扫描范围内发现明显入站引用，可能是入口文件、动态调用或暂未被使用。")
    if outbound:
        summary.append(f"主要出站调用线索：{', '.join(outbound[:8])}")
    return summary


def _assess_testability(text: str, suffix: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    score = 80
    notes: list[str] = []
    if len(text.splitlines()) > 350:
        score -= 15
        notes.append("文件较长，建议拆分后再做单元测试。")
    if re.search(r"\b(datetime|time|random|uuid|subprocess|fetch|requests|axios)\b", text, re.IGNORECASE):
        score -= 10
        notes.append("存在时间、随机、外部进程或网络调用，测试时需要注入或 mock。")
    if re.search(r"\bopen\(|read_text\(|write_text\(|sqlite3|Path\(", text):
        score -= 10
        notes.append("存在文件或数据库 I/O，建议抽象边界并使用临时目录/测试库。")
    if any(item["severity"] in {"critical", "high"} for item in findings):
        score -= 10
        notes.append("高风险规则命中会增加回归测试优先级。")
    if suffix in {".tsx", ".jsx"} and "useState" in text:
        notes.append("前端状态逻辑建议覆盖交互状态和空状态。")
    if not notes:
        notes.append("代码边界相对清晰，可从公开函数或组件行为开始补测试。")
    return {"score": max(0, min(100, score)), "notes": notes}


def _build_file_risks(
    findings: list[dict[str, Any]],
    text: str,
    dependencies: list[str],
    testability: dict[str, Any],
) -> list[str]:
    risks: list[str] = []
    if any(item["severity"] == "critical" for item in findings):
        risks.append("存在严重安全规则命中，必须优先处理后再合入。")
    if any(item["severity"] == "high" for item in findings):
        risks.append("存在高风险代码模式，需要补充修复和回归测试。")
    if len(dependencies) > 12:
        risks.append("依赖数量偏多，文件可能承担过多职责或耦合过高。")
    if len(text.splitlines()) > 500:
        risks.append("文件长度超过 500 行，职责边界和评审成本较高。")
    if testability.get("score", 100) < 65:
        risks.append("可测试性偏弱，后续修改容易缺少回归保障。")
    if not risks:
        risks.append("未发现明显高风险，但仍建议结合真实调用链做语义审查。")
    return risks


def _build_file_suggestions(
    rel_path: str,
    findings: list[dict[str, Any]],
    dependencies: list[str],
    testability: dict[str, Any],
) -> list[str]:
    suggestions = [
        "为该文件补一条文件级职责说明，明确它在项目治理中的边界。",
        "把本次文件审查结果沉淀到任务报告或 project-memory，便于后续追问。",
    ]
    if findings:
        suggestions.append("按 severity 先处理 critical/high，再处理 medium/low。")
    if len(dependencies) > 8:
        suggestions.append("梳理依赖方向，考虑把外部 I/O、工具调用或 UI 状态拆到更小模块。")
    if testability.get("score", 100) < 75:
        suggestions.append("优先补充围绕公开函数/组件行为的测试，并对 I/O 或外部调用做 mock。")
    if rel_path.lower().endswith((".tsx", ".ts", ".jsx", ".js")):
        suggestions.append("前端文件建议覆盖加载、空数据、错误和用户交互状态。")
    if rel_path.lower().endswith(".py"):
        suggestions.append("Python 文件建议覆盖异常分支、路径边界和核心纯函数。")
    return _unique(suggestions)


def _semantic_file_review(
    rel_path: str,
    text: str,
    responsibilities: list[str],
    dependencies: list[str],
    api_surface: list[str],
    call_chain: dict[str, Any],
    findings: list[dict[str, Any]],
    risks: list[str],
    testability: dict[str, Any],
) -> dict[str, Any]:
    fallback = _semantic_fallback(rel_path, responsibilities, dependencies, api_surface, call_chain, findings, risks, testability)
    prompt = {
        "file_path": rel_path,
        "responsibilities": responsibilities,
        "dependencies": dependencies[:15],
        "api_surface": api_surface[:20],
        "call_chain": call_chain,
        "rule_findings": findings[:20],
        "risks": risks,
        "testability": testability,
        "code_excerpt": text[:12000],
    }
    markdown = llm_provider.generate(
        "你是资深代码审查 Agent。请基于规则命中、调用链上下文和代码片段做语义级文件审查。不要编造未出现的事实。",
        (
            "请输出中文 Markdown，必须包含：\n"
            "1. 语义职责判断\n"
            "2. 调用链影响\n"
            "3. 隐性风险\n"
            "4. 测试建议\n"
            "5. 治理优先级\n\n"
            f"审查上下文：{prompt}"
        ),
        fallback["markdown"],
        agent="file_reviewer",
        prompt_version="file_reviewer.semantic.v1",
    )
    mode = "llm" if llm_provider.enabled and markdown != fallback["markdown"] else "deterministic_fallback"
    return {
        "mode": mode,
        "model": llm_provider.model if llm_provider.enabled else None,
        "markdown": markdown,
        "fallback_used": mode == "deterministic_fallback",
    }


def _semantic_fallback(
    rel_path: str,
    responsibilities: list[str],
    dependencies: list[str],
    api_surface: list[str],
    call_chain: dict[str, Any],
    findings: list[dict[str, Any]],
    risks: list[str],
    testability: dict[str, Any],
) -> dict[str, str]:
    impact = "中"
    if any(item.get("severity") in {"critical", "high"} for item in findings):
        impact = "高"
    elif not call_chain.get("inbound_references"):
        impact = "低到中"
    markdown = f"""### 语义审查结论

- 审查模式：确定性语义 fallback（未配置 LLM 或 LLM 调用失败）
- 文件：`{rel_path}`
- 影响面判断：{impact}
- 主要职责：{'; '.join(responsibilities[:4])}
- 调用链摘要：{'; '.join(call_chain.get('summary', [])[:3])}

### 隐性风险

- 规则命中数量：{len(findings)}
- 依赖数量：{len(dependencies)}
- 对外接口/关键函数数量：{len(api_surface)}
- 可测试性评分：{testability.get('score', 0)}/100
- 风险摘要：{'; '.join(risks[:3])}

### 测试建议

- 优先围绕公开函数、入站引用最多的符号和高风险规则命中补测试。
- 对文件 I/O、网络、时间、随机值或数据库访问使用 mock/临时资源隔离。
- 若该文件处在调用链入口，建议补充端到端或集成级回归场景。
"""
    return {"markdown": markdown}


def _file_report(
    rel_path: str,
    line_count: int,
    suffix: str,
    responsibilities: list[str],
    dependencies: list[str],
    api_surface: list[str],
    call_chain: dict[str, Any],
    findings: list[dict[str, Any]],
    risks: list[str],
    testability: dict[str, Any],
    semantic_review: dict[str, Any],
    suggestions: list[str],
) -> str:
    responsibility_text = "\n".join(f"- {item}" for item in responsibilities)
    dependency_text = "\n".join(f"- `{item}`" for item in dependencies) or "- 暂未识别显式依赖"
    api_text = "\n".join(f"- {item}" for item in api_surface) or "- 暂未识别公开函数/接口"
    call_chain_summary = "\n".join(f"- {item}" for item in call_chain.get("summary", []))
    inbound_text = "\n".join(
        f"- `{item['path']}` 引用 `{item['symbol']}`" for item in call_chain.get("inbound_references", [])[:20]
    ) or "- 暂未发现明显入站引用"
    outbound_text = "\n".join(f"- `{item}`" for item in call_chain.get("outbound_calls", [])[:20]) or "- 暂未识别明显出站调用"
    finding_text = "\n".join(
        f"- [{item['severity']}] `{item['path']}:{item['line']}` {item['message']}"
        for item in findings[:30]
    ) or "- 暂未发现规则命中的问题"
    risk_text = "\n".join(f"- {item}" for item in risks)
    test_notes = "\n".join(f"- {item}" for item in testability.get("notes", []))
    suggestion_text = "\n".join(f"- {item}" for item in suggestions)
    return f"""# 文件级审查报告：{rel_path}

## 文件概览

- 文件类型：`{suffix}`
- 行数：{line_count}
- 可测试性评分：{testability.get('score', 0)}/100

## 职责判断

{responsibility_text}

## 依赖线索

{dependency_text}

## 对外接口 / 关键函数

{api_text}

## 调用链上下文

{call_chain_summary}

### 入站引用

{inbound_text}

### 出站调用

{outbound_text}

## 风险与规则命中

{finding_text}

## 风险判断

{risk_text}

## 可测试性

{test_notes}

## LLM / 语义审查

{semantic_review.get('markdown', '')}

## 治理建议

{suggestion_text}
"""


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _finding(category: str, severity: str, path: str, line: int, message: str) -> dict[str, Any]:
    return {"category": category, "severity": severity, "path": path, "line": line, "message": message}


def _build_risks(findings: list[dict[str, Any]], scan: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    if any(item["severity"] == "critical" for item in findings):
        risks.append("存在严重安全风险，需要优先处理硬编码密钥或敏感信息。")
    if any(item["category"] == "security" for item in findings):
        risks.append("检测到安全相关问题，建议进行专项安全审查。")
    if any(item["category"] == "reliability" for item in findings):
        risks.append("异常处理存在改进空间，可能影响线上排障和稳定性。")
    if not any("test" in file["path"].lower() for file in scan["files"]):
        risks.append("未明显发现测试目录或测试文件，回归保障不足。")
    if not risks:
        risks.append("未发现明显高风险问题，建议接入 LLM 做语义级审查。")
    return risks


def _build_suggestions(findings: list[dict[str, Any]], scan: dict[str, Any]) -> list[str]:
    fallback_suggestions = [
        "为审查结果建立 severity 分级处理流程。",
        "把关键规则沉淀为 CI 检查，避免问题反复出现。",
    ]
    if not any("test" in file["path"].lower() for file in scan["files"]):
        fallback_suggestions.append("补充单元测试或集成测试，并在报告中展示测试覆盖情况。")
    if any(item["category"] == "database" for item in findings):
        fallback_suggestions.append("对 SQL 访问层增加参数化查询、分页和字段白名单检查。")
    fallback = "\n".join(f"- {item}" for item in fallback_suggestions)
    text = llm_provider.generate(
        "你是 ValuSee 的代码审查修复建议 Agent。规则命中由确定性扫描给出，你只负责生成修复建议、测试建议和治理优先级。",
        (
            "请输出 3-7 条中文 bullet。不要新增不存在的问题，不要编造文件内容。\n"
            f"项目：{scan.get('project_name')}\n"
            f"文件数量：{len(scan.get('files', []))}\n"
            f"关键文件：{scan.get('key_files', [])[:20]}\n"
            f"规则命中：{findings[:30]}"
        ),
        fallback,
        agent="code_reviewer",
        prompt_version="code_reviewer.suggestions.v1",
    )
    suggestions = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
    return suggestions or fallback_suggestions


def _build_suggestion_records(
    findings: list[dict[str, Any]],
    suggestions: list[str],
    scan: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, finding in enumerate(findings[:30], 1):
        category = str(finding.get("category") or "quality")
        severity = str(finding.get("severity") or "medium")
        path = str(finding.get("path") or "")
        line = finding.get("line")
        records.append(
            {
                "id": f"finding-{index}",
                "finding": finding,
                "risk_level": _risk_from_severity(severity),
                "action": _action_for_finding(category, severity),
                "test_case": _test_case_for_finding(category, path),
                "review_required": severity in {"critical", "high"},
                "next_actions": [
                    f"Inspect {path}:{line} and confirm the rule hit.",
                    "Apply the smallest safe fix around the finding.",
                    "Add or update the suggested regression test.",
                ],
            }
        )
    if records:
        return records
    if not any("test" in file["path"].lower() for file in scan.get("files", [])):
        return [
            {
                "id": "test-coverage-baseline",
                "finding": None,
                "risk_level": "medium",
                "action": "建立项目级测试基线，至少覆盖核心 API/Workflow/RAG 流程。",
                "test_case": "新增 smoke/integration 测试：运行一次任务，断言事件、报告、Agent 输出和状态持久化均生成。",
                "review_required": False,
                "next_actions": ["Select the critical user journey.", "Add one smoke test.", "Wire it into CI."],
            }
        ]
    return [
        {
            "id": "governance-baseline",
            "finding": None,
            "risk_level": "low",
            "action": suggestions[0] if suggestions else "保留当前治理基线，并持续沉淀审查规则。",
            "test_case": "保持现有测试可运行，并为新 Agent/Workflow 行为补充回归用例。",
            "review_required": False,
            "next_actions": suggestions[:3] or ["Keep current checks green."],
        }
    ]


def _risk_from_severity(severity: str) -> str:
    if severity == "critical":
        return "critical"
    if severity == "high":
        return "high"
    if severity == "medium":
        return "medium"
    return "low"


def _action_for_finding(category: str, severity: str) -> str:
    if category == "security":
        return "优先消除安全风险，禁止带入发布流程。"
    if category == "reliability":
        return "收敛异常处理和日志路径，确保线上可诊断。"
    if category == "database":
        return "改为显式字段、参数化查询和边界校验。"
    if severity in {"critical", "high"}:
        return "先修复高风险命中，再进入人工复核。"
    return "纳入常规重构队列，并用测试锁定行为。"


def _test_case_for_finding(category: str, path: str) -> str:
    if category == "security":
        return f"为 `{path}` 增加恶意输入/敏感信息扫描回归测试，断言不会泄露或拼接危险数据。"
    if category == "reliability":
        return f"为 `{path}` 增加异常分支测试，断言错误被统一记录并返回可控结果。"
    if category == "database":
        return f"为 `{path}` 增加 SQL 参数边界测试，断言字段白名单、分页和参数化行为。"
    return f"为 `{path}` 增加行为回归测试，覆盖正常路径、空数据和错误输入。"


def _score(findings: list[dict[str, Any]], scan: dict[str, Any]) -> int:
    score = 90
    penalty = {"critical": 20, "high": 10, "medium": 4, "low": 1}
    for item in findings[:50]:
        score -= penalty.get(item["severity"], 2)
    if not any("test" in file["path"].lower() for file in scan["files"]):
        score -= 8
    return max(0, min(100, score))


def _report(scan: dict[str, Any], findings: list[dict[str, Any]], risks: list[str], suggestions: list[str], score: int) -> str:
    finding_text = "\n".join(
        f"- [{item['severity']}] `{item['path']}:{item['line']}` {item['message']}"
        for item in findings[:40]
    ) or "- 暂未发现规则命中的问题"
    risk_text = "\n".join(f"- {item}" for item in risks)
    suggestion_text = "\n".join(f"- {item}" for item in suggestions)
    return f"""# {scan['project_name']} 代码审查报告

## 概览

- 审查文件数：{len(scan['files'])}
- 问题数量：{len(findings)}
- 质量评分：{score}/100

## 问题清单

{finding_text}

## 风险判断

{risk_text}

## 修改建议

{suggestion_text}
"""
