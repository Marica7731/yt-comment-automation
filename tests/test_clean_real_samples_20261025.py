"""2026-10-25 真实样例：结构化歌单中的あくび计数器不是歌曲。"""

from yt_comment_automation import clean


def test_bv1snht6tebx_repeated_numbered_yawn_markers_are_not_songs():
    source = """セトリ＆タイムスタンプ
2:24 声入り
4:30 1. 気まぐれロマンティック / いきものがかり
8:41 あくび1
9:00 2. Love so sweet / 嵐
32:47 あくび2
35:19 6. 星座になれたら / 結束バンド
39:36 あくび3
41:48 7. 君はロックを聴かない / あいみょん
2:00:58 あくび6
2:07:47 20. ベテルギウス / 優里
3:37:36 あくび16
4:04:32 36. 晩餐歌 / tuki.
4:13:29 あくび18
"""

    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [item.song for item in items] == [
        "声入り",
        "気まぐれロマンティック",
        "Love so sweet",
        "星座になれたら",
        "君はロックを聴かない",
        "ベテルギウス",
        "晩餐歌",
    ]


def test_bare_akubi_title_is_not_globally_filtered():
    items = clean.extract_plain_songs_from_source_timeline("0:20:29 あくび")
    assert [item.song for item in items] == ["あくび"]
