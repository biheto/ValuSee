from pathlib import Path

from app.core.paths import runtime_data_dir, runtime_root


def test_runtime_root_uses_vercel_tmp(monkeypatch):
    monkeypatch.delenv("VALUSee_DATA_DIR", raising=False)
    monkeypatch.setenv("VERCEL", "1")
    assert runtime_root() == Path("/tmp/valuesee")


def test_configured_runtime_root_takes_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VALUSee_DATA_DIR", str(tmp_path))
    assert runtime_root() == tmp_path.resolve()
    assert runtime_data_dir("uploads") == tmp_path.resolve() / "data" / "uploads"
