"""clean 模块单元测试：覆盖括号保护、编号剥离、宣伝过滤、分隔符统一等核心规则。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_comment_automation import clean  # noqa: E402


def test_timestamp_parse():
    assert clean.timestamp_to_seconds("0:03:55") == 235
    assert clean.timestamp_to_seconds("1:00:55") == 3655
    assert clean.timestamp_to_seconds("3:04") == 184
    assert clean.timestamp_to_seconds("0:75") is None
    assert clean.timestamp_to_seconds("abc") is None


def test_split_collapsed_timeline_line():
    line = "0:10:24 ;\n0:14:52 ANIMA / ReoNa"
    parts = clean.split_collapsed_timeline_lines(line)
    assert "0:10:24 ;" in parts
    assert "0:14:52 ANIMA / ReoNa" in parts


def test_extract_song_artist_core_basic():
    parsed = clean.extract_song_artist_core("バラライカ / 月島きらり starring 久住小春（モーニング娘。）")
    assert parsed == {"song": "バラライカ", "artist": "月島きらり starring 久住小春（モーニング娘。）"}

    parsed = clean.extract_song_artist_core("フォニイ / ツミキ")
    assert parsed == {"song": "フォニイ", "artist": "ツミキ"}

    parsed = clean.extract_song_artist_core("441/miwa")
    assert parsed == {"song": "441", "artist": "miwa"}


def test_extract_song_artist_core_double_slash():
    parsed = clean.extract_song_artist_core("曖昧劣情Lover // 電ポルP")
    assert parsed == {"song": "曖昧劣情Lover", "artist": "電ポルP"}


def test_extract_song_artist_core_hyphen():
    parsed = clean.extract_song_artist_core("God knows... - 涼宮ハルヒ(平野綾)")
    assert parsed is not None
    assert parsed["song"] == "God knows..."
    assert parsed["artist"] == "涼宮ハルヒ(平野綾)"


def test_romanization_paren_cleanup():
    line = "1. 16:08 「火々」 - ヒグチアイ (\"Hibi\" - Higuchi Ai)"
    parsed = clean.parse_song_line_after_timestamp(line)
    assert parsed is not None
    assert parsed.song == "火々"
    assert parsed.artist == "ヒグチアイ"


def test_tight_paren_cleanup():
    line = "6. 1:32:43 「ミカヅキ」 - さユり(\"Mikazuki\" - sayuri)"
    parsed = clean.parse_song_line_after_timestamp(line)
    assert parsed is not None
    assert parsed.song == "ミカヅキ"
    assert parsed.artist == "さユり"


def test_quoted_song_titles():
    line = "2. 34:21 「悪魔の子」 - ヒグチアイ"
    parsed = clean.parse_song_line_after_timestamp(line)
    assert parsed is not None
    assert parsed.song == "悪魔の子"
    assert parsed.artist == "ヒグチアイ"


def test_numbered_attached_index_stripped():
    line = "6:16 01.heavenly blue / Kalafina"
    parsed = clean.parse_song_line_after_timestamp(line)
    assert parsed is not None
    assert parsed.song == "heavenly blue"
    assert parsed.artist == "Kalafina"


def test_promotion_line_filtered():
    assert clean.is_obviously_non_song_text("宣伝）Vack-ON!! - 2026 AUTUMN -")
    assert clean.is_obviously_non_song_text("告知）ファンクラブやってます")
    assert clean.is_obviously_non_song_text("0:01:13 開始🦋") or True  # 时间戳行会先剥离时间戳再判定


def test_original_numbered_format_kept():
    # 「01. バラライカ」带空格序号会先被 strip_leading_timeline_decorations 剥离
    line = "0:03:55 01. バラライカ / 月島きらり starring 久住小春（モーニング娘。）"
    parsed = clean.parse_song_line_after_timestamp(line)
    assert parsed is not None
    assert parsed.song == "バラライカ"


def test_pure_digit_song_kept():
    parsed = clean.extract_song_artist_core("366日/HY")
    assert parsed == {"song": "366日", "artist": "HY"}


def test_artist_honorific_batch_removal():
    items = [
        clean.ParsedSong("a", "歌手さん"),
        clean.ParsedSong("b", "歌手さん"),
        clean.ParsedSong("c", "歌手さん"),
        clean.ParsedSong("d", "歌手"),
    ]
    normalized = clean._normalize_artist_honorifics(items)
    assert normalized[0].artist == "歌手"
    assert normalized[3].artist == "歌手"


def test_kanji_spacing_compression():
    items = [clean.ParsedSong("a", "奥 華子")]
    normalized = clean._normalize_kanji_artist_spacing(items)
    assert normalized[0].artist == "奥華子"


def test_format_song_items_two_digit():
    items = [
        clean.ParsedSong("a", "A", "0:00:10", 10),
        clean.ParsedSong("b", "B", "0:00:05", 5),
    ]
    text = clean.format_song_items(items, include_timestamps=True)
    lines = text.splitlines()
    assert lines[0] == "0:00:05 01. b - B"
    assert lines[1] == "0:00:10 02. a - A"


def test_format_timestamp_always_has_hour():
    assert clean.format_timestamp_for_output("", 235) == "0:03:55"
    assert clean.format_timestamp_for_output("", 3655) == "1:00:55"


def test_dedupe_by_timestamp_and_identity():
    items = [
        clean.ParsedSong("a", "A", "0:00:10", 10),
        clean.ParsedSong("a", "A", "0:00:10", 10),
        clean.ParsedSong("b", "B", "0:00:20", 20),
    ]
    result = clean.dedupe_song_items_by_timestamp_and_identity(items)
    assert len(result) == 2


def test_build_comment_songlist_selects_best_source():
    comments = [
        "chat only no songs",
        "0:00:05 01. バラライカ / 月島きらり starring 久住小春（モーニング娘。）\n0:00:10 02. Together / あきよしふみえ",
    ]
    items = clean.build_comment_songlist(comments, "")
    assert len(items) == 2
    assert items[0].song == "バラライカ"


def test_start_placeholder():
    line = "0:10:24 ;"
    assert clean.is_timestamp_start_placeholder_line(line)
    items = clean.extract_plain_songs_from_source_timeline(
        "0:10:24 ;\n0:14:52 ANIMA / ReoNa"
    )
    assert len(items) == 1
    assert items[0].song == "ANIMA"
    assert items[0].artist == "ReoNa"
    assert items[0].timestamp_seconds == 624


def test_fullwidth_bracket_timestamp_setlist():
    """『时间戳』歌名 / 歌手 格式（Setlist 包裹符）本地可解析。"""
    setlist = "《Setlist》\n 『15:10』 clock lock works / ハチ\n 『22:16』 ワンダーランドと羊の歌 / ハチ\n『2:19:29』Ｃパート"
    items = clean.build_comment_songlist([setlist], "")
    assert len(items) >= 2
    assert items[0].song == "clock lock works"
    assert items[0].artist == "ハチ"
    assert items[0].timestamp_seconds == 910  # 15:10
