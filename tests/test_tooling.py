from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.check_docs import validate
from tools.sqlite_ops import backup, drill, main, restore, verify


def test_document_validator_detects_links_and_make_targets(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    target = tmp_path / "target.md"
    target.write_text("ok", encoding="utf-8")
    good.write_text("[ok](target.md)", encoding="utf-8")
    assert validate((good,)) == []
    bad = tmp_path / "bad.md"
    bad.write_text("[missing](none.md)\n`make nonexistent-target`", encoding="utf-8")
    errors = validate((bad,))
    assert any("missing link" in error for error in errors)
    assert any("unknown make target" in error for error in errors)


def test_sqlite_backup_restore_and_drill(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    snapshot = tmp_path / "snapshot.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE proof(value TEXT)")
        connection.execute("INSERT INTO proof VALUES ('ok')")
    backup(source, snapshot)
    preserved = restore(source, snapshot)
    assert preserved is not None and preserved.exists()
    verify(source)
    drill()


def test_sqlite_verify_rejects_missing_and_corrupt_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        verify(tmp_path / "missing.db")
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_text("not sqlite", encoding="utf-8")
    with pytest.raises(sqlite3.DatabaseError):
        verify(corrupt)


@pytest.mark.parametrize(
    ("args", "called"),
    [
        (["backup", "a", "b"], "backup"),
        (["restore", "a", "b"], "restore"),
        (["verify", "a"], "verify"),
        (["drill"], "drill"),
    ],
)
def test_sqlite_cli_dispatch(args: list[str], called: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("sys.argv", ["sqlite_ops.py", *args])
    for name in ("backup", "restore", "verify", "drill"):
        monkeypatch.setattr(f"tools.sqlite_ops.{name}", lambda *_, n=name: calls.append(n))
    main()
    assert calls == [called]
