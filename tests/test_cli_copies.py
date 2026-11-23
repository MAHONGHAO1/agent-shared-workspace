"""Keep the packaged CLI and its standalone copies honest."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cli_copies_are_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_cli.py"), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_version_matches_pyproject() -> None:
    cli = (ROOT / "src" / "agent_shared_workspace" / "cli.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^CLI_VERSION = "([^"]+)"', cli, re.MULTILINE)
    assert match is not None, "CLI_VERSION is missing from cli.py"
    assert f'version = "{match.group(1)}"' in pyproject


def test_version_flag_works_from_standalone_copy() -> None:
    output = subprocess.check_output(
        [sys.executable, str(ROOT / "src" / "workspace_tool.py"), "--version"],
        cwd=ROOT,
        text=True,
    )
    assert output.strip().startswith("agent-workspace ")
