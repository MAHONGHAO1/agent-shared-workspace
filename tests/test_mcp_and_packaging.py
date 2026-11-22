"""Tests for the zero-dependency MCP stdio server and multi-channel packaging."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class McpAndPackagingTest(unittest.TestCase):
    def _send_rpc_session(self, requests: list[dict], workspace_root: Path) -> list[dict]:
        env = dict(os.environ, AGENT_WORKSPACE_ROOT=str(workspace_root), PYTHONIOENCODING="utf-8")
        src_dir = str(ROOT / "src")
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)

        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n"
        proc = subprocess.run(
            [sys.executable, "-m", "agent_shared_workspace.mcp_server"],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, f"MCP server exited non-zero: {proc.stderr}")
        responses = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line:
                responses.append(json.loads(line))
        return responses

    def test_mcp_stdio_full_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            responses = self._send_rpc_session(
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test"}},
                    },
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {"name": "workspace_init", "arguments": {"lang": "en"}},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 5,
                        "method": "tools/call",
                        "params": {
                            "name": "exp_add",
                            "arguments": {
                                "title": "MCP stdio stdout must stay clean",
                                "tags": ["mcp", "stdio"],
                                "phenomenon": "Client fails to parse JSON-RPC",
                                "cause": "Debug print wrote to stdout",
                                "solution": "Write logs to stderr only",
                                "criteria": "tools/list succeeds",
                                "agent": "test-client",
                            },
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "tools/call",
                        "params": {"name": "exp_search", "arguments": {"tags": ["mcp"]}},
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "method": "tools/call",
                        "params": {"name": "workspace_guard", "arguments": {}},
                    },
                ],
                ws,
            )

            by_id = {r["id"]: r for r in responses}
            self.assertEqual(set(by_id.keys()), {1, 2, 3, 4, 5, 6, 7})

            # initialize
            self.assertEqual(by_id[1]["result"]["serverInfo"]["name"], "agent-shared-workspace")
            # tools/list
            tool_names = {t["name"] for t in by_id[3]["result"]["tools"]}
            self.assertIn("exp_add", tool_names)
            self.assertIn("handoff_record", tool_names)
            self.assertIn("workspace_guard", tool_names)
            # init
            self.assertFalse(by_id[4]["result"]["isError"])
            self.assertTrue((ws / "EXPERIENCES.md").is_file())
            # exp_add
            self.assertFalse(by_id[5]["result"]["isError"])
            self.assertIn("EXP-001", by_id[5]["result"]["content"][0]["text"])
            # exp_search
            self.assertFalse(by_id[6]["result"]["isError"])
            self.assertIn("MCP stdio stdout must stay clean", by_id[6]["result"]["content"][0]["text"])
            # guard detects dirty files (exit code 1 -> isError True)
            self.assertTrue(by_id[7]["result"]["isError"])
            self.assertIn("GUARD WARNING", by_id[7]["result"]["content"][0]["text"])

    def test_bundled_copies_are_in_sync(self) -> None:
        canonical_tool = (ROOT / "src" / "workspace_tool.py").read_bytes()
        for copy_path in (
            ROOT / "src" / "agent_shared_workspace" / "cli.py",
            ROOT / "skills" / "shared-workspace" / "scripts" / "workspace_tool.py",
            ROOT / "integrations" / "deepseek-harness" / "skills" / "shared-workspace" / "scripts" / "workspace_tool.py",
        ):
            self.assertTrue(copy_path.is_file(), f"Missing bundled copy: {copy_path}")
            self.assertEqual(copy_path.read_bytes(), canonical_tool, f"Out-of-sync copy: {copy_path}")

        canonical_skill = (ROOT / "skills" / "shared-workspace" / "SKILL.md").read_bytes()
        dsh_skill = ROOT / "integrations" / "deepseek-harness" / "skills" / "shared-workspace" / "SKILL.md"
        self.assertEqual(dsh_skill.read_bytes(), canonical_skill)

    def test_plugin_and_registry_manifests_are_valid_json(self) -> None:
        for rel in (
            ".claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
            ".mcp.json",
            "server.json",
            "integrations/deepseek-harness/package.json",
        ):
            path = ROOT / rel
            self.assertTrue(path.is_file(), f"Missing manifest: {rel}")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)

        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(plugin["name"], "agent-shared-workspace")
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertTrue(market["plugins"])


if __name__ == "__main__":
    unittest.main()
