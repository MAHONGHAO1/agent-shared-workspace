# 开源 Agent 记忆中枢

- 项目编号：Project_038
- 目标与范围：把本机私有的 `workspace_tool.py` 与 `shared-workspace` skill 抽离为可开源发布的「多 Agent 共享记忆」项目：参数化、脱敏、补测试、写文档与接入示例。不负责发布到 GitHub（由用户确认后执行）。
- 负责人或执行主体：DeepSeek Harness（lead）
- 当前状态：2026-11-22 抽离与文档第一批完成；工具已参数化并在真实工作区验证；待补测试、脱敏复核、合并 Antigravity 的并发锁
- 启动日期：2026-11-22
- 启动前检查：已于 2026-11-21 阅读 `AGENTS.md`（全文）、`全局工作台.md`（全文）、`新项目创建SOP.md`（全文）、`全局复用与踩坑日志.md`（索引）
- 相关经验：EXP-151（界面标签与实际模式不一致）
- 主要文件：
  - `src/workspace_tool.py`：抽离版 CLI，支持 `AGENT_WORKSPACE_ROOT`，默认当前目录
  - `README.md`：开源项目说明（中英）
  - `LICENSE`：MIT
  - `examples/SKILL.md`：脱敏后的 skill 定义
  - `examples/AGENTS-snippet.md`：Codex / Claude Code / DSH / Antigravity 的入口片段
  - `docs/开源方案.md`：分工、脱敏清单、测试与发布前检查
- 验证与交付标准：在临时目录用 `AGENT_WORKSPACE_ROOT` 跑通 status / exp add / exp update / handoff / project new / commit；README 命令逐条可复制；不含私有路径、公司名与凭据。
