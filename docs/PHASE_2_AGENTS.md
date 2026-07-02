# 第二阶段：七类 Agent MVP

本阶段把 DevAgent Studio 从单一项目分析 Agent 扩展为面向开发者的 Agent 工作站。

## 已实现能力

```text
1. 项目分析 Agent
2. 代码审查 Agent
3. RAG 知识加工 Agent
4. 学习陪练 Agent
5. MCP 工具市场
6. 可视化 Workflow 编排
7. 多 Agent 协作与人工审核
```

## 设计取舍

当前版本以 MVP 闭环为目标：

- API 先稳定
- LangGraph 流程先跑通
- 结果先结构化
- LLM、向量库、真实 MCP 调用后续增强

## 接口清单

| 能力 | 方法 | 路径 |
| --- | --- | --- |
| 项目分析 | POST | `/api/v1/projects/analyze` |
| 项目分析流式事件 | POST | `/api/v1/projects/analyze/stream` |
| 代码审查 | POST | `/api/v1/code/review` |
| RAG 知识加工 | POST | `/api/v1/rag/process` |
| 学习陪练 | POST | `/api/v1/learning/coach/plan` |
| MCP 工具列表 | GET | `/api/v1/mcp/tools` |
| MCP 工具权限检查 | POST | `/api/v1/mcp/tools/allow-check` |
| Workflow 执行 | POST | `/api/v1/workflows/run` |
| 多 Agent 协作 | POST | `/api/v1/agents/collaborate` |

## 后续增强建议

- 为每个 Agent 接入 Chat Model，生成更自然的总结。
- 为 RAG Agent 增加 pgvector 写入和检索接口。
- 为 MCP 市场增加真实 server 配置、启停检测和权限审批。
- 为 Workflow 增加 React Flow / FlowGram 前端编排。
- 为人工审核增加任务状态表和审核回调接口。
