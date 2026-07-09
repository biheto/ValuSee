# DevAgent Studio

**DevAgent Studio** is a multi-agent workbench for software project understanding and engineering governance. It uses **FastAPI + LangGraph + React** to orchestrate project analysis, code review, RAG knowledge processing, learning coaching, MCP tools, visual workflows, human review, LLM governance, and benchmark evaluation.

**DevAgent Studio** 是一个面向软件项目理解与研发治理的多 Agent 工作台。项目基于 **FastAPI + LangGraph + React**，用于编排项目分析、代码审查、RAG 知识加工、学习陪练、MCP 工具、可视化 Workflow、人工审核、LLM 治理和 Benchmark 评测。

> This is not a code-writing IDE. It focuses on project understanding, traceable agent workflows, risk discovery, knowledge preservation, and evaluation.
>
> 它不是代码编写平台，而是面向项目理解、流程追踪、风险识别、知识沉淀和评测治理的 Agent 工作台。

## Preview / 页面预览

### Run Workbench / 运行工作台

![Run Workbench](docs/assets/run-preview.png)

### Visual Workflow / 可视化 Workflow

![Visual Workflow](docs/assets/workflow-preview.png)

### Interactive Chat / 项目追问

![Interactive Chat](docs/assets/chat-preview.png)

### LLM Console / LLM 控制台

![LLM Console](docs/assets/llm-console-preview.png)

### MCP Console / MCP 管理台

![MCP Console](docs/assets/mcp-console-preview.png)

### Benchmark Dashboard / Benchmark 评测面板

![Benchmark Dashboard](docs/assets/benchmark-dashboard-preview.png)

### Architecture / 架构图

![Architecture](docs/assets/architecture.png)

## Highlights / 项目亮点

- **LangGraph orchestration**: project analyzer, code reviewer, RAG processor, supervisor, reporter, and collaboration graph.
- **Visual workflow execution**: drag-and-drop workflow canvas compiled into executable LangGraph workflows.
- **Harness Runtime**: deterministic runtime wrapper with task events, artifacts, persistence, and review flow.
- **LLM governance**: prompt versions, LLM call traces, token/cost dashboard, prompt A/B testing, and per-agent model config.
- **RAG persistence**: SQLite keyword retrieval by default, optional PostgreSQL + pgvector semantic retrieval.
- **Real MCP client**: stdio MCP server configuration, tool discovery, approval, enable/disable, call logs, and workflow tool nodes.
- **Benchmark suite**: MCP, LLM, RAG, Workflow, and multi-agent collaboration benchmark runners.
- **Human-in-the-loop**: node-level review, approval/rejection, resume visualization, and governance suggestions.

中文概览：

- **LangGraph 编排**：项目分析、代码审查、RAG 加工、监督、报告和多 Agent 协作。
- **可视化 Workflow**：拖拽画布可以编译为真实 LangGraph 工作流执行。
- **Harness Runtime**：统一任务运行、事件、产物、持久化和人工审核流程。
- **LLM 治理**：Prompt 版本、调用 Trace、token/cost 看板、A/B Test、不同 Agent 模型配置。
- **RAG 持久化**：默认 SQLite 关键词检索，可切换 PostgreSQL + pgvector 向量检索。
- **真实 MCP Client**：MCP Server 配置、Discover、审批、启停、调用日志和 Workflow Tool 节点。
- **Benchmark 体系**：覆盖 MCP、LLM、RAG、Workflow、多 Agent 协作评测。
- **人工审核闭环**：节点级审核、拒绝/通过、resume 可视化和治理建议。

## What Can It Do? / 能做什么

| Area | Capability | API / UI |
| --- | --- | --- |
| Project Analysis | Scan structure, stack, modules, risks, suggestions | `POST /api/v1/projects/analyze` |
| Code Review | Rule + call-chain + semantic review, suggestions, test ideas | `POST /api/v1/code/review` |
| RAG Knowledge | Process, ingest, retrieve, and save project notes | `/api/v1/rag/*` |
| Learning Coach | Generate learning plans and interactive follow-up questions | `/api/v1/learning/*` |
| Workflow | Compile visual workflow JSON into LangGraph execution | `/api/v1/workflows/*` |
| Collaboration | Run planner, analyzer, reviewer, RAG, supervisor, reporter | `/api/v1/tasks/collaborate` |
| LLM Console | Trace calls, manage prompts, compare prompt versions | UI: `LLM` |
| MCP Console | Register MCP servers, discover tools, approve calls, view logs | UI: `MCP` |
| Benchmark | Evaluate MCP, LLM, RAG, Workflow, Collaboration quality | UI: `Bench` |

## Core Components / 核心组件

DevAgent Studio is built as a clean multi-agent workbench with explicit runtime boundaries. Agents are not only prompt wrappers; each capability is exposed through a reusable Skill, executed through a governed Harness Runtime, and then composed by LangGraph workflows.

DevAgent Studio 按“可复用能力 + 可治理运行时 + 可编排图”的方式组织。Agent 不只是 prompt 封装，每个能力都通过 Skill 暴露，再由 Harness Runtime 统一执行，最后交给 LangGraph 工作流编排。

| Component | Role | Implementation |
| --- | --- | --- |
| Skill | Encapsulates a reusable agent capability such as code review, RAG processing, learning coaching, or workflow execution. | `app/skills/base.py`, `app/skills/builtin.py`, `app/skills/registry.py` |
| Harness Runtime | Adds deterministic execution control around skills and agents, including task context, event emission, artifacts, policy checks, and human review state. | `app/harness/runtime.py`, `app/harness/context.py`, `app/harness/events.py`, `app/harness/policy.py` |
| LangGraph Workflows | Composes skills, agents, tools, review nodes, and reporter nodes into executable graphs. | `app/graphs/studio_graphs.py`, `app/graphs/workflow_compiler.py` |
| Providers | Connects external capabilities such as LLM, MCP tools, and RAG storage behind stable provider interfaces. | `app/providers/`, `app/persistence/` |

Typical execution flow:

```text
User task
  -> FastAPI task API
  -> Harness Runtime creates execution context
  -> Skill or LangGraph node runs deterministic/LLM/tool logic
  -> events, artifacts, traces and review state are persisted
  -> Reporter produces final governance report
```

典型执行链路：

```text
用户任务
  -> FastAPI 任务接口
  -> Harness Runtime 创建执行上下文
  -> Skill 或 LangGraph 节点运行规则、LLM 或工具逻辑
  -> 持久化事件、产物、Trace 和人工审核状态
  -> Reporter 生成最终治理报告
```

## Quick Start / 快速启动

### 1. Clone and enter the project / 克隆项目

```powershell
git clone https://github.com/biheto/DevAgent-Studio.git
cd DevAgent-Studio
```

### 2. Create Python environment / 创建 Python 环境

Python 3.11+ is recommended. Python 3.13 is also supported by the current local setup.

推荐 Python 3.11+，当前项目也可以在 Python 3.13 下运行。

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

Optional extras:

```powershell
# LLM support
pip install -e ".[llm]"

# pgvector RAG support
pip install -e ".[vector]"

# development tools
pip install -e ".[dev]"
```

### 3. Install frontend dependencies / 安装前端依赖

```powershell
cd web
npm install
npm run build
cd ..
```

### 4. Start backend / 启动后端

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Open:

```text
http://127.0.0.1:8100/
http://127.0.0.1:8100/docs
```

### One-command Windows setup / Windows 一键启动

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\setup-and-start.ps1
```

The script installs dependencies, builds the frontend, and starts the backend on port `8100`.

该脚本会安装依赖、构建前端，并在 `8100` 端口启动后端。

## Configuration / 配置

Copy the example environment file:

复制示例配置：

```powershell
copy .env.example .env
```

### LLM

Without an API key, the system still works in fallback mode. With an API key, Planner, Reporter, Supervisor, Code Review, Learning Coach, task Q&A, and Benchmark can use real LLM calls.

没有 API Key 时系统会走 fallback；配置 API Key 后，Planner、Reporter、Supervisor、代码审查、学习陪练、任务追问和 Benchmark 会调用真实 LLM。

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=
DEV_AGENT_LLM_MODEL=gpt-4o-mini
```

Per-agent model override:

```env
DEV_AGENT_LLM_MODEL_PLANNER=gpt-4o-mini
DEV_AGENT_LLM_MODEL_REPORTER=gpt-4o-mini
DEV_AGENT_LLM_MODEL_CODE_REVIEWER=gpt-4o-mini
```

### RAG Store

Default:

```env
DEV_AGENT_RAG_STORE=sqlite
```

pgvector:

```env
DEV_AGENT_RAG_STORE=pgvector
PGVECTOR_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dev_agent_studio
```

Start pgvector:

```powershell
docker compose -f docker-compose.pgvector.yml up -d
```

### MCP Provider

Local deterministic provider:

```env
DEV_AGENT_MCP_PROVIDER=local
```

Real MCP provider:

```env
DEV_AGENT_MCP_PROVIDER=mcp
```

Built-in stdio MCP examples:

```text
scripts/launch_mcp_filesystem.py
scripts/launch_mcp_memory.py
scripts/fake_mcp_server.py
```

## Benchmark / 评测体系

DevAgent Studio includes an internal benchmark suite.

DevAgent Studio 内置 Benchmark 评测体系。

| Benchmark | What It Evaluates | Key Metrics |
| --- | --- | --- |
| MCP Benchmark | Tool stability and approval correctness | success rate, latency, P95, failures |
| LLM Benchmark | Prompt/model response quality | quality score, tokens, estimated cost, fallback |
| RAG Benchmark | Retrieval quality | hit rate, source quality, result count |
| Workflow Benchmark | Workflow runtime reliability | success rate, failed nodes, latency |
| Collaboration Benchmark | Multi-agent report quality | completeness, risk score, human review trigger |

API examples:

```text
POST /api/v1/benchmarks/mcp/run
POST /api/v1/benchmarks/llm/run
POST /api/v1/benchmarks/rag/run
POST /api/v1/benchmarks/workflow/run
POST /api/v1/benchmarks/collaboration/run
GET  /api/v1/benchmarks
GET  /api/v1/benchmarks/{run_id}
```

P95 means the 95th percentile latency. It is useful because average latency can hide long-tail slow runs.

P95 表示 95 分位延迟，比平均值更能反映长尾慢请求。

## Project Structure / 项目结构

```text
DevAgent Studio/
  app/
    agents/              # Project, code review, RAG, learning, workflow helpers
    api/                 # FastAPI routes
    graphs/              # LangGraph workflows and workflow compiler
    harness/             # Runtime context, events, policy, execution wrapper
    persistence/         # SQLite task store and RAG stores
    providers/           # LLM and MCP providers
    schemas/             # Pydantic schemas
    skills/              # Skill abstraction and registry
    benchmark_runner.py  # MCP/LLM/RAG/Workflow/Collaboration benchmarks
    main.py              # FastAPI app entry
  web/
    src/                 # React workbench
    package.json
  scripts/               # MCP server launchers and fake MCP server
  docs/                  # Design docs and implementation timeline
  examples/              # Example API payloads
  docker-compose.pgvector.yml
  pyproject.toml
  README.md
```

## Main Pages / 主要页面

- **Run**: run Agent, Planner, Workflow, Tool, Knowledge, or Collaboration mode.
- **Workflow**: drag and arrange workflow nodes, validate and execute.
- **Reports**: final report, governance suggestions, Mermaid graph.
- **Chat**: task Q&A, knowledge query, learning coach.
- **History**: replay task records and artifacts.
- **LLM**: traces, prompt versions, token/cost dashboard, A/B tests.
- **MCP**: server config, tool discovery, approval, test call logs.
- **Bench**: MCP/LLM/RAG/Workflow/Collaboration benchmark dashboard.

中文：

- **Run**：运行 Agent、Planner、Workflow、Tool、Knowledge、Collaboration 模式。
- **Workflow**：拖拽编排节点，校验并执行。
- **Reports**：查看最终报告、治理建议和 Mermaid 图。
- **Chat**：任务追问、知识库问答、学习陪练。
- **History**：历史任务回放。
- **LLM**：Trace、Prompt 版本、token/cost、A/B Test。
- **MCP**：Server 配置、工具发现、审批和调用日志。
- **Bench**：MCP、LLM、RAG、Workflow、多 Agent 协作评测。

## Example Request / 示例请求

```powershell
curl -X POST "http://127.0.0.1:8100/api/v1/tasks/run" `
  -H "Content-Type: application/json" `
  -d '{
    "goal": "Analyze this project and provide governance suggestions",
    "project_path": "D:/Java/project/Project/AI Agent/DevAgent Studio",
    "max_files": 100,
    "require_human_review": true,
    "execution_mode": "planner"
  }'
```

## Development Checks / 开发验证

```powershell
# Backend import/compile check
.\.venv\Scripts\python.exe -m compileall -q app

# Frontend build
cd web
npm run build
```

## Implementation Timeline / 实现时间线

See:

- [Implementation Timeline](docs/IMPLEMENTATION_TIMELINE.md)
- [Workflow Production Notes](docs/PHASE_8_WORKFLOW_PRODUCTION.md)

## Roadmap / 后续计划

- Rewrite and expand automated tests.
- Add benchmark dataset management and benchmark report export.
- Improve workflow input/output mapping and conditional branch UI.
- Add richer permission controls for high-risk MCP tools.
- Add screenshots/GIFs generated from real demo sessions.
- Improve documentation for deployment and production hardening.

## License / 许可证

This project is licensed under the [MIT License](LICENSE).

Copyright (c) 2026 biheto. If you use, modify, or distribute this project,
please keep the original copyright notice and license text.

本项目使用 [MIT License](LICENSE) 开源。你可以使用、修改和分发本项目，
但需要保留原始版权声明和许可证文本。

## Attribution / 引用说明

If this project helps your research, study, or engineering work, attribution is appreciated:

```text
DevAgent Studio by biheto
https://github.com/biheto/DevAgent-Studio
```

如果本项目对你的研究、学习或工程实践有帮助，欢迎在相关文档、项目说明或引用中注明来源：

```text
DevAgent Studio by biheto
https://github.com/biheto/DevAgent-Studio
```
