from __future__ import annotations

import os
from pathlib import Path


def runtime_root() -> Path:
    """Return a writable root for mutable runtime data."""
    configured = os.getenv("VALUSee_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if os.getenv("VERCEL", "").strip():
        return Path("/tmp/valuesee")
    return Path.cwd()


def runtime_data_dir(*parts: str) -> Path:
    path = runtime_root() / "data"
    if parts:
        path = path.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
