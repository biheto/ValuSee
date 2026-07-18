from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

from app.persistence.memory_store import SQLiteMemoryStore


class MemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_mode = os.environ.get("DEV_AGENT_MEMORY_EXTRACTOR")
        os.environ["DEV_AGENT_MEMORY_EXTRACTOR"] = "rule"

    def tearDown(self) -> None:
        if self.previous_mode is None:
            os.environ.pop("DEV_AGENT_MEMORY_EXTRACTOR", None)
        else:
            os.environ["DEV_AGENT_MEMORY_EXTRACTOR"] = self.previous_mode

    def test_memory_requires_confirmation_and_replaces_conflicting_preference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteMemoryStore(Path(directory) / "memory.db")
            first = store.extract_candidates("我希望代码审查报告请用中文。")
            self.assertEqual(1, len(first))
            self.assertEqual("candidate", first[0]["status"])

            confirmed = store.confirm(first[0]["memory_id"], "memory/first")
            self.assertEqual("confirmed", confirmed["status"])

            second = store.extract_candidates("我希望代码审查报告请用英文。")
            self.assertEqual(first[0]["memory_id"], second[0]["conflict_with"])
            store.confirm(second[0]["memory_id"], "memory/second")

            records = {item["memory_id"]: item for item in store.list_memories()}
            self.assertEqual("superseded", records[first[0]["memory_id"]]["status"])
            self.assertEqual("confirmed", records[second[0]["memory_id"]]["status"])

    def test_non_explicit_text_does_not_become_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteMemoryStore(Path(directory) / "memory.db")
            self.assertEqual([], store.extract_candidates("checkpoint 是什么？"))


if __name__ == "__main__":
    unittest.main()
