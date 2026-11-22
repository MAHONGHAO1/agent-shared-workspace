---
name: shared-workspace
description: >-
  Shared memory for multiple coding agents: init workspace, query/add/update
  tagged experiences, record handoffs, create projects by SOP, guard dirty
  working trees, and commit to local Git with cross-process file locking.
  Use before debugging, before starting a new project, and before ending a task.
---

# Shared Workspace Skill

把「共享记忆」做成可执行的并发安全 CLI，而不是让每个 Agent 每次都读一遍全局文档。

## 前提

- 工作空间根目录由环境变量 `AGENT_WORKSPACE_ROOT` 指定；未设置时用当前目录。
- 工具：`<repo>/src/workspace_tool.py`，只依赖 Python 标准库，内置跨进程文件锁（`.workspace.lock`）。
- 首次使用运行 `init --lang zh` 或 `init --lang en`，自动生成骨架文档与 `workspace.config.json`。

## 什么时候用

| 时机 | 命令 |
| --- | --- |
| 初始化新工作空间 | `init --lang zh`（英文骨架传 `--lang en`） |
| 排查问题、用新库、改配置前 | `exp search "关键词"` / `exp search --tag 标签`，命中后 `exp get EXP-编号` |
| 解决了坑、验证了新做法 | `exp add --title ... --tag "t1,t2" --phenomenon ... --cause ... --solution ... --criteria ...` |
| 同一问题有新证据 | `exp update EXP-编号 --note "新证据"`，不另开条目 |
| 阶段完成 / 暂停 / 换 Agent | `handoff <编号> --agent ... --status ... --done ... --evidence ... --todo ...` |
| 新建项目 | `project new "名称" --owner "agent"`，不手动建目录 |
| 任务结束 | `guard` 巡检并 `commit -m "说明"`，禁止把改动留在未提交工作树 |

## 规则

1. 所有写操作均通过 CLI 完成，依赖文件锁避免多 Agent 并发冲突。
2. 交接只写「已完成 / 证据 / 未完成 / 下一步」，不写流水账。
3. 经验一条一件事；项目细节用 `--sink <编号>` 下沉到项目 `docs/`，全局只留一行结论和指针。
4. 没有新经验不要凑条目；同类问题优先 `exp update`。

## 命令速查

```bash
export AGENT_WORKSPACE_ROOT=/path/to/workspace
python src/workspace_tool.py init --lang zh
python src/workspace_tool.py status --guard
python src/workspace_tool.py exp search "关键词" --tag docker
python src/workspace_tool.py exp search --list-tags
python src/workspace_tool.py exp get EXP-001
python src/workspace_tool.py exp add --title "..." --tag "docker,linux" --phenomenon "..." --cause "..." --solution "..." --criteria "..."
python src/workspace_tool.py exp update EXP-001 --note "..."
python src/workspace_tool.py handoff 001 --agent codex --status "..." --done "..." --evidence "..." --todo "..."
python src/workspace_tool.py project new "项目名称" --owner codex
python src/workspace_tool.py guard
python src/workspace_tool.py commit -m "docs: ..."
```
