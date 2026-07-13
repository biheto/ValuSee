from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4


SANDBOX_RUNNER = r"""
import importlib.util
import json
import sys
from pathlib import Path

entrypoint_path = Path(sys.argv[1]).resolve()
function_name = sys.argv[2]
input_path = Path(sys.argv[3])
output_path = Path(sys.argv[4])

payload = json.loads(input_path.read_text(encoding="utf-8"))
spec = importlib.util.spec_from_file_location("devagent_external_skill", entrypoint_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load skill entrypoint: {entrypoint_path}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
handler = getattr(module, function_name, None)
if handler is None:
    raise RuntimeError(f"Entrypoint function not found: {function_name}")
result = handler(payload)
if not isinstance(result, dict):
    result = {"result": result}
output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
"""


def run_python_skill_sandbox(
    entrypoint_path: str,
    function_name: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    config = _sandbox_config()
    if config["mode"] == "docker":
        try:
            return run_python_skill_docker_sandbox(
                entrypoint_path,
                function_name,
                payload,
                timeout_seconds=timeout_seconds,
                image=config["docker_image"],
                memory=config["memory"],
                cpus=config["cpus"],
                pids_limit=config["pids_limit"],
            )
        except Exception:
            if not config["fallback"]:
                raise
    return run_python_skill_subprocess_sandbox(
        entrypoint_path,
        function_name,
        payload,
        timeout_seconds=timeout_seconds,
    )


def run_python_skill_subprocess_sandbox(
    entrypoint_path: str,
    function_name: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    path = Path(entrypoint_path).resolve()
    if not path.exists() or path.suffix.lower() != ".py":
        raise FileNotFoundError(f"Python skill entrypoint not found: {entrypoint_path}")
    with tempfile.TemporaryDirectory(prefix="devagent_skill_") as temp_dir:
        temp = Path(temp_dir)
        input_path = temp / "input.json"
        output_path = temp / "output.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                SANDBOX_RUNNER,
                str(path),
                function_name or "run",
                str(input_path),
                str(output_path),
            ],
            cwd=temp,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Python skill failed").strip()
            raise RuntimeError(message[:2000])
        if not output_path.exists():
            raise RuntimeError("Python skill completed without output.json")
        output = json.loads(output_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(output, dict):
            return {"result": output}
        return output


def run_python_skill_docker_sandbox(
    entrypoint_path: str,
    function_name: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int = 10,
    image: str = "python:3.13-slim",
    memory: str = "256m",
    cpus: str = "0.5",
    pids_limit: int = 64,
) -> dict[str, Any]:
    path = Path(entrypoint_path).resolve()
    if not path.exists() or path.suffix.lower() != ".py":
        raise FileNotFoundError(f"Python skill entrypoint not found: {entrypoint_path}")
    if shutil.which("docker") is None:
        raise RuntimeError("Docker sandbox is enabled but docker CLI was not found.")

    entry_dir = path.parent
    entry_name = path.name
    with tempfile.TemporaryDirectory(prefix="devagent_skill_docker_") as temp_dir:
        temp = Path(temp_dir).resolve()
        container_name = f"devagent-skill-{uuid4().hex[:12]}"
        input_path = temp / "input.json"
        output_path = temp / "output.json"
        runner_path = temp / "runner.py"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        runner_path.write_text(SANDBOX_RUNNER, encoding="utf-8")
        os.chmod(temp, 0o777)
        os.chmod(input_path, 0o666)
        os.chmod(runner_path, 0o644)
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--memory",
            memory,
            "--cpus",
            cpus,
            "--pids-limit",
            str(pids_limit),
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--tmpfs",
            "/tmp:rw,nosuid,size=64m",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-v",
            f"{_docker_path(temp)}:/sandbox:rw",
            "-v",
            f"{_docker_path(entry_dir)}:/workspace/skill:ro",
            image,
            "python",
            "-I",
            "/sandbox/runner.py",
            f"/workspace/skill/{entry_name}",
            function_name or "run",
            "/sandbox/input.json",
            "/sandbox/output.json",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=temp,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 3,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True, check=False)
            raise TimeoutError(f"Docker skill timed out after {timeout_seconds}s") from exc
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "Docker skill failed").strip()
            raise RuntimeError(message[:2000])
        if not output_path.exists():
            raise RuntimeError("Docker skill completed without output.json")
        output = json.loads(output_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(output, dict):
            return {"result": output}
        return output


def _sandbox_config() -> dict[str, Any]:
    values = _read_env_file()
    values.update({key: value for key, value in os.environ.items() if key.startswith("DEV_AGENT_SKILL_SANDBOX")})
    return {
        "mode": values.get("DEV_AGENT_SKILL_SANDBOX", "subprocess").strip().lower(),
        "docker_image": values.get("DEV_AGENT_SKILL_SANDBOX_IMAGE", "python:3.13-slim").strip() or "python:3.13-slim",
        "memory": values.get("DEV_AGENT_SKILL_SANDBOX_MEMORY", "256m").strip() or "256m",
        "cpus": values.get("DEV_AGENT_SKILL_SANDBOX_CPUS", "0.5").strip() or "0.5",
        "pids_limit": int(values.get("DEV_AGENT_SKILL_SANDBOX_PIDS_LIMIT", "64") or 64),
        "fallback": values.get("DEV_AGENT_SKILL_SANDBOX_FALLBACK", "false").strip().lower() in {"1", "true", "yes", "on"},
    }


def python_skill_sandbox_status() -> dict[str, Any]:
    config = _sandbox_config()
    return {
        "mode": config["mode"],
        "docker_image": config["docker_image"] if config["mode"] == "docker" else None,
        "network": "none" if config["mode"] == "docker" else "host-process",
        "read_only_root": config["mode"] == "docker",
        "memory": config["memory"] if config["mode"] == "docker" else None,
        "cpus": config["cpus"] if config["mode"] == "docker" else None,
        "pids_limit": config["pids_limit"] if config["mode"] == "docker" else None,
        "fallback_enabled": config["fallback"],
    }


def _read_env_file() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _docker_path(path: Path) -> str:
    text = str(path)
    if os.name == "nt":
        return text.replace("\\", "/")
    return text
