from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PACKAGE_ENTRY = Path("node_modules/@modelcontextprotocol/server-filesystem/dist/index.js")


def candidate_entries() -> list[Path]:
    entries: list[Path] = []
    explicit = os.getenv("MCP_FILESYSTEM_ENTRY")
    if explicit:
        entries.append(Path(explicit))

    project_root = Path(__file__).resolve().parents[1]
    entries.append(project_root / PACKAGE_ENTRY)

    npm_cache = Path(os.getenv("LOCALAPPDATA", "")) / "npm-cache" / "_npx"
    try:
        if npm_cache.is_dir():
            entries.extend(npm_cache.glob(f"*/{PACKAGE_ENTRY.as_posix()}"))
    except OSError:
        pass

    return entries


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    return None


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    entry = first_existing(candidate_entries())
    if not entry:
        print(
            "Cannot find @modelcontextprotocol/server-filesystem. "
            "Run: npx -y @modelcontextprotocol/server-filesystem <project_path>",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
    raise SystemExit(subprocess.call(["node", str(entry), str(root)], env=os.environ.copy()))


if __name__ == "__main__":
    main()
