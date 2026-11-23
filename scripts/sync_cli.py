#!/usr/bin/env python3
"""Keep the standalone CLI copies in sync with the packaged module.

The skill and DeepSeek Harness packages ship a standalone ``workspace_tool.py``
so they can run without installing the package. That copy must stay identical
to ``src/agent_shared_workspace/cli.py``; this script is the single writer and
``--check`` is the CI guard.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "agent_shared_workspace" / "cli.py"
TARGETS = [
    ROOT / "src" / "workspace_tool.py",
    ROOT / "skills" / "shared-workspace" / "scripts" / "workspace_tool.py",
    ROOT
    / "integrations"
    / "deepseek-harness"
    / "skills"
    / "shared-workspace"
    / "scripts"
    / "workspace_tool.py",
]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(check: bool = False) -> int:
    source = SOURCE.read_bytes()
    if check:
        drift = [target for target in TARGETS if not target.exists() or _digest(target) != _digest(SOURCE)]
        if drift:
            print("CLI copies are out of sync:")
            for target in drift:
                print(f"  {target.relative_to(ROOT)}")
            print("Run: python scripts/sync_cli.py")
            return 1
        print("CLI copies are in sync.")
        return 0

    for target in TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source)
    print(f"Synced {len(TARGETS)} CLI copies from {SOURCE.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(check="--check" in sys.argv[1:]))
