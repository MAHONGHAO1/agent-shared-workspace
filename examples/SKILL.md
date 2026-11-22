---
name: shared-workspace
description: >-
  Shared memory for multiple coding agents: query/add/update experiences,
  record handoffs, create projects by SOP, and commit the workspace to Git.
  Use before debugging, before starting a new project, and before ending a task.
---

# Shared Workspace Skill

把「共享记忆」做成可执行的 CLI，而不是让每个 Agent 每次都读一遍全局文档。

## 前提

- 工作空间根目录由环境变量 `AGENT_WORKSPACE_ROOT` 指定；未设置时用当前目录。
- 工具：`<repo>/workspace_tool.py`，只依赖 Python 标准库。
- 文件布局见 README；文件名可在工具顶部常量修改。

## 什么时候用

| 时机 | 命令 |
| --- | --- |
| 排查问题、用新库、改配置前 | `exp search "关键词"`，命中后 `exp get EXP-编号` |
| 解决了坑、验证了新做法 | `exp add --title ... --phenomenon ... --cause ... --solution ... --criteria ...` |
| 同一问题有新证据 | `exp update EXP-编号 --note "新证据"`，不另开条目 |
| 阶段完成 / 暂停 / 换 Agent | `handoff <编号> --agent ... --status ... --done ... --evidence ... --todo ...` |
| 新建项目 | `project new "名称" --owner "agent"`，不手动建目录 |
| 任务结束 | `commit -m "说明"`，禁止把改动留在未提交工作树 |

## 规则

1. 写共享文件前先读最新内容，只改必要段落，保留其他 Agent 的修改。
2. 交接只写「已完成 / 证据 / 未完成 / 下一步 / 修改文件」，不写流水账。
3. 经验一条一件事；项目细节放项目 `docs/`，全局只留一行结论和指针。
4. 没有新经验不要凑条目；同类问题优先 update。

## 命令

```bash
export AGENT_WORKSPACE_ROOT=/path/to/workspace
python workspace_tool.py status
python workspace_tool.py exp search "关键词"
python workspace_tool.py exp get EXP-001
python workspace_tool.py exp add --title "..." --phenomenon "..." --cause "..." --solution "..." --criteria "..."
python workspace_tool.py exp update EXP-001 --note "..."
python workspace_tool.py handoff 001 --agent codex --status "..." --done "..." --evidence "..." --todo "..."
python workspace_tool.py project new "项目名称" --owner codex
python workspace_tool.py commit -m "docs: ..."
```
