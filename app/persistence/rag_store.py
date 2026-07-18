from __future__ import annotations

import re
import sqlite3
import hashlib
import math
import os
from pathlib import Path
from typing import Any

from app.harness.events import utc_now_iso


class SQLiteRagStore:
    def __init__(self, db_path: str | Path = "data/dev_agent_studio.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_document (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_chunk (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collection TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def ingest(self, collection: str, documents: list[dict[str, Any]], chunks: list[dict[str, str]]) -> dict[str, int]:
        with self._connect() as conn:
            conn.execute("DELETE FROM rag_document WHERE collection = ?", (collection,))
            conn.execute("DELETE FROM rag_chunk WHERE collection = ?", (collection,))
            for doc in documents:
                conn.execute(
                    "INSERT INTO rag_document(collection, path, size, created_at) VALUES (?, ?, ?, ?)",
                    (collection, doc["path"], doc.get("size"), utc_now_iso()),
                )
            for chunk in chunks:
                conn.execute(
                    "INSERT INTO rag_chunk(collection, chunk_id, path, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (collection, chunk["chunk_id"], chunk["path"], chunk["content"], utc_now_iso()),
                )
        return {"document_count": len(documents), "chunk_count": len(chunks)}

    def query(self, collection: str, question: str, limit: int = 5) -> list[dict[str, Any]]:
        terms = [term.lower() for term in question.split() if term.strip()]
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, path, content
                FROM rag_chunk
                WHERE collection = ?
                """,
                (collection,),
            ).fetchall()
        scored = []
        for row in rows:
            content = row["content"]
            lower = content.lower()
            score = sum(lower.count(term) for term in terms) if terms else 0
            if score > 0 or not terms:
                scored.append(
                    {
                        "chunk_id": row["chunk_id"],
                        "path": row["path"],
                        "score": score,
                        "content": content[:800],
                    }
                )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:limit]

    def list_documents(self, collection: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if collection:
                rows = conn.execute(
                    "SELECT collection, path, size, created_at FROM rag_document WHERE collection = ? ORDER BY path",
                    (collection,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT collection, path, size, created_at FROM rag_document ORDER BY collection, path"
                ).fetchall()
        return [dict(row) for row in rows]

    def add_note(self, collection: str, path: str, content: str) -> dict[str, str]:
        safe_path = path.strip() or "manual-note"
        chunk_id = f"{safe_path}#note-{self._slug(content)[:24]}"
        now = utc_now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM rag_document WHERE collection = ? AND path = ?",
                (collection, safe_path),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE rag_document SET size = ?, created_at = ? WHERE id = ?",
                    (len(content), now, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO rag_document(collection, path, size, created_at) VALUES (?, ?, ?, ?)",
                    (collection, safe_path, len(content), now),
                )
            conn.execute(
                "INSERT INTO rag_chunk(collection, chunk_id, path, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (collection, chunk_id, safe_path, content, now),
            )
        return {"collection": collection, "chunk_id": chunk_id, "path": safe_path}

    def delete_note(self, collection: str, path: str) -> bool:
        with self._connect() as conn:
            removed = conn.execute(
                "DELETE FROM rag_chunk WHERE collection = ? AND path = ?", (collection, path)
            ).rowcount
            conn.execute("DELETE FROM rag_document WHERE collection = ? AND path = ?", (collection, path))
        return bool(removed)

    def status(self) -> dict[str, Any]:
        return {
            "kind": "sqlite",
            "database_path": str(self.db_path),
            "retrieval": "keyword",
            "embedding_source": None,
        }

    def _slug(self, text: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip().lower()).strip("-")
        return slug or "note"


class EmbeddingProvider:
    def __init__(self, dimension: int = 1536):
        self.dimension = dimension
        self.model = _config().get("DEV_AGENT_EMBEDDING_MODEL", "text-embedding-3-small")
        self._last_source = "not_used"

    @property
    def source(self) -> str:
        return self._last_source

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        config = _config()
        api_key = config.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                from langchain_openai import OpenAIEmbeddings

                kwargs: dict[str, Any] = {"model": self.model, "api_key": api_key}
                if config.get("OPENAI_BASE_URL"):
                    kwargs["base_url"] = config["OPENAI_BASE_URL"]
                embeddings = OpenAIEmbeddings(**kwargs)
                vectors = embeddings.embed_documents(texts)
                self._last_source = "openai"
                return [_fit_dimension(vector, self.dimension) for vector in vectors]
            except Exception:
                pass
        self._last_source = "hash_fallback"
        return [self._hash_embedding(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        config = _config()
        api_key = config.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                from langchain_openai import OpenAIEmbeddings

                kwargs: dict[str, Any] = {"model": self.model, "api_key": api_key}
                if config.get("OPENAI_BASE_URL"):
                    kwargs["base_url"] = config["OPENAI_BASE_URL"]
                embeddings = OpenAIEmbeddings(**kwargs)
                self._last_source = "openai"
                return _fit_dimension(embeddings.embed_query(text), self.dimension)
            except Exception:
                pass
        self._last_source = "hash_fallback"
        return self._hash_embedding(text)

    def _hash_embedding(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fa5]{1,}", text.lower())
        if not tokens:
            tokens = [text[:64] or "empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class PgVectorRagStore:
    def __init__(self):
        config = _config()
        self.database_url = config.get("PGVECTOR_DATABASE_URL") or config.get("DATABASE_URL", "")
        self.dimension = int(config.get("DEV_AGENT_EMBEDDING_DIM", "1536") or 1536)
        self.embedding = EmbeddingProvider(self.dimension)
        if not self.database_url:
            raise RuntimeError("PGVECTOR_DATABASE_URL or DATABASE_URL is required for pgvector RAG store")
        self._init_schema()

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required. Install with: pip install -e \".[vector]\"") from exc
        return psycopg.connect(self.database_url)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_document (
                        id BIGSERIAL PRIMARY KEY,
                        collection TEXT NOT NULL,
                        path TEXT NOT NULL,
                        size INTEGER,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE(collection, path)
                    )
                    """
                )
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS rag_chunk (
                        id BIGSERIAL PRIMARY KEY,
                        collection TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        path TEXT NOT NULL,
                        content TEXT NOT NULL,
                        embedding vector({self.dimension}) NOT NULL,
                        embedding_source TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        UNIQUE(collection, chunk_id)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rag_document_collection ON rag_document(collection)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rag_chunk_collection ON rag_chunk(collection)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_rag_chunk_embedding ON rag_chunk USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
                )
            conn.commit()

    def ingest(self, collection: str, documents: list[dict[str, Any]], chunks: list[dict[str, str]]) -> dict[str, int]:
        vectors = self.embedding.embed_documents([chunk["content"] for chunk in chunks])
        now = utc_now_iso()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM rag_document WHERE collection = %s", (collection,))
                cur.execute("DELETE FROM rag_chunk WHERE collection = %s", (collection,))
                for doc in documents:
                    cur.execute(
                        """
                        INSERT INTO rag_document(collection, path, size, created_at)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (collection, doc["path"], doc.get("size"), now),
                    )
                for chunk, vector in zip(chunks, vectors, strict=False):
                    cur.execute(
                        """
                        INSERT INTO rag_chunk(collection, chunk_id, path, content, embedding, embedding_source, created_at)
                        VALUES (%s, %s, %s, %s, %s::vector, %s, %s)
                        """,
                        (
                            collection,
                            chunk["chunk_id"],
                            chunk["path"],
                            chunk["content"],
                            _vector_literal(vector),
                            self.embedding.source,
                            now,
                        ),
                    )
            conn.commit()
        return {"document_count": len(documents), "chunk_count": len(chunks)}

    def query(self, collection: str, question: str, limit: int = 5) -> list[dict[str, Any]]:
        vector = self.embedding.embed_query(question)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chunk_id, path, content, 1 - (embedding <=> %s::vector) AS score
                    FROM rag_chunk
                    WHERE collection = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (_vector_literal(vector), collection, _vector_literal(vector), limit),
                )
                rows = cur.fetchall()
        return [
            {"chunk_id": row[0], "path": row[1], "score": float(row[3]), "content": str(row[2])[:800]}
            for row in rows
        ]

    def list_documents(self, collection: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                if collection:
                    cur.execute(
                        """
                        SELECT collection, path, size, created_at
                        FROM rag_document
                        WHERE collection = %s
                        ORDER BY path
                        """,
                        (collection,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT collection, path, size, created_at
                        FROM rag_document
                        ORDER BY collection, path
                        """
                    )
                rows = cur.fetchall()
        return [
            {"collection": row[0], "path": row[1], "size": row[2], "created_at": str(row[3])}
            for row in rows
        ]

    def add_note(self, collection: str, path: str, content: str) -> dict[str, str]:
        safe_path = path.strip() or "manual-note"
        chunk_id = f"{safe_path}#note-{_slug(content)[:24]}"
        now = utc_now_iso()
        vector = self.embedding.embed_query(content)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO rag_document(collection, path, size, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(collection, path)
                    DO UPDATE SET size = EXCLUDED.size, created_at = EXCLUDED.created_at
                    """,
                    (collection, safe_path, len(content), now),
                )
                cur.execute(
                    """
                    INSERT INTO rag_chunk(collection, chunk_id, path, content, embedding, embedding_source, created_at)
                    VALUES (%s, %s, %s, %s, %s::vector, %s, %s)
                    ON CONFLICT(collection, chunk_id)
                    DO UPDATE SET content = EXCLUDED.content,
                                  embedding = EXCLUDED.embedding,
                                  embedding_source = EXCLUDED.embedding_source,
                                  created_at = EXCLUDED.created_at
                    """,
                    (
                        collection,
                        chunk_id,
                        safe_path,
                        content,
                        _vector_literal(vector),
                        self.embedding.source,
                        now,
                    ),
                )
            conn.commit()
        return {"collection": collection, "chunk_id": chunk_id, "path": safe_path}

    def delete_note(self, collection: str, path: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM rag_chunk WHERE collection = %s AND path = %s", (collection, path))
                removed = cur.rowcount
                cur.execute("DELETE FROM rag_document WHERE collection = %s AND path = %s", (collection, path))
            conn.commit()
        return bool(removed)

    def status(self) -> dict[str, Any]:
        return {
            "kind": "pgvector",
            "database_url_configured": bool(self.database_url),
            "embedding_model": self.embedding.model,
            "embedding_source": self.embedding.source,
            "embedding_dim": self.dimension,
        }


def create_rag_store() -> SQLiteRagStore | PgVectorRagStore:
    kind = _config().get("DEV_AGENT_RAG_STORE", "sqlite").lower()
    if kind == "pgvector":
        return PgVectorRagStore()
    return SQLiteRagStore()


def _config() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    env_path = root / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key in [
        "DEV_AGENT_RAG_STORE",
        "PGVECTOR_DATABASE_URL",
        "DATABASE_URL",
        "DEV_AGENT_EMBEDDING_MODEL",
        "DEV_AGENT_EMBEDDING_DIM",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ]:
        if os.getenv(key):
            values[key] = os.getenv(key, "")
    return values


def _fit_dimension(vector: list[float], dimension: int) -> list[float]:
    values = [float(value) for value in vector]
    if len(values) == dimension:
        return values
    if len(values) > dimension:
        return values[:dimension]
    return values + [0.0] * (dimension - len(values))


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", text.strip().lower()).strip("-")
    return slug or "note"


rag_store = create_rag_store()
