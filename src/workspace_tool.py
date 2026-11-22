#!/usr/bin/env python3
r"""Shared Workspace Management CLI Tool.

A portable, dependency-free CLI for a file-based multi-agent shared memory
workspace: query/append/update experiences (EXP), record handoffs, create
projects by SOP, and commit changes to local Git.

Workspace root resolution: ``AGENT_WORKSPACE_ROOT`` environment variable,
otherwise the current working directory.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

def resolve_workspace_root() -> Path:
    """Workspace root: AGENT_WORKSPACE_ROOT override, else the current directory."""
    override = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.cwd().resolve()


WORKSPACE_ROOT = resolve_workspace_root()
GLOBAL_LOG = WORKSPACE_ROOT / "全局复用与踩坑日志.md"
GLOBAL_BOARD = WORKSPACE_ROOT / "全局工作台.md"
SOP_FILE = WORKSPACE_ROOT / "新项目创建SOP.md"
AGENTS_FILE = WORKSPACE_ROOT / "AGENTS.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def find_project_dir(proj_key: str) -> Path | None:
    """Finds a Project_xxx directory by number (e.g. 13, 013, P013) or name substring."""
    proj_key_clean = proj_key.strip()
    m = re.match(r"^[pP]?(\d+)$", proj_key_clean)
    target_num = int(m.group(1)) if m else None

    for entry in WORKSPACE_ROOT.iterdir():
        if entry.is_dir() and entry.name.startswith("Project_"):
            if target_num is not None:
                em = re.match(r"^Project_(\d+)_", entry.name)
                if em and int(em.group(1)) == target_num:
                    return entry
            else:
                if proj_key_clean.lower() in entry.name.lower():
                    return entry
    return None


# -------------------------------------------------------------
# EXP Operations (Read, Add, Update)
# -------------------------------------------------------------
def get_max_exp_id() -> int:
    if not GLOBAL_LOG.exists():
        return 0
    content = read_text(GLOBAL_LOG)
    max_id = 0
    for match in re.finditer(r"^\|\s*EXP-(\d+)\s*\|", content, re.MULTILINE):
        val = int(match.group(1))
        if val > max_id:
            max_id = val
    return max_id


def cmd_exp_search(query: str) -> None:
    if not GLOBAL_LOG.exists():
        print(f"Error: {GLOBAL_LOG} not found.", file=sys.stderr)
        sys.exit(1)

    content = read_text(GLOBAL_LOG)
    lines = content.splitlines()

    print(f"=== 搜索踩坑与复用经验 (关键词: '{query}') ===")
    matches = 0
    in_table = False
    for line in lines:
        if line.startswith("| EXP-") or (in_table and line.startswith("|")):
            in_table = True
            if query.lower() in line.lower():
                print(line)
                matches += 1
        elif in_table and not line.startswith("|"):
            in_table = False

    if matches == 0:
        print("未在经验索引表中找到匹配项，尝试检索全文段落...")
        for idx, line in enumerate(lines):
            if line.startswith("### EXP-") and query.lower() in line.lower():
                snippet = "\n".join(lines[idx : min(idx + 10, len(lines))])
                print(f"\n{snippet}\n---")
                matches += 1

    if matches == 0:
        print("无匹配经验条目。")
    else:
        print(f"\n共找到 {matches} 条匹配记录。使用 'exp get EXP-xxx' 查看具体详情。")


def cmd_exp_get(exp_id: str) -> None:
    exp_id = exp_id.upper()
    if not exp_id.startswith("EXP-"):
        exp_id = f"EXP-{exp_id}"

    content = read_text(GLOBAL_LOG)
    lines = content.splitlines()

    location = None
    for line in lines:
        if f"| {exp_id} |" in line or f"|{exp_id}|" in line:
            print(f"【索引登记】: {line}")
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 6:
                location = parts[5]
            break

    found = False
    captured: list[str] = []
    recording = False
    for line in lines:
        if line.startswith(f"### {exp_id}") or line.startswith(f"## {exp_id}"):
            recording = True
            captured.append(line)
            continue
        if recording:
            if line.startswith("### ") or line.startswith("## "):
                break
            captured.append(line)

    if captured:
        print("\n".join(captured).strip())
        found = True

    if not found:
        if location and "下沉" in location:
            print(f"\n该条目细节已下沉至项目文档: {location}")
        else:
            print(f"\n未在全局日志正文中检索到 {exp_id} 的详情。可能已归档或下沉。")


def cmd_exp_add(
    title: str,
    exp_type: str = "踩坑+复用方法",
    phenomenon: str = "",
    cause: str = "",
    solution: str = "",
    criteria: str = "",
    sink_proj: str | None = None,
    agent: str = "Agent",
) -> None:
    if not GLOBAL_LOG.exists():
        print(f"错误: 找不到 {GLOBAL_LOG}", file=sys.stderr)
        sys.exit(1)

    next_id = get_max_exp_id() + 1
    exp_tag = f"EXP-{next_id:03d}"
    today = datetime.date.today().strftime("%Y-%m-%d")

    # 1. Determine location & sink target
    sink_dir = find_project_dir(sink_proj) if sink_proj else None
    if sink_proj and not sink_dir:
        print(f"警告: 找不到项目 '{sink_proj}'，将直接写入全局正文。", file=sys.stderr)

    if sink_dir:
        p_name = sink_dir.name
        docs_dir = sink_dir / "docs"
        docs_dir.mkdir(exist_ok=True)
        sink_file = docs_dir / "踩坑与复用经验.md"
        location_str = f"下沉；{p_name} `docs/踩坑与复用经验.md`"

        exp_body = f"""### {exp_tag}｜{today}｜{title}

- 记录主体：{agent}；类型：{exp_type}
- 现象：{phenomenon or '（无）'}
- 定位：{cause or '（无）'}
- 处理：{solution or '（无）'}
- 判据：{criteria or '（无）'}
"""
        if sink_file.exists():
            old_sink = read_text(sink_file)
            write_text(sink_file, old_sink.rstrip() + "\n\n" + exp_body)
        else:
            header = f"# {p_name} 踩坑与复用经验下沉库\n\n"
            write_text(sink_file, header + exp_body)
        print(f"详细经验已下沉写入: {sink_file}")
    else:
        location_str = "正文"

    # 2. Update 全局复用与踩坑日志.md table
    content = read_text(GLOBAL_LOG)

    def repl_count(m: re.Match) -> str:
        cur_cnt = int(m.group(1))
        return f"### 现行条目（{cur_cnt + 1} 条）"

    content = re.sub(r"### 现行条目（(\d+)\s*条）", repl_count, content, count=1)

    table_header_pat = r"(\|\s*编号\s*\|\s*日期\s*\|\s*类型\s*\|\s*标题\s*\|\s*位置\s*\|\s*\n\|\s*---[^\n]+\n)"
    m_header = re.search(table_header_pat, content)
    if not m_header:
        print("错误: 无法在全局日志中定位索引表格头！", file=sys.stderr)
        sys.exit(1)

    new_row = f"| {exp_tag} | {today} | {exp_type} | {title} | {location_str} |\n"
    pos = m_header.end()
    content = content[:pos] + new_row + content[pos:]

    # 3. If writing to global body, insert above the highest existing body section
    if not sink_dir:
        exp_body = f"""### {exp_tag}｜{today}｜{title}

- 类型：{exp_type}；记录主体：{agent}。
- 现象：{phenomenon or '待补充'}
- 定位：{cause or '待补充'}
- 处理：{solution or '待补充'}
- 判据：{criteria or '待补充'}

"""
        body_pat = r"(\n### EXP-\d{3}｜)"
        m_body = re.search(body_pat, content)
        if m_body:
            b_pos = m_body.start() + 1
            content = content[:b_pos] + exp_body + content[b_pos:]
        else:
            content += "\n\n" + exp_body

    write_text(GLOBAL_LOG, content)
    print(f"成功沉淀新经验记忆: {exp_tag}")
    print(f"标题: {title}")
    print(f"位置: {location_str}")


def cmd_exp_update(exp_id: str, note: str, agent: str = "Agent") -> None:
    exp_id = exp_id.upper()
    if not exp_id.startswith("EXP-"):
        exp_id = f"EXP-{exp_id}"

    if not GLOBAL_LOG.exists():
        print(f"错误: 找不到 {GLOBAL_LOG}", file=sys.stderr)
        sys.exit(1)

    content = read_text(GLOBAL_LOG)
    today = datetime.date.today().strftime("%Y-%m-%d")

    pat = rf"(### {exp_id}｜[^\n]+\n(?:(?!### EXP-).)*)"
    m = re.search(pat, content, re.DOTALL)
    if m:
        original_section = m.group(1).rstrip()
        append_line = f"\n- 补充（{today} {agent}）：{note}\n"
        updated_section = original_section + append_line
        new_content = content[: m.start(1)] + updated_section + content[m.end(1) :]
        write_text(GLOBAL_LOG, new_content)
        print(f"成功为 {exp_id} 追加补充更新记忆。")
        return

    for line in content.splitlines():
        if f"| {exp_id} |" in line and "下沉" in line:
            parts = [p.strip() for p in line.split("|")]
            loc = parts[5] if len(parts) >= 6 else ""
            m_proj = re.search(r"(Project_\d+_[^`\s]+)", loc)
            if m_proj:
                p_dir = WORKSPACE_ROOT / m_proj.group(1)
                sink_file = p_dir / "docs" / "踩坑与复用经验.md"
                if sink_file.exists():
                    s_content = read_text(sink_file)
                    s_m = re.search(pat, s_content, re.DOTALL)
                    if s_m:
                        orig_s = s_m.group(1).rstrip()
                        up_s = orig_s + f"\n- 补充（{today} {agent}）：{note}\n"
                        new_s_content = s_content[: s_m.start(1)] + up_s + s_content[s_m.end(1) :]
                        write_text(sink_file, new_s_content)
                        print(f"成功在下沉文件 {sink_file} 中更新 {exp_id}。")
                        return

    print(f"未找到 {exp_id} 的正文段落，无法追加。请核对编号。", file=sys.stderr)
    sys.exit(1)


# -------------------------------------------------------------
# Project Operations (Read, New, Update, Handoff)
# -------------------------------------------------------------
def get_max_project_id() -> int:
    max_id = 0
    for entry in WORKSPACE_ROOT.iterdir():
        if entry.is_dir() and entry.name.startswith("Project_"):
            m = re.match(r"^Project_(\d+)_", entry.name)
            if m:
                num = int(m.group(1))
                if num > max_id:
                    max_id = num
    return max_id


def cmd_project_list() -> None:
    print(f"{'编号':<6} {'目录名':<45} {'更新时间'}")
    print("-" * 75)
    projects: list[tuple[int, str, str]] = []
    for entry in sorted(WORKSPACE_ROOT.iterdir(), key=lambda x: x.name):
        if entry.is_dir() and entry.name.startswith("Project_"):
            m = re.match(r"^Project_(\d+)_", entry.name)
            pid = int(m.group(1)) if m else 0
            mtime = datetime.datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            projects.append((pid, entry.name, mtime))

    for pid, name, mtime in sorted(projects, key=lambda x: x[0]):
        print(f"P{pid:03d}   {name:<45} {mtime}")
    print(f"\n当前共 {len(projects)} 个项目，最大编号: P{get_max_project_id():03d}")


def cmd_project_new(name: str, owner: str = "Agent") -> None:
    next_id = get_max_project_id() + 1
    dir_name = f"Project_{next_id:03d}_{name}"
    proj_dir = WORKSPACE_ROOT / dir_name

    if proj_dir.exists():
        print(f"错误: 目标目录 {proj_dir} 已存在！", file=sys.stderr)
        sys.exit(1)

    today = datetime.date.today().strftime("%Y-%m-%d")

    proj_dir.mkdir(parents=True)
    docs_dir = proj_dir / "docs"
    docs_dir.mkdir()
    (proj_dir / "output").mkdir()
    (proj_dir / "tmp").mkdir()

    readme_content = f"""# {name}

- 项目编号：Project_{next_id:03d}
- 目标与范围：
- 负责人或执行主体：{owner}
- 当前状态：进行中
- 启动日期：{today}
- 启动前检查：已阅读 `AGENTS.md`、`全局工作台.md`、`新项目创建SOP.md` 全文及 `全局复用与踩坑日志.md` 经验索引
- 相关经验：暂无
- 主要目录与文件：
  - `docs/`: 状态交接与过程方案
  - `output/`: 构建产物与交付件
  - `tmp/`: 过程临时数据
- 验证与交付标准：
"""
    write_text(proj_dir / "README.md", readme_content)

    handoff_content = f"""# 当前状态与交接

- 项目：{dir_name}
- 记录主体：{owner}
- 创建时间：{today}

## 1. 当前目标与范围
- 待补充

## 2. 已完成工作与一手证据
- 基础目录结构已按 SOP 初始化完成。

## 3. 未完成与下一步
- 开始业务需求分析与一手事实核验。
"""
    write_text(docs_dir / "当前状态与交接.md", handoff_content)

    if GLOBAL_BOARD.exists():
        board_content = read_text(GLOBAL_BOARD)
        new_row = f"| {next_id:03d} | {dir_name} | 进行中：初始化建项 | `README.md` → `docs/当前状态与交接.md` |\n"
        pattern = r"(\| \d{3} \| Project_\d{3}_[^\n]+\n)"
        matches = list(re.finditer(pattern, board_content))
        if matches:
            insert_pos = matches[-1].end()
        else:
            # 空登记表也要能登记第一个项目：插在表头分隔行之后。
            header = re.search(r"\| 编号 \| 目录 \| 当前状态 \| 接续入口 \|\n\| ---[^\n]+\n", board_content)
            insert_pos = header.end() if header else len(board_content)
        updated_board = board_content[:insert_pos] + new_row + board_content[insert_pos:]
        write_text(GLOBAL_BOARD, updated_board)
        print("已自动登记到 全局工作台.md 项目登记表。")

    print(f"成功创建新项目：{dir_name}")
    print(f"路径: {proj_dir}")


def cmd_project_update(proj_key: str, status: str, entry: str | None = None) -> None:
    p_dir = find_project_dir(proj_key)
    if not p_dir:
        print(f"错误: 找不到项目 '{proj_key}'", file=sys.stderr)
        sys.exit(1)

    m = re.match(r"^Project_(\d+)_", p_dir.name)
    num_str = m.group(1) if m else ""

    readme_file = p_dir / "README.md"
    if readme_file.exists():
        r_text = read_text(readme_file)
        r_text = re.sub(r"-\s*当前状态：[^\n]+", f"- 当前状态：{status}", r_text)
        write_text(readme_file, r_text)
        print(f"已更新 {p_dir.name}/README.md 中的当前状态。")

    if GLOBAL_BOARD.exists() and num_str:
        b_text = read_text(GLOBAL_BOARD)
        row_pat = rf"(\|\s*{num_str}\s*\|\s*{re.escape(p_dir.name)}\s*\|)([^|]+)(\|)([^|]+)(\|)"
        m_row = re.search(row_pat, b_text)
        if m_row:
            new_entry_col = f" {entry.strip()} " if entry else m_row.group(4)
            repl = f"\\g<1> {status.strip()} \\g<3>{new_entry_col}\\g<5>"
            b_text = re.sub(row_pat, repl, b_text)
            write_text(GLOBAL_BOARD, b_text)
            print("已同步更新 全局工作台.md 登记表状态。")


def cmd_handoff_record(
    proj_key: str,
    agent: str,
    status: str,
    done: str,
    evidence: str = "",
    todo: str = "",
) -> None:
    p_dir = find_project_dir(proj_key)
    if not p_dir:
        print(f"错误: 找不到项目 '{proj_key}'", file=sys.stderr)
        sys.exit(1)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    docs_dir = p_dir / "docs"
    docs_dir.mkdir(exist_ok=True)
    handoff_file = docs_dir / "当前状态与交接.md"

    done_lines = "\n".join(f"- {line.strip()}" for line in done.splitlines() if line.strip())
    todo_lines = "\n".join(f"- {line.strip()}" for line in todo.splitlines() if line.strip()) if todo else "- 待定"
    evidence_section = ""
    if evidence:
        evidence_lines = "\n".join(f"- {line.strip()}" for line in evidence.splitlines() if line.strip())
        evidence_section = f"\n### 证据\n{evidence_lines}\n"

    turn_block = f"""
## {agent} 交接（{now_str}）

- 当前状态：{status}

### 已完成
{done_lines}
{evidence_section}
### 未完成与下一步
{todo_lines}
"""

    if handoff_file.exists():
        old_text = read_text(handoff_file)
        write_text(handoff_file, old_text.rstrip() + "\n\n" + turn_block.strip() + "\n")
    else:
        header = f"# 当前状态与交接\n\n- 项目：{p_dir.name}\n"
        write_text(handoff_file, header + turn_block.strip() + "\n")

    print(f"已向 {handoff_file} 写入交接记忆记录。")
    cmd_project_update(proj_key, f"{now_str.split()[0]} {status}")


# -------------------------------------------------------------
# Status and Git Operations
# -------------------------------------------------------------
def cmd_status() -> None:
    print("=== Workspace 当前全局状态概览 ===")
    if GLOBAL_BOARD.exists():
        content = read_text(GLOBAL_BOARD)
        print("\n【进行中 / 重点项目】:")
        for line in content.splitlines():
            if re.match(r"^\|\s*\d{3}\s*\|", line) and ("进行中" in line or "待" in line or "验证" in line):
                print(line)

    print("\n【Git 变更状态】:")
    res = run_git(["status", "--short"])
    if res.stdout.strip():
        print(res.stdout.strip())
    else:
        print("工作树干净，无未提交改动。")


def cmd_commit(msg: str) -> None:
    if not msg:
        print("错误: 必须提供 commit 信息 (-m)", file=sys.stderr)
        sys.exit(1)

    print(f"=== 提交 Workspace 变更: '{msg}' ===")
    add_res = run_git(["add", "."])
    if add_res.returncode != 0:
        print(f"git add 失败: {add_res.stderr}", file=sys.stderr)
        sys.exit(1)

    commit_res = run_git(["commit", "-m", msg])
    if commit_res.returncode != 0:
        if "nothing to commit" in commit_res.stdout or "nothing to commit" in commit_res.stderr:
            print("无需提交：无文件变更。")
            return
        print(f"git commit 失败: {commit_res.stderr}", file=sys.stderr)
        sys.exit(1)

    print(commit_res.stdout.strip())


# -------------------------------------------------------------
# Main CLI Router
# -------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Agent Workspace Hub CLI")
    subparsers = parser.add_subparsers(dest="command")

    # --- exp ---
    exp_parser = subparsers.add_parser("exp", help="查询、沉淀与修订踩坑经验")
    exp_sub = exp_parser.add_subparsers(dest="exp_command")
    
    # exp search
    exp_search_p = exp_sub.add_parser("search", help="搜索经验索引")
    exp_search_p.add_argument("query", help="关键词")
    
    # exp get
    exp_get_p = exp_sub.add_parser("get", help="查看指定 EXP 条目详情")
    exp_get_p.add_argument("exp_id", help="经验编号，如 EXP-146")
    
    # exp add
    exp_add_p = exp_sub.add_parser("add", help="沉淀新增经验条目")
    exp_add_p.add_argument("--title", required=True, help="一句话标题/结论")
    exp_add_p.add_argument("--type", default="踩坑+复用方法", help="类型，默认'踩坑+复用方法'")
    exp_add_p.add_argument("--phenomenon", default="", help="触发条件与现象")
    exp_add_p.add_argument("--cause", default="", help="定位与根本原因")
    exp_add_p.add_argument("--solution", default="", help="解决步骤与处理")
    exp_add_p.add_argument("--criteria", default="", help="判据与验证结论")
    exp_add_p.add_argument("--sink", default=None, help="下沉目标项目编号/目录（若提供则落盘到该项目docs）")
    exp_add_p.add_argument("--agent", default="Agent", help="记录主体 Agent")
    
    # exp update
    exp_up_p = exp_sub.add_parser("update", help="为已有经验追加补充更新")
    exp_up_p.add_argument("exp_id", help="经验编号，如 EXP-146")
    exp_up_p.add_argument("--note", required=True, help="补充内容或验证结论")
    exp_up_p.add_argument("--agent", default="Agent", help="记录主体 Agent")

    # --- project ---
    proj_parser = subparsers.add_parser("project", help="项目管理与 SOP 建项")
    proj_sub = proj_parser.add_subparsers(dest="proj_command")
    proj_sub.add_parser("list", help="列出所有项目")
    
    proj_new_p = proj_sub.add_parser("new", help="按 SOP 规范创建新项目")
    proj_new_p.add_argument("name", help="项目简短名称")
    proj_new_p.add_argument("--owner", default="Agent", help="负责人或执行主体")
    
    proj_up_p = proj_sub.add_parser("update", help="更新项目状态与接续入口")
    proj_up_p.add_argument("project", help="项目编号或名称")
    proj_up_p.add_argument("--status", required=True, help="最新状态说明")
    proj_up_p.add_argument("--entry", default=None, help="接续入口路径")

    # --- handoff ---
    handoff_parser = subparsers.add_parser("handoff", help="多 Agent 交接记录管理")
    handoff_parser.add_argument("project", help="项目编号或名称")
    handoff_parser.add_argument("--agent", required=True, help="执行主体 Agent 名字")
    handoff_parser.add_argument("--status", required=True, help="最新状态")
    handoff_parser.add_argument("--done", required=True, help="已完成工作清单")
    handoff_parser.add_argument("--evidence", default="", help="关键证据路径或核验证明")
    handoff_parser.add_argument("--todo", default="", help="未完成与下一步计划")

    # --- status & commit ---
    subparsers.add_parser("status", help="查看活跃项目与工作区状态")
    commit_p = subparsers.add_parser("commit", help="提交工作区全局文档与项目变更到本地 Git")
    commit_p.add_argument("-m", "--message", required=True, help="提交日志")

    args = parser.parse_args()

    if args.command == "exp":
        if args.exp_command == "search":
            cmd_exp_search(args.query)
        elif args.exp_command == "get":
            cmd_exp_get(args.exp_id)
        elif args.exp_command == "add":
            cmd_exp_add(
                title=args.title,
                exp_type=args.type,
                phenomenon=args.phenomenon,
                cause=args.cause,
                solution=args.solution,
                criteria=args.criteria,
                sink_proj=args.sink,
                agent=args.agent,
            )
        elif args.exp_command == "update":
            cmd_exp_update(args.exp_id, args.note, args.agent)
        else:
            exp_parser.print_help()
    elif args.command == "project":
        if args.proj_command == "list":
            cmd_project_list()
        elif args.proj_command == "new":
            cmd_project_new(args.name, args.owner)
        elif args.proj_command == "update":
            cmd_project_update(args.project, args.status, args.entry)
        else:
            proj_parser.print_help()
    elif args.command == "handoff":
        cmd_handoff_record(
            proj_key=args.project,
            agent=args.agent,
            status=args.status,
            done=args.done,
            evidence=args.evidence,
            todo=args.todo,
        )
    elif args.command == "status":
        cmd_status()
    elif args.command == "commit":
        cmd_commit(args.message)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
