"""End-to-end tests for the portable workspace CLI.

Run from the project root:
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
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


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)


class WorkspaceCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "全局复用与踩坑日志.md").write_text(LOG, encoding="utf-8")
        (self.root / "全局工作台.md").write_text(BOARD, encoding="utf-8")
        (self.root / "新项目创建SOP.md").write_text(SOP, encoding="utf-8")
        (self.root / "AGENTS.md").write_text(AGENTS, encoding="utf-8")
        _init_git(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_tool(
        self,
        *args: str,
        root: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        target_root = root or self.root
        env = dict(os.environ, AGENT_WORKSPACE_ROOT=str(target_root), PYTHONIOENCODING="utf-8")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            cwd=target_root,
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

    def test_exp_tags_add_search_and_list(self) -> None:
        r1 = self.run_tool(
            "exp", "add",
            "--title", "容器挂载权限不足",
            "--tag", "docker,linux",
            "--phenomenon", "Permission denied",
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        r2 = self.run_tool(
            "exp", "add",
            "--title", "串口波特率不匹配",
            "--tag", "hardware",
            "--tag", "linux",
        )
        self.assertEqual(r2.returncode, 0, r2.stderr)

        by_tag = self.run_tool("exp", "search", "--tag", "docker")
        self.assertEqual(by_tag.returncode, 0, by_tag.stderr)
        self.assertIn("EXP-001", by_tag.stdout)
        self.assertNotIn("EXP-002", by_tag.stdout)

        combined = self.run_tool("exp", "search", "串口", "--tag", "linux")
        self.assertEqual(combined.returncode, 0, combined.stderr)
        self.assertIn("EXP-002", combined.stdout)
        self.assertNotIn("EXP-001", combined.stdout)

        tag_list = self.run_tool("exp", "search", "--list-tags")
        self.assertEqual(tag_list.returncode, 0, tag_list.stderr)
        self.assertIn("#linux", tag_list.stdout)
        self.assertIn("#docker", tag_list.stdout)
        self.assertIn("#hardware", tag_list.stdout)

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

    def test_commit_reports_nothing_to_do_when_clean_and_skips_lock_file(self) -> None:
        commit_res = self.run_tool("commit", "-m", "init workspace")
        self.assertEqual(commit_res.returncode, 0, commit_res.stderr)

        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        self.assertNotIn(".workspace.lock", tracked)

        noop = self.run_tool("commit", "-m", "noop")
        self.assertEqual(noop.returncode, 0, noop.stderr)
        self.assertIn("无需提交", noop.stdout)

    def test_guard_and_status_guard_detect_dirty_tree(self) -> None:
        dirty = self.run_tool("guard")
        self.assertEqual(dirty.returncode, 1)
        self.assertIn("GUARD WARNING", dirty.stdout)

        status_dirty = self.run_tool("status", "--guard")
        self.assertEqual(status_dirty.returncode, 1)
        self.assertIn("GUARD WARNING", status_dirty.stdout)

        self.run_tool("commit", "-m", "clean baseline")

        clean = self.run_tool("guard")
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertIn("GUARD OK", clean.stdout)

        status_clean = self.run_tool("status", "--guard")
        self.assertEqual(status_clean.returncode, 0, status_clean.stderr)

    def test_init_english_skeleton_and_full_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as fresh:
            fresh_root = Path(fresh)
            init_res = self.run_tool("init", "--lang", "en", root=fresh_root)
            self.assertEqual(init_res.returncode, 0, init_res.stderr)
            self.assertTrue((fresh_root / "AGENTS.md").is_file())
            self.assertTrue((fresh_root / "WORKSPACE.md").is_file())
            self.assertTrue((fresh_root / "EXPERIENCES.md").is_file())
            self.assertTrue((fresh_root / "NEW_PROJECT_SOP.md").is_file())
            self.assertTrue((fresh_root / "workspace.config.json").is_file())
            self.assertTrue((fresh_root / ".git").is_dir())

            # Configure git identity in fresh repo for commit check
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=fresh_root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=fresh_root, check=True)

            # Re-running init should be idempotent and never overwrite existing files
            (fresh_root / "AGENTS.md").write_text("# Custom Rule\n", encoding="utf-8")
            reinit = self.run_tool("init", "--lang", "en", root=fresh_root)
            self.assertEqual(reinit.returncode, 0, reinit.stderr)
            self.assertEqual((fresh_root / "AGENTS.md").read_text(encoding="utf-8"), "# Custom Rule\n")

            add_res = self.run_tool("exp", "add", "--title", "Cache miss on CI", "--tag", "ci", root=fresh_root)
            self.assertEqual(add_res.returncode, 0, add_res.stderr)
            log = (fresh_root / "EXPERIENCES.md").read_text(encoding="utf-8")
            self.assertIn("Active Entries (1)", log)
            self.assertIn("EXP-001", log)
            self.assertIn("#ci", log)

            proj_res = self.run_tool("project", "new", "DemoService", "--owner", "codex", root=fresh_root)
            self.assertEqual(proj_res.returncode, 0, proj_res.stderr)
            board = (fresh_root / "WORKSPACE.md").read_text(encoding="utf-8")
            self.assertIn("Project_001_DemoService", board)

            commit_res = self.run_tool("commit", "-m", "initial en workspace", root=fresh_root)
            self.assertEqual(commit_res.returncode, 0, commit_res.stderr)
            guard_res = self.run_tool("guard", root=fresh_root)
            self.assertEqual(guard_res.returncode, 0, guard_res.stderr)

    def test_concurrent_exp_add_is_serialized_by_file_lock(self) -> None:
        workers = 8
        env = dict(os.environ, AGENT_WORKSPACE_ROOT=str(self.root), PYTHONIOENCODING="utf-8")
        procs: list[subprocess.Popen[str]] = []
        for i in range(workers):
            procs.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        str(TOOL),
                        "exp",
                        "add",
                        "--title",
                        f"并发写入条目-{i}",
                        "--tag",
                        "concurrency",
                        "--agent",
                        f"worker-{i}",
                    ],
                    cwd=self.root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
            )

        outputs = [p.communicate(timeout=60) for p in procs]
        for idx, (p, (out, err)) in enumerate(zip(procs, outputs)):
            self.assertEqual(p.returncode, 0, f"worker-{idx} failed: stdout={out!r} stderr={err!r}")

        log = (self.root / "全局复用与踩坑日志.md").read_text(encoding="utf-8")
        self.assertIn(f"现行条目（{workers} 条）", log)

        index_ids = re.findall(r"^\|\s*(EXP-\d{3})\s*\|", log, re.MULTILINE)
        self.assertEqual(sorted(index_ids), [f"EXP-{i:03d}" for i in range(1, workers + 1)])

        for i in range(workers):
            self.assertIn(f"并发写入条目-{i}", log)

    def test_lock_timeout_fails_cleanly_when_lock_held(self) -> None:
        holder_code = (
            "import os, sys, time\n"
            "from pathlib import Path\n"
            "lock_path = Path(sys.argv[1])\n"
            "f = open(lock_path, 'a+b')\n"
            "if os.name == 'nt':\n"
            "    import msvcrt\n"
            "    f.seek(0)\n"
            "    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)\n"
            "else:\n"
            "    import fcntl\n"
            "    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "print('LOCKED', flush=True)\n"
            "time.sleep(2.0)\n"
            "if os.name == 'nt':\n"
            "    f.seek(0)\n"
            "    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)\n"
            "else:\n"
            "    fcntl.flock(f.fileno(), fcntl.LOCK_UN)\n"
            "f.close()\n"
        )
        lock_file = self.root / ".workspace.lock"
        holder = subprocess.Popen(
            [sys.executable, "-c", holder_code, str(lock_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout is not None
            ready = holder.stdout.readline().strip()
            self.assertEqual(ready, "LOCKED")

            start = time.monotonic()
            blocked = self.run_tool(
                "exp", "add", "--title", "应超时条目",
                extra_env={"AGENT_WORKSPACE_LOCK_TIMEOUT": "0.25"},
            )
            elapsed = time.monotonic() - start
            self.assertEqual(blocked.returncode, 1)
            self.assertIn("超时", blocked.stderr)
            self.assertGreaterEqual(elapsed, 0.2)
        finally:
            holder.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
