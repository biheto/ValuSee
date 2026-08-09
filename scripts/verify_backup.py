from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path


REQUIRED_FILES = {"postgres.sql", "minio-data.tgz", "attachments.tgz"}


def verify_backup(directory: Path) -> dict[str, object]:
    root = directory.resolve(strict=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    entries = manifest.get("files") if isinstance(manifest, dict) else manifest
    if not isinstance(entries, list):
        raise ValueError("backup manifest files must be a list")
    names = {str(item.get("file") or "") for item in entries if isinstance(item, dict)}
    missing = REQUIRED_FILES - names
    if missing:
        raise ValueError(f"backup manifest is missing required files: {', '.join(sorted(missing))}")
    for item in entries:
        name = str(item.get("file") or "")
        if not name or Path(name).name != name:
            raise ValueError("backup manifest contains an unsafe file name")
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root) or path.stat().st_size <= 0:
            raise ValueError(f"backup file is empty or unsafe: {name}")
        expected_size = int(item.get("bytes") or 0)
        if expected_size and path.stat().st_size != expected_size:
            raise ValueError(f"backup size mismatch: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest.lower() != str(item.get("sha256") or "").lower():
            raise ValueError(f"backup checksum mismatch: {name}")
        if name.endswith(".tgz"):
            _verify_tar(path)
    return {"status": "ok", "files": len(entries), "bytes": sum((root / name).stat().st_size for name in names)}


def _verify_tar(path: Path) -> None:
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            value = Path(member.name)
            if value.is_absolute() or ".." in value.parts or member.issym() or member.islnk():
                raise ValueError(f"backup archive contains an unsafe member: {member.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a ValuSee production backup without restoring it.")
    parser.add_argument("backup_directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_backup(args.backup_directory), separators=(",", ":")))


if __name__ == "__main__":
    main()
