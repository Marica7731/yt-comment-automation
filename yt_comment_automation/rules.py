"""从 DS 差异样本提炼的统一规则实现（对应根目录 RULES.md R01-R17）。

规则来源：extract_rules.py → data/rules_from_ds.json（DeepSeek reasoning high 提炼）。
本模块把这些规则以确定性函数落地，供 clean.py 与未来插件/其他项目移植。
所有正则兼容 Python 与 JS（不使用 \\p 等差异语法）。
"""
from __future__ import annotations

import re
from typing import Optional

# --- R01 / R10 全角数字/字母转半角 ---
FULLWIDTH_DIGITS_RE = re.compile(r"[０-９]")
FULLWIDTH_ASCII_RE = re.compile(r"[０-９Ａ-Ｚａ-ｚ]")

# --- R02 行首数字序号剥离（点后非数字才剥离，保护 8.32）---
LEADING_NUMERAL_PREFIX_RE = re.compile(r"^[0-9０-９]+[.、.)）．](?![0-9０-９])\s*")

# --- R03 全角括号序号 ---
LEADING_FULLWIDTH_BRACKET_NUMERAL_RE = re.compile(r"^〔[0-9０-９]+〕\s*")

# --- R04 行首列表装饰符 ---
LIST_DECORATION_PREFIX_RE = re.compile(r"^[└├│▸▪●○◆◇☆★➔→・]\s*")

# --- R05 歌名最外层成对单引号 ---
SURROUNDING_SINGLE_QUOTES_RE = re.compile(r"^'([^']*)'")

# --- R06 末尾译文/罗马字括号（内含空格或 |；版本词 Remix/Mix/Live/Ver 保护，忽略大小写）---
TRANSLITERATION_PAREN_SUFFIX_RE = re.compile(
    r"(?i)\s*[(（](?!.*\b(?:remix|mix|live|ver\.?|edit|instrumental)\b)[^)）]*(?:\s|\|)[^)）]*[)）]\s*(?=/|$)"
)

# --- R07 末尾表演备注括号 ---
PERFORMANCE_NOTE_PAREN_SUFFIX_RE = re.compile(
    r"\s*[（(](?:少し|ちょっと|うろ覚え|練習|[0-9０-９]+番のみ|short\.?|ワンコーラス|途中まで)[）)]\s*(?=/|$)"
)

# --- R08 非歌曲噪音行 ---
NOISE_LINE_RE = re.compile(r"^(?:締め|[0-9０-９]+[,，][0-9０-９]+曲リクエスト)$")

# --- R09 保护正式标题符号（命中则整个字段跳过清洗）---
PROTECTED_TITLE_PATTERNS = [
    re.compile(r"DISH//"),
    re.compile(r"Don't say \"lazy\""),
    re.compile(r"God knows\.\.\."),
    re.compile(r"ハロ／ハワユ"),
    re.compile(r"ryo\(supercell\)"),
    re.compile(r"ナノウ\(ほえほえP\)"),
    re.compile(r"ツインテールは20歳まで♡"),
]

# --- R13 标题前数字序号（后跟空格或非数字）---
TRACK_NUMBER_PREFIX_RE = re.compile(r"^\s*[0-9０-９]{1,3}\s*[.．:：](?:\s+|(?=[^0-9０-９\s]))")

# --- R14 末尾注音假名括号（括号内全为假名）---
FURIGANA_PAREN_SUFFIX_RE = re.compile(r"\s*[（(][ぁ-んァ-ヶー]+[）)]\s*(?=/|$)")

# --- R15 末尾发行日期括号（完整日期，锚定行尾；避免与日期内 / 冲突）---
RELEASE_DATE_PAREN_SUFFIX_RE = re.compile(
    r"\s*[\[（(]\s*(?:18|19|20|21)\d{2}(?:\s*[\/.\-]\s*\d{1,2})?(?:\s*[\/.\-]\s*\d{1,2})?\s*(?:年|月)?\s*日?\s*[\]）)]\s*$"
)


def normalize_fullwidth(text: str) -> str:
    """R01+R10：全角数字/ASCII 字母统一半角。"""
    value = FULLWIDTH_DIGITS_RE.sub(lambda m: str(ord(m.group(0)) - 0xFF10), text or "")
    return FULLWIDTH_ASCII_RE.sub(
        lambda m: chr(ord(m.group(0)) - 0xFEE0), value
    )


def strip_leading_numeral_prefix(text: str) -> str:
    """R02+R13：剥离行首/标题前数字序号（保护 8.32、RE:I AM）。"""
    t = LEADING_NUMERAL_PREFIX_RE.sub("", text or "")
    t = TRACK_NUMBER_PREFIX_RE.sub("", t)
    return t


def strip_leading_fullwidth_bracket_numeral(text: str) -> str:
    """R03：剥离 〔10〕 序号前缀。"""
    return LEADING_FULLWIDTH_BRACKET_NUMERAL_RE.sub("", text or "")


def strip_list_decoration_prefix(text: str) -> str:
    """R04：剥离行首列表装饰符（树形 setlist）。"""
    return LIST_DECORATION_PREFIX_RE.sub("", text or "")


def strip_surrounding_single_quotes(text: str) -> str:
    """R05：剥离歌名最外层成对单引号（'PPPP' → PPPP）。"""
    m = SURROUNDING_SINGLE_QUOTES_RE.match(text or "")
    if m:
        return m.group(1)
    return text or ""


def has_protected_title(text: str) -> bool:
    """R09：是否命中受保护正式标题（命中则不允许删改）。"""
    return any(p.search(text or "") for p in PROTECTED_TITLE_PATTERNS)


def strip_performance_note_parens(text: str) -> str:
    """R07：删除末尾表演备注括号（（少し）（ちょっと）（1番のみ）等）。"""
    return PERFORMANCE_NOTE_PAREN_SUFFIX_RE.sub("", text or "")


def strip_furigana_parens(text: str) -> str:
    """R14：删除末尾注音假名括号（奏（かなで）→ 奏，仅当括号全为假名）。"""
    return FURIGANA_PAREN_SUFFIX_RE.sub("", text or "")


def strip_release_date_parens(text: str) -> str:
    """R15：删除末尾发行日期括号。"""
    return RELEASE_DATE_PAREN_SUFFIX_RE.sub("", text or "")


def strip_parenthetical_transliteration(text: str) -> str:
    """R06：删除末尾含空格或 | 的罗马字/译文括号（保护 ryo(supercell)）。"""
    return TRANSLITERATION_PAREN_SUFFIX_RE.sub("", text or "")


def is_noise_line(text: str) -> bool:
    """R08：是否噪音行（締め、1,2曲リクエスト）。"""
    return bool(NOISE_LINE_RE.match((text or "").strip()))


def apply_song_cleanup(text: str) -> str:
    """对单个歌名字段应用本模块规则（顺序：保护 → 规范化 → 剥离）。

    注意：R06/R07/R14 的括号删除只在括号位于「/ 分隔符前」时安全执行，
    因此此处先按 / 切分，只对歌名部分做括号清理，歌手字段不动。
    """
    raw = (text or "").strip()
    if not raw or has_protected_title(raw):
        return raw

    # 保护纯数字歌名（8.32、441）
    if re.fullmatch(r"\d{1,4}[.．]\d{1,4}", raw):
        return raw

    t = normalize_fullwidth(raw)
    # 剥离 R02/R03/R04/R05 前缀
    t = strip_leading_numeral_prefix(t)
    t = strip_leading_fullwidth_bracket_numeral(t)
    t = strip_list_decoration_prefix(t)
    t = strip_surrounding_single_quotes(t).strip()
    if not t:
        return t

    # 括号清理只对歌名部分（/ 前）执行；跳过括号内部的 /（如日期 2019/05/05、DISH//）
    slash_idx = -1
    depth = 0
    for i, ch in enumerate(t):
        if ch in "([{（［【「『《〈":
            depth += 1
            continue
        if ch in ")]}）］】」』》〉":
            depth = max(0, depth - 1)
            continue
        if depth != 0:
            continue
        if ch in "/／" and (i == 0 or t[i - 1] not in "/／") and (i + 1 >= len(t) or t[i + 1] not in "/／"):
            slash_idx = i
            break
    if slash_idx > 0:
        song = t[:slash_idx]
        artist = t[slash_idx + 1 :]
    else:
        song = t
        artist = ""
    # 后缀括号清理（表演备注/注音/日期/译文）对歌名部分执行
    song = strip_performance_note_parens(song)
    song = strip_furigana_parens(song)
    song = strip_release_date_parens(song)
    song = strip_parenthetical_transliteration(song).strip()
    song = song.strip()
    if not artist:
        return song
    artist = artist.strip()
    return f"{song} / {artist}".strip(" /")
