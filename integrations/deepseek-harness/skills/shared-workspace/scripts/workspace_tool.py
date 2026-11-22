#!/usr/bin/env python3
r"""Shared Workspace Management CLI Tool.

Enforces SOP rules, query/append/update experiences (EXP), manage projects,
record handoffs, guard dirty working trees, and perform local Git commits
with cross-process file locking.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# Local upstream default; set to None in portable distributions to default to cwd.
DEFAULT_WORKSPACE_ROOT: Path | None = None

DEFAULT_FILES_ZH = {
    "agents": "AGENTS.md",
    "board": "全局工作台.md",
    "log": "全局复用与踩坑日志.md",
    "sop": "新项目创建SOP.md",
}

DEFAULT_FILES_EN = {
    "agents": "AGENTS.md",
    "board": "WORKSPACE.md",
    "log": "EXPERIENCES.md",
    "sop": "NEW_PROJECT_SOP.md",
}

CONFIG_FILENAME = "workspace.config.json"
LOCK_FILENAME = ".workspace.lock"


def resolve_workspace_root() -> Path:
    """Resolve workspace root: AGENT_WORKSPACE_ROOT > DEFAULT_WORKSPACE_ROOT > cwd."""
    override = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if DEFAULT_WORKSPACE_ROOT is not None:
        return DEFAULT_WORKSPACE_ROOT.resolve()
    return Path.cwd().resolve()


def load_workspace_config(root: Path) -> tuple[str, dict[str, str]]:
    """Load language and filenames from workspace.config.json or auto-detect layout."""
    cfg_path = root / CONFIG_FILENAME
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            lang = str(data.get("lang", "zh")).lower()
            defaults = DEFAULT_FILES_EN if lang == "en" else DEFAULT_FILES_ZH
            files = dict(defaults)
            if isinstance(data.get("files"), dict):
                for key in ("agents", "board", "log", "sop"):
                    val = data["files"].get(key)
                    if isinstance(val, str) and val.strip():
                        files[key] = val.strip()
            return lang, files
        except (OSError, json.JSONDecodeError):
            pass

    if (root / DEFAULT_FILES_EN["log"]).exists() or (root / DEFAULT_FILES_EN["board"]).exists():
        if not (root / DEFAULT_FILES_ZH["log"]).exists() and not (root / DEFAULT_FILES_ZH["board"]).exists():
            return "en", dict(DEFAULT_FILES_EN)

    return "zh", dict(DEFAULT_FILES_ZH)


WORKSPACE_ROOT = resolve_workspace_root()
WORKSPACE_LANG, WORKSPACE_FILES = load_workspace_config(WORKSPACE_ROOT)
GLOBAL_LOG = WORKSPACE_ROOT / WORKSPACE_FILES["log"]
GLOBAL_BOARD = WORKSPACE_ROOT / WORKSPACE_FILES["board"]
SOP_FILE = WORKSPACE_ROOT / WORKSPACE_FILES["sop"]
AGENTS_FILE = WORKSPACE_ROOT / WORKSPACE_FILES["agents"]
LOCK_FILE = WORKSPACE_ROOT / LOCK_FILENAME


# -------------------------------------------------------------
# Cross-process Reentrant File Lock (stdlib only)
# -------------------------------------------------------------
class WorkspaceLock:
    """Cross-process exclusive file lock (msvcrt on Windows, fcntl on POSIX).

    Reentrant within the same Python process so compound commands like
    ``handoff`` -> ``project update`` never self-deadlock.
    """

    _held: dict[Path, tuple[int, Any]] = {}

    def __init__(self, lock_path: Path | None = None, timeout: float | None = None) -> None:
        self.lock_path = (lock_path or LOCK_FILE).resolve()
        if timeout is None:
            env_timeout = os.environ.get("AGENT_WORKSPACE_LOCK_TIMEOUT", "10").strip()
            try:
                timeout = float(env_timeout)
            except ValueError:
                timeout = 10.0
        self.timeout = max(0.0, timeout)

    def acquire(self) -> None:
        if self.lock_path in self._held:
            depth, handle = self._held[self.lock_path]
            self._held[self.lock_path] = (depth + 1, handle)
            return

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.lock_path, "a+b")
        deadline = time.monotonic() + self.timeout

        while True:
            try:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._held[self.lock_path] = (1, handle)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise TimeoutError(
                        f"等待工作区写锁超时（{self.timeout:.1f}s）：{self.lock_path}。"
                        "可能有其他 Agent 正在写入，请稍后重试。"
                    )
                time.sleep(0.05)

    def release(self) -> None:
        entry = self._held.get(self.lock_path)
        if not entry:
            return
        depth, handle = entry
        if depth > 1:
            self._held[self.lock_path] = (depth - 1, handle)
            return

        del self._held[self.lock_path]
        try:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> WorkspaceLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


# -------------------------------------------------------------
# Basic Helpers
# -------------------------------------------------------------
def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd or WORKSPACE_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def get_dirty_files() -> tuple[bool, list[str], str]:
    """Return (is_git_repo, dirty_lines, error_message), excluding the lock file."""
    res = run_git(["-c", "core.quotepath=false", "status", "--porcelain"])
    if res.returncode != 0:
        return False, [], res.stderr.strip() or res.stdout.strip()
    lines: list[str] = []
    for raw in res.stdout.splitlines():
        if not raw.strip():
            continue
        path_part = raw[3:].strip().strip('"')
        if path_part == LOCK_FILENAME or path_part.endswith("/" + LOCK_FILENAME):
            continue
        lines.append(raw)
    return True, lines, ""


def find_project_dir(proj_key: str) -> Path | None:
    """Find a Project_xxx directory by number (e.g. 13, 013, P013) or name substring."""
    proj_key_clean = proj_key.strip()
    m = re.match(r"^[pP]?(\d+)$", proj_key_clean)
    target_num = int(m.group(1)) if m else None

    if not WORKSPACE_ROOT.exists():
        return None

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


def parse_tags(raw_tags: list[str] | None) -> list[str]:
    """Normalize tags from repeated --tag flags or comma/space-separated values."""
    if not raw_tags:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        for token in re.split(r"[,，\s]+", item.strip()):
            clean = token.strip().lstrip("#")
            if not clean:
                continue
            key = clean.lower()
            if key not in seen:
                seen.add(key)
                result.append(clean)
    return result


def extract_hashtags(text: str) -> list[str]:
    """Extract #tag tokens from markdown text without matching markdown headings."""
    tags: list[str] = []
    for match in re.finditer(r"(?:^|[\s（(\[|，,])#([^\s#|,，。）\]]+)", text):
        tag = match.group(1).strip()
        if tag and not re.fullmatch(r"\d+", tag):
            tags.append(tag)
    return tags


def text_matches_tags(text: str, required_tags: list[str]) -> bool:
    if not required_tags:
        return True
    present = {t.lower() for t in extract_hashtags(text)}
    return all(req.lower() in present for req in required_tags)


# -------------------------------------------------------------
# Init Operation
# -------------------------------------------------------------
def _skeleton_docs(lang: str) -> dict[str, str]:
    if lang == "en":
        return {
            DEFAULT_FILES_EN["agents"]: """# Shared Workspace Rules

This workspace is the single source of truth for all coding agents.

## First-turn checklist
1. Read `AGENTS.md`, `WORKSPACE.md`, `NEW_PROJECT_SOP.md`, and the index table of `EXPERIENCES.md`.
2. Before debugging or adding a dependency, run `exp search` first.
3. Keep all project artifacts inside `Project_XXX_<Name>/`.
4. Before ending a task, record `handoff` (when applicable) and run `commit -m "..."`.
""",
            DEFAULT_FILES_EN["board"]: """# Workspace Board

## Projects

| ID | Directory | Status | Entry |
| --- | --- | --- | --- |
""",
            DEFAULT_FILES_EN["log"]: """# Experience & Pitfall Log

## Experience Index

### Active Entries (0)

| ID | Date | Type | Title | Location |
| --- | --- | --- | --- | --- |

## Records
""",
            DEFAULT_FILES_EN["sop"]: """# New Project SOP

1. Check `WORKSPACE.md` to ensure no duplicate project exists.
2. Create the project directory using `workspace_tool.py project new "<name>" --owner "<agent>"`.
3. Update `docs/当前状态与交接.md` via `handoff` before pausing or finishing.
4. Commit all changes via `commit -m "..."`.
""",
        }

    return {
        DEFAULT_FILES_ZH["agents"]: """# 共享工作空间规则

本工作空间是所有 Agent 的唯一记忆与项目协作入口。

## 启动与操作约定
1. 新建对话首轮读取 `AGENTS.md`、`全局工作台.md`、`新项目创建SOP.md` 及 `全局复用与踩坑日志.md` 的索引表。
2. 排查问题或引入新依赖前，先执行 `exp search "关键词"` 检索已有经验。
3. 所有项目产物必须落盘到对应 `Project_编号_项目名称/` 目录。
4. 阶段完成用 `handoff` 交接，新经验用 `exp add` / `exp update` 沉淀，结束前用 `commit -m "..."` 固化到 Git。
""",
        DEFAULT_FILES_ZH["board"]: """# 全局工作台

## 项目登记与接续入口

| 编号 | 目录 | 当前状态 | 接续入口 |
| --- | --- | --- | --- |
""",
        DEFAULT_FILES_ZH["log"]: """# 全局复用与踩坑日志

## 经验索引

### 现行条目（0 条）

| 编号 | 日期 | 类型 | 标题 | 位置 |
| --- | --- | --- | --- | --- |

## 记录
""",
        DEFAULT_FILES_ZH["sop"]: """# 新项目创建 SOP

1. 检查 `全局工作台.md`，确认无同目标项目。
2. 使用 `workspace_tool.py project new "<名称>" --owner "<agent>"` 建项，不手动建目录。
3. 阶段完成或暂停前使用 `handoff` 更新交接与登记表。
4. 结束前使用 `commit -m "..."` 提交工作区变更。
""",
    }


def cmd_init(lang: str = "zh", no_git: bool = False) -> None:
    lang = "en" if lang.lower() == "en" else "zh"
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

    with WorkspaceLock():
        created: list[str] = []
        skipped: list[str] = []

        docs = _skeleton_docs(lang)
        for filename, content in docs.items():
            target = WORKSPACE_ROOT / filename
            if target.exists():
                skipped.append(filename)
            else:
                write_text(target, content)
                created.append(filename)

        cfg_path = WORKSPACE_ROOT / CONFIG_FILENAME
        files_map = DEFAULT_FILES_EN if lang == "en" else DEFAULT_FILES_ZH
        if cfg_path.exists():
            skipped.append(CONFIG_FILENAME)
        else:
            cfg_data = {"lang": lang, "files": files_map}
            write_text(cfg_path, json.dumps(cfg_data, ensure_ascii=False, indent=2) + "\n")
            created.append(CONFIG_FILENAME)

        gitignore_path = WORKSPACE_ROOT / ".gitignore"
        if not gitignore_path.exists():
            write_text(
                gitignore_path,
                f"{LOCK_FILENAME}\n**/tmp/\n**/__pycache__/\n*.pyc\n.DS_Store\n",
            )
            created.append(".gitignore")
        else:
            gi_text = read_text(gitignore_path)
            if LOCK_FILENAME not in gi_text.splitlines():
                write_text(gitignore_path, gi_text.rstrip() + f"\n{LOCK_FILENAME}\n")
                print(f"已向 .gitignore 追加 {LOCK_FILENAME}")
            skipped.append(".gitignore")

        if not no_git and not (WORKSPACE_ROOT / ".git").exists():
            res = run_git(["init"])
            if res.returncode == 0:
                run_git(["config", "core.quotepath", "false"])
                print(f"已初始化 Git 仓库: {WORKSPACE_ROOT}")
            else:
                print(f"警告: git init 失败: {res.stderr.strip()}", file=sys.stderr)

    print(f"工作空间初始化完成（语言: {lang}，目录: {WORKSPACE_ROOT}）")
    if created:
        print("新建文件: " + ", ".join(created))
    if skipped:
        print("已存在跳过: " + ", ".join(skipped))


# -------------------------------------------------------------
# EXP Operations (Read, Add, Update, Tags)
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


def cmd_exp_list_tags() -> None:
    if not GLOBAL_LOG.exists():
        print(f"Error: {GLOBAL_LOG} not found.", file=sys.stderr)
        sys.exit(1)

    content = read_text(GLOBAL_LOG)
    counts: dict[str, int] = {}
    display_name: dict[str, str] = {}

    for line in content.splitlines():
        if line.startswith("| EXP-") or line.startswith("- 标签：") or line.startswith("- Tags:"):
            for tag in extract_hashtags(line):
                key = tag.lower()
                counts[key] = counts.get(key, 0) + 1
                display_name.setdefault(key, tag)

    if not counts:
        print("当前暂无已登记标签。使用 `exp add --tag <标签>` 为经验打标。")
        return

    print("=== 经验标签统计 ===")
    for key, cnt in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"#{display_name[key]} ({cnt})")


def cmd_exp_search(query: str = "", raw_tags: list[str] | None = None, list_tags: bool = False) -> None:
    if list_tags:
        cmd_exp_list_tags()
        return

    tags = parse_tags(raw_tags)
    if not query and not tags:
        print("错误: 请至少提供检索关键词或 --tag 标签。", file=sys.stderr)
        sys.exit(1)

    if not GLOBAL_LOG.exists():
        print(f"Error: {GLOBAL_LOG} not found.", file=sys.stderr)
        sys.exit(1)

    content = read_text(GLOBAL_LOG)
    lines = content.splitlines()

    cond_parts: list[str] = []
    if query:
        cond_parts.append(f"关键词: '{query}'")
    if tags:
        cond_parts.append("标签: " + " ".join(f"#{t}" for t in tags))
    print(f"=== 搜索踩坑与复用经验 ({'，'.join(cond_parts)}) ===")

    matches = 0
    in_table = False
    for line in lines:
        if line.startswith("| EXP-") or (in_table and line.startswith("|")):
            in_table = True
            q_ok = (not query) or (query.lower() in line.lower())
            t_ok = text_matches_tags(line, tags)
            if q_ok and t_ok:
                print(line)
                matches += 1
        elif in_table and not line.startswith("|"):
            in_table = False

    if matches == 0:
        print("未在经验索引表中找到匹配项，尝试检索全文段落...")
        sections = re.split(r"(?=^### EXP-\d+)", content, flags=re.MULTILINE)
        for sec in sections:
            if not sec.startswith("### EXP-"):
                continue
            q_ok = (not query) or (query.lower() in sec.lower())
            t_ok = text_matches_tags(sec, tags)
            if q_ok and t_ok:
                snippet = "\n".join(sec.splitlines()[:10])
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

    if not GLOBAL_LOG.exists():
        print(f"Error: {GLOBAL_LOG} not found.", file=sys.stderr)
        sys.exit(1)

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
        if location and ("下沉" in location or "sunk" in location.lower()):
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
    raw_tags: list[str] | None = None,
) -> None:
    if not GLOBAL_LOG.exists():
        print(f"错误: 找不到 {GLOBAL_LOG}", file=sys.stderr)
        sys.exit(1)

    tags = parse_tags(raw_tags)
    tag_str = " ".join(f"#{t}" for t in tags)
    display_title = title.strip()
    if tags:
        existing_tags = {t.lower() for t in extract_hashtags(display_title)}
        missing_tags = [f"#{t}" for t in tags if t.lower() not in existing_tags]
        if missing_tags:
            display_title = f"{display_title} {' '.join(missing_tags)}"

    with WorkspaceLock():
        next_id = get_max_exp_id() + 1
        exp_tag = f"EXP-{next_id:03d}"
        today = datetime.date.today().strftime("%Y-%m-%d")

        sink_dir = find_project_dir(sink_proj) if sink_proj else None
        if sink_proj and not sink_dir:
            print(f"警告: 找不到项目 '{sink_proj}'，将直接写入全局正文。", file=sys.stderr)

        tag_meta_line = f"- 标签：{tag_str}\n" if tag_str else ""

        if sink_dir:
            p_name = sink_dir.name
            docs_dir = sink_dir / "docs"
            docs_dir.mkdir(exist_ok=True)
            sink_file = docs_dir / "踩坑与复用经验.md"
            location_str = f"下沉；{p_name} `docs/踩坑与复用经验.md`"

            exp_body = (
                f"### {exp_tag}｜{today}｜{display_title}\n\n"
                f"- 记录主体：{agent}；类型：{exp_type}\n"
                f"{tag_meta_line}"
                f"- 现象：{phenomenon or '（无）'}\n"
                f"- 定位：{cause or '（无）'}\n"
                f"- 处理：{solution or '（无）'}\n"
                f"- 判据：{criteria or '（无）'}\n"
            )
            if sink_file.exists():
                old_sink = read_text(sink_file)
                write_text(sink_file, old_sink.rstrip() + "\n\n" + exp_body)
            else:
                header = f"# {p_name} 踩坑与复用经验下沉库\n\n"
                write_text(sink_file, header + exp_body)
            print(f"详细经验已下沉写入: {sink_file}")
        else:
            location_str = "正文"

        content = read_text(GLOBAL_LOG)

        def repl_count_zh(m: re.Match[str]) -> str:
            return f"### 现行条目（{int(m.group(1)) + 1} 条）"

        def repl_count_en(m: re.Match[str]) -> str:
            return f"### Active Entries ({int(m.group(1)) + 1})"

        content, n_zh = re.subn(r"### 现行条目（(\d+)\s*条）", repl_count_zh, content, count=1)
        if n_zh == 0:
            content = re.sub(r"### Active Entries \((\d+)\)", repl_count_en, content, count=1)

        table_header_pat = (
            r"(\|\s*(?:编号|ID)\s*\|\s*(?:日期|Date)\s*\|\s*(?:类型|Type)\s*"
            r"\|\s*(?:标题|Title)\s*\|\s*(?:位置|Location)\s*\|\s*\n\|\s*---[^\n]+\n)"
        )
        m_header = re.search(table_header_pat, content)
        if not m_header:
            print("错误: 无法在全局日志中定位索引表格头！", file=sys.stderr)
            sys.exit(1)

        new_row = f"| {exp_tag} | {today} | {exp_type} | {display_title} | {location_str} |\n"
        pos = m_header.end()
        content = content[:pos] + new_row + content[pos:]

        if not sink_dir:
            exp_body = (
                f"### {exp_tag}｜{today}｜{display_title}\n\n"
                f"- 类型：{exp_type}；记录主体：{agent}。\n"
                f"{tag_meta_line}"
                f"- 现象：{phenomenon or '待补充'}\n"
                f"- 定位：{cause or '待补充'}\n"
                f"- 处理：{solution or '待补充'}\n"
                f"- 判据：{criteria or '待补充'}\n\n"
            )
            body_pat = r"(\n### EXP-\d+(?:｜|\s*\|))"
            m_body = re.search(body_pat, content)
            if m_body:
                b_pos = m_body.start() + 1
                content = content[:b_pos] + exp_body + content[b_pos:]
            else:
                content = content.rstrip() + "\n\n" + exp_body

        write_text(GLOBAL_LOG, content)

    print(f"成功沉淀新经验记忆: {exp_tag}")
    print(f"标题: {display_title}")
    if tag_str:
        print(f"标签: {tag_str}")
    print(f"位置: {location_str}")


def cmd_exp_update(exp_id: str, note: str, agent: str = "Agent") -> None:
    exp_id = exp_id.upper()
    if not exp_id.startswith("EXP-"):
        exp_id = f"EXP-{exp_id}"

    if not GLOBAL_LOG.exists():
        print(f"错误: 找不到 {GLOBAL_LOG}", file=sys.stderr)
        sys.exit(1)

    with WorkspaceLock():
        content = read_text(GLOBAL_LOG)
        today = datetime.date.today().strftime("%Y-%m-%d")

        pat = rf"(### {re.escape(exp_id)}(?:｜|\s*\|)[^\n]+\n(?:(?!### EXP-).)*)"
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
            if f"| {exp_id} |" in line and ("下沉" in line or "sunk" in line.lower()):
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
    if not WORKSPACE_ROOT.exists():
        return 0
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
    if WORKSPACE_ROOT.exists():
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
    with WorkspaceLock():
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
- 启动前检查：已阅读 `{WORKSPACE_FILES['agents']}`、`{WORKSPACE_FILES['board']}`、`{WORKSPACE_FILES['sop']}` 全文及 `{WORKSPACE_FILES['log']}` 经验索引
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
                header = re.search(
                    r"\|\s*(?:编号|ID)\s*\|\s*(?:目录|Directory)\s*\|\s*(?:当前状态|Status)\s*\|\s*(?:接续入口|Entry)\s*\|\n\|\s*---[^\n]+\n",
                    board_content,
                )
                insert_pos = header.end() if header else len(board_content)
            updated_board = board_content[:insert_pos] + new_row + board_content[insert_pos:]
            write_text(GLOBAL_BOARD, updated_board)
            print(f"已自动登记到 {GLOBAL_BOARD.name} 项目登记表。")

    print(f"成功创建新项目：{dir_name}")
    print(f"路径: {proj_dir}")


def cmd_project_update(proj_key: str, status: str, entry: str | None = None) -> None:
    with WorkspaceLock():
        p_dir = find_project_dir(proj_key)
        if not p_dir:
            print(f"错误: 找不到项目 '{proj_key}'", file=sys.stderr)
            sys.exit(1)

        m = re.match(r"^Project_(\d+)_", p_dir.name)
        num_str = m.group(1) if m else ""

        readme_file = p_dir / "README.md"
        if readme_file.exists():
            r_text = read_text(readme_file)
            r_text = re.sub(r"-\s*(?:当前状态：|Status:\s*)[^\n]+", f"- 当前状态：{status}", r_text)
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
                print(f"已同步更新 {GLOBAL_BOARD.name} 登记表状态。")


def cmd_handoff_record(
    proj_key: str,
    agent: str,
    status: str,
    done: str,
    evidence: str = "",
    todo: str = "",
) -> None:
    with WorkspaceLock():
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
# Status, Guard and Git Operations
# -------------------------------------------------------------
def cmd_guard() -> None:
    is_repo, dirty_lines, err = get_dirty_files()
    if not is_repo:
        print(f"[GUARD ERROR] 当前目录不是有效的 Git 仓库：{err}", file=sys.stderr)
        sys.exit(2)

    if dirty_lines:
        print(f"[GUARD WARNING] 检测到 {len(dirty_lines)} 项未提交的工作区变更！")
        for line in dirty_lines:
            print(f"  {line}")
        print('建议立即固化版本：python workspace_tool.py commit -m "<变更说明>"')
        sys.exit(1)

    print("[GUARD OK] 工作树干净，无未提交改动。")


def cmd_status(guard: bool = False) -> None:
    print(f"=== Workspace 当前全局状态概览 ({WORKSPACE_ROOT}) ===")
    if GLOBAL_BOARD.exists():
        content = read_text(GLOBAL_BOARD)
        print("\n【进行中 / 重点项目】:")
        for line in content.splitlines():
            if re.match(r"^\|\s*\d{3}\s*\|", line) and (
                "进行中" in line or "待" in line or "验证" in line or "in progress" in line.lower()
            ):
                print(line)

    print("\n【Git 变更状态】:")
    is_repo, dirty_lines, err = get_dirty_files()
    if not is_repo:
        print(f"未检测到 Git 仓库：{err}")
        if guard:
            sys.exit(2)
        return

    if dirty_lines:
        print("\n".join(dirty_lines))
        if guard:
            print(f"\n[GUARD WARNING] 检测到 {len(dirty_lines)} 项未提交变更，退出前请执行 commit。")
            sys.exit(1)
    else:
        print("工作树干净，无未提交改动。")


def cmd_commit(msg: str) -> None:
    if not msg:
        print("错误: 必须提供 commit 信息 (-m)", file=sys.stderr)
        sys.exit(1)

    with WorkspaceLock():
        print(f"=== 提交 Workspace 变更: '{msg}' ===")
        add_res = run_git(["add", "-A"])
        if add_res.returncode != 0:
            print(f"git add 失败: {add_res.stderr}", file=sys.stderr)
            sys.exit(1)

        # Ensure the transient lock file is never staged even if .gitignore lacks it.
        run_git(["reset", "-q", "--", LOCK_FILENAME])

        diff_res = run_git(["diff", "--cached", "--quiet"])
        if diff_res.returncode == 0:
            print("无需提交：无文件变更。")
            return

        commit_res = run_git(["commit", "-m", msg])
        if commit_res.returncode != 0:
            err_msg = commit_res.stderr.strip() or commit_res.stdout.strip()
            print(f"git commit 失败: {err_msg}", file=sys.stderr)
            sys.exit(1)

        print(commit_res.stdout.strip())


# -------------------------------------------------------------
# Main CLI Router
# -------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Agent Workspace Hub CLI")
    subparsers = parser.add_subparsers(dest="command")

    # --- init ---
    init_p = subparsers.add_parser("init", help="初始化共享工作空间骨架文档与配置")
    init_p.add_argument("--lang", choices=["zh", "en"], default="zh", help="骨架文档语言（默认 zh）")
    init_p.add_argument("--no-git", action="store_true", help="跳过 git init")

    # --- exp ---
    exp_parser = subparsers.add_parser("exp", help="查询、沉淀与修订踩坑经验")
    exp_sub = exp_parser.add_subparsers(dest="exp_command")

    # exp search
    exp_search_p = exp_sub.add_parser("search", help="按关键词和/或标签搜索经验索引")
    exp_search_p.add_argument("query", nargs="?", default="", help="关键词（可选，与 --tag 组合或单独使用）")
    exp_search_p.add_argument("--tag", action="append", default=None, help="按标签筛选（支持逗号分隔或多次传参）")
    exp_search_p.add_argument("--list-tags", action="store_true", help="列出所有已登记标签及频次")

    # exp get
    exp_get_p = exp_sub.add_parser("get", help="查看指定 EXP 条目详情")
    exp_get_p.add_argument("exp_id", help="经验编号，如 EXP-146")

    # exp add
    exp_add_p = exp_sub.add_parser("add", help="沉淀新增经验条目")
    exp_add_p.add_argument("--title", required=True, help="一句话标题/结论")
    exp_add_p.add_argument("--type", default="踩坑+复用方法", help="类型，默认'踩坑+复用方法'")
    exp_add_p.add_argument("--tag", action="append", default=None, help="分类标签（如 --tag docker,linux）")
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

    # --- status, guard & commit ---
    status_p = subparsers.add_parser("status", help="查看活跃项目与工作区状态")
    status_p.add_argument("--guard", action="store_true", help="若有未提交改动则打印警告并返回退出码 1")
    subparsers.add_parser("guard", help="巡检工作树是否干净（有未提交改动则返回退出码 1）")
    commit_p = subparsers.add_parser("commit", help="提交工作区全局文档与项目变更到本地 Git")
    commit_p.add_argument("-m", "--message", required=True, help="提交日志")

    args = parser.parse_args()

    try:
        if args.command == "init":
            cmd_init(lang=args.lang, no_git=args.no_git)
        elif args.command == "exp":
            if args.exp_command == "search":
                cmd_exp_search(args.query, raw_tags=args.tag, list_tags=args.list_tags)
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
                    raw_tags=args.tag,
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
            cmd_status(guard=args.guard)
        elif args.command == "guard":
            cmd_guard()
        elif args.command == "commit":
            cmd_commit(args.message)
        else:
            parser.print_help()
    except TimeoutError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
