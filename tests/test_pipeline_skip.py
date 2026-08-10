
from yt_comment_automation.pipeline import raw_has_timestamp_songlist  # noqa: E402


def test_raw_songlist_detected():
    """BV1vLuY6yEXo 式歌单（歌名+时间戳，含分隔符）→ 判定有歌单。"""
    raw = {"comments": [
        {"text": "ライラック 11:10\n私は最強 18:46\nサウダージ 23:23\n世界は恋に落ちている 31:01"},
        {"text": "おつイズです！楽しかった"},
    ]}
    assert raw_has_timestamp_songlist(raw) is True


def test_raw_pure_chat_no_songlist():
    """纯聊天无时间戳 → 无歌单（应每次重抓）。"""
    raw = {"comments": [{"text": "おつイズです！久しぶりの縦型配信良かった！"}, {"text": "ありがとうございました"}]}
    assert raw_has_timestamp_songlist(raw) is False


def test_raw_markers_only_no_songlist():
    """只有開始/MC/雑談 标记 → 无歌单（应重抓）。"""
    raw = {"comments": [{"text": "4:26 [開始]\n16:12 [雑談time☆]\n1:50:10 [あくび]"}]}
    assert raw_has_timestamp_songlist(raw) is False


def test_raw_one_songline_detected():
    """至少 1 个歌曲行即判定有歌单（不限条数）。"""
    raw = {"comments": [{"text": "0:12:11 Tokimeki / Vaundy\n3:49 開始~start~"}]}
    assert raw_has_timestamp_songlist(raw) is True
