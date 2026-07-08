from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PACKAGE_ENTRY = Path("node_modules/@modelcontextprotocol/server-memory/dist/index.js")


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    entry = project_root / PACKAGE_ENTRY
    if not entry.is_file():
        print(
            "Cannot find @modelcontextprotocol/server-memory. "
            "Run: npm install --no-save @modelcontextprotocol/server-memory",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)

    memory_path = project_root / "data" / "mcp-memory.jsonl"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("MEMORY_FILE_PATH", str(memory_path))
    raise SystemExit(subprocess.call(["node", str(entry)], env=env))


if __name__ == "__main__":
    main()
