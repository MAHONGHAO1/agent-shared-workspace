---
name: shared-workspace
description: >-
  Shared plain-text memory hub for multiple coding agents (Codex, Claude Code,
  DeepSeek Harness, Antigravity). Use to initialize a workspace, search/add/update
  tagged pitfalls and reusable lessons (EXP), create SOP-compliant projects,
  record structured multi-agent handoffs, guard uncommitted changes, and commit
  safely to Git with cross-process file locking.
---

# Shared Workspace Skill

Keep a single plain-text Markdown memory across all coding agents, guarded by a zero-dependency CLI with cross-process file locking (`.workspace.lock`).

## Tool Location

This skill ships with a self-contained Python stdlib CLI right next to this file:

```bash
python <this-skill-dir>/scripts/workspace_tool.py <command>
```

If installed via PyPI / `uvx`, you can also invoke `agent-workspace <command>` directly.

Workspace root resolution: `AGENT_WORKSPACE_ROOT` environment variable, otherwise the current working directory.

## When to Use Each Command

| Trigger | Command |
| --- | --- |
| First time setting up a workspace | `init --lang zh` (or `init --lang en` for English filenames) |
| Before debugging, adding a library, or changing config | `exp search "keyword"` or `exp search --tag <tag>`, then `exp get EXP-001` |
| After verifying a fix or reusable pattern | `exp add --title "..." --tag "t1,t2" --phenomenon "..." --cause "..." --solution "..." --criteria "..."` |
| New evidence on an existing pitfall (never duplicate) | `exp update EXP-001 --note "..." --agent "<name>"` |
| Starting a new project | `project new "<name>" --owner "<agent>"` (never mkdir manually) |
| Finishing a phase or handing off to another agent | `handoff <id> --agent "<name>" --status "..." --done "..." --evidence "..." --todo "..."` |
| Before ending the session | `guard` to check dirty files, then `commit -m "..."` |

## Operating Rules

1. Always read/write shared memory through `workspace_tool.py` so cross-process locking (`msvcrt`/`fcntl`) prevents concurrent Markdown corruption and ID collisions.
2. Prefer `exp update` over creating duplicate entries for the same root cause.
3. For project-specific troubleshooting details, pass `--sink <project-id>` to keep the global index compact.
4. Never leave uncommitted changes at task exit — run `guard` and `commit -m "..."`.
5. Never record secrets, tokens, passwords, or personal credentials in workspace docs.

## Quick Command Reference

```bash
export AGENT_WORKSPACE_ROOT=/path/to/workspace
python scripts/workspace_tool.py init --lang en
python scripts/workspace_tool.py status --guard
python scripts/workspace_tool.py exp search "docker" --tag linux
python scripts/workspace_tool.py exp search --list-tags
python scripts/workspace_tool.py exp get EXP-001
python scripts/workspace_tool.py exp add --title "Non-root bind mount EACCES" --tag "docker,linux" --phenomenon "..." --cause "..." --solution "..." --criteria "..." --agent "claude-code"
python scripts/workspace_tool.py exp update EXP-001 --note "Verified on Ubuntu 24.04" --agent "codex"
python scripts/workspace_tool.py project new "ApiGateway" --owner "codex"
python scripts/workspace_tool.py handoff 001 --agent "codex" --status "Rate limiter verified" --done "12 tests passing" --evidence "tests/test_rl.py" --todo "Canary deploy"
python scripts/workspace_tool.py guard
python scripts/workspace_tool.py commit -m "docs: record EXP-001 and P001 handoff"
```
