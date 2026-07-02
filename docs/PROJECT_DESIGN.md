# 项目设计文档

## 1. 项目定位

DevAgent Studio 是一个面向开发者的多智能体任务工作站。它的目标不是提供普通聊天，而是提供可执行、可追踪、可复盘的 Agent 工作流。

第一阶段先完成项目分析 Agent，后续逐步扩展到代码审查、RAG 知识加工、学习陪练、MCP 工具市场和可视化 Workflow 编排。

## 2. 设计原则

- Agent 负责角色
- Graph 负责流程编排
- Tool 负责确定性动作
- Supervisor 负责质量检查
- Reporter 负责最终表达
- API 负责对外服务

## 3. 第一阶段 LangGraph 流程

```text
scan_project
  ↓
identify_stack
  ↓
analyze_structure
  ↓
generate_findings
  ↓
supervise_report
  ↓
generate_report
  ↓
END
```

## 4. 为什么使用 LangGraph

LangGraph 适合长任务、有状态、多步骤、多 Agent 编排。它后续可以自然扩展：

- Checkpoint 持久化
- Human-in-the-loop
- 多 Agent 子图
- Streaming 事件
- 任务中断恢复
- Supervisor 质量闭环

## 5. 和原 AI Agent Station 项目的关系

继承原项目的优势：

- 可配置 Agent
- MCP 工具接入
- SSE 过程输出
- 分析-执行-监督-总结闭环
- 可视化流程编排思想

重做时的变化：

- 用 LangGraph 替代手写策略树
- 用 FastAPI 提供轻量 Agent Runtime
- 第一阶段先做开发者项目分析场景
- 后续再加 RAG、MCP、任务持久化和前端工作台
