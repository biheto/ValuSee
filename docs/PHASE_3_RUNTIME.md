# Phase 3：可观测多 Agent Runtime

本阶段把 ValuSee 从 Agent API MVP 升级为可运行、可记录、可回放的多 Agent Runtime。

## 已完成内容

1. **Skill 抽象**
   - 新增 `app/skills/base.py`
   - 新增 `app/skills/registry.py`
   - 新增 `app/skills/builtin.py`
   - 代码审查、RAG 加工、学习陪练、Workflow 运行已通过 SkillRegistry 调用

2. **Harness Runtime**
   - 新增 `app/harness/context.py`
   - 新增 `app/harness/events.py`
   - 新增 `app/harness/runtime.py`
   - 新增 `app/harness/policy.py`
   - 支持 task_id、事件收集、权限检查和图执行包装

3. **真实 collaboration_graph 调用子图**
   - `collaboration_graph` 已改为真实调用：
     - `project_analyzer_graph`
     - `code_review_graph`
     - `rag_process_graph`
   - 流程为 Planner -> Project Analyzer -> Code Reviewer -> RAG Processor -> Supervisor -> Human Review -> Reporter

4. **任务事件和 SQLite 持久化**
   - 新增 `app/persistence/sqlite_store.py`
   - 自动创建 `data/dev_agent_studio.db`
   - 保存任务、事件、图结果和最终报告

5. **统一任务 API**
   - `POST /api/v1/tasks/run`
   - `POST /api/v1/tasks/run/stream`
   - `GET /api/v1/tasks`
   - `GET /api/v1/tasks/{task_id}`
   - `GET /api/v1/tasks/{task_id}/events`
   - `GET /api/v1/tasks/{task_id}/report`

6. **Planner/Reporter 接 LLM**
   - 新增 `app/providers/llm_provider.py`
   - 无 `OPENAI_API_KEY` 时走确定性 fallback
   - 安装 `pip install -e .[llm]` 并配置 Key 后，可让 Planner/Reporter 使用 LLM

7. **RAG 入库和检索**
   - 新增 `app/persistence/rag_store.py`
   - `POST /api/v1/rag/ingest`
   - `POST /api/v1/rag/query`
   - `GET /api/v1/rag/documents`

8. **MCP filesystem/git 接入**
   - 新增 `app/providers/mcp_provider.py`
   - 当前为 MCP-shaped 本地适配器
   - 支持文件列表、文件读取、Git status、Git log

9. **Workflow JSON 编译成 LangGraph**
   - 新增 `app/graphs/workflow_compiler.py`
   - `/api/v1/workflows/run` 会把前端传入的 nodes/edges 编译为 LangGraph 后执行

## 统一任务运行示例

```json
{
  "goal": "分析 AI Agent Station 项目并给出重构建议",
  "project_path": "D:/Java/project/Project/AI Agent/ai-agent-station-study",
  "max_files": 500,
  "require_human_review": true
}
```

## 环境提醒

项目要求 Python 3.11+。如果虚拟环境指向已经不存在的 Python 安装目录，需要删除并重建：

```powershell
cd "D:\Java\project\Project\AI Agent\ValuSee"
Remove-Item -Recurse -Force .venv
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
pip install -e .
python -m uvicorn app.main:app --reload --port 8100
```

如果要启用 LLM：

```powershell
pip install -e .[llm]
Copy-Item .env.example .env
# 编辑 .env:
# OPENAI_API_KEY=你的 Key
# DEV_AGENT_LLM_MODEL=gpt-4o-mini
```

LLM Provider 会在每次调用前读取 `.env`，因此修改 key、model 或 `OPENAI_BASE_URL`
后，下一次文件级语义审查会自动生效，不需要重启后端。也可以访问
`/api/v1/llm/status` 查看是否已启用，接口不会返回 key。

## 下一步建议

- 修复/重建本地 Python 虚拟环境后运行完整导入测试。
- 增加任务审核 approve/reject/revise 接口。
- 将 RAG store 从关键词检索替换为 pgvector。
- 将 MCP-shaped provider 替换为真实 MCP Client。
- 做前端可视化工作台，展示节点状态、事件时间线、审核弹窗和最终报告。
