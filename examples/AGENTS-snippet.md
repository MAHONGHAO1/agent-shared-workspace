# 把这段贴进各 Agent 的启动入口

目标：让 Agent 知道「什么时候用什么命令」，而不是每次读一遍全局文档。

## 通用原则

- 入口只写调用约定，不抄全局文档正文。
- 用环境变量 `AGENT_WORKSPACE_ROOT` 指定工作空间，不要写死绝对路径。
- 规则只有一份，放在工作空间的 `AGENTS.md`；各入口指向它。

## Codex（`~/.codex/AGENTS.md`）

```markdown
## 共享工作空间

工作空间根目录：$AGENT_WORKSPACE_ROOT（未设置时用当前目录）。
工具：`python $AGENT_WORKSPACE_ROOT/workspace_tool.py`

- 排查问题、用新库、改配置前：`exp search "关键词"`，命中后 `exp get EXP-编号`
- 解决坑或验证新方法后：`exp add --title ... --phenomenon ... --cause ... --solution ... --criteria ...`
- 同一问题有新证据：`exp update EXP-编号 --note "..."`，不另开条目
- 阶段完成或交接：`handoff <编号> --agent codex --status ... --done ... --evidence ... --todo ...`
- 新建项目：`project new "名称" --owner codex`
- 任务结束：`commit -m "说明"`

完整规则见 `$AGENT_WORKSPACE_ROOT/AGENTS.md`，命令细节见 `examples/SKILL.md`。
```

## Claude Code（`~/.claude/CLAUDE.md`）

```markdown
## Shared workspace memory

Workspace root: `$AGENT_WORKSPACE_ROOT` (falls back to cwd).
CLI: `python $AGENT_WORKSPACE_ROOT/workspace_tool.py`

- Before debugging or adopting a new dependency: `exp search "keyword"`, then `exp get EXP-123`
- After solving a problem: `exp add --title ... --phenomenon ... --cause ... --solution ... --criteria ...`
- Same problem, new evidence: `exp update EXP-123 --note "..."`
- Phase done: `handoff <id> --agent claude-code --status ... --done ... --evidence ... --todo ...`
- Before ending the task: `commit -m "..."`

Read `AGENTS.md` in the workspace for the full rules.
```

## DeepSeek Harness（`~/.dsh/AGENTS.md`）

```markdown
## 共享空间与记忆中枢

根目录：`$AGENT_WORKSPACE_ROOT`
工具：`python $AGENT_WORKSPACE_ROOT/workspace_tool.py`

1. 排查前先 `exp search`；命中后 `exp get`。
2. 有新经验 `exp add`；同类问题 `exp update`。
3. 阶段交接用 `handoff`。
4. 建项目用 `project new`，不手动建目录。
5. 任务结束 `commit -m`。
```

## Antigravity（`<workspace>/.agents/skills/shared-workspace/SKILL.md`）

直接使用 `examples/SKILL.md`。

## 不要写进入口的东西

- 整段全局文档（会让每个会话开头多耗几千 token）
- 具体项目状态（会过期，应从 `WORKSPACE.md` 实时读）
- 个人路径、账号、密钥
