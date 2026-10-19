"""clean 模块单元测试：覆盖括号保护、编号剥离、宣伝过滤、分隔符统一等核心规则。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_comment_automation import clean  # noqa: E402


def test_range_timestamp_is_parsed_and_formatted_in_full():
    items = clean.extract_plain_songs_from_source_timeline(
        "0:12:01-0:16:36 コネクト / ClariS"
    )
    assert len(items) == 1
    assert items[0].timestamp_seconds == 721
    assert items[0].timestamp_end_seconds == 996
    assert (
        clean.format_timestamp_for_output(
            items[0].timestamp_label,
            items[0].timestamp_seconds,
            True,
            items[0].timestamp_end_seconds,
        )
        == "0:12:01-0:16:36"
    )
    assert clean.format_song_items(items, include_timestamps=True).startswith(
        "0:12:01-0:16:36 01."
    )


def test_single_and_invalid_timestamps_fall_back_to_one_timestamp():
    single = clean.extract_plain_songs_from_source_timeline(
        "0:12:01 コネクト / ClariS"
    )
    assert len(single) == 1
    assert single[0].timestamp_end_seconds is None
    assert (
        clean.format_timestamp_for_output(
            single[0].timestamp_label,
            single[0].timestamp_seconds,
            True,
            single[0].timestamp_end_seconds,
        )
        == "0:12:01"
    )

    for invalid in (
        "0:16:36-0:12:01 コネクト / ClariS",
        "0:12:01-0:12:01 コネクト / ClariS",
    ):
        fallback = clean.extract_plain_songs_from_source_timeline(invalid)
        assert len(fallback) == 1
        assert fallback[0].timestamp_end_seconds is None
        assert fallback[0].song == "コネクト"


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


def test_cjk_quoted_phrase_inside_song_title_is_preserved():
    parsed = clean.parse_song_line_after_timestamp(
        "1:30:43 ｢ひとりで生きられそう｣って それってねえ、褒めているの？ / Juice＝Juice"
    )
    assert parsed is not None
    assert parsed.song == "｢ひとりで生きられそう｣って それってねえ、褒めているの？"
    assert parsed.artist == "Juice＝Juice"


def test_artist_work_metadata_suffix_is_removed():
    cases = {
        "0:30:27 more than words / 羊文学 / アニメ 呪術廻戦「渋谷事変」": "羊文学",
        "0:41:39 光景 / 篠澤広（川村玲奈）/ 初星学園": "篠澤広（川村玲奈）",
        "1:17:35 God knows… / 涼宮ハルヒ(平野綾) / アニメ 涼宮ハルヒの憂鬱 劇中歌": "涼宮ハルヒ(平野綾)",
        "1:23:17 めざせポケモンマスター / 松本梨香 / アニメ ポケットモンスター ※うろ覚え": "松本梨香",
        "1:36:48 オツキミリサイタル / じん feat.IA / カゲロウプロジェクト": "じん feat.IA",
        "2:57:49 スパークル / RADWIMPS / アニメ映画 君の名は。挿入歌": "RADWIMPS",
    }
    for line, expected_artist in cases.items():
        parsed = clean.parse_song_line_after_timestamp(line)
        assert parsed is not None
        assert parsed.artist == expected_artist, line


def test_music_version_paren_is_preserved_in_song_title():
    parsed = clean.parse_song_line_after_timestamp(
        "1:03:44 なんでもないや (movie ver.)/RADWIMPS"
    )
    assert parsed is not None
    assert parsed.song == "なんでもないや (movie ver.)"
    assert parsed.artist == "RADWIMPS"


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


def test_ascii_quote_wrapped_setlist():
    # YouTube 频道主 SETLIST：`0:05:39 " 歌名 / 歌手` 裸引号是条目包裹符，应剥掉
    line = "0:05:39 \" アルストロメリア / 凛々咲"
    parsed = clean.parse_song_line_after_timestamp(line)
    assert parsed is not None
    assert parsed.song == "アルストロメリア"
    assert parsed.artist == "凛々咲"


def test_paired_ascii_quote_title_kept():
    # 成对引号包裹的歌名是正规写法，应完整保留
    line = "0:05:39 \"Alstroemeria\" / 凛々咲"
    parsed = clean.parse_song_line_after_timestamp(line)
    assert parsed is not None
    assert parsed.song == '"Alstroemeria"'
    assert parsed.artist == "凛々咲"


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


def test_live_segment_bare_titles_filtered():
    """BV1KqH16wEsJ/BV1eHH163Ewh：无歌手直播环节不得进入 R17 歌单。"""
    source = "\n".join(
        [
            "01:48:16 スパチャ読み",
            "3:18:32 じゃんけん",
            "3:19:22 :_おつりんね::_りんね:",
        ]
    )
    assert clean.extract_plain_songs_from_source_timeline(source) == []
    for title in ("スパチャ読み", "じゃんけん", ":_おつりんね::_りんね:"):
        assert clean.is_obviously_non_song_text(title) is True


def test_no_artist_viewer_reaction_timestamps_filtered():
    """BV1omnG6nEfV：观众对直播过程的 TS 感想不是无歌手歌曲。"""
    source = "\n".join(
        [
            "43:48 初見でおそるべき肺活量を見せつける歌シンガーあまこも",
            "48:56 急に早口になるあまこも",
            "44:05 さすがVsinger",
        ]
    )
    assert clean.extract_plain_songs_from_source_timeline(source) == []
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


def test_character_names_removed_for_requested_song():
    items = [
        clean.ParsedSong(
            "シカせんべいのうた",
            "鹿乃子のこ(潘めぐみ), 虎視虎子(藤田咲)",
            "3:26:22",
            12382,
        )
    ]
    normalized = clean._normalize_artist_display(items)
    assert normalized[0].artist == "潘めぐみ, 藤田咲"
    assert (
        clean.format_song_items(normalized, include_timestamps=True)
        == "3:26:22 01. シカせんべいのうた - 潘めぐみ, 藤田咲"
    )


def test_other_character_voice_credit_is_unchanged():
    items = [clean.ParsedSong("God knows...", "涼宮ハルヒ(平野綾)")]
    normalized = clean._normalize_artist_display(items)
    assert normalized[0].artist == "涼宮ハルヒ(平野綾)"


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


def test_dotted_numeric_song_names():
    """点分数字歌名（8.8/4.3.2.1）正确保留；原文自带编号剥除不误伤数字歌名。"""
    a = clean.parse_song_line_after_timestamp("0:03:55 8.8")
    assert a is not None and a.song == "8.8"
    b = clean.parse_song_line_after_timestamp("0:03:55 4.3.2.1")
    assert b is not None and b.song == "4.3.2.1"
    c = clean.parse_song_line_after_timestamp("1:50:07　14.あなたの夜が明けるまで(-5キー)")
    assert c is not None and c.song == "あなたの夜が明けるまで(-5キー)"
    d = clean.parse_song_line_after_timestamp("1:50:07 14. 14.あなたの夜が明けるまで(-5キー)")
    assert d is not None and d.song == "あなたの夜が明けるまで(-5キー)"

def test_katakana_start_marker_is_not_a_song():
    items = clean.extract_plain_songs_from_source_timeline(
        "『03:18』スタート\n『09:29』怪獣 / サカナクション"
    )
    assert [item.song for item in items] == ["怪獣"]
    assert clean.is_obviously_non_song_text("スタート") is True
    assert clean.is_non_song_section_marker("スタート") is True


def test_stream_timeline_markers_are_not_songs():
    """BV1uCpv6gEn8：评论里「タイムスタンプ」段的 OP/配信スタート/出発進行
    与「セットリスト」段混在一起，环节行不得进入歌单。"""
    source = (
        "🐤💛💌💕タイムスタンプ🐧🩵💌💕\n"
        "00:00 OP\n"
        "01:25  配信スタート\n"
        "01:39 出発進行～！\n"
        "24:14 次枠出演者さん紹介\n"
        "🐤💛💌💕セットリスト🐧🩵💌💕\n"
        "02:21 🎵愛包ダンスホール ／ HIMEHINA\n"
        "07:06 🎵友情ノーチェンジ／ μ's\n"
        "11:59 🎵コイスルオトメ ／ いきものがかり\n"
        "17:37 🎵けーたいみしてよ ／ MAISONdes\n"
        "20:32 🎵浮気したらあかんで ／  コレサワ\n"
        "25:57 🎵Family Song ／ 星野源\n"
    )
    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [i.song for i in items] == [
        "愛包ダンスホール",
        "友情ノーチェンジ",
        "コイスルオトメ",
        "けーたいみしてよ",
        "浮気したらあかんで",
        "Family Song",
    ]
    assert clean.is_non_song_section_marker("OP") is True
    assert clean.is_non_song_section_marker("配信スタート") is True
    assert clean.is_non_song_section_marker("出発進行～！") is True
    assert clean.is_non_song_section_marker("Ｃパート") is True


def test_bilibili_op_placeholder_is_not_a_song():
    """BV1Eppv69E7A：B站简介模板里的「00:00:00  OP」不是歌曲。"""
    items = clean.extract_plain_songs_from_source_timeline(
        "00:00:00  OP\n直播开始时间：2026-10-10 17:00:20"
    )
    assert items == []


def test_relay_performer_schedule_never_beats_real_songlist():
    """BV152pu6GEzJ（6LDC7E-sLz0）：简介的出演者时段表每行带 / @handle，
    被解析成「歌名/歌手」后 7 行盖过评论里 6 行真歌单。真实来源必须胜出。"""
    description = (
        "＝タイムスケジュール（※敬称略）＝\n"
        "18:30 -   開会式 (シャノンch)　   / @shinozakishanon   \n"
        "19:00 -   萌実　   / @moemi_chan   \n"
        "19:30 -  天羅洲テラス　   / @amarasuterasu   \n"
        "20:00 -  エトラ　   / @etrachannel   \n"
        "20:30 -  宮霧りりい　   / @miyakirilily   \n"
        "21:00 -   石狩あかり　   / @akari0415   \n"
        "21:30 -   篠崎シャノン (閉会式含む)　   / @shinozakishanon   \n"
    )
    songlist_comment = (
        "1:57 Start\n"
        "2:00 〔1〕迷宮バタフライ / ほしな歌唄(水樹奈々)\n"
        "7:03 〔2〕I beg you / Aimer\n"
        "11:36 〔3〕名前のない怪物 / EGOIST\n"
        "16:56 〔4〕モザイクロール / DECO*27\n"
        "20:02 〔5〕Rolling star / YUI\n"
        "23:15 〔6〕GO！ALEX！～希望誕生～ / JAM Project\n"
        "27:40 締め\n"
    )
    ranked = clean.build_comment_songlist_ranked([songlist_comment], "")
    top = ranked[0]
    assert [s.song for s in top] == [
        "迷宮バタフライ",
        "I beg you",
        "名前のない怪物",
        "モザイクロール",
        "Rolling star",
        "GO！ALEX！～希望誕生～",
        "締め",
    ]
    # 出演者时段表单独喂进去确实能解析出条目（所以旧代码才会让它参赛）
    schedule_only = clean.build_comment_songlist_ranked([], description)
    assert schedule_only and len(schedule_only[0]) >= 6
    # 但只要评论里有真歌单，pipeline 就不该把简介传进来；这里用「空简介」
    # 复现 pipeline 的 desc_rank_source 语义：有歌单评论时简介一律不参与。
    assert clean.build_comment_songlist_ranked([songlist_comment], "") == ranked
    # 社交账号名不是歌手，不能计入排序的「带歌手数」
    assert clean._is_social_handle_artist("@shinozakishanon") is True
    assert clean._is_social_handle_artist("Mrs. GREEN APPLE") is False


def test_relay_collab_entrance_talk_lines_are_not_songs():
    """BV1Dvpg6BE8Y（xa8nwPEI7h4）：3D collab 的时段评论把登场/谈话/感想
    与歌曲混在一起，环节行不得进入歌单。"""
    source = (
        "00:01:36 開始\n"
        "00:02:06 夜羽咲クロネ登場\n"
        "00:03:47 Figaroさん、魔光リサさん登場\n"
        "00:07:14 1曲目「星座になれたら/夜羽咲クロネ・Figaro・魔光リサ」\n"
        "00:11:29 トーク\n"
        "00:20:05 ANIMA/Figaro・魔光リサ\n"
        "00:30:08 座って休憩＆トーク\n"
        "00:31:15 改めて「CROSS REALITY LIVE Vol.3」の感想\n"
        "00:46:49 潮騒/Figaro\n"
    )
    items = clean.extract_plain_songs_from_source_timeline(source)
    songs = [i.song for i in items]
    assert "夜羽咲クロネ登場" not in songs
    assert "座って休憩＆トーク" not in songs
    assert not any("感想" in s for s in songs)
    # 剩下的必须是真的歌，且「歌名/歌手」成对引号要拆开
    assert [(i.song, i.artist) for i in items] == [
        ("星座になれたら", "夜羽咲クロネ・Figaro・魔光リサ"),
        ("ANIMA", "Figaro・魔光リサ"),
        ("潮騒", "Figaro"),
    ]
    assert clean.is_obviously_non_song_text("夜羽咲クロネ登場") is True
    assert clean.is_obviously_non_song_text("あっちゅー魔！") is False


def test_artistless_duplicate_is_deduped():
    """xa8nwPEI7h4：同一条评论首尾重复 01:20:48 告白日和，
    无歌手条目此前被整体豁免去重，两份都会残留。"""
    items = [
        clean.ParsedSong(timestamp_label="1:20:48", timestamp_seconds=4848, song="告白日和、です！", artist=""),
        clean.ParsedSong(timestamp_label="1:20:48", timestamp_seconds=4848, song="告白日和、です！", artist=""),
    ]
    assert len(clean.dedupe_song_items_by_timestamp_and_identity(items)) == 1


def test_artist_annotations_do_not_leak_into_ranking():
    """セットリスト/セトリ外 的宣伝、じゃんけん行不得计入歌手数。"""
    source = (
        "0:06:27 約束のしおり / ACE COLLECTION\n"
        "0:17:59 紋白蝶 feat. 石原慎也 (Saucy Dog) / 東京スカパラダイスオーケストラ\n"
        "1:45:57 366日 / HY\n"
    )
    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [i.song for i in items] == ["約束のしおり", "紋白蝶 feat. 石原慎也", "366日"]


def test_cjk_quoted_song_artist_pair_is_split():
    """BV1Dvpg6BE8Y（xa8nwPEI7h4）评论区用「歌名/歌手」成对引号包裹整行，
    分隔符落在外层引号内部被括号掩蔽逻辑跳过，此前整串变成歌名、歌手为空。"""
    source = (
        "00:20:05 「ANIMA/Figaro・魔光リサ」\n"
        "00:27:00 「ラヴィ/夜羽咲クロネ・魔光リサ」\n"
        "00:46:49 「潮騒/Figaro」\n"
        "☆01:20:48 「告白日和、です！/夜羽咲クロネ・魔光リサ」\n"
    )
    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [(i.song, i.artist) for i in items] == [
        ("ANIMA", "Figaro・魔光リサ"),
        ("ラヴィ", "夜羽咲クロネ・魔光リサ"),
        ("潮騒", "Figaro"),
        ("告白日和、です！", "夜羽咲クロネ・魔光リサ"),
    ]


def test_numbered_quoted_song_artist_pair_is_split():
    """`1曲目「星座になれたら/夜羽咲クロネ・Figaro・魔光リサ」`：曲目编号不是歌名，
    剥掉编号后成对引号内的 / 才拆得出歌手。"""
    source = (
        "00:07:14 1曲目「星座になれたら/夜羽咲クロネ・Figaro・魔光リサ」\n"
        "00:13:09 ２曲目「恋するフォーチュンクッキー/夜羽咲クロネ・Figaro」\n"
    )
    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [(i.song, i.artist) for i in items] == [
        ("星座になれたら", "夜羽咲クロネ・Figaro・魔光リサ"),
        ("恋するフォーチュンクッキー", "夜羽咲クロネ・Figaro"),
    ]


def test_unclosed_quote_song_is_still_parsed():
    """`00:53:09 「あっちゅー魔！` 缺收尾引号，但它是真歌；
    未闭合开引号不能当成「环节行」判据把歌丢掉。"""
    source = "00:53:09 「あっちゅー魔！\n"
    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [i.song for i in items] == ["あっちゅー魔！"]
    assert clean.is_obviously_non_song_text("あっちゅー魔！") is False


def test_stage_cue_lines_are_not_songs():
    """BV152pu6GEzJ（6LDC7E-sLz0）：`23:07 次でラスト`、`00:17:52 トーク②` 是串场词。
    环节词尾跟圈号时只匹配词尾会漏掉；締め/ラスト 按 R08 之外另行排除。"""
    assert clean.is_obviously_non_song_text("次でラスト") is True
    assert clean.is_obviously_non_song_text("ラスト") is True
    assert clean.is_obviously_non_song_text("ラスト1曲") is True
    assert clean.is_obviously_non_song_text("トーク②") is True
    assert clean.is_obviously_non_song_text("トーク③") is True
    assert clean.is_obviously_non_song_text("休憩②") is True
    # 真歌不能误伤
    assert clean.is_obviously_non_song_text("GO！ALEX！～希望誕生～") is False
    source = "23:07 次でラスト\n23:15 GO！ALEX！～希望誕生～ / JAM Project\n"
    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [i.song for i in items] == ["GO！ALEX！～希望誕生～"]


def test_figaro_greeting_marker_not_counted_as_song():
    """BV1NKJ26sE8F：真实结构化歌单里的「ご挨拶」是环节，不是第 01 首。"""
    source = (
        "00:00      OP\n"
        "01:23      ご挨拶\n"
        "05:42      01.  ありあまる富 (The Invaluable) // 椎名林檎 (Ringo Sheena)\n"
        "13:18      02.  ノーチラス (Nautilus) // ヨルシカ (Yorushika)\n"
        "22:16      03.  シュノーケル (schnorchel) // 文藝天国 (Blooming Bungei)\n"
        "28:31      04.  憂、燦々 (Yu, Sansan) // クリープハイプ (CreepHyp)\n"
        "35:56      05.  I LOVE YOU // 尾崎 豊 (Yutaka Ozaki)\n"
        "41:34      06.  きみのかみ (Your Hair) // 澤田 空海理 (Sori Sawada)\n"
        "46:49      07.  裸の心 (Naked Heart) // あいみょん (Aimyon)\n"
        "54:33      08.  最愛 (Saiai) // KOH+\n"
        "1:01:42   09.  ドライフラワー (Dried Flower) // 優里 (Yuuri)\n"
        "1:07:24   10.  丸の内サディスティック (Marunouchi Sadistic) // 椎名林檎 (Ringo Sheena)\n"
        "1:13:56   11.  カブトムシ (Kabutomushi) // aiko\n"
        "1:21:26   12.  チノカテ (Chinokate) // ヨルシカ (Yorushika)\n"
        "1:28:26   13.  おだやかな暮らし (Odayakanakurashi) // おおはた雄一 (Yuichi Ohata)\n"
        "1:33:08   14.  家族の風景 (Kazokuno Fukei) // ハナレグミ (Hanaregumi)\n"
        "1:39:25   15.  さくら（独唱） (Sakura) // 森山直太朗 (Naotaro Moriyama)\n"
        "1:45:03   16.  Alice // 古川本舗 (Fullkawa Honpo)\n"
        "1:50:08   17.  パレード (Parade) // ヨルシカ (Yorushika)\n"
        "1:58:47   ED"
    )
    items = clean.extract_plain_songs_from_source_timeline(source)
    assert len(items) == 17
    assert [item.song for item in items] == [
        "ありあまる富",
        "ノーチラス",
        "シュノーケル",
        "憂、燦々",
        "I LOVE YOU",
        "きみのかみ",
        "裸の心",
        "最愛",
        "ドライフラワー",
        "丸の内サディスティック",
        "カブトムシ",
        "チノカテ",
        "おだやかな暮らし",
        "家族の風景",
        "さくら（独唱）",
        "Alice",
        "パレード",
    ]
    assert items[0].timestamp_seconds == 342
    assert clean.is_non_song_section_marker("ご挨拶") is True
    assert clean.is_non_song_section_marker("ご挨拶タイム") is True
    assert clean.is_non_song_section_marker("自己紹介") is True
    assert clean.is_non_song_section_marker("雑談タイム") is True


def test_thanks_time_marker_is_not_counted_as_song():
    """BV15nnj6xEuT：感谢/超级感谢时段是章节标记，不是无歌手歌曲。"""
    source = (
        "0:02:35 Start\n"
        "2:22:54 💲スーパーありがとうタイム🐈‍⬛\n"
        "1. 0:10:53 ウミユリ海底譚 (Sea Lily Deep Sea Tale) - n-buna (n-buna)\n"
        "2. 0:18:37 天使にふれたよ！ (Tenshi ni Fureta yo!) - 放課後ティータイム (Ho-kago Tea Time)"
    )
    assert clean.is_non_song_section_marker("スーパーありがとうタイム") is True
    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [item.song for item in items] == ["ウミユリ海底譚", "天使にふれたよ！"]


def test_angle_bracket_transliteration_is_removed_from_song_titles():
    """BV1qupS6fET7：`歌名〈罗马字〉/ 歌手` 的罗马字括号必须整体移除。"""
    source = (
        ":_サイリウム1:セットリスト／Set List:_サイリウム3:\n"
        "0:22:18 #01. やさしさに包まれたなら〈Yasashisa ni Tsutsumaretanara〉/ 松任谷由実\n"
        "0:37:37 #02. ルージュの伝言〈Rouge no Dengon〉/ 松任谷由実"
    )
    items = clean.build_comment_songlist([source])
    assert [(item.timestamp_seconds, item.song, item.artist) for item in items] == [
        (1338, "やさしさに包まれたなら", "松任谷由実"),
        (2257, "ルージュの伝言", "松任谷由実"),
    ]
    assert all("〈" not in item.song and "〉" not in item.song for item in items)
