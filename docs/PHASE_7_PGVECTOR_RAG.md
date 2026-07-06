# Phase 7: pgvector RAG Store

本阶段把 RAG 知识库从 SQLite 关键词检索升级为可切换的 pgvector 向量检索。

## 已实现

- 新增 `PgVectorRagStore`
  - 表：`rag_document`
  - 表：`rag_chunk`
  - 向量字段：`embedding vector(DEV_AGENT_EMBEDDING_DIM)`
  - 检索方式：`embedding <=> query_embedding`
- 新增 Embedding Provider
  - 优先使用 `OPENAI_API_KEY` + `DEV_AGENT_EMBEDDING_MODEL`
  - 未配置或调用失败时使用 hash fallback embedding，保证本地流程可运行
- 新增 `/api/v1/rag/status`
  - 查看当前 RAG store 类型、embedding 来源、维度等
- 保留 SQLite fallback
  - `.env` 不配置 pgvector 时，原有关键词检索继续可用
- 新增 `docker-compose.pgvector.yml`
  - 用于本地启动 PostgreSQL + pgvector

## 配置

`.env` 示例：

```env
DEV_AGENT_RAG_STORE=pgvector
PGVECTOR_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/dev_agent_studio
DEV_AGENT_EMBEDDING_MODEL=text-embedding-3-small
DEV_AGENT_EMBEDDING_DIM=1536
```

如果希望使用真实语义 embedding，还需要配置：

```env
OPENAI_API_KEY=你的 key
# OPENAI_BASE_URL=兼容 OpenAI 的代理地址，可选
```

## 启动 pgvector

```powershell
docker compose -f docker-compose.pgvector.yml up -d
```

安装依赖：

```powershell
.\.venv\Scripts\pip.exe install -e ".[vector]"
```

启动后查看状态：

```powershell
.\.venv\Scripts\python.exe -c "from fastapi.testclient import TestClient; from app.main import app; print(TestClient(app).get('/api/v1/rag/status').json())"
```

## API 使用

入库：

```http
POST /api/v1/rag/ingest
```

查询：

```http
POST /api/v1/rag/query
```

文档列表：

```http
GET /api/v1/rag/documents?collection=project-memory
```

## 当前边界

- 切换 `DEV_AGENT_RAG_STORE` 后需要重启后端。
- pgvector 数据库需要外部 PostgreSQL 服务。
- 如果没有 `OPENAI_API_KEY`，仍会写入 pgvector，但 embedding 是 hash fallback，不等于真实语义 embedding。
- 后续可以增加 collection 级重建、删除、embedding 版本迁移和索引重建接口。
