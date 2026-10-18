from yt_comment_automation import clean


def test_ririsya_20261018_description_setlist_excludes_next_segment_and_merges_artist():
    source = (
        "0:00:00  sssSTART\n"
        "1:30　My Dearest /Supercell\n"
        "7:15    ANIMA/ReoNa\n"
        "16:12  Departures ～あなたにおくるアイの歌～/\n"
        "EGOIST \n"
        "25:30  NEXT歌枠紹介 陽茅ほのかちゃん\n"
        "26:35  声の在処/凛々咲"
    )

    items = clean.extract_plain_songs_from_source_timeline(source)
    assert [(item.song, item.artist) for item in items] == [
        ("My Dearest", "Supercell"),
        ("ANIMA", "ReoNa"),
        ("Departures ～あなたにおくるアイの歌～", "EGOIST"),
        ("声の在処", "凛々咲"),
    ]
    assert clean.is_obviously_non_song_text("NEXT歌枠紹介 陽茅ほのかちゃん") is True
