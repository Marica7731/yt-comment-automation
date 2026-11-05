"""频道名称 / YouTube handle 解析。

设计原则：**不发起任何 YouTube 请求**，也**不依赖任何本地配置**。
频道信息只来自一个既有抓取字段——B 站简介里的「主播：名称@handle」行
（由 pipeline / bili_comment 抓取后存入 `desc_profile`，纯本地数据）。

真实 `主播` 行样本（来自生产 data/codex_review）：
- `主播：なつかしちゃん@natsume_ikune`
- `主播：花鹿 める / Kajica Mel@mel_samui`
- `主播：音羽ララ (Otohane Lara) / シアーミュージックV@lara_songs`
- `主播：-sumica-澄花@sumica-澄花`（@ 后是中日文，非干净 handle，只显示名称）
- `主播：一色イズ ⟡ Isshiki_IS@一色イズ`（同上）

没有干净 ASCII handle 时（如上面两种中日文混排），只返回名称，绝不编造。
"""
from __future__ import annotations

import re

_ANCHOR_RE = re.compile(
    r"^(?:主播(?:/稿件上传者)?|配信者|上传者)[：:]\s*(?P<value>.+?)\s*$"
)
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._\-]{2,}$")


def _split_anchor(value: str) -> tuple[str, str]:
    """从「主播」行取值里拆出 (名称, handle)。

    以最后一个 @/＠ 为界：@ 之后是「干净 ASCII handle」才采用；否则把整串
    （去掉结尾的 @脏串）当作名称返回，只显示名称。避免把 `sumica-澄花`、
    `一色イズ` 这类中日文混排误当成 handle。
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


def channel_label(desc_profile: str = "") -> str:
    """返回 `名称 @handle`；缺干净 handle 时退回 `名称`；都缺时返回空串。

    只解析 B 站简介的「主播」行，不发起任何网络请求，也不依赖任何配置。
    """
    if not desc_profile:
        return ""
    for line in desc_profile.splitlines():
        match = _ANCHOR_RE.match(line.strip())
        if not match:
            continue
        name, handle = _split_anchor(match.group("value"))
        if handle:
            return f"{name} @{handle}"
        if name:
            return name
    return ""
