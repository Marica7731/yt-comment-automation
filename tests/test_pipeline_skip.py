"""跳过判定单元测试：任何作者的真歌单才跳过；非歌标记不跳过。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_comment_automation.pipeline import has_any_timestamp_songlist  # noqa: E402


def test_real_songlist_with_marker_line():
    """BV1NV3g6eEpF 案例：2首真歌 + 開始标记 → 跳过。"""
    comments = [
        "3:49 開始~start~\n\n😈本日のSet List💝\n12:11 Tokimeki / Vaundy\n30:41 メランコリック / Junky feat. 鏡音リン"
    ]
    assert has_any_timestamp_songlist(comments) is True


def test_pure_markers_not_songlist():
    """纯开始/MC/章节标记 → 不跳过，让 DS 继续。"""
    comments = ["0:05:57 開始\n0:14:55 MC\n0:30:00 雑談コーナー\n0:45:00 スクショタイム"]
    assert has_any_timestamp_songlist(comments) is False


def test_songname_only_no_separator():
    """只有歌名无歌手无分隔符 → 不跳过（DS 可能仍能识别）。"""
    comments = ["0:05:00 夜に駆ける\n0:10:00 アイドル\n0:15:00 千本桜"]
    assert has_any_timestamp_songlist(comments) is False


def test_numbered_songlist():
    """带编号的真歌单 → 跳过。"""
    comments = ["0:06:41 01. おジャ魔女カーニバル!! - 歌手\n0:09:27 02. Together - あきよしふみえ\n0:14:57 03. ココロのちず - BOYSTYLE"]
    assert has_any_timestamp_songlist(comments) is True


def test_chapter_timeline_not_songlist():
    """章节时间轴（opening/1曲目/雑談/告知）→ 不跳过。"""
    comments = ["0:00:00 オープニング\n0:05:00 1曲目\n0:20:00 雑談\n0:40:00 告知"]
    assert has_any_timestamp_songlist(comments) is False


def test_short_chat_no_timestamp():
    """普通聊天无时间戳 → 不跳过。"""
    comments = ["配信お疲れ様でした！楽しかった〜"]
    assert has_any_timestamp_songlist(comments) is False


def test_two_song_lines_with_atsign():
    """＠ 歌手格式的真歌单 → 跳过。"""
    comments = ["0:06:45　ヒトリゴト(＠ClariS)\n0:18:14　U&I(＠放課後ティータイム)\n0:25:08　小悪魔だってかまわない！(＠めいちゃん)"]
    assert has_any_timestamp_songlist(comments) is True
