from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.project_tools import EXCLUDED_DIRS
from app.harness.events import utc_now_iso
from app.persistence.sqlite_store import task_store


class LocalMCPProvider:
    """Local deterministic MCP-shaped adapter kept as the default provider."""

    def _root(self, root_path: str) -> Path:
        root = Path(root_path).expanduser().resolve()
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        return root

    def _safe_target(self, root_path: str, path: str = ".") -> tuple[Path, Path]:
        root = self._root(root_path)
        target = (root / path).resolve()
        if target != root and root not in target.parents:
            raise PermissionError("Refusing to access outside root path")
        return root, target

    def list_files(self, root_path: str, max_files: int = 200) -> dict[str, Any]:
        root = self._root(root_path)
        files = []
        for path in root.rglob("*"):
            if len(files) >= max_files:
                break
            if path.is_dir():
                continue
            if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
                continue
            files.append(path.relative_to(root).as_posix())
        return {"provider": "local", "root": root.as_posix(), "files": files}

    def read_file(self, root_path: str, file_path: str, max_chars: int = 4000) -> dict[str, Any]:
        root, target = self._safe_target(root_path, file_path)
        if not target.is_file():
            raise FileNotFoundError(str(target))
        content = target.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        return {"provider": "local", "root": root.as_posix(), "path": target.relative_to(root).as_posix(), "content": content}

    def list_directory(self, root_path: str, path: str = ".", limit: int = 100) -> dict[str, Any]:
        root, base = self._safe_target(root_path, path)
        if not base.is_dir():
            raise NotADirectoryError(str(base))
        entries = []
        for child in sorted(base.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if len(entries) >= limit:
                break
            if child.name in EXCLUDED_DIRS:
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": child.relative_to(root).as_posix(),
                    "type": "directory" if child.is_dir() else "file",
                }
            )
        return {"provider": "local", "root": root.as_posix(), "path": base.relative_to(root).as_posix() or ".", "entries": entries}

    def directory_tree(self, root_path: str, path: str = ".", max_depth: int = 2, limit: int = 200) -> dict[str, Any]:
        root, base = self._safe_target(root_path, path)
        if not base.is_dir():
            raise NotADirectoryError(str(base))
        tree = []
        for child in base.rglob("*"):
            relative_to_base = child.relative_to(base)
            relative_to_root = child.relative_to(root)
            if any(part in EXCLUDED_DIRS for part in relative_to_root.parts):
                continue
            if len(relative_to_base.parts) > max_depth:
                continue
            tree.append(
                {
                    "path": relative_to_root.as_posix(),
                    "type": "directory" if child.is_dir() else "file",
                    "depth": len(relative_to_base.parts),
                }
            )
            if len(tree) >= limit:
                break
        return {"provider": "local", "root": root.as_posix(), "path": base.relative_to(root).as_posix() or ".", "tree": tree}

    def search_files(self, root_path: str, query: str, path: str = ".", limit: int = 50) -> dict[str, Any]:
        root, base = self._safe_target(root_path, path)
        if not base.is_dir():
            raise NotADirectoryError(str(base))
        matches = []
        needle = query.lower()
        text_suffixes = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".txt", ".json", ".css", ".html", ".yml", ".yaml"}
        for child in base.rglob("*"):
            if len(matches) >= limit:
                break
            if not child.is_file():
                continue
            relative = child.relative_to(root)
            if any(part in EXCLUDED_DIRS for part in relative.parts):
                continue
            relative_text = relative.as_posix()
            matched = needle in relative_text.lower()
            snippet = ""
            if not matched and child.suffix.lower() in text_suffixes:
                text = child.read_text(encoding="utf-8", errors="ignore")
                index = text.lower().find(needle)
                matched = index >= 0
                if matched:
                    snippet = text[max(0, index - 80) : index + 160]
            if matched:
                matches.append({"path": relative_text, "snippet": snippet})
        return {"provider": "local", "root": root.as_posix(), "query": query, "matches": matches}

    def git_status(self, repo_path: str) -> dict[str, Any]:
        root = Path(repo_path).expanduser().resolve()
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        return {
            "provider": "local",
            "repo": root.as_posix(),
            "returncode": result.returncode,
            "stdout": result.stdout.splitlines(),
            "stderr": result.stderr,
        }

    def git_log(self, repo_path: str, limit: int = 10) -> dict[str, Any]:
        root = Path(repo_path).expanduser().resolve()
        result = subprocess.run(
            ["git", "-C", str(root), "log", f"-{limit}", "--oneline"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        return {
            "provider": "local",
            "repo": root.as_posix(),
            "returncode": result.returncode,
            "commits": result.stdout.splitlines(),
            "stderr": result.stderr,
        }


class RealMCPProvider:
    """Minimal stdio MCP client.

    It intentionally opens a short-lived connection per operation. That keeps the
    runtime deterministic for the current FastAPI app while still speaking the
    real MCP JSON-RPC protocol over stdio.
    """

    def status(self) -> dict[str, Any]:
        servers = task_store.list_mcp_servers()
        tools = task_store.list_mcp_tools()
        return {
            "provider": "mcp",
            "server_count": len(servers),
            "enabled_servers": len([item for item in servers if item.get("enabled")]),
            "tool_count": len(tools),
        }

    def save_server(self, server: dict[str, Any]) -> dict[str, Any]:
        return task_store.save_mcp_server(server)

    def list_servers(self) -> list[dict[str, Any]]:
        return task_store.list_mcp_servers()

    def set_server_enabled(self, server_id: str, enabled: bool) -> dict[str, Any] | None:
        status = "enabled" if enabled else "disabled"
        return task_store.update_mcp_server_status(server_id, status, None, enabled=enabled)

    def discover_tools(self, server_id: str) -> dict[str, Any]:
        server = self._enabled_server(server_id, require_enabled=False)
        started = time.perf_counter()
        try:
            result = self._request(server, "tools/list", {})
            tools = result.get("tools") if isinstance(result, dict) else []
            saved = []
            discovered_names: set[str] = set()
            for tool in tools or []:
                if not isinstance(tool, dict):
                    continue
                name = str(tool.get("name") or "").strip()
                if not name:
                    continue
                discovered_names.add(name)
                saved.append(
                    task_store.upsert_mcp_tool(
                        {
                            "server_id": server_id,
                            "name": name,
                            "description": tool.get("description"),
                            "input_schema": tool.get("inputSchema") or tool.get("input_schema") or {},
                            "enabled": True,
                            "status": "available",
                        }
                    )
                )
            task_store.prune_mcp_tools(server_id, discovered_names)
            task_store.update_mcp_server_status(server_id, "connected", None)
            return {"server_id": server_id, "status": "connected", "tools": saved, "latency_ms": self._elapsed_ms(started)}
        except Exception as exc:
            task_store.update_mcp_server_status(server_id, "failed", str(exc))
            raise

    def list_tools(self, server_id: str | None = None) -> list[dict[str, Any]]:
        return task_store.list_mcp_tools(server_id)

    def set_tool_enabled(self, server_id: str, tool_name: str, enabled: bool) -> dict[str, Any] | None:
        return task_store.update_mcp_tool_enabled(server_id, tool_name, enabled)

    def set_approval(self, agent_code: str, server_id: str, tool_name: str, allowed: bool, reason: str | None = None) -> dict[str, Any]:
        return task_store.set_mcp_tool_approval(agent_code, server_id, tool_name, allowed, reason)

    def check_approval(self, agent_code: str, server_id: str, tool_name: str) -> dict[str, Any]:
        approval = task_store.get_mcp_tool_approval(agent_code, server_id, tool_name)
        allowed = bool(approval and approval.get("allowed"))
        reason = approval.get("reason") if approval else "MCP tool has not been approved for this agent."
        return {"agent_code": agent_code, "server_id": server_id, "tool_name": tool_name, "allowed": allowed, "reason": reason}

    def call_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any] | None = None, agent_code: str = "workflow_runner") -> dict[str, Any]:
        call_id = f"mcp_call_{uuid4().hex}"
        started = time.perf_counter()
        arguments = arguments or {}
        try:
            server = self._enabled_server(server_id)
            tool = task_store.get_mcp_tool(server_id, tool_name)
            if tool and not tool.get("enabled"):
                raise PermissionError(f"MCP tool disabled: {server_id}:{tool_name}")
            approval = self.check_approval(agent_code, server_id, tool_name)
            if not approval["allowed"]:
                raise PermissionError(str(approval["reason"]))
            result = self._request(
                server,
                "tools/call",
                {"name": tool_name, "arguments": arguments},
            )
            output = {"provider": "mcp", "server_id": server_id, "tool_name": tool_name, "result": result}
            mcp_error = self._mcp_error_message(result)
            task_store.save_mcp_call_log(
                {
                    "call_id": call_id,
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "agent_code": agent_code,
                    "input": arguments,
                    "output": output,
                    "status": "failed" if mcp_error else "completed",
                    "error_message": mcp_error,
                    "latency_ms": self._elapsed_ms(started),
                    "created_at": utc_now_iso(),
                }
            )
            return {**output, "call_id": call_id, "status": "failed" if mcp_error else "completed", "error_message": mcp_error}
        except Exception as exc:
            task_store.save_mcp_call_log(
                {
                    "call_id": call_id,
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "agent_code": agent_code,
                    "input": arguments,
                    "output": {},
                    "status": "failed",
                    "error_message": str(exc),
                    "latency_ms": self._elapsed_ms(started),
                    "created_at": utc_now_iso(),
                }
            )
            raise

    def list_call_logs(self, limit: int = 100, server_id: str | None = None) -> list[dict[str, Any]]:
        return task_store.list_mcp_call_logs(limit=limit, server_id=server_id)

    def _mcp_error_message(self, result: dict[str, Any]) -> str | None:
        if not result.get("isError"):
            return None
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    return item["text"]
        return "MCP tool returned isError=true"

    def _enabled_server(self, server_id: str, *, require_enabled: bool = True) -> dict[str, Any]:
        server = task_store.get_mcp_server(server_id)
        if not server:
            raise KeyError(f"MCP server not found: {server_id}")
        if require_enabled and not server.get("enabled"):
            raise PermissionError(f"MCP server disabled: {server_id}")
        if server.get("transport") != "stdio":
            raise NotImplementedError("Only stdio MCP transport is supported in this phase")
        if not server.get("command"):
            raise ValueError("MCP stdio server command is required")
        return server

    def _request(self, server: dict[str, Any], method: str, params: dict[str, Any]) -> dict[str, Any]:
        command = [str(server["command"]), *[str(item) for item in server.get("args", [])]]
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in (server.get("env") or {}).items()})
        messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        stderr_chunks: list[bytes] = []
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            env=env,
        )
        reader = threading.Thread(target=self._read_messages, args=(process, messages), daemon=True)
        reader.start()
        stderr_reader = threading.Thread(target=self._read_stderr, args=(process, stderr_chunks), daemon=True)
        stderr_reader.start()
        try:
            request_id = 1
            self._write_message(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "ValuSee", "version": "0.1.0"},
                    },
                },
            )
            self._read_response(messages, request_id, stderr_chunks)
            self._write_message(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            request_id += 1
            self._write_message(process, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            return self._read_response(messages, request_id, stderr_chunks)
        finally:
            try:
                process.terminate()
            except Exception:
                pass

    def _write_message(self, process: subprocess.Popen[bytes], payload: dict[str, Any]) -> None:
        if not process.stdin:
            raise RuntimeError("MCP process stdin is not available")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        process.stdin.write(body + b"\n")
        process.stdin.flush()

    def _read_response(
        self,
        messages: queue.Queue[dict[str, Any] | None],
        request_id: int,
        stderr_chunks: list[bytes],
        timeout_seconds: float = 15.0,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        while time.perf_counter() - started < timeout_seconds:
            try:
                message = messages.get(timeout=0.25)
            except queue.Empty:
                continue
            if not message:
                continue
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
            result = message.get("result")
            return result if isinstance(result, dict) else {"result": result}
        stderr = b"".join(stderr_chunks).decode("utf-8", errors="ignore")
        raise TimeoutError(f"MCP request timed out: {stderr}")

    def _read_messages(self, process: subprocess.Popen[bytes], messages: queue.Queue[dict[str, Any] | None]) -> None:
        while True:
            try:
                message = self._read_message(process)
            except Exception:
                message = None
            if not message:
                messages.put(None)
                return
            messages.put(message)

    def _read_message(self, process: subprocess.Popen[bytes]) -> dict[str, Any] | None:
        if not process.stdout:
            raise RuntimeError("MCP process stdout is not available")
        first_line = process.stdout.readline()
        if not first_line:
            return None
        if not first_line.lower().startswith(b"content-length:"):
            text = first_line.decode("utf-8", errors="ignore").strip()
            if not text:
                return None
            return json.loads(text)
        headers: dict[str, str] = {}
        text = first_line.decode("ascii", errors="ignore").strip()
        key, value = text.split(":", 1)
        headers[key.lower()] = value.strip()
        while True:
            line = process.stdout.readline()
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
        body = process.stdout.read(length)
        return json.loads(body.decode("utf-8"))

    def _read_stderr(self, process: subprocess.Popen[bytes], stderr_chunks: list[bytes]) -> None:
        if not process.stderr:
            return
        while True:
            chunk = process.stderr.readline()
            if not chunk:
                return
            stderr_chunks.append(chunk)

    def _elapsed_ms(self, started: float) -> int:
        return max(0, int((time.perf_counter() - started) * 1000))


class MCPProvider:
    """Facade selected by DEV_AGENT_MCP_PROVIDER=local|mcp."""

    def __init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[2]
        self.env_path = self.project_root / ".env"
        self.local = LocalMCPProvider()
        self.real = RealMCPProvider()

    @property
    def provider_kind(self) -> str:
        return (os.getenv("DEV_AGENT_MCP_PROVIDER") or self._read_env_file().get("DEV_AGENT_MCP_PROVIDER") or "local").strip().lower()

    def status(self) -> dict[str, Any]:
        if self.provider_kind == "mcp":
            return self.real.status()
        return {"provider": "local", "server_count": 0, "tool_count": 4}

    def list_files(self, root_path: str, max_files: int = 200) -> dict[str, Any]:
        return self.local.list_files(root_path, max_files)

    def read_file(self, root_path: str, file_path: str, max_chars: int = 4000) -> dict[str, Any]:
        return self.local.read_file(root_path, file_path, max_chars)

    def git_status(self, repo_path: str) -> dict[str, Any]:
        return self.local.git_status(repo_path)

    def git_log(self, repo_path: str, limit: int = 10) -> dict[str, Any]:
        return self.local.git_log(repo_path, limit)

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None, *, server_id: str | None = None, agent_code: str = "workflow_runner") -> dict[str, Any]:
        if self.provider_kind == "mcp":
            if not server_id:
                raise ValueError("server_id is required when DEV_AGENT_MCP_PROVIDER=mcp")
            return self.real.call_tool(server_id, tool_name, arguments, agent_code=agent_code)
        return self._call_local_tool(tool_name, arguments or {})

    def _call_local_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        root_path = str(arguments.get("root_path") or arguments.get("repo_path") or ".")
        if tool_name in {"filesystem.read", "read_file"}:
            return self.read_file(root_path, str(arguments.get("file_path") or arguments.get("path") or "README.md"), int(arguments.get("max_chars") or 4000))
        if tool_name in {"filesystem.list", "list_directory"}:
            if "path" in arguments:
                return self.local.list_directory(root_path, str(arguments.get("path") or "."), int(arguments.get("limit") or 100))
            return self.list_files(root_path, int(arguments.get("max_files") or arguments.get("limit") or 200))
        if tool_name == "directory_tree":
            return self.local.directory_tree(root_path, str(arguments.get("path") or "."), int(arguments.get("max_depth") or 2), int(arguments.get("limit") or 200))
        if tool_name == "search_files":
            return self.local.search_files(root_path, str(arguments.get("query") or ""), str(arguments.get("path") or "."), int(arguments.get("limit") or 50))
        if tool_name == "git.status":
            return self.git_status(root_path)
        if tool_name == "git.log":
            return self.git_log(root_path, int(arguments.get("limit") or 10))
        return self.list_files(root_path, int(arguments.get("max_files") or 200))

    def _read_env_file(self) -> dict[str, str]:
        if not self.env_path.exists():
            return {}
        values: dict[str, str] = {}
        for raw_line in self.env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
        return values


mcp_provider = MCPProvider()
