# DevAgent Studio

DevAgent Studio 是一个基于 FastAPI + LangGraph 的多智能体任务工作站。它不是普通聊天机器人，而是面向开发者场景的 Agent 执行平台：用户提交一个目标或项目目录，系统自动规划、扫描、分析、监督质量并生成结构化报告。

第一阶段聚焦 **项目分析 Agent**：给定本地项目路径，自动识别项目类型、技术栈、目录结构、关键文件、潜在风险，并生成 Markdown 项目分析报告和 Mermaid 架构草图。

## 核心定位

```text
用户目标
  ↓
LangGraph 任务图
  ↓
项目扫描 / 技术栈识别 / 结构分析 / 质量监督 / 报告生成
  ↓
FastAPI 返回结构化结果或 SSE 流式过程
```

## 第一阶段能力

- 本地项目目录扫描
- 自动识别技术栈
- 自动识别关键文件与模块
- 生成项目结构摘要
- 输出潜在风险和优化建议
- 生成 Markdown 报告
- 提供 FastAPI 接口
- 预留 SSE 流式事件接口

## 当前已实现的 Agent 能力

| 能力 | 接口 | 状态 |
| --- | --- | --- |
| 项目分析 Agent | `POST /api/v1/projects/analyze` | 已实现 |
| 代码审查 Agent | `POST /api/v1/code/review` | 已实现 MVP |
| RAG 知识加工 Agent | `POST /api/v1/rag/process` | 已实现 MVP |
| 学习陪练 Agent | `POST /api/v1/learning/coach/plan` | 已实现 MVP |
| MCP 工具市场 | `GET /api/v1/mcp/tools` | 已实现 MVP |
| 可视化 Workflow 编排 | `POST /api/v1/workflows/run` | 已实现 MVP |
| 多 Agent 协作与人工审核 | `POST /api/v1/agents/collaborate` | 已实现 MVP |
| 统一任务 Runtime | `POST /api/v1/tasks/run` | 已实现 MVP |
| RAG 入库/检索 | `POST /api/v1/rag/ingest` / `POST /api/v1/rag/query` | 已实现 MVP |
| MCP 文件/Git 工具 | `/api/v1/mcp/filesystem/*` / `/api/v1/mcp/git/*` | 已实现 MVP |

## 技术栈

- Python 3.11+
- FastAPI
- LangGraph
- Pydantic v2
- Uvicorn

## 快速启动

```bash
cd "D:\Java\project\Project\AI Agent\DevAgent Studio"
python -m venv .venv
.venv\Scripts\activate
pip install -e .
uvicorn app.main:app --reload --port 8100
```

打开接口文档：

```text
http://127.0.0.1:8100/docs
```

## 前端工作台

Phase 4 增加了 React + TypeScript 前端工作台，包含：

- 多 Agent 任务运行表单
- SSE 执行时间线
- 最终 Markdown 报告
- 历史任务回放
- 可拖拽 Workflow 画布

开发模式：

```bash
cd web
npm install
npm run dev
```

访问：

```text
http://127.0.0.1:5173
```

生产构建：

```bash
cd web
npm run build
```

构建后 FastAPI 会自动托管 `web/dist`：

```text
http://127.0.0.1:8100/
```

## 示例请求

```bash
curl -X POST "http://127.0.0.1:8100/api/v1/projects/analyze" ^
  -H "Content-Type: application/json" ^
  -d "{\"project_path\": \"D:/Java/project/Project/AI Agent/ai-agent-station-study\", \"max_files\": 500}"
```

代码审查：

```bash
curl -X POST "http://127.0.0.1:8100/api/v1/code/review" ^
  -H "Content-Type: application/json" ^
  -d "{\"project_path\": \"D:/Java/project/Project/AI Agent/ai-agent-station-study\", \"max_files\": 500}"
```

学习陪练：

```bash
curl -X POST "http://127.0.0.1:8100/api/v1/learning/coach/plan" ^
  -H "Content-Type: application/json" ^
  -d "{\"topic\": \"LangGraph 多 Agent\", \"level\": \"beginner\", \"days\": 7}"
```

## 项目结构

```text
DevAgent Studio/
├─ app/
│  ├─ main.py
│  ├─ api/
│  │  └─ routes.py
│  ├─ agents/
│  │  └─ project_tools.py
│  ├─ core/
│  │  └─ config.py
│  ├─ graphs/
│  │  └─ project_analyzer_graph.py
│  └─ schemas/
│     └─ project.py
├─ docs/
│  ├─ PROJECT_DESIGN.md
│  └─ PHASE_1.md
├─ examples/
│  └─ analyze-project.json
├─ tests/
├─ pyproject.toml
├─ .env.example
└─ README.md
```

## 后续路线

1. 项目分析 Agent
2. 代码审查 Agent
3. RAG 知识加工 Agent
4. 学习陪练 Agent
5. MCP 工具市场
6. 可视化 Workflow 编排
7. 多 Agent 协作与人工审核

## 说明

当前版本优先完成运行闭环，以确定性分析为主，不强依赖大模型 API。后续可以把每个 Agent 的报告生成、代码语义审查、知识问答和人工审核节点替换为真正的 LLM / MCP / 向量库实现。

Phase 3 已补充 Skill、Harness Runtime、真实多 Agent 子图调用、SQLite 任务持久化、统一任务 API、LLM Provider、RAG 本地入库检索、MCP-shaped 文件/Git 工具和 Workflow JSON -> LangGraph 编译能力。详细见 `docs/PHASE_3_RUNTIME.md`。

Phase 4 已补充前端工作台和可拖拽 Workflow 画布。详细见 `docs/PHASE_4_WEB_WORKBENCH.md`。

Phase 7 已补充 pgvector RAG Store，可通过 `DEV_AGENT_RAG_STORE=pgvector`
切换到 PostgreSQL + pgvector 向量检索。详细见 `docs/PHASE_7_PGVECTOR_RAG.md`。
