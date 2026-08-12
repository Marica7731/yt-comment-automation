
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


def test_raw_two_songlines_detected():
    """BV1NV3g6eEpF 式：2 首真歌 + 開始标记 → 判定有歌单。"""
    raw = {"comments": [{"text": "3:49 開始~start~\n12:11 Tokimeki / Vaundy\n30:41 メランコリック / Junky feat. 鏡音リン"}]}
    assert raw_has_timestamp_songlist(raw) is True


def test_raw_scattered_chat_not_songlist():
    """BV1eYgV6WEq3 式：感想夹 1 个时间戳 → 不是歌单。"""
    raw = {"comments": [{"text": "おつかささまでしたー！！\n1:30:53 つかさくんの『悪ノ召使』めっっちゃ良いー\n最後のお焚き上げも面白かったwww"}]}
    assert raw_has_timestamp_songlist(raw) is False



def test_songlist_comment_vs_scattered_chat():
    """BV1eYgV6WEq3 区分：结构化歌单 vs 零散感想。"""
    from yt_comment_automation.pipeline import _is_songlist_comment

    # 结构化歌单（Setlist 每行时间戳+歌名/歌手）→ True
    setlist = "『15:10』 clock lock works / ハチ\n『22:16』 ワンダーランドと羊の歌 / ハチ\n『35:29』 Q / 椎名もた"
    assert _is_songlist_comment(setlist) is True

    # 零散感想（夹 1 个时间戳的聊天）→ False，不喂 DS
    chat = "おつかささまでしたー！！\n1:30:53 つかさくんの『悪ノ召使』めっっちゃ良いー\n最後のお焚き上げも面白かったwww"
    assert _is_songlist_comment(chat) is False

    # BV1NV3g6eEpF 真实小歌单（2 首，时间戳行密集）→ True
    small = "3:49 開始~start~\n12:11 Tokimeki / Vaundy\n30:41 メランコリック / Junky feat. 鏡音リン"
    assert _is_songlist_comment(small) is True

    # BV1vLuY6yEXo 歌名+时间戳 无分隔符格式 → True
    nodelim = "ライラック 11:10\n私は最強 18:46\nサウダージ 23:23\n世界は恋に落ちている 31:01"
    assert _is_songlist_comment(nodelim) is True


def test_upgrade_logic_count():
    """质量升级：数已发歌单首数（时间戳+编号格式）。"""
    from yt_comment_automation.pipeline import _count_own_songlist_lines
    msg = "0:06:41 01. おジャ魔女カーニバル!! - 歌手\n0:09:27 02. Together - あきよしふみえ"
    assert _count_own_songlist_lines(msg) == 2
    # 低质量 1 首
    assert _count_own_songlist_lines("1:30:53 01. 悪ノ召使 - つかさくん") == 1
    # 旧格式（无编号）
    assert _count_own_songlist_lines("0:17:27 Butter-Fly / 和田光司") == 0


def test_scattered_chat_not_cut():
    """感想夹 1 个时间戳的评论：不因密度一刀砍（放宽后 _is_songlist_comment 只看 ≥2 歌曲行）。"""
    from yt_comment_automation.pipeline import _is_songlist_comment
    # 半歌单半感想（2 歌曲行 + 1 感想行）→ 仍算歌单（不再要求密度≥50%）
    mixed = "おつかささまでした\n1:30:53 悪ノ召使 / mothy\n1:37:25 廃都アトリエスタにて / 暴走P"
    assert _is_songlist_comment(mixed) is True
