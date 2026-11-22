#!/usr/bin/env python3
"""Zero-dependency MCP (Model Context Protocol) stdio server for Agent Shared Workspace.

Implements JSON-RPC 2.0 over stdio using Python's standard library only.
Delegates every operation to ``workspace_tool`` via subprocess so all commands
share identical CLI semantics and cross-process file locking.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__

PROTOCOL_VERSION = "2024-11-05"
CLI_MODULE = "agent_shared_workspace.cli"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "workspace_init",
        "description": "Idempotently initialize shared workspace skeleton docs, workspace.config.json, .gitignore, and Git.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lang": {"type": "string", "enum": ["zh", "en"], "default": "en", "description": "Language for skeleton docs."},
                "no_git": {"type": "boolean", "default": False, "description": "Skip git init when true."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "workspace_status",
        "description": "Show active projects and Git working tree status for the shared workspace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "guard": {"type": "boolean", "default": False, "description": "Return an error status if uncommitted changes exist."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "workspace_guard",
        "description": "Check whether the shared workspace Git tree is clean. Returns an error if uncommitted changes remain.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "exp_search",
        "description": "Search shared pitfall/experience memory by keyword, tag, or list all registered tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": "", "description": "Keyword to match in index or entry body."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tag filters (AND match)."},
                "list_tags": {"type": "boolean", "default": False, "description": "When true, list all tags with counts."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "exp_get",
        "description": "Read the index row and full body (or sunk path) of a specific EXP entry, e.g. EXP-001.",
        "inputSchema": {
            "type": "object",
            "required": ["exp_id"],
            "properties": {
                "exp_id": {"type": "string", "description": "Experience ID such as EXP-001 or 001."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "exp_add",
        "description": "Record a new verified experience/pitfall with automatic sequential ID and cross-process locking.",
        "inputSchema": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string", "description": "One-line conclusion or pitfall title."},
                "exp_type": {"type": "string", "default": "踩坑+复用方法", "description": "Category label."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional classification tags."},
                "phenomenon": {"type": "string", "default": "", "description": "Observed symptom and trigger condition."},
                "cause": {"type": "string", "default": "", "description": "Verified root cause."},
                "solution": {"type": "string", "default": "", "description": "Fix or reusable procedure."},
                "criteria": {"type": "string", "default": "", "description": "Verification criteria."},
                "sink": {"type": "string", "description": "Optional project ID/name to sink detailed body into."},
                "agent": {"type": "string", "default": "mcp-agent", "description": "Recording agent name."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "exp_update",
        "description": "Append new evidence or follow-up notes to an existing EXP entry without creating a duplicate.",
        "inputSchema": {
            "type": "object",
            "required": ["exp_id", "note"],
            "properties": {
                "exp_id": {"type": "string", "description": "Experience ID such as EXP-001."},
                "note": {"type": "string", "description": "Additional verified evidence or revision note."},
                "agent": {"type": "string", "default": "mcp-agent", "description": "Recording agent name."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "project_list",
        "description": "List all Project_XXX directories and the current highest project ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "project_new",
        "description": "Create a new project directory following SOP and register it on the workspace board.",
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "description": "Short project name."},
                "owner": {"type": "string", "default": "mcp-agent", "description": "Owner agent name."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "project_update",
        "description": "Update a project's status in both its README and the global workspace board.",
        "inputSchema": {
            "type": "object",
            "required": ["project", "status"],
            "properties": {
                "project": {"type": "string", "description": "Project number (e.g. 001) or name substring."},
                "status": {"type": "string", "description": "Updated status text."},
                "entry": {"type": "string", "description": "Optional updated continuation entry pointer."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "handoff_record",
        "description": "Write a structured multi-agent handoff and atomically sync project README and workspace board.",
        "inputSchema": {
            "type": "object",
            "required": ["project", "agent", "status", "done"],
            "properties": {
                "project": {"type": "string", "description": "Project number or name substring."},
                "agent": {"type": "string", "description": "Agent name performing the handoff."},
                "status": {"type": "string", "description": "Current project status summary."},
                "done": {"type": "string", "description": "Completed items (newline-separated)."},
                "evidence": {"type": "string", "default": "", "description": "Evidence paths or verification results."},
                "todo": {"type": "string", "default": "", "description": "Remaining items and next steps."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
    {
        "name": "workspace_commit",
        "description": "Commit shared workspace changes to local Git (automatically excludes .workspace.lock).",
        "inputSchema": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "message": {"type": "string", "description": "Git commit message."},
                "workspace_root": {"type": "string", "description": "Optional override for AGENT_WORKSPACE_ROOT."},
            },
        },
    },
]


def _build_cli_args(tool_name: str, args: dict[str, Any]) -> list[str]:
    if tool_name == "workspace_init":
        cmd = ["init", "--lang", str(args.get("lang", "en"))]
        if args.get("no_git"):
            cmd.append("--no-git")
        return cmd

    if tool_name == "workspace_status":
        cmd = ["status"]
        if args.get("guard"):
            cmd.append("--guard")
        return cmd

    if tool_name == "workspace_guard":
        return ["guard"]

    if tool_name == "exp_search":
        cmd = ["exp", "search"]
        if args.get("list_tags"):
            cmd.append("--list-tags")
            return cmd
        query = str(args.get("query", "")).strip()
        if query:
            cmd.append(query)
        for tag in args.get("tags") or []:
            cmd.extend(["--tag", str(tag)])
        return cmd

    if tool_name == "exp_get":
        return ["exp", "get", str(args["exp_id"])]

    if tool_name == "exp_add":
        cmd = ["exp", "add", "--title", str(args["title"])]
        if args.get("exp_type"):
            cmd.extend(["--type", str(args["exp_type"])])
        for tag in args.get("tags") or []:
            cmd.extend(["--tag", str(tag)])
        for field in ("phenomenon", "cause", "solution", "criteria", "sink", "agent"):
            val = args.get(field)
            if val:
                cmd.extend([f"--{field}", str(val)])
        return cmd

    if tool_name == "exp_update":
        cmd = ["exp", "update", str(args["exp_id"]), "--note", str(args["note"])]
        if args.get("agent"):
            cmd.extend(["--agent", str(args["agent"])])
        return cmd

    if tool_name == "project_list":
        return ["project", "list"]

    if tool_name == "project_new":
        cmd = ["project", "new", str(args["name"])]
        if args.get("owner"):
            cmd.extend(["--owner", str(args["owner"])])
        return cmd

    if tool_name == "project_update":
        cmd = ["project", "update", str(args["project"]), "--status", str(args["status"])]
        if args.get("entry"):
            cmd.extend(["--entry", str(args["entry"])])
        return cmd

    if tool_name == "handoff_record":
        cmd = [
            "handoff",
            str(args["project"]),
            "--agent",
            str(args["agent"]),
            "--status",
            str(args["status"]),
            "--done",
            str(args["done"]),
        ]
        if args.get("evidence"):
            cmd.extend(["--evidence", str(args["evidence"])])
        if args.get("todo"):
            cmd.extend(["--todo", str(args["todo"])])
        return cmd

    if tool_name == "workspace_commit":
        return ["commit", "-m", str(args["message"])]

    raise KeyError(f"Unknown tool: {tool_name}")


def _invoke_tool(tool_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
    try:
        cli_args = _build_cli_args(tool_name, arguments)
    except KeyError as exc:
        return f"Invalid arguments for {tool_name}: {exc}", True

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    ws_override = arguments.get("workspace_root")
    if ws_override:
        env["AGENT_WORKSPACE_ROOT"] = str(ws_override)

    # Ensure package root is importable when executed directly from source tree.
    pkg_parent = str(Path(__file__).resolve().parents[1])
    existing_pp = env.get("PYTHONPATH", "")
    if pkg_parent not in existing_pp.split(os.pathsep):
        env["PYTHONPATH"] = f"{pkg_parent}{os.pathsep}{existing_pp}" if existing_pp else pkg_parent

    proc = subprocess.run(
        [sys.executable, "-m", CLI_MODULE, *cli_args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    combined = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part).strip()
    if not combined:
        combined = "(no output)"
    return combined, proc.returncode != 0


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    req_id = request.get("id")

    # JSON-RPC notifications have no id and must not receive a response.
    if method == "notifications/initialized" or (req_id is None and str(method).startswith("notifications/")):
        return None

    if method == "initialize":
        client_ver = (request.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": client_ver,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "agent-shared-workspace",
                    "version": __version__,
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = request.get("params") or {}
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        valid_names = {t["name"] for t in TOOLS}
        if tool_name not in valid_names:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
            }
        text, is_error = _invoke_tool(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            err = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        response = handle_request(payload)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
