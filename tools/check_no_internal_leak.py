#!/usr/bin/env python3
"""防泄露守卫：拦截对内 / 营销 / 销售材料进入公开仓库。

两类检查：
1. 路径黑名单 —— 某些文件根本不该出现在公开仓库（应放私有仓库 / 营销渠道）。
2. 内容黑名单 —— 文件里出现「销售口径」这类内部专用措辞即拦截。

用法：
    python3 tools/check_no_internal_leak.py            # 扫所有 git 跟踪文件（CI 用）
    python3 tools/check_no_internal_leak.py a.md b.py   # 只扫指定文件（pre-commit 用）

判据与清单见 CONTRIBUTING.md（公开）/ PUBLISHING-CHECKLIST.md（私有仓库）。
"""

from __future__ import annotations

import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

# 这些文件本身在描述/实现本策略，允许包含下列关键词，跳过扫描。
_ALLOWLIST: frozenset[str] = frozenset(
    {
        "CONTRIBUTING.md",
        "tools/check_no_internal_leak.py",
        "tests/test_check_no_internal_leak.py",
    }
)

# 不该进公开仓库的路径（fnmatch glob）。
_DENIED_PATH_GLOBS: tuple[str, ...] = (
    "docs/PRD.md",
    "docs/MARKETING.md",
    "docs/DEMO_SCRIPT.md",
    "docs/RUNBOOK_DEMO.md",
    "docs/FALLBACK_VIDEO.md",
    "docs/TODO.md",
    "docs/blog/*",  # 博客=营销内容，发公众号/官网，不进代码仓库
    "docs/blog/**",
    "src/sales/*",
    "src/sales/**",
    "tools/qualify_lead.py",
)

# 内部专用措辞（出现即拦）。刻意只取唯一性强的词，避免误伤公开定价/技术文档。
_CONTENT_MARKERS: dict[str, str] = {
    "销售口径": "内部销售口径",
    "全采纳": "ROI 全采纳假设（内部口径）",
    "净赚": "销售话术（净赚 N 倍）",
    "投放话术": "渠道投放 playbook",
}

_TEXT_SUFFIXES: frozenset[str] = frozenset(
    {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ""}
)


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def path_violation(path: str) -> str | None:
    for glob in _DENIED_PATH_GLOBS:
        if fnmatch(path, glob):
            return f"路径不该进公开仓库（放私有仓库/营销渠道）：匹配 {glob!r}"
    return None


def content_violations(path: str) -> list[str]:
    p = Path(path)
    if p.suffix.lower() not in _TEXT_SUFFIXES:
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError):
        return []
    hits: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for marker, label in _CONTENT_MARKERS.items():
            if marker in line:
                hits.append(f"{path}:{lineno} 命中内部措辞「{marker}」（{label}）")
    return hits


def check(paths: list[str]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        if path in _ALLOWLIST:
            continue
        pv = path_violation(path)
        if pv:
            problems.append(f"{path} — {pv}")
            continue
        problems.extend(content_violations(path))
    return problems


def main(argv: list[str]) -> int:
    paths = argv or _tracked_files()
    problems = check(paths)
    if problems:
        print("✗ 检测到不该进公开仓库的内容：\n", file=sys.stderr)
        for prob in problems:
            print("  - " + prob, file=sys.stderr)
        print(
            "\n营销/销售/对内材料请放私有仓库或发到公众号/官网。判据见 CONTRIBUTING.md。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
