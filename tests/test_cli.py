"""End-to-end tests for the portable workspace CLI.

Run from the project root:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "src" / "workspace_tool.py"

LOG = """# 全局复用与踩坑日志

## 经验索引

### 现行条目（0 条）

| 编号 | 日期 | 类型 | 标题 | 位置 |
| --- | --- | --- | --- | --- |

## 记录
"""

BOARD = """# 全局工作台

## 项目登记与接续入口

| 编号 | 目录 | 当前状态 | 接续入口 |
| --- | --- | --- | --- |
"""

SOP = "# 新项目创建 SOP\n\n## 1. 启动前阅读与确认\n\n## 2. 编号和建目录\n"

AGENTS = "# 规则\n\n启动前读四份文档。\n"


class WorkspaceCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "全局复用与踩坑日志.md").write_text(LOG, encoding="utf-8")
        (self.root / "全局工作台.md").write_text(BOARD, encoding="utf-8")
        (self.root / "新项目创建SOP.md").write_text(SOP, encoding="utf-8")
        (self.root / "AGENTS.md").write_text(AGENTS, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "test"], cwd=self.root, check=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, AGENT_WORKSPACE_ROOT=str(self.root), PYTHONIOENCODING="utf-8")
        return subprocess.run(
            ["python", str(TOOL), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=60,
        )

    def test_status_on_empty_workspace(self) -> None:
        result = self.run_tool("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Workspace", result.stdout)

    def test_exp_add_assigns_sequential_ids(self) -> None:
        first = self.run_tool("exp", "add", "--title", "第一条", "--phenomenon", "现象一")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("EXP-001", first.stdout)
        second = self.run_tool("exp", "add", "--title", "第二条", "--cause", "原因二")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("EXP-002", second.stdout)
        log = (self.root / "全局复用与踩坑日志.md").read_text(encoding="utf-8")
        self.assertIn("EXP-001", log)
        self.assertIn("EXP-002", log)
        self.assertIn("现行条目（2 条）", log)

    def test_exp_update_appends_note(self) -> None:
        self.run_tool("exp", "add", "--title", "待更新")
        result = self.run_tool("exp", "update", "EXP-001", "--note", "补一条新证据")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.root / "全局复用与踩坑日志.md").read_text(encoding="utf-8")
        self.assertIn("补一条新证据", log)

    def test_search_finds_added_experience(self) -> None:
        self.run_tool("exp", "add", "--title", "docker 挂载权限不足")
        result = self.run_tool("exp", "search", "docker")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("docker 挂载权限不足", result.stdout)

    def test_project_new_creates_directory_and_registers(self) -> None:
        result = self.run_tool("project", "new", "演示项目", "--owner", "tester")
        self.assertEqual(result.returncode, 0, result.stderr)
        dirs = [p for p in self.root.iterdir() if p.is_dir() and p.name.startswith("Project_")]
        self.assertEqual(len(dirs), 1, dirs)
        self.assertTrue((dirs[0] / "README.md").is_file())
        board = (self.root / "全局工作台.md").read_text(encoding="utf-8")
        self.assertIn("演示项目", board)

    def test_handoff_writes_project_docs(self) -> None:
        self.run_tool("project", "new", "交接项目", "--owner", "tester")
        proj = next(p for p in self.root.iterdir() if p.is_dir() and p.name.startswith("Project_"))
        result = self.run_tool(
            "handoff", proj.name[:10],
            "--agent", "tester",
            "--status", "进行中",
            "--done", "完成第一项",
            "--evidence", "tmp/a.log",
            "--todo", "继续第二项",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        handoff = proj / "docs" / "当前状态与交接.md"
        self.assertTrue(handoff.is_file())
        self.assertIn("完成第一项", handoff.read_text(encoding="utf-8"))

    def test_commit_reports_nothing_to_do_when_clean(self) -> None:
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=self.root, check=True)
        result = self.run_tool("commit", "-m", "noop")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("无需提交", result.stdout)


if __name__ == "__main__":
    unittest.main()
