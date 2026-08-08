# Phase 4：前端工作台 + 拖拽 Workflow

本阶段把 ValuSee 从后端 API 项目升级为可操作的多 Agent 工作台。

## 已实现功能

- 任务运行表单
- `/api/v1/tasks/run/stream` SSE 时间线
- 最终报告展示
- 历史任务列表
- 任务事件和报告回放
- 可拖拽 Workflow 画布
- 画布节点连线
- Workflow JSON 编译执行

## 前端路径

```text
web/
├─ src/App.tsx
├─ src/api.ts
├─ src/types.ts
├─ src/styles.css
├─ package.json
└─ vite.config.ts
```

## 启动方式

后端：

```powershell
cd "D:\Java\project\Project\AI Agent\ValuSee"
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --port 8100
```

前端开发：

```powershell
cd "D:\Java\project\Project\AI Agent\ValuSee\web"
npm install
npm run dev
```

生产构建：

```powershell
cd "D:\Java\project\Project\AI Agent\ValuSee\web"
npm run build
```

构建后访问：

```text
http://127.0.0.1:8100/
```

## 画布交互

- 从顶部工具条拖节点到画布
- 在画布中拖动节点调整位置
- 点击节点右侧圆形连接按钮，先选源节点，再选目标节点
- 点击“执行画布”把 nodes/edges 发送给后端

## 后续增强

- 增加审核 approve/reject/revise 后端接口
- 节点配置面板
- 条件边和循环边
- React Flow / FlowGram 替换原生画布
- 实时节点状态映射到画布
