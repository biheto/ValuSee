from pathlib import Path

from app.core.database import connect_database


def test_sqlite_path_can_be_isolated_by_environment(monkeypatch, tmp_path: Path):
    isolated = tmp_path / "isolated.db"
    default = tmp_path / "must-not-be-created.db"
    monkeypatch.setenv("VALUSee_SQLITE_PATH", str(isolated))

    connection = connect_database(default)
    try:
        connection.execute("CREATE TABLE isolation_check(value TEXT)")
        connection.commit()
    finally:
        connection.close()

    assert isolated.exists()
    assert not default.exists()
