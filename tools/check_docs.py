"""Validate relative Markdown links and documented Make targets."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"\[[^]]*]\(([^)]+)\)")
MAKE_RE = re.compile(r"(?:^|[\s`])make\s+([a-zA-Z][a-zA-Z0-9_-]*)")


def make_targets() -> set[str]:
    return set(re.findall(r"^([a-zA-Z][a-zA-Z0-9_-]*):", (ROOT / "Makefile").read_text(), re.M))


def validate(paths: tuple[Path, ...] | None = None) -> list[str]:
    root_documents = tuple(
        path for path in (ROOT / "README.md", ROOT / "CONTRIBUTING.md") if path.exists()
    )
    documents = paths or root_documents + tuple((ROOT / "docs").glob("*.md"))
    targets = make_targets()
    errors: list[str] = []
    for document in documents:
        label = document.relative_to(ROOT) if document.is_relative_to(ROOT) else document
        text = document.read_text(encoding="utf-8")
        for raw_link in LINK_RE.findall(text):
            link = raw_link.split("#", 1)[0]
            if not link or "://" in link or link.startswith("mailto:"):
                continue
            if not (document.parent / link).resolve().exists():
                errors.append(f"{label}: missing link {raw_link}")
        for target in MAKE_RE.findall(text):
            if target not in targets:
                errors.append(f"{label}: unknown make target {target}")
    return errors


def main() -> None:
    errors = validate()
    if errors:
        raise SystemExit("\n".join(errors))


if __name__ == "__main__":
    main()
