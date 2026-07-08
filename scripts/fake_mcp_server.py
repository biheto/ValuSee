from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", "dist", "build"}


def safe_path(path: str | None = None) -> Path:
    target = (ROOT / (path or ".")).resolve()
    if target != ROOT and ROOT not in target.parents:
        raise PermissionError("Refusing to access outside configured root")
    return target


def iter_paths(base: Path):
    for path in base.rglob("*"):
        try:
            relative = path.relative_to(ROOT)
        except ValueError:
            continue
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        yield path


def read_message() -> dict | None:
    headers: dict[str, str] = {}
    first_line = sys.stdin.buffer.readline()
    if not first_line:
        return None
    if not first_line.lower().startswith(b"content-length:"):
        text = first_line.decode("utf-8", errors="ignore").strip()
        return json.loads(text) if text else None
    text = first_line.decode("ascii", errors="ignore").strip()
    key, value = text.split(":", 1)
    headers[key.lower()] = value.strip()
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        text = line.decode("ascii", errors="ignore").strip()
        if ":" in text:
            key, value = text.split(":", 1)
            headers[key.lower()] = value.strip()
    length = int(headers.get("content-length") or 0)
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def send_message(payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()


def tool_list() -> list[dict]:
    return [
        {
            "name": "read_file",
            "description": "Read a UTF-8 text file under the configured project root.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to the MCP root."},
                    "max_chars": {"type": "integer", "default": 4000},
                },
                "required": ["path"],
            },
        },
        {
            "name": "list_directory",
            "description": "List direct children of a directory under the configured project root.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        },
        {
            "name": "directory_tree",
            "description": "Return a shallow directory tree under the configured project root.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "default": "."},
                    "max_depth": {"type": "integer", "default": 2},
                    "limit": {"type": "integer", "default": 200},
                },
            },
        },
        {
            "name": "search_files",
            "description": "Search file names and text content under the configured project root.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["query"],
            },
        },
    ]


def call_tool(name: str, arguments: dict) -> dict:
    if name == "read_file":
        target = safe_path(str(arguments.get("path") or arguments.get("file_path") or "README.md"))
        if not target.is_file():
            raise FileNotFoundError(target.as_posix())
        max_chars = int(arguments.get("max_chars") or 4000)
        content = target.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        return {
            "content": [{"type": "text", "text": content}],
            "root": ROOT.as_posix(),
            "path": target.relative_to(ROOT).as_posix(),
            "truncated": len(content) >= max_chars,
        }
    if name == "list_directory":
        base = safe_path(str(arguments.get("path") or "."))
        if not base.is_dir():
            raise NotADirectoryError(base.as_posix())
        limit = int(arguments.get("limit") or 100)
        entries = []
        for child in sorted(base.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if len(entries) >= limit:
                break
            if child.name in EXCLUDED_DIRS:
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": child.relative_to(ROOT).as_posix(),
                    "type": "directory" if child.is_dir() else "file",
                }
            )
        return {"content": [{"type": "text", "text": json.dumps(entries, ensure_ascii=False, indent=2)}], "entries": entries}
    if name == "directory_tree":
        base = safe_path(str(arguments.get("path") or "."))
        max_depth = int(arguments.get("max_depth") or 2)
        limit = int(arguments.get("limit") or 200)
        nodes = []
        for path in iter_paths(base):
            relative = path.relative_to(base)
            if len(relative.parts) > max_depth or len(nodes) >= limit:
                continue
            nodes.append(
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "type": "directory" if path.is_dir() else "file",
                    "depth": len(relative.parts),
                }
            )
        return {"content": [{"type": "text", "text": json.dumps(nodes, ensure_ascii=False, indent=2)}], "tree": nodes}
    if name == "search_files":
        base = safe_path(str(arguments.get("path") or "."))
        query = str(arguments.get("query") or "").lower()
        limit = int(arguments.get("limit") or 50)
        matches = []
        for path in iter_paths(base):
            if len(matches) >= limit or not path.is_file():
                continue
            relative = path.relative_to(ROOT).as_posix()
            matched = query in relative.lower()
            snippet = ""
            if not matched and path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".txt", ".json", ".css", ".html"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                index = text.lower().find(query)
                matched = index >= 0
                if matched:
                    snippet = text[max(0, index - 80) : index + 160]
            if matched:
                matches.append({"path": relative, "snippet": snippet})
        return {"content": [{"type": "text", "text": json.dumps(matches, ensure_ascii=False, indent=2)}], "matches": matches}
    raise ValueError(f"Unknown tool: {name}")


def main() -> None:
    while True:
        message = read_message()
        if not message:
            break
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized":
            continue
        if method == "initialize":
            send_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake-mcp-server", "version": "0.1.0"},
                    },
                }
            )
            continue
        if method == "tools/list":
            send_message({"jsonrpc": "2.0", "id": request_id, "result": {"tools": tool_list()}})
            continue
        if method == "tools/call":
            params = message.get("params") or {}
            try:
                result = call_tool(str(params.get("name") or ""), params.get("arguments") or {})
                send_message({"jsonrpc": "2.0", "id": request_id, "result": result})
            except Exception as exc:
                send_message({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}})
            continue
        send_message({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}})


if __name__ == "__main__":
    main()
