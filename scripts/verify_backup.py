from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def verify_backup(directory: Path) -> dict[str, object]:
    from app.core.backup_verification import verify_backup as verify

    return verify(directory)


def main() -> None:
    from app.core.backup_verification import main as run

    run()


if __name__ == "__main__":
    main()
