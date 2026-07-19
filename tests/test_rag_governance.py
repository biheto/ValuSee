from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.persistence.rag_store import SQLiteRagStore


class RagGovernanceTest(unittest.TestCase):
    def test_incremental_versioning_acl_and_gold_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteRagStore(Path(tmpdir) / "rag.db")
            docs = [{"path": "README.md", "size": 30}]
            chunks = [{"chunk_id": "README.md#1", "path": "README.md", "content": "FastAPI LangGraph workflow resume"}]

            first = store.ingest("default", docs, chunks)
            second = store.ingest("default", docs, chunks)
            self.assertEqual(first["changed_document_count"], 1)
            self.assertEqual(second["changed_document_count"], 0)

            changed = [{"chunk_id": "README.md#1", "path": "README.md", "content": "FastAPI LangGraph workflow resume benchmark"}]
            third = store.ingest("default", docs, changed)
            self.assertEqual(third["changed_document_count"], 1)
            versions = store.list_documents("default")
            self.assertEqual([item["version"] for item in versions], [2, 1])
            self.assertTrue(versions[0]["is_current"])

            self.assertTrue(store.set_document_acl("default", "README.md", ["alice"]))
            self.assertEqual(store.query("default", "benchmark", actor_id="bob"), [])
            self.assertEqual(store.query("default", "benchmark", actor_id="alice")[0]["chunk_id"], "README.md#1")

            case = store.save_gold_case(
                {
                    "case_id": "readme_workflow_gold",
                    "collection": "default",
                    "question": "workflow resume benchmark",
                    "expected_chunk_ids": ["README.md#1"],
                    "expected_paths": ["README.md"],
                    "expected_keywords": ["benchmark"],
                    "enabled": True,
                }
            )
            self.assertEqual(case["case_id"], "readme_workflow_gold")
            self.assertEqual(store.list_gold_cases("default")[0]["expected_chunk_ids"], ["README.md#1"])
            self.assertTrue(store.delete_gold_case("readme_workflow_gold"))


if __name__ == "__main__":
    unittest.main()
