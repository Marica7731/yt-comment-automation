"""YouTube 评论时间轴 → 歌曲列表 本地规则清洗（Python 移植版）。

规则设计移植自油猴脚本「YouTube 评论纯文本复制 + AI整理（括号保护 + 曲目数量校正版）」
的核心本地清洗逻辑：括号保护、译文/罗马字括号删除、分隔符统一、时间戳提取、
多行折叠时间轴合并、去重、格式化输出。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .rules import apply_song_cleanup as apply_unified_rules  # noqa: F401
from .rules import has_protected_title as rules_has_protected_title  # noqa: F401

# ---------- 基础文本规整 ----------


def normalize_text(text: str) -> str:
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ").replace("\u200b", "")
    lines = []
    for line in value.split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines).strip()


def normalize_timeline_marker_chars(text: str) -> str:
    value = text or ""
    value = re.sub(r"[０-９]", lambda m: str(ord(m.group(0)) - 0xFF10), value)
    value = value.replace("：", ":").replace("．", ".").replace("＃", "#")
    return value


def timestamp_to_seconds(timestamp: str) -> Optional[int]:
    parts = normalize_timeline_marker_chars(str(timestamp or "")).split(":")
    if len(parts) < 2 or len(parts) > 3:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if any(not (0 <= n) for n in nums):
        return None
    seconds, minutes = nums[-1], nums[-2]
    hours = nums[0] if len(nums) == 3 else 0
    if seconds >= 60 or minutes >= 60 or hours < 0:
        return None
    return hours * 3600 + minutes * 60 + seconds


def find_timestamp_start_positions_in_line(line: str) -> list[int]:
    source = normalize_timeline_marker_chars(line or "")
    positions: list[int] = []
    regex = re.compile(r"(^|[^\d])((?:[\[【(（『]\s*)?\d{1,2}:\d{2}(?::\d{2})?(?:\s*[\]】)）』])?)(?!\d)")
    for match in regex.finditer(source):
        raw_timestamp = re.sub(r"^[\[【(（『]\s*", "", match.group(2) or "")
        raw_timestamp = re.sub(r"\s*[\]】)）』]$", "", raw_timestamp)
        if timestamp_to_seconds(raw_timestamp) is None:
            continue
        index = match.start() + (len(match.group(1)) if match.group(1) else 0)
        if index > 0 and source[index - 1].isdigit():
            continue
        positions.append(index)
    return sorted(set(positions))


def split_collapsed_timeline_line(line: str) -> list[str]:
    """单行多个时间戳时按时间戳切分（同 start 样式），保留起止时间行不切。"""
    source = normalize_timeline_marker_chars(line or "").strip()
    if not source:
        return []
    if should_keep_inline_setlist_range_line(source):
        return [source]
    positions = find_timestamp_start_positions_in_line(source)
    if len(positions) <= 1:
        return [source]
    result: list[str] = []
    if positions[0] > 0:
        prefix = source[: positions[0]].strip()
        if prefix:
            result.append(prefix)
    for i in range(len(positions)):
        start = positions[i]
        end = positions[i + 1] if i + 1 < len(positions) else len(source)
        chunk = source[start:end].strip()
        if chunk:
            result.append(chunk)
    return result


def should_keep_inline_setlist_range_line(line: str) -> bool:
    source = normalize_timeline_marker_chars(line or "").strip()
    if not source:
        return False
    # 1曲目 38:12~43:24「ガーネット／奥華子」
    return bool(
        re.search(
            r"^第?\s*\d{1,3}\s*(?:曲目|曲)\s*[：:\s\u3000]*\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜\-－—–−]\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?:[「『｢《〈【]|[\s\S]*[\/／|｜￤∣丨])[\s\S]+$",
            source,
        )
    )


def split_collapsed_timeline_lines(text: str) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    lines: list[str] = []
    for line in normalized.split("\n"):
        for part in split_collapsed_timeline_line(line):
            value = part.strip()
            if value:
                lines.append(value)
    return lines


# ---------- 时间戳信息 ----------


def extract_first_timestamp_info(text: str) -> dict:
    normalized = normalize_timeline_marker_chars(text or "")
    match = re.search(r"\d{1,2}:\d{2}(?::\d{2})?", normalized)
    if not match:
        return {"label": "", "seconds": None}
    seconds = timestamp_to_seconds(match.group(0))
    if seconds is None:
        return {"label": "", "seconds": None}
    return {"label": match.group(0), "seconds": seconds}


def extract_primary_timestamp(text: str) -> str:
    match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", text or "")
    return match.group(1) if match else ""


def extract_timeline_timestamps(text: str) -> list[dict]:
    normalized = normalize_text(text or "")
    if not normalized:
        return []
    seen: set[str] = set()
    result: list[dict] = []
    for match in re.finditer(r"(^|[^\d])(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)", normalized):
        label = match.group(2)
        seconds = timestamp_to_seconds(label)
        if seconds is None or label in seen:
            continue
        seen.add(label)
        result.append({"label": label, "seconds": seconds})
    return result


# ---------- 字符/语言判断 ----------

_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_MUSIC_QUALIFIER_RE = re.compile(
    r"\b(feat\.?|ft\.?|ver\.?|version|mix|remix|edit|size|inst(?:rumental)?|off\s*vocal|live|solo|duet|acoustic|arrange|cover|chorus|short|full|tv|anime|movie|op|ed|from|single|album|demo|self[\s-]?cover|piano|guitar)\b",
    re.IGNORECASE,
)


def contains_japanese(text: str) -> bool:
    return bool(_JAPANESE_RE.search(text or ""))


def contains_latin(text: str) -> bool:
    return bool(_LATIN_RE.search(text or ""))


def looks_like_latin_annotation(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if not contains_latin(t):
        return False
    if contains_japanese(t):
        return False
    return bool(
        re.fullmatch(
            r"[A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F0-9 .,:'’\"“”&+_\-/!?~～()[\]（）［］#＃♯♭★☆♪♫♡♥◎・･=×∞]+",
            t,
        )
    )


def looks_like_romanization_or_translation(text: str) -> bool:
    t = (text or "").strip()
    if not looks_like_latin_annotation(t):
        return False
    if _MUSIC_QUALIFIER_RE.search(t):
        return False
    return True


def looks_like_music_qualifier(text: str) -> bool:
    return bool(_MUSIC_QUALIFIER_RE.search(text or ""))


# ---------- 括号处理 ----------


def strip_transliteration_parens_from_line(line: str) -> str:
    """删除「名称 + 空格 + (罗马字/译文)」里的译文括号；保留正式名称括号与音乐信息括号。"""
    if not line:
        return line

    def repl(match: re.Match) -> str:
        leading, open_b, inner, close_b = match.group(1), match.group(2), match.group(3), match.group(4)
        content = (inner or "").strip()
        if looks_like_romanization_or_translation(content):
            return ""
        return match.group(0)  # 保留音乐信息括号与正式名称括号

    return re.sub(r"([ \t\u3000]+)([\(（])([^()（）]{1,80})([\)）])", repl, line)


def find_trailing_bracket_suffix(text: str) -> Optional[dict]:
    raw = (text or "").strip()
    if not raw:
        return None
    close_to_open = {")": "(", "）": "（", "]": "[", "］": "［"}
    close = raw[-1]
    open_b = close_to_open.get(close)
    if not open_b:
        return None
    depth = 0
    for i in range(len(raw) - 1, -1, -1):
        ch = raw[i]
        if ch == close:
            depth += 1
            continue
        if ch != open_b:
            continue
        depth -= 1
        if depth != 0:
            continue
        if not re.match(r"[\s\u3000]", raw[i - 1] if i > 0 else ""):
            return None
        return {
            "before": raw[:i].strip(),
            "content": raw[i + 1 : len(raw) - 1].strip(),
            "removed": raw[i:].strip(),
        }
    return None


def normalize_duplicate_annotation_comparable(text: str) -> str:
    value = (text or "").normalize("NFKC") if hasattr(text, "normalize") else (text or "")
    value = re.sub(r"[“”‘’\"'`]", "", value)
    value = re.sub(r"[\s\u3000]+", "", value)
    value = re.sub(r"[.．。｡、,，:：;；!！?？~～\-—–−_/／|｜￤∣丨]+", "", value)
    return value.strip().lower()


def strip_trailing_latin_annotation_suffix(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return raw
    trailing = find_trailing_bracket_suffix(raw)
    if trailing and trailing["before"] and normalize_duplicate_annotation_comparable(
        trailing["before"]
    ) == normalize_duplicate_annotation_comparable(trailing["content"]):
        return trailing["before"]
    if trailing and trailing["before"] and contains_japanese(trailing["before"]) and looks_like_latin_annotation(
        trailing["content"]
    ):
        return trailing["before"]

    tight = re.search(r"([\(（\[［])([^()（）\[\]［］]{1,120})([\)）\]］])\s*$", raw)
    if tight:
        open_b, inner, close_b = tight.group(1), tight.group(2), tight.group(3)
        before = raw[: tight.start()].strip()
        content = (inner or "").strip()
        matched = {")": "(", "）": "（", "]": "[", "］": "［"}
        if matched.get(close_b) == open_b and before:
            if normalize_duplicate_annotation_comparable(before) == normalize_duplicate_annotation_comparable(content):
                return before
            if contains_japanese(before) and looks_like_latin_annotation(content):
                return before

    def repl(match: re.Match) -> str:
        leading, open_b, inner, close_b = match.group(1), match.group(2), match.group(3), match.group(4)
        before = raw[: match.start()].strip()
        content = (inner or "").strip()
        matched = {")": "(", "）": "（", "]": "[", "］": "［"}
        if matched.get(close_b) != open_b:
            return match.group(0)
        if before and normalize_duplicate_annotation_comparable(before) == normalize_duplicate_annotation_comparable(
            content
        ):
            return ""
        if before and contains_japanese(before) and looks_like_latin_annotation(content):
            return ""
        return match.group(0)

    return re.sub(r"([ \t\u3000]+)([\(（\[［])([^()（）\[\]［］]{1,120})([\)）\]］])\s*$", repl, raw).strip()


# ---------- 字段清理 ----------


def strip_leading_song_index_marker(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    without = re.sub(r"^\d{1,3}\s*[\-—–−]\s*", "", t).strip()
    if without != t:
        return without
    without = re.sub(r"^[#＃]\s*\d{1,3}\s*[.)．。、,，：:\-—–−]\s*", "", t).strip()
    if without != t:
        return without
    # 「01.heavenly」这类编号紧贴歌名（点后无空格）也要剥离，但不伤害 8.32 这类数字歌名
    without = re.sub(r"^\d{1,3}\s*[.)．。]\s*(?=[A-Za-z\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff])", "", t).strip()
    if without != t:
        return without
    return re.sub(r"^[#＃]\s*\d{1,3}[\s\u3000]+", "", t).strip()


def strip_leading_song_context_marker(text: str) -> str:
    return re.sub(r"^(?:encore|アンコール)[\s\u3000]+", "", text or "", flags=re.IGNORECASE).strip()


def strip_leading_serial_marker(text: str) -> str:
    t = normalize_timeline_marker_chars(text or "").strip()
    patterns = [
        re.compile(r"^Re\s*[:：]\s*(?![A-Za-z])", re.IGNORECASE),
        re.compile(r"^【\s*\d{1,3}\s*】\s*"),
        re.compile(r"^[⟦〚]\s*\d{1,3}\s*[⟧〛]\s*"),
        re.compile(r"^\[\s*\d{1,3}\s*\]\s*"),
        re.compile(r"^\(\s*\d{1,3}\s*\)\s*"),
        re.compile(r"^\d{1,3}\s*曲\s*[\/／]\s*"),
        re.compile(r"^\d{1,3}\s+(?=\d{1,2}:\d{2}(?::\d{2})?\b)"),
        re.compile(r"^\d{1,3}\s*[,，]\s+(?!\d)"),
        re.compile(r"^\d{1,3}\s*[\-—–−]\s*"),
        re.compile(r"^\d{1,3}\s*[.)．。、,，：:]\s+(?!\d)"),
    ]
    for p in patterns:
        if p.search(t):
            t = p.sub("", t).strip()
            break
    return t


def strip_leading_timeline_icon_marks(text: str) -> str:
    value = re.sub(
        r"^(?:[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000]*(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]|[♪♫♬♩]))+\s*",
        "",
        text or "",
    )
    return strip_timeline_tree_prefix(value).strip()


def strip_timeline_tree_prefix(text: str) -> str:
    return re.sub(
        r"^[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000]*(?:[├└┣┗┝┖│┃┆┇┊┋]+|[>＞]+|[-－—–−]+|[・･●○◆◇■□]+)\s*",
        "",
        text or "",
    ).strip()


def strip_weird_leading_chars(text: str) -> str:
    return re.sub(r"^[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000️]+", "", text or "").strip()


def strip_leading_timestamp(text: str) -> str:
    t = normalize_timeline_marker_chars(strip_timeline_tree_prefix(text or "")).strip()
    timestamp_pattern = re.compile(
        r"^(?:[\[【(（『]\s*)?\d{1,2}:\d{2}(?::\d{2})?\s*(?:[\]】)）』])?(?:[\s\u3000]*[;；,，、~～\-—–−]+\s*)?"
    )
    for _ in range(8):
        next_t = strip_timeline_tree_prefix(timestamp_pattern.sub("", t)).strip()
        if next_t == t:
            break
        t = next_t
    return t


def strip_leading_timeline_decorations(text: str) -> str:
    t = strip_timeline_tree_prefix(text or "").strip()
    for _ in range(6):
        next_t = strip_leading_serial_marker(
            strip_leading_timeline_icon_marks(strip_leading_timestamp(strip_timeline_tree_prefix(t)))
        )
        if next_t == t:
            break
        t = next_t
    return t


def strip_trailing_visual_decorations(text: str) -> str:
    t = (text or "").strip()
    for _ in range(6):
        next_t = re.sub(r"[\s\u00A0\u3000\uFE0F\u200D]*(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]|[♪♫♬♩♡♥★☆⭐✨❄☂])\s*$", "", t)
        next_t = re.sub(r"[\s\u00A0\u3000\uFE0F\u200D]+$", "", next_t).strip()
        if next_t == t:
            break
        t = next_t
    return t


def strip_trailing_year_annotation(text: str) -> str:
    return re.sub(r"\s*[\[［【(（]\s*(?:18|19|20|21)\d{2}\s*(?:年)?\s*[\]］】)）]?\s*$", "", text or "").strip()


def strip_loose_edge_title_quotes(text: str) -> str:
    t = (text or "").strip()
    for _ in range(3):
        next_t = re.sub(r"^[「『｢《〈【]+", "", t)
        next_t = re.sub(r"[」』｣》〉】]+$", "", next_t).strip()
        if next_t == t:
            break
        t = next_t
    return t


def strip_unpaired_leading_ascii_quote(text: str) -> str:
    """剥掉歌名前导的裸 ASCII 引号（YouTube 频道主 SETLIST 用 `"` 包裹条目）。

    只处理「以引号开头、但后续没有配对收尾引号」的情况：
    - `" アルストロメリア / 凛々咲` → `アルストロメリア / 凛々咲`（真实场景，引号是条目包裹开始符）
    - `"Alstroemeria" / 凛々咲` → 保留（成对引号包裹的歌名，是正规写法）
    """
    t = (text or "").strip()
    if not t or not t.startswith('"'):
        return t
    rest = t[1:].strip()
    if not rest:
        return rest
    # 行内任意位置存在配对的收尾引号 → 成对包裹，不剥
    if rest.endswith('"') or '"' in rest:
        return t
    return rest


def clean_song_or_artist_part(text: str) -> str:
    raw = text or ""
    # 受保护正式标题（R09）：任何清洗步骤都不删改符号，直接返回干净结果
    if rules_has_protected_title(raw):
        return raw.strip()
    # 先套用 DS 提炼的统一规则（R06/R07/R13/R14/R15：表演备注、译文括号、注音、日期、序号）
    t = apply_unified_rules(raw)
    t = strip_transliteration_parens_from_line(t).strip()
    t = strip_timeline_tree_prefix(t)
    t = strip_trailing_latin_annotation_suffix(t)
    t = strip_leading_song_index_marker(t).strip()
    t = strip_leading_song_context_marker(t).strip()
    t = strip_loose_edge_title_quotes(t)
    # 只清理真正像分隔符的边缘字符，不再清理 . " [] 等可能属于正式名称的字符
    t = re.sub(r"^[\[［]+", "", t)
    t = re.sub(r"[\]］]+$", "", t)
    t = re.sub(r"^[\-—–−/／|｜￤∣丨:：;；]+", "", t)
    t = re.sub(r"[\-—–−/／|｜￤∣丨:：;；]+$", "", t)
    t = t.strip()
    t = strip_trailing_year_annotation(t)
    return strip_trailing_visual_decorations(strip_loose_edge_title_quotes(t))


def is_bad_field(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if re.match(r"^(歌名|歌手|编号|未确定)$", t, re.IGNORECASE):
        return True
    if re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", t):
        return True
    if re.match(r"^(talk|mc|雑談|聊天|感想|开场|结束|告知|返场|休息)$", t):
        return True
    return False


# ---------- 歌名/歌手拆分 ----------

_FULLWIDTH_BRACKETS_OPEN = "([{（［【「『《〈｢"
_FULLWIDTH_BRACKETS_CLOSE = ")]}）］】」』》〉｣"


def _is_whitespace_char(ch: str) -> bool:
    return bool(re.match(r"[\s\u3000]", ch or ""))


def _find_spaced_delimiters_outside_brackets(text: str, delimiters: str) -> list[dict]:
    matches: list[dict] = []
    depth = 0
    for i, ch in enumerate(text):
        if ch in _FULLWIDTH_BRACKETS_OPEN:
            depth += 1
            continue
        if ch in _FULLWIDTH_BRACKETS_CLOSE:
            depth = max(0, depth - 1)
            continue
        if depth != 0:
            continue
        if ch in delimiters and _is_whitespace_char(text[i - 1] if i > 0 else "") and _is_whitespace_char(
            text[i + 1] if i + 1 < len(text) else ""
        ):
            matches.append({"index": i, "length": 1})
    return matches


def _is_date_slash_delimiter_at(text: str, index: int) -> bool:
    source = normalize_timeline_marker_chars(text or "")
    if index <= 0 or index >= len(source) - 1 or source[index] != "/":
        return False
    before = source[:index]
    after = source[index + 1 :]
    return bool(re.search(r"\d{1,4}\s*$", before)) and bool(re.match(r"^\s*\d{1,2}(?:\D|$)", after))


def _find_loose_song_artist_delimiter_index(text: str) -> int:
    source = text or ""
    if not source:
        return -1
    depth = 0
    ascii_slash: list[int] = []
    fullwidth_slash: list[int] = []
    pipe: list[int] = []
    for i, ch in enumerate(source):
        if ch in _FULLWIDTH_BRACKETS_OPEN:
            depth += 1
            continue
        if ch in _FULLWIDTH_BRACKETS_CLOSE:
            depth = max(0, depth - 1)
            continue
        if depth != 0:
            continue
        if ch == "/":
            if not _is_date_slash_delimiter_at(source, i):
                ascii_slash.append(i)
            continue
        if ch == "／":
            fullwidth_slash.append(i)
            continue
        if ch in "|｜￤∣丨":
            pipe.append(i)
    if ascii_slash:
        return ascii_slash[0]
    if pipe:
        return pipe[-1]
    if fullwidth_slash:
        return fullwidth_slash[-1]
    return -1


def _find_spaced_double_slash_outside_brackets(text: str) -> int:
    source = text or ""
    depth = 0
    for i in range(len(source) - 1):
        ch = source[i]
        if ch in _FULLWIDTH_BRACKETS_OPEN:
            depth += 1
            continue
        if ch in _FULLWIDTH_BRACKETS_CLOSE:
            depth = max(0, depth - 1)
            continue
        if depth != 0:
            continue
        if source[i] == "/" and source[i + 1] == "/" and _is_whitespace_char(
            source[i - 1] if i > 0 else ""
        ) and _is_whitespace_char(source[i + 2] if i + 2 < len(source) else ""):
            return i
    return -1


def _clean_artist_part(text: str) -> str:
    raw = clean_song_or_artist_part(text)
    return strip_trailing_visual_decorations(raw)


def _clean_artist_with_optional_metadata(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    pipe_matches = _find_spaced_delimiters_outside_brackets(raw, "|｜￤∣丨")
    if not pipe_matches:
        return _clean_artist_part(raw)
    first_pipe = pipe_matches[0]
    artist = _clean_artist_part(raw[: first_pipe["index"]])
    metadata = clean_song_or_artist_part(raw[first_pipe["index"] + first_pipe["length"] :])
    if not artist:
        return _clean_artist_part(raw)
    if not metadata:
        return artist
    return f"{artist} [{metadata}]"


@dataclass
class ParsedSong:
    song: str
    artist: str
    timestamp_label: str = ""
    timestamp_seconds: Optional[int] = None


def extract_song_artist_core(text: str) -> Optional[dict]:
    """按优先级拆分「歌名 / 歌手」。"""
    raw = (text or "").strip()
    if not raw:
        return None

    # 双斜杠分隔：A // B
    double_slash_idx = _find_spaced_double_slash_outside_brackets(raw)
    if double_slash_idx > 0:
        song = clean_song_or_artist_part(raw[:double_slash_idx])
        artist = _clean_artist_with_optional_metadata(raw[double_slash_idx + 2 :])
        if not is_bad_field(song) and not is_bad_field(artist):
            return {"song": song, "artist": artist}

    # 空格分隔的 /、｜、|（括号外）
    spaced = _find_spaced_delimiters_outside_brackets(raw, "/／|｜￤∣丨")
    if spaced:
        first = spaced[0]
        song = clean_song_or_artist_part(raw[: first["index"]])
        artist = _clean_artist_with_optional_metadata(raw[first["index"] + first["length"] :])
        if not is_bad_field(song) and not is_bad_field(artist):
            return {"song": song, "artist": artist}

    # 前后都有空格的分隔符，贪婪左侧
    m = re.match(r"^(.+)\s+[\/／|｜￤∣丨]\s+(.+)$", raw)
    if m:
        song = clean_song_or_artist_part(m.group(1))
        artist = _clean_artist_with_optional_metadata(m.group(2))
        if not is_bad_field(song) and not is_bad_field(artist):
            return {"song": song, "artist": artist}

    # 连字符分隔必须两边有空格（避免误切开 Os-宇宙人）
    m = re.match(r"^(.+)\s+[-—–−]\s+(.+)$", raw)
    if m:
        song = clean_song_or_artist_part(m.group(1))
        artist = _clean_artist_with_optional_metadata(m.group(2))
        if not is_bad_field(song) and not is_bad_field(artist):
            return {"song": song, "artist": artist}

    # 无空格写法：441/miwa、366日/HY
    idx = _find_loose_song_artist_delimiter_index(raw)
    if idx > 0 and idx < len(raw) - 1:
        song = clean_song_or_artist_part(raw[:idx])
        artist = _clean_artist_with_optional_metadata(raw[idx + 1 :])
        if not is_bad_field(song) and not is_bad_field(artist):
            return {"song": song, "artist": artist}

    return None


# ---------- 非歌曲判定 ----------


def is_obviously_non_song_text(text: str) -> bool:
    t = strip_weird_leading_chars(text or "")
    t = strip_trailing_visual_decorations(t)
    if not t:
        return True
    if re.match(r"^(開始|结束|終了|end|start)$", t, re.IGNORECASE):
        return True
    if re.match(r"^(talk|mc|雑談|聊天|感想|告知|返场|休息)$", t):
        return True
    if re.search(r"(?:宣伝|告知|お知らせ)\s*$", t):
        return True
    # 宣伝/告知 开头的行（宣伝）Vack-ON!! 这类）整体视为非歌曲
    if re.match(r"^[（(]?\s*(?:宣伝|告知|お知らせ)[)）]?", t):
        return True
    if re.match(r"^編集中です", t):
        return True
    return False


def is_timestamp_only_line(text: str) -> bool:
    t = normalize_timeline_marker_chars(strip_timeline_tree_prefix(strip_weird_leading_chars(text or "")))
    if re.match(r"^(?:[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000]*(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]|[♪♫♬♩▶▷►▸▹>|・･●○◆◇■□]))*\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)*\s*$", t):
        return True
    return is_timestamp_start_placeholder_line(t)


def is_timestamp_start_placeholder_line(text: str) -> bool:
    t = normalize_timeline_marker_chars(strip_timeline_tree_prefix(strip_weird_leading_chars(text or "")))
    return bool(
        re.match(
            r"^(?:[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000]*(?:[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]|[♪♫♬♩▶▷►▸▹>|・･●○◆◇■□]))*\s*\d{1,2}:\d{2}(?::\d{2})?\s*[;；]+\s*$",
            t,
        )
    )


def is_timestamp_range_like_line(text: str) -> bool:
    t = normalize_timeline_marker_chars(strip_weird_leading_chars(text or "")).strip()
    if not t:
        return False
    return bool(
        re.match(
            r"^(?:[#＃]?\s*\d{1,3}\s*[.)．。、,，：:]?\s*)?\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜-－—–−]\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*$",
            t,
        )
    )


def is_standalone_setlist_number_line(text: str) -> bool:
    t = strip_weird_leading_chars(text or "")
    t = re.sub(r"[①②③④⑤⑥⑦⑧⑨]", lambda m: str("①②③④⑤⑥⑦⑧⑨".index(m.group(0)) + 1), t)
    return bool(re.match(r"^[#＃]?\s*\d{1,3}\s*[.)．。、,，：:]?\s*$", t))


def looks_like_meta_only(line: str) -> bool:
    t = (line or "").strip()
    if not t:
        return True
    if re.match(r"^(```|~~~)", t):
        return True
    if re.match(r"^(以下|下面|整理|结果|输出|歌曲列表|最终结果|说明|注：|注意|按顺序|已按顺序|共\s*\d+\s*首|共\d+首)", t):
        return True
    if re.search(r"编号.*歌名.*歌手", t):
        return True
    return False


# ---------- 行解析 ----------


def _strip_leading_numbered_marker(text: str) -> str:
    """去掉行首的序号前缀：「1. 16:08 ...」/「2) 34:21 ...」/「10: 2:03:23 ...」。

    只去掉「数字 + 标点 + 空格」前缀且后跟时间戳，不伤害 441/miwa 这类无标点数字歌名。
    """
    t = normalize_timeline_marker_chars(text or "").strip()
    m = re.match(r"^(\d{1,3})\s*[.)．。、,，：:]\s+(.+)$", t)
    if m and re.match(r"^\d{1,2}:\d{2}(?::\d{2})?", m.group(2)):
        return m.group(2)
    return t


def parse_song_line_after_timestamp(line: str) -> Optional[ParsedSong]:
    """处理单行时间轴：「0:03:55 バラライカ / 月島きらり ...」。

    兼容：
    - 「1. 16:08 歌名 - 歌手」序号前缀
    - 行尾罗马字/译文括号（先删再拆，避免其内部 " - " 被误当分隔符）
    """
    t = strip_weird_leading_chars(line)
    # 兼容带包裹符的时间戳：『15:10』、[15:10]、15:10 等
    ts_prefixed = re.match(r"^[\[【(（『]\s*\d{1,2}:\d{2}(?::\d{2})?\s*[\]】)）』]\s*", t)
    if not re.match(r"^\d{1,2}:\d{2}(?::\d{2})?\s*", t):
        stripped = _strip_leading_numbered_marker(t)
        if stripped == t:
            # 若还不是数字时间戳开头，但带包裹符时间戳（『15:10』）则继续
            if not ts_prefixed:
                return None
        else:
            t = stripped
    if not re.match(r"^\d{1,2}:\d{2}(?::\d{2})?\s*", t) and not ts_prefixed:
        return None
    timestamp_info = extract_first_timestamp_info(t)
    t = strip_leading_timeline_decorations(t)
    # YouTube 频道主 SETLIST 用裸引号包裹条目：`0:05:39 " 歌名 / 歌手` → 剥掉前导引号
    t = strip_unpaired_leading_ascii_quote(t)
    if not t or is_obviously_non_song_text(t):
        return None
    # 先清理行尾译文/罗马字括号，避免其内部 " - " 干扰歌名/歌手拆分
    t = strip_transliteration_parens_from_line(t)
    t = strip_trailing_latin_annotation_suffix(t)
    if not t or is_obviously_non_song_text(t):
        return None
    parsed = extract_song_artist_core(t)
    if not parsed or is_bad_field(parsed["song"]) or is_bad_field(parsed["artist"]):
        return None
    if is_non_song_chapter_like_pair(parsed["song"], parsed["artist"]):
        return None
    return ParsedSong(
        song=parsed["song"],
        artist=parsed["artist"],
        timestamp_label=timestamp_info["label"],
        timestamp_seconds=timestamp_info["seconds"],
    )


_NON_SONG_SECTION_MARKER_RE = re.compile(
    r"^(opening|open|op|start|starting|intro|introduction|幕開け|開幕|開始|オープニング|closing|close|end|ending|ed|outro|閉幕|終幕|終了|エンディング)$"
)


def normalize_section_marker_text(text: str) -> str:
    value = (text or "").normalize("NFKC") if hasattr(text, "normalize") else (text or "")
    value = re.sub(r"[\s　_\-—–−/／|｜￤∣丨:：;；,，.。!！?？~～・･]+", "", value)
    return value.strip().lower()


def is_non_song_section_marker(text: str) -> bool:
    return bool(_NON_SONG_SECTION_MARKER_RE.match(normalize_section_marker_text(text)))


def is_non_song_chapter_like_pair(song: str, artist: str) -> bool:
    s, a = (song or "").strip(), (artist or "").strip()
    if not s or not a:
        return False
    if is_non_song_section_marker(s) and is_non_song_section_marker(a):
        return True
    return False


def is_likely_translation_only_line(text: str) -> bool:
    t = strip_timeline_tree_prefix(strip_weird_leading_chars(text or "")).strip()
    if not t:
        return True
    m = re.match(r"^[\(（\[［][^()（）\[\]［］]{1,140}[\)）\]］]$", t)
    if m:
        inner = t[1:-1].strip()
        return looks_like_latin_annotation(inner)
    return False


# ---------- 多行时间轴合并（树形 setlist、时间行+歌名行等） ----------


def _is_song_artist_only_line(text: str) -> bool:
    t = normalize_timeline_marker_chars(strip_weird_leading_chars(text or ""))
    if not t or extract_first_timestamp_info(t)["label"]:
        return False
    if is_timestamp_only_line(t):
        return False
    t = strip_leading_timeline_decorations(t)
    if not t or is_obviously_non_song_text(t):
        return False
    return bool(extract_song_artist_core(t))


def _find_song_line_after_setlist_time_block(raw_lines: list[str], start_index: int, max_lookahead: int = 8):
    start_info = None
    saw_time_block = False
    for j in range(start_index, min(len(raw_lines), start_index + max_lookahead)):
        candidate = strip_weird_leading_chars(raw_lines[j] or "")
        if not candidate:
            continue
        if is_standalone_setlist_number_line(candidate):
            if saw_time_block:
                break
            continue
        if is_timestamp_range_like_line(candidate) or is_timestamp_start_placeholder_line(candidate):
            info = extract_first_timestamp_info(candidate)
            if info["label"] and not start_info:
                start_info = info
            saw_time_block = True
            continue
        if is_timestamp_only_line(candidate):
            info = extract_first_timestamp_info(candidate)
            if info["label"] and not start_info:
                start_info = info
            saw_time_block = True
            continue
        if is_likely_translation_only_line(candidate):
            continue
        if not saw_time_block or not start_info or not start_info["label"]:
            break
        song_candidate = strip_timeline_tree_prefix(candidate)
        if song_candidate and not is_obviously_non_song_text(song_candidate) and _is_song_artist_only_line(song_candidate):
            return {"timestamp": start_info, "line": song_candidate, "index": j}
        break
    return None


def _extract_song_item_from_inline_setlist_range_line(text: str) -> Optional[ParsedSong]:
    t = strip_weird_leading_chars(text or "")
    m = re.match(
        r"^第?\s*\d{1,3}\s*(?:曲目|曲)\s*[：:\s\u3000]*(\d{1,2}:\d{2}(?::\d{2})?)\s*[~～〜\-－—–−]\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*(.+)$",
        t,
    )
    if not m:
        return None
    label = m.group(1)
    seconds = timestamp_to_seconds(label)
    if seconds is None:
        return None
    body = m.group(2).strip()
    body = re.sub(r"\s+\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜\-－—–−]\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*$", "", body).strip()
    body = strip_trailing_visual_decorations(strip_loose_edge_title_quotes(body))
    if not body or is_obviously_non_song_text(body):
        return None
    parsed = extract_song_artist_core(body)
    if not parsed or is_bad_field(parsed["song"]) or is_bad_field(parsed["artist"]):
        return None
    return ParsedSong(song=parsed["song"], artist=parsed["artist"], timestamp_label=label, timestamp_seconds=seconds)


def _extract_song_artist_from_setlist_title_line(text: str) -> Optional[dict]:
    t = strip_weird_leading_chars(text or "")
    if not re.match(r"^第?\s*\d{1,3}\s*(?:曲目|曲)\s*[：:]", t):
        return None
    t = re.sub(r"^第?\s*\d{1,3}\s*曲目\s*[：:]\s*", "", t)
    t = re.sub(r"^第?\s*\d{1,3}\s*曲\s*[：:]\s*", "", t)
    t = re.sub(r"\s+\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜\-－—–−]\s*\d{1,2}:\d{2}(?::\d{2})?\s*$", "", t).strip()
    t = strip_trailing_visual_decorations(strip_loose_edge_title_quotes(t))
    if not t or is_obviously_non_song_text(t):
        return None
    parsed = extract_song_artist_core(t)
    if not parsed:
        return None
    if not parsed["song"] or not parsed["artist"] or is_bad_field(parsed["song"]) or is_bad_field(parsed["artist"]):
        return None
    return parsed


def _find_start_timestamp_after_setlist_title(raw_lines: list[str], start_index: int, max_lookahead: int = 6):
    for j in range(start_index, min(len(raw_lines), start_index + max_lookahead)):
        candidate = strip_weird_leading_chars(raw_lines[j] or "")
        if not candidate:
            continue
        if is_likely_translation_only_line(candidate):
            continue
        if is_timestamp_range_like_line(candidate) or is_timestamp_start_placeholder_line(candidate) or is_timestamp_only_line(
            candidate
        ):
            info = extract_first_timestamp_info(candidate)
            if not info["label"]:
                continue
            index = j
            next_line = strip_weird_leading_chars(raw_lines[j + 1] if j + 1 < len(raw_lines) else "")
            if (
                next_line
                and is_timestamp_only_line(next_line)
                and not is_timestamp_start_placeholder_line(next_line)
                and (re.match(r"^\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜-－—–−]\s*$", candidate) or not re.search(r"[~～〜-－—–−]", candidate))
            ):
                index = j + 1
            return {"timestamp": info, "index": index}
        if is_standalone_setlist_number_line(candidate) or _extract_song_artist_from_setlist_title_line(candidate):
            return None
        if is_obviously_non_song_text(candidate):
            continue
        return None
    return None


# ---------- 主提取函数 ----------


def _normalize_artist_honorifics(items: list[ParsedSong]) -> list[ParsedSong]:
    """多数歌手统一带敬语（さん/様/氏）时批量去掉。"""
    valid = [it for it in items if it.artist and it.artist.strip()]
    if not valid:
        return items
    honorific_count = sum(1 for it in valid if re.search(r"(?:さん|様|氏)\s*$", it.artist))
    if honorific_count < 3 or honorific_count / len(valid) < 0.6:
        return items
    result = []
    for it in items:
        if it.artist and re.search(r"(?:さん|様|氏)\s*$", it.artist):
            it = ParsedSong(it.song, re.sub(r"(?:さん|様|氏)\s*$", "", it.artist).strip(), it.timestamp_label, it.timestamp_seconds)
        result.append(it)
    return result


def _normalize_kanji_artist_spacing(items: list[ParsedSong]) -> list[ParsedSong]:
    """压缩汉字之间的空格：奥 華子 -> 奥華子。"""
    result = []
    for it in items:
        if it.artist:
            artist = re.sub(r"(?<=[\u3400-\u9FFF\uF900-\uFAFF])\s+(?=[\u3400-\u9FFF\uF900-\uFAFF])", "", it.artist).strip()
            it = ParsedSong(it.song, artist, it.timestamp_label, it.timestamp_seconds)
        result.append(it)
    return result


def _normalize_artist_display(items: list[ParsedSong]) -> list[ParsedSong]:
    return _normalize_kanji_artist_spacing(_normalize_artist_honorifics(items))


def extract_plain_songs_from_source_timeline(text: str) -> list[ParsedSong]:
    """从评论/简介文本中提取歌曲列表（时间戳 + 歌名 + 歌手）。"""
    normalized = normalize_text(text)
    if not normalized:
        return []
    raw_lines = [
        strip_weird_leading_chars(line)
        for line in split_collapsed_timeline_lines(normalized)
        if strip_weird_leading_chars(line)
    ]
    merged_lines: list[str] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if not line:
            i += 1
            continue

        inline_range = _extract_song_item_from_inline_setlist_range_line(line)
        if inline_range:
            merged_lines.append(f"{inline_range.timestamp_label} {inline_range.song} / {inline_range.artist}")
            i += 1
            continue

        title_parsed = _extract_song_artist_from_setlist_title_line(line)
        if title_parsed:
            time_after = _find_start_timestamp_after_setlist_title(raw_lines, i + 1)
            if time_after and time_after["timestamp"]["label"]:
                merged_lines.append(f"{time_after['timestamp']['label']} {title_parsed['song']} / {title_parsed['artist']}")
                i = time_after["index"] + 1
                continue

        if is_standalone_setlist_number_line(line) or is_timestamp_range_like_line(line):
            block = _find_song_line_after_setlist_time_block(
                raw_lines, i + 1 if is_standalone_setlist_number_line(line) else i
            )
            if block and block["timestamp"]["label"] and block["line"]:
                merged_lines.append(f"{block['timestamp']['label']} {block['line']}")
                i = block["index"] + 1
                continue

        if is_timestamp_start_placeholder_line(line):
            ts = extract_primary_timestamp(line)
            next_line = strip_timeline_tree_prefix(
                strip_weird_leading_chars(raw_lines[i + 1] if i + 1 < len(raw_lines) else "")
            )
            if ts and next_line and not is_timestamp_only_line(next_line) and not is_obviously_non_song_text(next_line):
                merged_lines.append(f"{ts} {next_line}")
                i += 2
                continue
            i += 1
            continue

        # 歌名行 + 下一行时间：🎸 衛星 / 赤い公園 / ▶ 02:22
        if _is_song_artist_only_line(line) and is_timestamp_only_line(
            raw_lines[i + 1] if i + 1 < len(raw_lines) else ""
        ) and not is_timestamp_start_placeholder_line(raw_lines[i + 1] if i + 1 < len(raw_lines) else ""):
            ts = extract_primary_timestamp(raw_lines[i + 1] if i + 1 < len(raw_lines) else "")
            if ts:
                merged_lines.append(f"{ts} {line}")
                i += 2
                continue

        # 时间行 + 下一行歌名：8:47 / 蜩/tetoさん
        if is_timestamp_only_line(line):
            ts = extract_primary_timestamp(line)
            next_line = strip_timeline_tree_prefix(
                strip_weird_leading_chars(raw_lines[i + 1] if i + 1 < len(raw_lines) else "")
            )
            next_has_own_timestamp = bool(extract_first_timestamp_info(next_line)["label"])
            if next_line and not next_has_own_timestamp and not is_timestamp_only_line(next_line) and not is_obviously_non_song_text(
                next_line
            ):
                merged_lines.append(f"{ts} {next_line}")
                i += 2
                continue
            i += 1
            continue

        merged_lines.append(line)
        i += 1

    items: list[ParsedSong] = []
    for line in merged_lines:
        parsed = parse_song_line_after_timestamp(line)
        if parsed:
            items.append(parsed)
    return _normalize_artist_display(items)


# ---------- 去重 ----------


def _normalize_loose_comparable_text(text: str) -> str:
    value = (text or "").normalize("NFKC") if hasattr(text, "normalize") else (text or "")
    value = re.sub(r"[“”‘’\"'`]", "", value)
    value = re.sub(r"[\s\u3000]+", "", value)
    value = re.sub(r"[，,、｡。]", "", value)
    value = re.sub(r"[!！?？~～]", "", value)
    value = re.sub(r"[.．…]+", "", value)
    return value.strip().lower()


def dedupe_song_items_by_timestamp_and_identity(items: list[ParsedSong]) -> list[ParsedSong]:
    seen: set[str] = set()
    result: list[ParsedSong] = []
    for item in items:
        song_key = _normalize_loose_comparable_text(item.song)
        artist_key = _normalize_loose_comparable_text(item.artist)
        if not song_key or not artist_key or item.timestamp_seconds is None:
            result.append(item)
            continue
        key = f"{item.timestamp_seconds}|{song_key}|{artist_key}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


# ---------- 输出 ----------


def format_timestamp_for_output(label: str, seconds: Optional[int], force_hours: bool = False) -> str:
    if seconds is None:
        label_seconds = timestamp_to_seconds(label or "")
        if label_seconds is None:
            return ""
        seconds = label_seconds
    total = max(0, seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    rest = total % 60
    mm = f"{minutes:02d}"
    ss = f"{rest:02d}"
    # 参考已发布评论格式：始终带小时位 0:03:55（1 小时以上则正常 H:MM:SS）
    return f"{hours}:{mm}:{ss}"


def format_song_items(items: list[ParsedSong], include_timestamps: bool = False) -> str:
    if not items:
        return ""
    width = 3 if len(items) >= 100 else 2
    # 稳定排序：有时间戳的按时间升序，无时间戳的保持原顺序
    ordered = sorted(
        enumerate(items),
        key=lambda pair: (
            pair[1].timestamp_seconds is None,
            pair[1].timestamp_seconds if pair[1].timestamp_seconds is not None else 0,
            pair[0],
        ),
    )
    ordered = [pair[1] for pair in ordered]
    force_hours = include_timestamps and any(
        it.timestamp_seconds is not None and it.timestamp_seconds >= 3600 for it in ordered
    )
    lines = []
    for idx, item in enumerate(ordered, 1):
        if item.artist:
            line = f"{str(idx).zfill(width)}. {item.song} - {item.artist}"
        else:
            line = f"{str(idx).zfill(width)}. {item.song}"
        if include_timestamps:
            ts = format_timestamp_for_output(item.timestamp_label, item.timestamp_seconds, force_hours)
            if ts:
                line = f"{ts} {line}"
        lines.append(line)
    return "\n".join(lines)


def build_comment_songlist(comment_texts: list[str], description: str = "") -> list[ParsedSong]:
    """多来源提取 + 择优：返回最优来源的歌曲列表。

    与 song_serch_lyrics 的 _select_best_comment_songs 相同策略：
    无 EDL 时选「条数最多 + 带歌手最多」的来源。
    """
    all_texts = [t for t in comment_texts if t and t.strip()] + ([description] if description and description.strip() else [])
    sources: list[list[ParsedSong]] = []
    for text in all_texts:
        songs = dedupe_song_items_by_timestamp_and_identity(extract_plain_songs_from_source_timeline(text))
        if songs:
            sources.append(songs)
    if not sources:
        return []
    return max(sources, key=lambda songs: (len(songs), sum(1 for s in songs if s.artist)))
