"""Safe SQLite backup, restore, verification, and disposable recovery drill."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def verify(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result != ("ok",):
        raise RuntimeError(f"integrity check failed: {result}")


def backup(source: Path, target: Path) -> None:
    verify(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)
    verify(target)


def restore(target: Path, source: Path) -> Path | None:
    verify(source)
    preserved = None
    if target.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        preserved = target.with_name(f"{target.name}.before-restore-{stamp}")
        shutil.move(target, preserved)
    backup(source, target)
    return preserved


def drill() -> None:
    with tempfile.TemporaryDirectory() as raw_dir:
        root = Path(raw_dir)
        original = root / "original.db"
        snapshot = root / "snapshot.db"
        with sqlite3.connect(original) as connection:
            connection.execute("CREATE TABLE proof(value TEXT NOT NULL)")
            connection.execute("INSERT INTO proof VALUES ('recoverable')")
        backup(original, snapshot)
        original.unlink()
        restore(original, snapshot)
        verify(original)
        with sqlite3.connect(original) as connection:
            assert connection.execute("SELECT value FROM proof").fetchone() == ("recoverable",)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("backup", "restore"):
        child = subparsers.add_parser(command)
        child.add_argument("source", type=Path)
        child.add_argument("target", type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("path", type=Path)
    subparsers.add_parser("drill")
    args = parser.parse_args()
    if args.command == "backup":
        backup(args.source, args.target)
    elif args.command == "restore":
        restore(args.target, args.source)
    elif args.command == "verify":
        verify(args.path)
    else:
        drill()


if __name__ == "__main__":
    main()
