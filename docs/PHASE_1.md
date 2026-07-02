# 第一阶段：项目分析 Agent

## 目标

完成一个可以运行的项目分析 Agent。用户提交本地项目路径后，系统自动扫描并生成项目分析报告。

## 输入

```json
{
  "project_path": "D:/path/to/project",
  "max_files": 500
}
```

## 输出

- 项目基本信息
- 文件数量与目录摘要
- 关键文件列表
- 技术栈识别
- 模块结构分析
- 风险与优化建议
- Markdown 报告
- Mermaid 架构草图

## API

```text
GET  /health
POST /api/v1/projects/analyze
POST /api/v1/projects/analyze/stream
```

## MVP 范围

本阶段以确定性代码分析为主，不强依赖大模型 API。这样项目可以先稳定运行，后续再引入 LLM 做更深的总结、代码语义分析和重构建议。

## 后续增强

- 接入 LLM 生成更自然的报告
- 接入 MCP filesystem/git 工具
- 增加代码审查 Agent
- 增加任务历史表和报告保存
- 前端执行时间线展示
