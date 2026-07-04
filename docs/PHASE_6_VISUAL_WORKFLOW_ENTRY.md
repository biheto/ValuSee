# Phase 6: Visual Workflow As Task Entry

本阶段把可视化 Workflow 从旁路演示画布升级为任务执行入口。

## 已完成

- 左侧任务入口支持四类模式：
  - Agent
  - Workflow
  - Tool
  - Knowledge
- 左侧“运行当前画布”会把当前画布的 `nodes` / `edges` 一起提交到 `/api/v1/tasks/run/stream`。
- 后端 `TaskRunRequest` 新增：
  - `execution_mode`
  - `workflow_id`
  - `workflow_name`
  - `input_text`
  - `nodes`
  - `edges`
- `/api/v1/tasks/run` 不再固定只走 `collaboration_graph`，而是进入 `run_task_workflow`。
- Workflow 节点已接入真实能力：
  - `agent/project_analyzer` 调用项目分析子图
  - `agent/code_reviewer` 调用代码审查子图
  - `agent/rag_processor` 调用 RAG 加工子图
  - `rag` 调用本地 RAG store 检索
  - `mcp_tool` 调用 MCP-shaped filesystem/git provider
  - `human_review` 生成审核包
  - `reporter` 汇总最终报告
- SSE 事件包含节点 ID，前端会把执行状态映射回画布节点。
- 前端布局调整为：
  - 左侧：Agent / Workflow / Tool / Knowledge、任务输入、节点库、已保存 Workflow
  - 中间：执行时间线 + 图形化流程
  - 右侧：当前状态、人工审核、节点配置、工具调用、Agent 输出、历史任务
  - 底部：最终报告、Mermaid 图、优化建议

## 新执行路径

```text
前端运行当前画布
  -> POST /api/v1/tasks/run/stream
  -> Harness Runtime 创建 task_id
  -> run_task_workflow
  -> Workflow JSON 编译成 LangGraph
  -> 节点按图执行真实 Agent / Tool / Knowledge
  -> 事件持久化到 SQLite
  -> SSE 返回时间线和最终报告
```

## 验证

已通过：

```text
npm run build
```

未完成完整后端 smoke test，原因是当前虚拟环境仍绑定到已经不存在的 Python 3.13 路径：

```text
C:\Users\13231\AppData\Local\Programs\Python\Python313\python.exe
```

当前系统默认 Python 是 3.9.9，而项目要求 Python 3.11+。
