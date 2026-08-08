"""DeepSeek AI 兜底整理（responses API，自动命中 prompt 缓存节省成本）。

本地规则清洗优先；当本地结果为空、或本地结果疑似不完整（歌曲数过少）时，
用 DeepSeek 直接从原文整理歌曲列表。提示词与参考评论输出格式保持一致。
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from . import config
from .clean import ParsedSong

BASE = "https://api.deepseek.com/v1"
MODEL = "deepseek-v4-flash"

PROMPT_TEMPLATE = """你现在要根据我提供的一段 YouTube 评论区时间轴，整理出歌曲命名列表。

这是一个严格筛选任务。你的目标不是"尽量多提取"，而是"只保留可以明确判断为歌曲的条目"，宁可少收，也不要把杂谈、MC、感想、互动、开场、结束、企划说明、串场、聊天内容误判成歌曲。

【核心原则】
1. 只提取"明确是歌曲"的条目，按原出现顺序输出。
2. 每首歌必须同时出现"歌名"和"歌手"才算有效；没有歌手的行直接跳过，不输出。
3. 不要联网，不要用外部知识补全，不要猜测，不要脑补，只能根据我提供的文本判断。
4. 最终只输出结果列表，不能有任何说明文字。

【时间戳处理】
1. 每一行必须保留原文里该歌曲对应的开始时间戳（形如 0:03:55、3:04、1:01:09）。
2. 如果原文该行没有时间戳，但上一行/下一行有时间戳或范围，取开始时间。
3. 找不到对应时间戳的行，跳过不输出。
4. 时间戳一律用半角数字和冒号，全角转半角。

【严格筛选规则】
以下内容一律视为非歌曲，直接跳过：
1. talk、雑談、MC、聊天、感想、开场、结束、告知、企划说明、串场、休息、返场。
2. 只有时间戳，没有歌名歌手的行。
3. 只有歌名，没有歌手的行。
4. 只有歌手，没有歌名的行。
5. 描述性内容、说明性内容、话题、段子、互动内容。
6. 宣伝、告知、お知らせ、ファンクラブ等宣传内容。

【括号内容处理】
1. 括号内容是罗马字、英文对照、读音、翻译说明时删除（如 ("Hibi" - Higuchi Ai)、[Rokutōsei]）。
2. 括号是正式名称的一部分时必须保留：ryo(supercell)、久住小春（モーニング娘。）、涼宮ハルヒ(平野綾)。
3. 歌名或歌手后面的 (＠歌手) 写法中，＠ 后面是歌手，应把歌手提取出来。
4. 表演备注如（ちょっと）、（練習）、（short.）属于脏信息，删除。

【分隔符统一】
1. 原文中歌名与歌手之间可能用 /、／、|、｜、-、＠ 等分隔。
2. 最终输出统一用半角连字符 -，左右各一个半角空格：歌名 - 歌手。

【输出格式】
1. 每行一首，格式严格为：时间戳 NN. 歌名 - 歌手（例如：0:03:55 01. バラライカ - 月島きらり）
2. 编号从 01 开始连续递增，1-99 首用两位编号 01.，100 首以上用三位 001.。
3. 禁止输出空行、标题、前言、后记、代码块标记、括号补充、备注。
4. 除结果列表外不能输出任何其他内容。
5. 如果整份列表里的条目全都没有歌手信息，只输出：请提供歌手信息后再处理。

下面是要整理的时间轴："""


def _extract_output_text(resp: dict) -> str:
    parts = []
    for item in resp.get("output", []) or []:
        if item.get("type") == "message":
            for c in item.get("content", []) or []:
                if c.get("type") == "output_text" and c.get("text"):
                    parts.append(c["text"])
    return "\n".join(parts).strip()


def call_deepseek(user_text: str, timeout: int = 180, retries: int = 2) -> tuple[str, Optional[str]]:
    """调用 DeepSeek responses API。返回 (结果文本, 错误信息)。"""
    api_key = config.deepseek_api_key()
    if not api_key:
        return "", "未配置 DEEPSEEK_API_KEY"
    payload = {
        "model": MODEL,
        "input": [
            {"role": "developer", "content": "你是精确的歌曲列表整理助手。"},
            {"role": "user", "content": PROMPT_TEMPLATE + "\n" + user_text},
        ],
        "max_output_tokens": 8000,
        "temperature": 0,
        "reasoning": {"effort": "low"},
    }
    last_err = ""
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            f"{BASE}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as err:  # noqa: BLE001
            last_err = f"DeepSeek 请求失败: {type(err).__name__}: {err}"
            continue
        if data.get("status") != "completed":
            last_err = f"DeepSeek 状态异常: {data.get('status')} error={data.get('error')}"
            if attempt < retries:
                continue
            return "", last_err
        text = _extract_output_text(data)
        if not text:
            last_err = "DeepSeek 未返回文本结果"
            continue
        return text, None
    return "", last_err


def parse_ai_output_to_items(text: str) -> list[ParsedSong]:
    """解析 DeepSeek 输出「时间戳 NN. 歌名 - 歌手」为条目。

    兼容两种输出：
    - 0:03:55 01. バラライカ - 月島きらり（新提示词）
    - 01. バラライカ - 月島きらり（旧提示词兜底）
    无时间戳、无歌手、或格式不符的行直接跳过（无置信来源不输出）。
    """
    import re

    items: list[ParsedSong] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 提取行首时间戳（可选）
        ts_match = re.match(r"^(\d{1,2}:\d{2}(?::\d{2})?)\s+", line)
        ts_label = ""
        ts_seconds = None
        if ts_match:
            ts_label = ts_match.group(1)
            ts_seconds = clean_timestamp_to_seconds(ts_label)
            line = line[ts_match.end() :].strip()
        # 剥离编号前缀
        m = re.match(r"^(\d{1,3})[.)．。、]\s*(.+)$", line)
        if not m:
            continue
        body = m.group(2).strip()
        # 歌名 - 歌手（最后一个 " - " 分隔，避免歌名本身含连字符）
        split_idx = body.rfind(" - ")
        if split_idx <= 0:
            # 兼容 / 分隔
            split_idx = body.rfind(" / ")
            if split_idx <= 0:
                continue
        song = body[:split_idx].strip()
        artist = body[split_idx + 3 :].strip()
        # 清理外侧书名号；引号只在首尾成对时去掉（保留 Don't say "lazy" 这类正式歌名）
        song = song.strip("「」『』")
        if len(song) >= 2 and song[0] == song[-1] and song[0] in {'"', "'", '“', '”', '‘', '’'}:
            song = song[1:-1].strip()
        artist = artist.strip()
        if not song or not artist:
            continue
        if re.match(r"^(未記載|未确定|不明|unknown)$", artist, re.IGNORECASE):
            continue
        items.append(ParsedSong(song=song, artist=artist, timestamp_label=ts_label, timestamp_seconds=ts_seconds))
    return items


def clean_timestamp_to_seconds(label: str) -> Optional[int]:
    """与 clean.timestamp_to_seconds 相同逻辑（避免循环依赖）。"""
    from .clean import timestamp_to_seconds

    return timestamp_to_seconds(label)


def is_special_no_artist_response(text: str) -> bool:
    normalized = "".join(text.split())
    return normalized == "请提供歌手信息后再处理。"
