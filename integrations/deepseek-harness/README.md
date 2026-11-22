# dsh-agent-shared-workspace

DeepSeek Harness (DSH) Skill bundle for [Agent Shared Workspace](https://github.com/MAHONGHAO1/agent-shared-workspace): plain-text shared memory across multiple coding agents (Markdown SSOT + cross-process locked CLI + Git).

## Install in DeepSeek Harness

```bash
dsh plugin add dsh-agent-shared-workspace
```

After restarting DeepSeek Harness, the `shared-workspace` skill and its bundled zero-dependency `workspace_tool.py` CLI are automatically discovered via `@deepseek-ai/dsh-skill-filesystem`.

## Quick Setup

Set `AGENT_WORKSPACE_ROOT` to your shared workspace folder (or run inside it) and initialize once:

```bash
export AGENT_WORKSPACE_ROOT=~/agent-workspace
python <skill-dir>/scripts/workspace_tool.py init --lang zh   # or --lang en
```

## Features Included

- Cross-process reentrant file locking (`msvcrt` on Windows / `fcntl` on POSIX)
- Tagged experience memory (`exp add --tag`, `exp search --tag`, `--list-tags`)
- Structured multi-agent handoffs synced across handoff doc, project README, and workspace board
- Dirty working tree guard (`guard` / `status --guard`) and safe Git commits

## License

MIT
