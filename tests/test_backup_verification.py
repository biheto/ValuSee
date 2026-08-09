import hashlib
import io
import json
import tarfile

import pytest

from scripts.verify_backup import verify_backup


def make_backup(tmp_path, unsafe_tar=False):
    files = {}
    sql = tmp_path / "postgres.sql"
    sql.write_text("SELECT 1;", encoding="utf-8")
    files[sql.name] = sql
    for name in ("minio-data.tgz", "attachments.tgz"):
        path = tmp_path / name
        with tarfile.open(path, "w:gz") as archive:
            content = b"content"
            info = tarfile.TarInfo("../escape" if unsafe_tar and name == "minio-data.tgz" else "data/file.txt")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        files[name] = path
    manifest = {
        "version": 1,
        "files": [
            {"file": name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for name, path in files.items()
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_backup_verifier_accepts_complete_safe_backup(tmp_path):
    make_backup(tmp_path)
    result = verify_backup(tmp_path)
    assert result["status"] == "ok" and result["files"] == 3


def test_backup_verifier_rejects_checksum_mismatch(tmp_path):
    make_backup(tmp_path)
    (tmp_path / "postgres.sql").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="size mismatch|checksum mismatch"):
        verify_backup(tmp_path)


def test_backup_verifier_rejects_archive_path_traversal(tmp_path):
    make_backup(tmp_path, unsafe_tar=True)
    with pytest.raises(ValueError, match="unsafe member"):
        verify_backup(tmp_path)
