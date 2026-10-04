
from yt_comment_automation.pipeline import raw_has_timestamp_songlist  # noqa: E402
from yt_comment_automation import pipeline  # noqa: E402


def test_refetch_gate_new_video_every_round_old_video_twelve_hours(tmp_path):
    import datetime as dt
    assert pipeline.OLD_VIDEO_REFETCH_HOURS == 12
    assert pipeline.PENDING_RECHECK_HOURS == 12

    new_interval, new_age = pipeline._refetch_gate(
        tmp_path, "new-video", dt.date.today().isoformat()
    )
    assert (new_interval, new_age) == (0.0, 0.0)

    old_interval, old_age = pipeline._refetch_gate(
        tmp_path, "old-video", "2020-01-01"
    )
    assert old_interval == 12 * 3600.0
    assert old_age == float("inf")


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


def test_scattered_chat_multiple_timestamps_not_songlist():
    """BV1ZehV6LEMc 式：感想夹多个时间戳（25:39、40:58）不是歌单。"""
    from yt_comment_automation.pipeline import _is_songlist_comment
    chat = """25:39、52:40ここ好き！！！
40:58の「すずめ」のところの合いの手が面白すぎるwww
どうしても、にじゅなさんの左手がストップウォッチを
持ってる様に見えて仕方なかったwww"""
    assert _is_songlist_comment(chat) is False


def test_song_line_with_feeling_word_still_song():
    """歌名含好き/最高 等词但有 歌名/歌手 分隔符 → 仍是歌单。"""
    from yt_comment_automation.pipeline import _is_songlist_comment
    setlist = """0:05:39 好きだ / コブクロ
0:07:33 最高到達点 / SEKAI NO OWARI
0:12:02 マリーゴールド / あいみょん"""
    assert _is_songlist_comment(setlist) is True


def test_split_timestamp_song_lines_songlist():
    """时间戳单独一行 + 下一行歌名的跨行歌单 → 是歌单。"""
    from yt_comment_automation.pipeline import _is_songlist_comment
    text = """3:40
ミックスナッツ/ Official髭男dism
6:01
何なんw / 藤井風
15:40
プラスティック・ラブ / 竹内 まりや"""
    assert _is_songlist_comment(text) is True


def test_meme_markers_not_songlist():
    """时间戳+梗/闲聊（うんぽころこ、文房具マウント 等）→ 不是歌单。"""
    from yt_comment_automation.pipeline import _is_songlist_comment
    text = """2:01 声入り
3:00 開始
14:21 スクショタイム
38:21 文房具マウント
44:16 ｳﾝﾎﾟｺﾛｺ
45:19 ご飯？お風呂？それとも...
1:00:21 ジュエルありがとうの話"""
    assert _is_songlist_comment(text) is False


def test_split_items_by_pages_recalcs_timestamps():
    """多P视频按各P时长切分；P2+ 时间戳重算为 P 内相对时间。"""
    from yt_comment_automation.pipeline import split_items_by_pages
    from yt_comment_automation.clean import ParsedSong

    items = [
        ParsedSong("A", "", "0:02:10", 130),
        ParsedSong("B", "", "9:47:21", 9 * 3600 + 47 * 60 + 21),   # 35241 < 35995 → P1
        ParsedSong("C", "", "10:14:06", 10 * 3600 + 14 * 60 + 6),  # 36846 → P2 (851)
    ]
    pages = split_items_by_pages(items, [35995, 3679])
    assert len(pages) == 2
    assert [it.song for it in pages[0]] == ["A", "B"]
    assert [it.song for it in pages[1]] == ["C"]
    assert pages[1][0].timestamp_seconds == 851
    # 边界：正好等于 P1 结束时刻 → 属于 P2（时间 0）
    edge = [ParsedSong("E", "", "9:59:55", 35995)]
    pages2 = split_items_by_pages(edge, [35995, 3679])
    assert len(pages2[0]) == 0
    assert pages2[1][0].timestamp_seconds == 0
    # 超出总时长 → 归入最后一个P
    over = [ParsedSong("O", "", "12:00:00", 12 * 3600)]
    pages3 = split_items_by_pages(over, [35995, 3679])
    assert len(pages3[1]) == 1


def test_is_junk_song_title_filters_onomatopoeia():
    """直播拟声碎片（ｺｯ/ﾋﾟﾖ）是脏歌名，真歌名不受影响。"""
    from yt_comment_automation.pipeline import is_junk_song_title
    assert is_junk_song_title("ｺｯ") is True
    assert is_junk_song_title("ﾋﾟﾖ") is True
    assert is_junk_song_title("ｳﾝ") is True
    assert is_junk_song_title("コ") is True
    assert is_junk_song_title("ｶﾞ") is True
    # 真歌名/长拟声词不误伤
    assert is_junk_song_title("すずめ") is False
    assert is_junk_song_title("楓") is False
    assert is_junk_song_title("ハチミツ") is False
    assert is_junk_song_title("うんぽころこ") is False
    assert is_junk_song_title("ハーモニカ") is False
    assert is_junk_song_title("ﾋﾟﾖﾋﾟﾖ") is False


def test_description_setlist_detected_as_songlist():
    """BV15wYE68EBb：B站简介自带 SETLIST（无歌手歌名）应判为歌单并进入审核候选。"""
    from yt_comment_automation.pipeline import _is_songlist_comment

    desc = """・セットリスト
0:00:00 Starry☆Melody
0:04:34 Citylight Fantasy
0:07:44 MC
0:17:06 トイ×トイ⭐︎パーティ！
0:20:44 Breeze in the Sun
0:25:17 Like a Night Crusing
0:27:54 浮かれたってムテキ
0:31:00 エンドカード"""
    assert _is_songlist_comment(desc) is True


def test_no_artist_opening_markers_filtered():
    """BV1K8Yo6RESA：无歌手开场标记（声入り）与口琴（ハーモニカ）不进歌单；带歌手真歌保留。"""
    from yt_comment_automation import clean
    from yt_comment_automation.pipeline import is_junk_song_title

    items = [
        clean.ParsedSong("声入り", "", "0:02:39", 159),
        clean.ParsedSong("わたしの一番かわいいところ", "FRUITS ZIPPER", "0:06:18", 378),
        clean.ParsedSong("ハーモニカ", "", "0:17:17", 1037),
        clean.ParsedSong("ハーモニカ", "aiko", "0:20:00", 1200),
        clean.ParsedSong("すずめ", "", "0:25:00", 1500),
    ]
    filtered = [
        it for it in items
        if it.timestamp_seconds is not None
        and not is_junk_song_title(it.song)
        and (it.artist or (
            not clean.is_bare_title_excluded(it.song)
            and not __import__("re").search("声入り|ハーモニカ|あくび", it.song)
        ))
    ]
    songs = [(it.song, it.artist) for it in filtered]
    assert ("声入り", "") not in songs
    assert ("ハーモニカ", "") not in songs          # 无歌手口琴标记剔除
    assert ("ハーモニカ", "aiko") in songs          # 带歌手真歌保留
    assert ("わたしの一番かわいいところ", "FRUITS ZIPPER") in songs
    assert ("すずめ", "") in songs


def test_pending_video_skips_before_youtube_for_twelve_hours(tmp_path, monkeypatch):
    from yt_comment_automation import collections

    video = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1PendingGate",
        title="pending gate",
        # 老视频才受 pending 12 小时节流；新视频必须每轮抓（见下一个用例）。
        part_date="2020-01-01",
        yt_id="abcdefghijk",
    )
    monkeypatch.setattr(pipeline.config, "ignore_bvids", lambda: set())
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(pipeline.bili_comment, "find_own_comment", lambda bvid, cookies: None)
    monkeypatch.setattr(
        pipeline,
        "_fetch_bili_video_info",
        lambda bvid, cookie_map=None: (
            "abcdefghijk", "https://youtu.be/abcdefghijk", []
        ),
    )
    monkeypatch.setattr(pipeline, "_pending_review_status", lambda bvid, data_dir: "pending")
    monkeypatch.setattr(pipeline, "_last_fetch_age", lambda cache_dir, yt_id: 11 * 3600.0)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("pending 12 小时门控内不应请求 YouTube")

    monkeypatch.setattr(pipeline.yt_fetch, "fetch_youtube_raw", fail_if_called)

    result = pipeline.process_video(video, tmp_path, dry_run=False)

    assert result.status == "skipped_no_songs"
    assert "不足 12" in result.error


def test_codex_scope_excludes_pre_takeover_videos(monkeypatch):
    from yt_comment_automation import config

    monkeypatch.setenv("CODEX_SCOPE_START_DATE", "2026-10-02")
    monkeypatch.delenv("CODEX_SCOPE_BVIDS", raising=False)
    assert config.in_codex_scope("BV1New", part_date="2026-10-02") is True
    assert config.in_codex_scope("BV1Old", part_date="2026-10-01") is False
    assert config.in_codex_scope("BV1Manual", part_date="2026-10-01") is False
    monkeypatch.setenv("CODEX_SCOPE_BVIDS", "BV1Manual")
    assert config.in_codex_scope("BV1Manual", part_date="2026-10-01") is True


def test_new_pending_video_is_not_throttled_by_pending_queue(tmp_path, monkeypatch):
    """新视频进 pending 队列后仍必须每轮抓，否则会错过延迟贴出的歌单。"""
    import datetime as dt
    from yt_comment_automation import collections

    video = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1NewPending",
        title="new pending",
        part_date=dt.date.today().isoformat(),
        yt_id="newpendingid",
    )
    monkeypatch.setattr(pipeline.config, "ignore_bvids", lambda: set())
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(pipeline.bili_comment, "find_own_comment", lambda bvid, cookies: None)
    monkeypatch.setattr(
        pipeline,
        "_fetch_bili_video_info",
        lambda bvid, cookie_map=None: (
            "newpendingid", "https://youtu.be/newpendingid", []
        ),
    )
    monkeypatch.setattr(pipeline, "_pending_review_status", lambda bvid, data_dir: "pending")
    # 距上次抓取很久：若仍被 12 小时节流就跳过，若新视频豁免生效则会真正抓取。
    monkeypatch.setattr(pipeline, "_last_fetch_age", lambda cache_dir, yt_id: 11 * 3600.0)

    called = []

    def fake_fetch(yt_id, **kwargs):
        called.append(yt_id)
        return {"comments": [], "description": ""}

    monkeypatch.setattr(pipeline.yt_fetch, "fetch_youtube_raw", fake_fetch)

    result = pipeline.process_video(video, tmp_path, dry_run=False)

    assert result.status != "skipped_no_songs", "新视频不应被 pending 队列节流"
    assert "newpendingid" in called, "新视频本轮应真正请求 YouTube"

def test_upgrade_target_acted_and_pruned(tmp_path, monkeypatch):
    """upgrade 候选必须进 Action 目标，歌单补足后必须从台账摘除。"""
    from yt_comment_automation import youtube_targets

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # 1. 记账 -> 台账可见
    pipeline.record_upgrade_target(data_dir, "BV1Upgrade", "upgradetvid")
    assert "upgradetvid" in pipeline.load_upgrade_targets(data_dir)

    # 2. 台账里的 yt_id 要进入 Action 目标（即使该 bvid 已 posted）
    class Snap:
        def __init__(self, videos):
            self.videos = videos

    video = type("V", (), {
        "bvid": "BV1Upgrade", "yt_id": "upgradetvid",
        "part_date": "2020-01-01",
    })()
    posted_video = type("V", (), {
        "bvid": "BV1Posted", "yt_id": "postedvid",
        "part_date": "2020-01-01",
    })()

    monkeypatch.setattr(
        youtube_targets.collections, "load_snapshot",
        lambda path=None: Snap([video, posted_video]),
    )
    monkeypatch.setattr(youtube_targets.config, "ignore_bvids", lambda: set())
    monkeypatch.setattr(youtube_targets.config, "in_codex_scope", lambda *a, **k: True)
    monkeypatch.setattr(youtube_targets.review, "list_comments", lambda **k: [])
    monkeypatch.setattr(
        pipeline, "load_processed", lambda p: {"BV1Posted", "BV1Upgrade"}
    )
    (data_dir / "yt_raw").mkdir()
    (data_dir / "yt_raw" / "fetch_times.json").write_text("{}")

    ids = youtube_targets.due_targets(data_dir, refresh=False)
    assert "upgradetvid" in ids, "已发布 upgrade 候选必须由 Action 重抓"
    assert "postedvid" not in ids, "已发布且无需升级的视频不应进 Action 目标"

    # 3. 歌单补足 -> 台账摘除
    pipeline.forget_upgrade_target(data_dir, "upgradetvid")
    assert pipeline.load_upgrade_targets(data_dir) == {}
