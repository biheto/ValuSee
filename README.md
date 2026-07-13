# DevAgent Studio

[English](#english) | [中文](#中文)

<a id="english"></a>

DevAgent Studio is an open-source multi-agent workbench for **software project understanding and engineering governance**. It is built with FastAPI, LangGraph, and React to help teams inspect project structure, review code risks, preserve project knowledge, govern AI and tool calls, and run traceable workflows.

It is deliberately not a code-writing IDE. Its focus is making software delivery work easier to understand, audit, evaluate, and improve.

![DevAgent Studio architecture](docs/assets/architecture.png)

## Why DevAgent Studio

- **Multi-agent workflows, not isolated prompts**: Planner, Project Analyzer, Code Reviewer, RAG Processor, Supervisor, and Reporter are composed through LangGraph.
- **Governed runtime**: Harness Runtime provides task context, event timelines, artifacts, review state, persistence, deterministic policy checks, and resume support.
- **Visual workflows that execute**: a drag-and-drop canvas is compiled into executable LangGraph workflows instead of serving as a static diagram.
- **Observable LLM operations**: prompt versions, model configuration, traces, token and cost data, fallback records, and A/B comparison are available from the UI.
- **Extensible Skills with guardrails**: Skills are versioned, permission-scoped, testable, dependency-aware, and usable from both the console and a workflow.
- **Plugin Marketplace**: install resource packs from built-in catalogs, local paths, URLs, GitHub-style sources, or an external `SKILL.md` file.
- **Safe third-party code execution**: Code Skills can run in a constrained Docker sandbox with no network, read-only mounts, resource limits, and audit logs.

## Product Preview

| Run workbench | Visual workflow |
| --- | --- |
| ![Run workbench](docs/assets/run-preview.png) | ![Visual workflow](docs/assets/workflow-preview.png) |

| Skills console | Plugin Marketplace |
| --- | --- |
| ![Skills console](docs/assets/skill-preview.png) | ![Plugin Marketplace](docs/assets/market-preview.png) |

| LLM console | Benchmark dashboard |
| --- | --- |
| ![LLM console](docs/assets/llm-console-preview.png) | ![Benchmark dashboard](docs/assets/benchmark-dashboard-preview.png) |

## Architecture

```text
User / React workbench
        |
        v
FastAPI APIs ---- Marketplace ---- Skills Console ---- MCP Console
        |
        v
Harness Runtime
  context | policy | events | artifacts | human review | persistence
        |
        +-----------------------+
        |                       |
        v                       v
LangGraph workflows          Skill Runtime
planner / reviewer /         prompt skills / code skills /
RAG / supervisor / reporter  dependency and permission checks
        |                       |
        +-----------+-----------+
                    v
      LLM / MCP / RAG / SQLite / pgvector / Docker sandbox
```

### Typical execution flow

```text
Task request
  -> FastAPI creates a task
  -> Harness Runtime creates context and emits events
  -> LangGraph invokes agents, Skills, LLMs, RAG, or MCP tools
  -> policy and human-review checks gate sensitive operations
  -> traces, artifacts, logs, and state are persisted
  -> Reporter produces a governance report
```

## Core Capabilities

| Area | What it provides |
| --- | --- |
| Project analysis | Structure scanning, technology identification, module summary, risks, and governance suggestions. |
| Code review | Hybrid rule, call-chain, and LLM semantic review with findings and test recommendations. |
| RAG knowledge | Document chunking, ingestion, retrieval, project notes, SQLite default storage, and optional pgvector retrieval. |
| Learning coach | Project-oriented learning plans and interactive follow-up questions. |
| Collaboration | Planner, analyzer, reviewer, RAG, supervisor, and reporter run as a traceable collaboration graph. |
| Workflow | Drag, connect, configure, validate, save, and execute workflow JSON compiled to LangGraph. |
| Human review | Node-level approval/rejection, checkpoint/resume, retry, and recovery visualization. |
| LLM governance | Per-agent model configuration, call trace, prompt versions, token/cost data, fallback display, and A/B tests. |
| MCP management | Server registration, stdio tool discovery, enable/disable, approval, test invocation, and call logs. |
| Benchmark | LLM, RAG, Workflow, MCP, and multi-agent evaluation with success rate, P95 latency, recall, completeness, token, and cost metrics. |

## Governed Skill Plugin System

A Skill is a reusable capability such as code review, RAG processing, learning coaching, security scanning, or workflow execution. A Skill can be tested in the Skills console or added to a visual workflow.

### Skill governance

| Capability | Purpose |
| --- | --- |
| Contract validation | Validates `input_schema`, `output_schema`, `permissions`, and `execution_type` during package preview and install. |
| Permission levels | Classifies access as `safe`, `project-read`, `llm`, `workflow-write`, `network`, or `filesystem`, and calculates risk. |
| Strict approvals | Approval is scoped by `skill_code + agent_code`; testing and workflow execution are independently approved. |
| Version management | Keeps Skill snapshots for upgrade comparison and rollback. |
| Dependencies | Declares MCP tools, RAG collections, prompt versions, and model requirements before execution. |
| Built-in tests | Allows packages to provide test cases and lets users run them after installation. |
| Trust metadata | Records source URL, author, manifest signature verification, install count, and local validation state. |
| Workflow mapping | Maps outputs from earlier workflow nodes into a Skill node input. |

### Prompt Skill and Code Skill

An external `SKILL.md` is imported as a **Prompt Skill** when there is no `plugin.json`. The system reads its instruction text and uses it as an LLM prompt. It never executes third-party code.

A **Code Skill** contains an executable entry point, for example:

```text
plugin/
  plugin.json
  skills/
    security_scan.py
```

```json
{
  "code": "security.scan",
  "execution_type": "python",
  "entrypoint": "skills/security_scan.py:run",
  "permissions": ["project-read"]
}
```

### Docker sandbox for Code Skills

Code Skills can use a Docker sandbox. The runtime starts a temporary container and removes it when execution ends. The sandbox applies:

- `--network none`: no outbound network access.
- `--read-only`: immutable container root filesystem.
- read-only mount for the Skill package.
- memory, CPU, PID, and execution-time limits.
- dropped Linux capabilities and `no-new-privileges`.
- invocation result and failure logging.

This makes third-party extensions practical without treating them as trusted local code. Docker isolation is a defense layer, not a substitute for reviewing plugin source and permissions.

## Plugin Marketplace

The Marketplace installs and tracks resource packages. Supported package types include `skill_pack`, `rag_pack`, `mcp_pack`, `prompt_pack`, `workflow_pack`, and `benchmark_pack`.

Supported sources:

- Built-in catalog packages.
- Local folders or a local `plugin.json`.
- URL and GitHub-style package sources.
- External `SKILL.md` files, automatically converted to a safe Prompt Skill.

After installation, the UI shows installed resources, source and trust details, available Skills, approval actions, test calls, workflow insertion, and uninstall status.

### Strict approval model

```text
approval key = skill_code + agent_code
```

The two common execution identities are:

| Agent code | Meaning |
| --- | --- |
| `skill_console` | Manual test call from the Skills page. |
| `workflow_runner` | Automatic call from a visual workflow. |

Approving `skill_console` does not approve `workflow_runner`. A Skill must be explicitly approved for the context in which it will run.

## Quick Start

### Requirements

- Python 3.11+ (Python 3.13 is supported by the current project setup)
- Node.js 18+
- Docker Desktop, optional for pgvector and Docker Code Skill sandboxing

### Install

```powershell
git clone https://github.com/biheto/DevAgent-Studio.git
cd DevAgent-Studio

python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[llm,vector,dev]"

cd web
npm install
npm run build
cd ..

copy .env.example .env
```

### Start the application

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Open `http://127.0.0.1:8100/` for the workbench and `http://127.0.0.1:8100/docs` for the API documentation.

### Optional services

Run pgvector:

```powershell
docker compose -f docker-compose.pgvector.yml up -d
```

Configure Docker Code Skill sandboxing in `.env`:

```env
DEV_AGENT_SKILL_SANDBOX=docker
DEV_AGENT_SKILL_SANDBOX_IMAGE=python:3.13-slim
DEV_AGENT_SKILL_SANDBOX_MEMORY=256m
DEV_AGENT_SKILL_SANDBOX_CPUS=0.5
DEV_AGENT_SKILL_SANDBOX_PIDS_LIMIT=64
DEV_AGENT_SKILL_SANDBOX_FALLBACK=false
```

`subprocess` is the default sandbox mode for local development. `docker` requires Docker Desktop to be running. The sandbox status can be checked at `GET /api/v1/skills/sandbox/status`.

### LLM configuration

The application works with deterministic fallback responses when no key is configured. Set an API key for real LLM calls:

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=
DEV_AGENT_LLM_MODEL=gpt-4o-mini

# Optional per-agent overrides
DEV_AGENT_LLM_MODEL_PLANNER=gpt-4o-mini
DEV_AGENT_LLM_MODEL_REPORTER=gpt-4o-mini
DEV_AGENT_LLM_MODEL_CODE_REVIEWER=gpt-4o-mini
```

## Development Checks

```powershell
# Backend compilation
.\.venv\Scripts\python.exe -m compileall -q app

# Frontend production build
cd web
npm run build
cd ..

# Verify the Skill sandbox configuration
.\.venv\Scripts\python.exe -c "from app.skills.sandbox import python_skill_sandbox_status; print(python_skill_sandbox_status())"
```

## Project Structure

```text
DevAgent Studio/
  app/
    agents/              # Project, review, RAG, learning, and report logic
    api/                 # FastAPI route modules
    graphs/              # LangGraph graphs and visual workflow compiler
    harness/             # Context, events, policy, artifacts, review/resume runtime
    marketplace/         # Package preview, installer, trust, and SKILL.md compatibility
    persistence/         # Task, governance, RAG, and trace persistence
    providers/           # LLM, MCP, and RAG provider interfaces
    skills/              # Registry, contracts, versions, dependencies, sandbox runtime
    benchmark_runner.py  # LLM/RAG/Workflow/MCP/collaboration benchmarks
  web/                   # React workbench
  scripts/               # MCP launchers and test servers
  docs/                  # Architecture and implementation notes
  examples/              # API request examples
  docker-compose.pgvector.yml
```

## Documentation

- [Implementation timeline](docs/IMPLEMENTATION_TIMELINE.md)
- [Workflow production notes](docs/PHASE_8_WORKFLOW_PRODUCTION.md)

## Roadmap

- Add a richer UI for Docker sandbox health and test invocation.
- Add signed external plugin publishing examples and contributor tooling.
- Expand API, workflow compiler, runtime-state, MCP contract, RAG retrieval, LLM fallback, and benchmark test coverage.
- Add conditional branch, parallel node, and richer input/output mapping UX for workflows.

## License and Attribution

This project is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 biheto. When redistributing the project, preserve the original copyright notice and license text.

```text
DevAgent Studio by biheto
https://github.com/biheto/DevAgent-Studio
```

---

<a id="中文"></a>

# DevAgent Studio 中文说明

DevAgent Studio 是一个面向**软件项目理解与研发治理**的开源多 Agent 工作台。项目基于 FastAPI、LangGraph 和 React 构建，用于帮助团队理解项目结构、识别代码风险、沉淀项目知识、治理 LLM 与工具调用，并执行可追踪的研发工作流。

它不是代码编写 IDE，核心目标是让研发过程更容易理解、审计、评估和持续改进。

## 项目亮点

- **多 Agent 协作而非单次 Prompt**：通过 LangGraph 编排 Planner、项目分析、代码审查、RAG、监督和报告节点。
- **Harness Runtime 运行时治理**：统一任务上下文、事件时间线、产物、策略、人工审核、持久化与恢复执行。
- **真正可执行的可视化 Workflow**：前端拖拽画布会编译成 LangGraph 工作流执行，而不只是展示图。
- **LLM 可观测与可治理**：可查看 Prompt 版本、调用 Trace、token/cost、fallback、A/B Test，以及按 Agent 配置模型。
- **安全可治理的 Skill 插件体系**：Skill 有契约校验、权限分级、严格审批、版本快照、依赖检测、测试用例和执行日志。
- **插件市场与外部兼容**：支持内置包、本地路径、URL、GitHub 风格来源，以及外部 `SKILL.md` 自动转换。
- **Docker 代码型 Skill 沙箱**：第三方代码可以在禁网、只读、限时限资源的临时容器中运行。

## 核心能力

| 模块 | 能力 |
| --- | --- |
| 项目分析 | 扫描目录、识别技术栈、归纳模块职责、风险和治理建议。 |
| 代码审查 | 结合规则、调用链与 LLM 语义审查，输出问题和测试建议。 |
| RAG 知识加工 | 文档切片、入库、检索、项目笔记；默认 SQLite，可选 pgvector。 |
| 学习陪练 | 基于项目上下文生成学习计划和追问。 |
| 多 Agent 协作 | Planner、Analyzer、Reviewer、RAG、Supervisor、Reporter 组成协作图。 |
| Workflow | 拖拽、连线、配置、校验、保存并执行 Workflow JSON。 |
| 人工审核 | 支持节点级通过/拒绝、checkpoint/resume、重试与恢复事件展示。 |
| MCP | 支持 Server 配置、工具发现、启停、审批、测试调用和日志追踪。 |
| Benchmark | 覆盖 LLM、RAG、Workflow、MCP、多 Agent 协作的指标评估。 |

## Skill 插件体系

Skill 是可复用能力，例如代码审查、RAG 加工、学习陪练、安全扫描或 Workflow 执行。它可以在 Skills 页面单独测试，也可以加入可视化 Workflow。

已实现的治理能力：

- **契约校验**：安装和预览时校验 `input_schema`、`output_schema`、`permissions`、`execution_type`，避免格式错误的包进入运行时。
- **权限风险分级**：使用 `safe`、`project-read`、`llm`、`workflow-write`、`network`、`filesystem` 标识访问能力和风险级别。
- **严格审批**：审批键为 `skill_code + agent_code`。手动测试和工作流执行分别审批，互不放行。
- **版本与回滚**：安装升级会保留版本快照，可对比和回滚。
- **依赖声明**：Skill 可声明依赖的 MCP 工具、RAG collection、Prompt 版本和 LLM 模型，运行前会检查缺失项。
- **测试用例**：插件包可携带测试用例，安装后可一键运行并记录结果。
- **可信来源**：记录来源 URL、作者、manifest SHA-256 签名校验、安装次数和本地校验状态。
- **Workflow 输入输出映射**：前序节点输出可映射到 Skill 节点输入，让 Skill 参与复杂工作流。

### Prompt Skill 与代码型 Skill

如果外部来源没有 `plugin.json`，但包含 `SKILL.md`，系统会将其识别为 **Prompt Skill**：只读取其中的指令文本并交给 LLM，不执行第三方代码。

**代码型 Skill** 则带有可执行入口，例如 Python 文件。它能力更强，但必须通过权限审批和沙箱限制后执行。

### Docker 沙箱

当 `.env` 中设置 `DEV_AGENT_SKILL_SANDBOX=docker` 后，代码型 Skill 会在临时 Docker 容器中执行，并使用以下限制：

- 禁止网络访问。
- 容器根文件系统只读，Skill 包只读挂载。
- 限制内存、CPU、进程数和执行超时。
- 移除 Linux capabilities，禁止提升权限。
- 执行结束自动删除容器，同时保留调用结果和失败日志。

Docker 沙箱是隔离层，不代表插件天然可信。安装前仍应检查来源、manifest、权限和代码内容。

## 插件市场

Marketplace 支持安装和管理 `skill_pack`、`rag_pack`、`mcp_pack`、`prompt_pack`、`workflow_pack`、`benchmark_pack` 等资源包。

支持的来源：内置资源包、本地目录或 `plugin.json`、URL/GitHub 风格地址，以及外部 `SKILL.md`。安装后可查看已安装资源、来源与信任信息、Skill 列表、权限审批、测试调用、添加到 Workflow 和卸载状态。

### 审批如何隔离

```text
审批键 = skill_code + agent_code
```

| Agent code | 使用场景 |
| --- | --- |
| `skill_console` | 在 Skills 页面手动点击测试调用。 |
| `workflow_runner` | 在可视化 Workflow 中自动执行。 |

因此，批准 `skill_console` 不等于批准 `workflow_runner`。Skill 必须在实际运行身份下单独获得批准。

## 快速启动

环境要求：Python 3.11+（当前项目支持 Python 3.13）、Node.js 18+；如需 pgvector 或 Docker 沙箱，还需要 Docker Desktop。

```powershell
git clone https://github.com/biheto/DevAgent-Studio.git
cd DevAgent-Studio

python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[llm,vector,dev]"

cd web
npm install
npm run build
cd ..

copy .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

打开 `http://127.0.0.1:8100/` 使用工作台，打开 `http://127.0.0.1:8100/docs` 查看 API 文档。

可选配置：

```env
# LLM
OPENAI_API_KEY=your_api_key
DEV_AGENT_LLM_MODEL=gpt-4o-mini

# pgvector RAG
DEV_AGENT_RAG_STORE=pgvector
PGVECTOR_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dev_agent_studio

# Docker 代码型 Skill 沙箱
DEV_AGENT_SKILL_SANDBOX=docker
DEV_AGENT_SKILL_SANDBOX_IMAGE=python:3.13-slim
DEV_AGENT_SKILL_SANDBOX_MEMORY=256m
DEV_AGENT_SKILL_SANDBOX_CPUS=0.5
DEV_AGENT_SKILL_SANDBOX_PIDS_LIMIT=64
DEV_AGENT_SKILL_SANDBOX_FALLBACK=false
```

启动 pgvector：

```powershell
docker compose -f docker-compose.pgvector.yml up -d
```

可通过 `GET /api/v1/skills/sandbox/status` 查看 Skill 沙箱配置状态。

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m compileall -q app

cd web
npm run build
cd ..

.\.venv\Scripts\python.exe -c "from app.skills.sandbox import python_skill_sandbox_status; print(python_skill_sandbox_status())"
```

## 项目结构

```text
DevAgent Studio/
  app/
    agents/              # 项目分析、代码审查、RAG、学习、报告逻辑
    api/                 # FastAPI 路由
    graphs/              # LangGraph 图与 Workflow 编译器
    harness/             # 上下文、事件、策略、产物、审核/恢复运行时
    marketplace/         # 资源包预览、安装、可信信息、SKILL.md 兼容层
    persistence/         # 任务、治理、RAG、Trace 持久化
    providers/           # LLM、MCP、RAG Provider
    skills/              # Registry、契约、版本、依赖、沙箱运行时
  web/                   # React 工作台
  scripts/               # MCP 启动和测试脚本
  docs/                  # 设计和实现说明
```

## 后续计划

- 增加 Docker 沙箱状态和测试调用的前端可视化。
- 增加外部签名插件发布示例和贡献工具。
- 补齐 API、Workflow 编译、Harness 状态、MCP 契约、RAG 命中、LLM fallback 和 Benchmark 的自动化测试。
- 增强 Workflow 条件分支、并行节点和输入输出映射交互。

## License / 引用

项目使用 [MIT License](LICENSE)。分发或修改时请保留原版权和许可证文本。

```text
DevAgent Studio by biheto
https://github.com/biheto/DevAgent-Studio
```
