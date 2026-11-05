"""频道名称 / YouTube handle 解析。

设计原则：**不发起任何 YouTube 请求**。字段来源只有两类：
1. B 站简介里的「主播：名称@handle」行（由 pipeline/bili_comment 已经抓取，纯本地数据）；
2. 仓库内静态目录 `channel_directory.json`（人工维护，供简介缺干净 ASCII handle 时兜底）。

真实 `主播` 行样本（来自生产 data/codex_review）：
- `主播：なつかしちゃん@natsume_ikune`
- `主播：花鹿 める / Kajica Mel@mel_samui`
- `主播：音羽ララ (Otohane Lara) / シアーミュージックV@lara_songs`
- `主播：-sumica-澄花@sumica-澄花`（handle 含中日文混排，无法解析成干净 handle）
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

DIRECTORY_PATH = Path(__file__).with_name("channel_directory.json")

_ANCHOR_RE = re.compile(
    r"^(?:主播(?:/稿件上传者)?|配信者|上传者)[：:]\s*(?P<value>.+?)\s*$"
)
_TRAILING_ASCII_HANDLE_RE = re.compile(r"[@＠]([A-Za-z0-9._\-]{2,})$")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._\-]{2,}$")


def _normalize_key(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace()).casefold()


def load_directory(path: Optional[Path] = None) -> dict[str, str]:
    """读取 name → handle 的兜底映射；任何读/解析异常都返回空 dict。"""
    target = path or DIRECTORY_PATH
    out: dict[str, str] = {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    channels = raw.get("channels") if isinstance(raw, dict) else None
    if not isinstance(channels, dict):
        return out
    for key, value in channels.items():
        handle = value.get("handle") if isinstance(value, dict) else value
        if not isinstance(handle, str):
            continue
        handle = handle.strip().lstrip("@＠").strip()
        if not _HANDLE_RE.fullmatch(handle):
            continue
        out[_normalize_key(str(key))] = handle
    return out


def _split_anchor(value: str) -> tuple[str, str]:
    """从「主播」行取值里拆出 (名称, handle)。

    以最后一个 @/＠ 为界：@ 之后是「干净 ASCII handle」才采用；否则把整串（去掉
    结尾的 @脏串）当作名称返回，交给调用方做目录兜底或只显示名称。避免把
    `sumica-澄花` 这类中日文混排误当成 handle。
    """
    value = value.strip()
    idx = max(value.rfind("@"), value.rfind("＠"))
    if idx < 0:
        return value, ""
    name = value[:idx].strip()
    cand = value[idx + 1 :].strip()
    if _HANDLE_RE.fullmatch(cand):
        return (name or value), cand
    return (name or value), ""


def channel_label(
    desc_profile: str = "",
    directory_path: Optional[Path] = None,
) -> str:
    """返回 `名称 @handle`；缺 handle 时退回 `名称`；都缺时返回空串。

    优先从 B 站简介的「主播」行解析；若该行没有干净 ASCII handle，则按名称查
    channel_directory.json 兜底。全程不发起任何 YouTube 请求。
    """
    if desc_profile:
        for line in desc_profile.splitlines():
            match = _ANCHOR_RE.match(line.strip())
            if not match:
                continue
            name, handle = _split_anchor(match.group("value"))
            if handle:
                return f"{name} @{handle}"
            if name:
                fallback = load_directory(directory_path).get(_normalize_key(name))
                return f"{name} @{fallback}" if fallback else name
    return ""
