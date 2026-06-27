"""防泄露守卫的测试 —— 跑实际 CLI，验证拦得住坏内容、放得过干净内容。

（tools/ 不在 --cov=src 范围内，这些测试只验证行为，不计入覆盖率。）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "check_no_internal_leak.py"


def _run(*paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *paths],
        capture_output=True,
        text=True,
    )


class TestContentMarkers:
    def test_internal_phrase_is_blocked(self, tmp_path: Path) -> None:
        f = tmp_path / "note.md"
        f.write_text("我们的销售口径会说净赚 4-6 倍\n", encoding="utf-8")
        result = _run(str(f))
        assert result.returncode == 1
        assert "销售口径" in result.stderr

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "readme.md"
        f.write_text("# 产品介绍\n年损 100-300 万推荐商业版，ROI 2-4×。\n", encoding="utf-8")
        result = _run(str(f))
        assert result.returncode == 0, result.stderr


class TestPathDenylist:
    def test_denied_path_is_blocked(self, tmp_path: Path) -> None:
        # 路径匹配走的是传入的字符串，不依赖文件真实存在
        result = _run("docs/PRD.md")
        assert result.returncode == 1
        assert "docs/PRD.md" in result.stderr

    def test_blog_path_is_blocked(self) -> None:
        result = _run("docs/blog/2026-06-04-some-article.md")
        assert result.returncode == 1

    def test_allowed_path_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "docs_TECH_SPEC.md"
        f.write_text("# 技术规格\nFastAPI + APScheduler。\n", encoding="utf-8")
        result = _run(str(f))
        assert result.returncode == 0, result.stderr


class TestAllowlist:
    def test_policy_doc_with_marker_is_skipped(self) -> None:
        # CONTRIBUTING.md 在白名单里，即便含"销售口径"也不应被拦
        result = _run("CONTRIBUTING.md")
        assert result.returncode == 0, result.stderr


class TestWholeRepo:
    def test_current_tree_is_clean(self) -> None:
        # 无参数 → 扫所有 git 跟踪文件；当前公开仓库应全干净
        result = _run()
        assert result.returncode == 0, result.stderr
