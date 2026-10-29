"""song_serch_lyrics 归档歌单导入：pending 候选缺少结构化来源时的补充检测层。

归档仓库（Marica7731/song_serch_lyrics，默认分支 song_serch_lyrics）按
`songlists/<日期范围>/*.md` 组织；合并文件内以「文件名：…[日期][yt_id]….md」分节，
每节带 主歌单 / 开始时间版索引 / 起止时间版索引 三个 text 代码块。

发布格式遵循 RULES.md 通用原则 #2：有起止时间戳输出 `开始-结束`，只有开始时间输出开始。
本模块不做猜测性补全；解析不出索引或行时返回 None / 跳过该行。
结构化 SETLIST 中没有歌手的编号歌曲仍是有效条目，按 R17 保留无歌手格式。
"""
from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("yt_comment_automation")

# WDC 上的 GitHub token 文件（项目 AGENTS.md 约定）；仅在 git fetch 时经环境变量注入，不落盘不进日志
DEFAULT_TOKEN_FILE = "/root/.secrets/github-token"
FETCH_TIMEOUT_SECONDS = 60.0

_RANGE_LINE_RE = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*[~～〜]\s*(?P<end>\d{1,2}:\d{2}(?::\d{2})?)\s+"
    r"(?P<num>\d{1,3})[.．]\s*(?P<title>.+?)\s*(?<![／/])[/／](?![/／])\s*(?P<artist>.+)$"
)
_START_LINE_RE = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<num>\d{1,3})[.．]\s*"
    r"(?P<title>.+?)\s*(?<![／/])[/／](?![/／])\s*(?P<artist>.+)$"
)
_RANGE_TITLE_ONLY_RE = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*[~～〜]\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<num>\d{1,3})[.．]\s*"
    r"(?P<title>.+?)\s*$"
)
_START_TITLE_ONLY_RE = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<num>\d{1,3})[.．]\s*"
    r"(?P<title>.+?)\s*$"
)
# 顺序即优先级：起止时间版 > 开始时间版（RULES.md 通用原则 #2）
_INDEX_HEADINGS = ("起止时间版索引", "开始时间版索引")

_refresh_attempted = False


@dataclass
class ArchiveDraft:
    source: str  # 审核队列 payload 的 source 字段，固定 song_serch_lyrics
    label: str  # 归档位置，如 songlists/2026-10-28至2026-10-29/歌单_xxx.md
    index_text: str  # 命中的原始索引行，随审核材料一并交给审核方
    messages: list[str]  # 发布格式草稿：单条多行消息，超长切分由发布层负责
    song_count: int  # 歌曲行数（≠ messages 条数）

    def review_addendum(self, prefix_empty: bool) -> str:
        header = f"[song_serch_lyrics 归档 {self.label}]\n{self.index_text}"
        if prefix_empty:
            return header
        return "\n\n---\n\n" + header


def refresh(root: str | Path, timeout: float = FETCH_TIMEOUT_SECONDS) -> bool:
    """有界 git fetch 更新本地归档克隆；工作树不干净时一律不动。

    归档克隆是只读镜像（reset --hard 到 FETCH_HEAD 即更新）；
    若把 SONG_SERCH_LYRICS_ROOT 指到有本地改动的克隆，这里会拒绝刷新以保护现场。
    """
    root_path = Path(root)
    if not (root_path / ".git").is_dir():
        return False
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        if dirty.stdout.strip():
            logger.warning("song_serch_lyrics 克隆有本地改动，跳过归档刷新: %s", root_path)
            return False
        branch = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        ).stdout.strip()
        env = dict(os.environ)
        token_file = Path(os.environ.get("SONG_SERCH_LYRICS_TOKEN_FILE", DEFAULT_TOKEN_FILE))
        if token_file.is_file():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                # github.com 的 git 端点只认 Basic（Bearer 仅 REST API 可用，实测 401）
                basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
                env["GIT_CONFIG_COUNT"] = "1"
                env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
                env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {basic}"
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", branch or "HEAD"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "reset", "--hard", "FETCH_HEAD"],
            cwd=root_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        return True
    except (OSError, subprocess.SubprocessError) as err:
        logger.warning("song_serch_lyrics 归档刷新失败（沿用本地现有数据）: %s", err)
        return False


def ensure_fresh(root: str | Path) -> bool:
    """每个管线进程只在首次命中归档检测时刷新一次，避免逐视频重复 fetch。"""
    global _refresh_attempted
    if _refresh_attempted:
        return False
    _refresh_attempted = True
    return refresh(root)


def reset_refresh_state_for_tests() -> None:
    global _refresh_attempted
    _refresh_attempted = False


def _split_sections(lines: list[str]) -> list[list[str]]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("文件名："):
            if current:
                sections.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        sections.append(current)
    return sections


def find_section(root: str | Path, yt_id: str) -> tuple[str, list[str]] | None:
    """按 [yt_id] 定位小节；目录与文件按名称倒序扫描（新日期范围优先）。"""
    yt = (yt_id or "").strip()
    if not yt:
        return None
    marker = f"[{yt}]"
    songlists = Path(root) / "songlists"
    if not songlists.is_dir():
        return None
    for md in sorted(songlists.glob("*/*.md"), reverse=True):
        try:
            lines = md.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        label = f"songlists/{md.parent.name}/{md.name}"
        for section in _split_sections(lines):
            if any(marker in line for line in section[:10]):
                return label, section
    return None


def _heading_block(section: list[str], heading: str) -> list[str]:
    for idx, line in enumerate(section):
        if line.strip().startswith("#") and heading in line:
            block: list[str] = []
            in_block = False
            for tail in section[idx + 1:]:
                stripped = tail.strip()
                if stripped.startswith("```"):
                    if in_block:
                        return block
                    in_block = True
                    continue
                if in_block:
                    block.append(tail)
            return block
    return []


def extract_index(section: list[str]) -> tuple[str, list[str]] | None:
    """返回 (kind, 原始行)；按编号优先使用区间时间，缺失行从开始时间版补齐。"""
    patterns = (
        _RANGE_LINE_RE,
        _START_LINE_RE,
        _RANGE_TITLE_ONLY_RE,
        _START_TITLE_ONLY_RE,
    )

    def parse_block(heading: str) -> list[str]:
        block = _heading_block(section, heading)
        return [ln for ln in block if any(pattern.match(ln.strip()) for pattern in patterns)]

    def numbered(lines: list[str]) -> list[tuple[tuple[int, int], str]]:
        occurrences: dict[int, int] = {}
        output: list[tuple[tuple[int, int], str]] = []
        for line in lines:
            text = line.strip()
            match = None
            for pattern in patterns:
                match = pattern.match(text)
                if match:
                    break
            if not match:
                continue
            number = int(match["num"])
            occurrence = occurrences.get(number, 0)
            occurrences[number] = occurrence + 1
            output.append(((number, occurrence), line))
        return output

    start_lines = parse_block(_INDEX_HEADINGS[1])
    range_lines = parse_block(_INDEX_HEADINGS[0])
    if range_lines:
        start_rows = numbered(start_lines)
        range_rows = numbered(range_lines)
        start_by_key = dict(start_rows)
        range_by_key = dict(range_rows)
        order = sorted(start_by_key.keys() | range_by_key.keys())
        return "range", [
            range_by_key[key] if key in range_by_key else start_by_key[key]
            for key in order
        ]
    if start_lines:
        return "start", start_lines
    return None


def build_messages(index_lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in index_lines:
        text = line.strip()
        if not text:
            continue
        m = _RANGE_LINE_RE.match(text)
        if m:
            out.append(f"{m['start']}-{m['end']} {m['num']}. {m['title']} - {m['artist']}")
            continue
        m = _START_LINE_RE.match(text)
        if m:
            out.append(f"{m['start']} {m['num']}. {m['title']} - {m['artist']}")
            continue
        m = _RANGE_TITLE_ONLY_RE.match(text)
        if m:
            out.append(f"{m['start']}-{m['end']} {m['num']}. {m['title'].strip()}")
            continue
        m = _START_TITLE_ONLY_RE.match(text)
        if m:
            out.append(f"{m['start']} {m['num']}. {m['title'].strip()}")
    return out


def import_draft(root: str | Path, yt_id: str) -> ArchiveDraft | None:
    found = find_section(root, yt_id)
    if not found:
        return None
    label, section = found
    index = extract_index(section)
    if not index:
        return None
    messages = build_messages(index[1])
    if not messages:
        return None
    return ArchiveDraft(
        source="song_serch_lyrics",
        label=label,
        index_text="\n".join(index[1]),
        messages=["\n".join(messages)],
        song_count=len(messages),
    )
