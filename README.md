# Agent Shared Workspace

**给多 Agent 用的一套共享记忆：纯文本 SSOT + 一个零依赖 CLI + Git 版本化。**

A dependency-free shared memory for multiple coding agents: plain-text single source of truth, one CLI, versioned by Git.

---

## 它解决什么问题

你同时用 Codex、Claude Code、DeepSeek Harness、Antigravity 或别的 Agent 做同一个项目。每个 Agent 各记各的，结果：

- 同一个坑，三个 Agent 踩三遍；
- 昨天的结论，今天的会话不知道；
- 想给它们一份「项目当前状态」，只能一遍遍贴进对话框；
- 上了向量库做记忆，召回不可控：人看不懂它为什么想起这条，也改不动。

这套东西换一个做法：**记忆就是仓库里的几个 Markdown 文件，Agent 用同一个 CLI 读写，Git 负责版本和回滚。**

## 目录结构

```text
your-workspace/
├── AGENTS.md                 # 规则与启动指针（各 Agent 入口指向它）
├── WORKSPACE.md              # 项目登记表与状态
├── EXPERIENCES.md            # 经验索引 + 正文（EXP-001…）
├── NEW_PROJECT_SOP.md        # 建项规范
└── Project_001_xxx/
    ├── README.md
    └── docs/
        ├── 当前状态与交接.md
        └── 计划.md
```

文件名可配置；默认值见 `src/workspace_tool.py` 顶部常量。

## 快速开始

```bash
# 1. 指定工作空间根目录（不设则用当前目录）
export AGENT_WORKSPACE_ROOT=/path/to/your-workspace      # Windows: $env:AGENT_WORKSPACE_ROOT="D:\workspace"

# 2. 看状态
python src/workspace_tool.py status

# 3. 查经验
python src/workspace_tool.py exp search "docker"

# 4. 沉淀一条经验
python src/workspace_tool.py exp add \
  --title "容器内挂载卷权限不足会导致写入失败" \
  --type "踩坑+复用方法" \
  --phenomenon "bind mount 后进程以 non-root 运行，创建目录报 Permission denied" \
  --cause "宿主目录属主是 root，容器内 uid 10001 无写权限" \
  --solution "compose 里指定 user: 或 entrypoint 内 chown" \
  --criteria "容器内成功创建文件并写入 1 KB" \
  --agent "codex"

# 5. 交接
python src/workspace_tool.py handoff 001 --agent "claude-code" \
  --status "接口联调完成" --done "四条接口冒烟通过" \
  --evidence "tmp/smoke.log" --todo "错误码对齐"

# 6. 收尾：把改动固化进 Git
python src/workspace_tool.py commit -m "docs: 交接与经验更新"
```

## 命令

| 命令 | 作用 |
| --- | --- |
| `status` | 概览：进行中项目、Git 状态 |
| `exp search <关键词>` | 按标题与正文检索经验 |
| `exp get EXP-123` | 查看某条经验的正文 |
| `exp add --title ... --phenomenon ...` | 新增经验，自动分配编号并更新索引 |
| `exp update EXP-123 --note ...` | 给已有经验补新证据（同一问题不重复开条） |
| `project new <名称> --owner <agent>` | 按 SOP 建项目目录、README 并登记 |
| `handoff <编号> --agent ... --status ...` | 写交接，同时更新项目 README 与登记表 |
| `commit -m <说明>` | 提交工作空间的改动 |

## 接入各 Agent

把 `examples/AGENTS-snippet.md` 里的约定贴到各 Agent 的启动入口：

| Agent | 入口 |
| --- | --- |
| Codex | `~/.codex/AGENTS.md` |
| Claude Code | `~/.claude/CLAUDE.md` |
| DeepSeek Harness | `~/.dsh/AGENTS.md` |
| Antigravity | `<workspace>/.agents/skills/shared-workspace/SKILL.md` |

入口只写「什么时候调用哪个命令」，不要把全局文档整段复制进去——那会让每个会话开头就吃掉几千 token。

## 为什么不用向量数据库

| | 向量 RAG | 本方案 |
| --- | --- | --- |
| 可读性 | 召回片段，人难核对 | 纯文本，人直接读改 |
| 可修正 | 改一条要靠重灌索引 | 改一个 Markdown 段落 |
| 版本与回滚 | 另建一套 | Git 原生 |
| 依赖 | 数据库 + embedding 服务 | Python 标准库 |
| 失败方式 | 悄悄召回错的东西 | 查不到就是查不到，可见 |

代价是检索能力弱：只有关键词和编号，没有语义相似度。对「几十到几百条经验、单人维护」的规模，够用；规模再大就该换方案。

## 测试

```bash
python -m unittest discover -s tests -v
```

7 个端到端用例，覆盖 status / exp add / exp update / exp search / project new / handoff / commit，全部在临时目录里跑，不碰真实工作区。

## 边界

- 单机、单用户、少量 Agent 并发。并发写靠 Git，暂不做跨进程锁（计划中）。
- 不替代项目文档：交接只放「当前状态 + 下一步」，设计细节留在项目 `docs/`。
- 不做自动记忆：写什么由 Agent 判断，工具只保证格式、编号与索引一致。

## License

MIT
