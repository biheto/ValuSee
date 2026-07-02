from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.agents.project_tools import scan_project

DOC_SUFFIXES = {".md", ".txt", ".rst", ".adoc", ".java", ".py", ".ts", ".tsx", ".sql", ".yml", ".yaml"}
STOPWORDS = {"the", "and", "for", "with", "this", "that", "from", "class", "public", "private", "return"}


def process_knowledge(project_path: str, max_files: int) -> dict[str, Any]:
    scan = scan_project(project_path, max_files)
    root = Path(scan["root"])
    documents = []
    chunks = []

    for file in scan["files"]:
        if file["suffix"] not in DOC_SUFFIXES:
            continue
        path = root / file["path"]
        text = _safe_read(path)
        if not text:
            continue
        documents.append({"path": file["path"], "size": len(text)})
        chunks.extend(_chunk_text(file["path"], text))

    keywords = _keywords(chunks)
    faq = _faq(chunks, keywords)
    report = _report(scan, documents, chunks, keywords, faq)
    return {
        "scan": scan,
        "documents": documents,
        "chunks": chunks,
        "keywords": keywords,
        "faq": faq,
        "report_markdown": report,
    }


def _safe_read(path: Path) -> str:
    try:
        if path.stat().st_size > 500_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _chunk_text(path: str, text: str, chunk_size: int = 900) -> list[dict[str, str]]:
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    chunks = []
    for index in range(0, len(normalized), chunk_size):
        content = normalized[index : index + chunk_size].strip()
        if len(content) >= 80:
            chunks.append({"path": path, "chunk_id": f"{path}#{len(chunks) + 1}", "content": content})
    return chunks


def _keywords(chunks: list[dict[str, str]]) -> list[str]:
    counter: Counter[str] = Counter()
    for chunk in chunks:
        words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fa5]{2,}", chunk["content"])
        for word in words:
            lower = word.lower()
            if lower not in STOPWORDS and len(lower) <= 32:
                counter[lower] += 1
    return [word for word, _ in counter.most_common(20)]


def _faq(chunks: list[dict[str, str]], keywords: list[str]) -> list[dict[str, str]]:
    faq = []
    for keyword in keywords[:8]:
        source = next((chunk for chunk in chunks if keyword.lower() in chunk["content"].lower()), None)
        if not source:
            continue
        faq.append(
            {
                "question": f"{keyword} 在项目中主要指什么？",
                "answer": f"可优先查看 `{source['path']}` 中的相关片段，并结合上下文补充业务解释。",
            }
        )
    return faq


def _report(scan: dict[str, Any], documents: list[dict[str, Any]], chunks: list[dict[str, str]], keywords: list[str], faq: list[dict[str, str]]) -> str:
    keyword_text = ", ".join(keywords) if keywords else "暂未提取"
    doc_text = "\n".join(f"- `{doc['path']}` ({doc['size']} chars)" for doc in documents[:30]) or "- 暂未发现可处理文档"
    faq_text = "\n".join(f"- Q: {item['question']}\n  A: {item['answer']}" for item in faq) or "- 暂未生成 FAQ"
    return f"""# {scan['project_name']} RAG 知识加工报告

## 文档概览

- 文档数量：{len(documents)}
- 切片数量：{len(chunks)}
- 高频关键词：{keyword_text}

## 文档列表

{doc_text}

## 自动 FAQ

{faq_text}

## 后续建议

- 将 chunks 写入 pgvector / Milvus 等向量库。
- 为每个回答展示来源路径和 chunk_id。
- 增加文档过期检测和知识冲突检测。
"""
