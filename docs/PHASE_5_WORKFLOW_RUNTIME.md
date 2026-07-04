# Phase 5: Workflow Runtime + Human Review

本阶段把 Phase 4 的可拖拽画布推进为可配置、可保存、可审核、可复盘的 Workflow Runtime MVP。

## 已完成能力

- Workflow 定义持久化到 SQLite。
- 前端画布支持保存、加载、执行 Workflow。
- 节点支持右侧配置面板。
- Workflow 执行结果返回节点级事件。
- 画布节点会根据执行事件显示状态。
- 统一任务 Runtime 支持 `waiting_review` 状态。
- 人工审核支持通过、拒绝、要求修改。
- 前端任务区支持对等待审核的任务提交审核意见。

## 新增后端表

```text
workflow_definition
human_review_action
```

## 新增 API

```text
GET  /api/v1/workflows
POST /api/v1/workflows
GET  /api/v1/workflows/{workflow_id}
PUT  /api/v1/workflows/{workflow_id}

POST /api/v1/tasks/{task_id}/approve
POST /api/v1/tasks/{task_id}/reject
POST /api/v1/tasks/{task_id}/revise
```

## 前端变化

- Workflow 顶部可编辑名称、描述、输入文本。
- 左侧节点 palette 可拖拽到画布。
- 点击节点后可配置：
  - 节点名称
  - 节点类型
  - Agent 类型
  - `max_files`
  - RAG collection / top_k
  - MCP tool_name
  - Human Review 是否要求意见
  - Reporter output_key
- 执行画布后，节点显示：
  - `idle`
  - `running`
  - `completed`
  - `waiting_review`
  - `failed`

## 当前边界

- Human Review 目前是任务状态闭环：任务运行后进入 `waiting_review`，审核 API 再更新任务状态。
- Workflow 画布仍是轻量原生实现，尚未替换为 React Flow 或 FlowGram。
- Workflow 节点执行仍是确定性 Runtime 封装，尚未把每个视觉节点全部映射到真实 Agent 子图、真实 MCP client 或向量数据库。
- 完整后端运行测试需要 Python 3.11+ 虚拟环境可用。

## 验证结果

已完成：

```text
npm run build
```

前端 TypeScript 和 Vite 生产构建通过。

后端 `.venv` 当前绑定到已经不存在的 Python 3.13 路径：

```text
C:\Users\13231\AppData\Local\Programs\Python\Python313\python.exe
```

因此后端端到端 API smoke test 暂时无法运行。恢复或重新安装 Python 3.11+ 后，建议重新执行：

```powershell
cd "D:\Java\project\Project\AI Agent\DevAgent Studio"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8100
```
