from __future__ import annotations

from pathlib import Path

from app.persistence.rag_store import rag_store

ROOT = Path(__file__).resolve().parents[1]


COLLECTION = "valuesee-shopping"
KNOWLEDGE_DIR = ROOT / "data" / "knowledge" / COLLECTION
CHUNK_SIZE = 900


def main() -> None:
    documents: list[dict[str, object]] = []
    chunks: list[dict[str, str]] = []

    for path in sorted(KNOWLEDGE_DIR.glob("[0-9][0-9]-*.md")):
        content = path.read_text(encoding="utf-8").strip()
        relative_path = path.relative_to(KNOWLEDGE_DIR.parent).as_posix()
        documents.append({"path": relative_path, "size": len(content)})
        normalized = content.replace("\r\n", "\n")
        chunk_index = 0
        for index in range(0, len(normalized), CHUNK_SIZE):
            text = normalized[index : index + CHUNK_SIZE].strip()
            if len(text) >= 80:
                chunk_index += 1
                chunks.append(
                    {
                        "path": relative_path,
                        "chunk_id": f"{relative_path}#{chunk_index}",
                        "content": text,
                    }
                )

    for support_file in ("README.md", "sources.md"):
        rag_store.delete_note(COLLECTION, f"{COLLECTION}/{support_file}")

    result = rag_store.ingest(COLLECTION, documents, chunks)
    print(
        f"collection={COLLECTION} documents={result['document_count']} "
        f"chunks={result['chunk_count']} changed={result['changed_document_count']}"
    )


if __name__ == "__main__":
    main()
