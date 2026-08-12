
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

from yt_comment_automation.pipeline import _verify_ai_items_against_source  # noqa: E402


def test_verify_hallucination_dropped():
    """BV1eYgV6WEq3：歌名'悪ノ召使'不在纯聊天原文里 → 幻觉丢弃。"""
    comments = [
        "おつかささまでした～。最高に楽しかった！",
        "今日も楽しかった～！いぇーい！",
    ]
    items = [type("X", (), {"song": "悪ノ召使", "artist": "つかさくん"})()]
    verified = _verify_ai_items_against_source(items, comments)
    assert len(verified) == 0


def test_verify_real_songs_kept():
    """BV1NV3g6eEpF：真实 2 首，歌名都在原文 → 全部保留。"""
    comments = [
        "3:49 開始~start~\n12:11 Tokimeki / Vaundy\n30:41 メランコリック / Junky feat. 鏡音リン"
    ]
    items = [
        type("X", (), {"song": "Tokimeki", "artist": "Vaundy"})(),
        type("X", (), {"song": "メランコリック", "artist": "Junky feat. 鏡音リン"})(),
    ]
    verified = _verify_ai_items_against_source(items, comments)
    assert len(verified) == 2


def test_verify_setlist_kept():
    """BV1eYgV6WEq3 的 Setlist：歌名都在原文 → 保留（含纯数字/短歌名）。"""
    comments = [
        "『15:10』 clock lock works / ハチ\n『22:16』 ワンダーランドと羊の歌 / ハチ\n『35:29』 Q / 椎名もた"
    ]
    items = [
        type("X", (), {"song": "clock lock works", "artist": "ハチ"})(),
        type("X", (), {"song": "ワンダーランドと羊の歌", "artist": "ハチ"})(),
        type("X", (), {"song": "Q", "artist": "椎名もた"})(),
    ]
    verified = _verify_ai_items_against_source(items, comments)
    assert len(verified) == 3
