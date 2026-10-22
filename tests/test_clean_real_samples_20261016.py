
from yt_comment_automation import clean


def test_leading_hyphen_song_title_is_preserved():
    parsed = clean.parse_song_line_after_timestamp("0:11:48 -ERROR / niki")

    assert parsed is not None
    assert parsed.song == "-ERROR"
    assert parsed.artist == "niki"


def test_trailing_hyphen_song_title_is_preserved():
    parsed = clean.parse_song_line_after_timestamp("0:11:11 夕星-ゆうづつ- / RADWIMPS")

    assert parsed is not None
    assert parsed.song == "夕星-ゆうづつ-"
    assert parsed.artist == "RADWIMPS"


def test_spaced_trailing_hyphen_decoration_is_removed():
    parsed = clean.parse_song_line_after_timestamp("0:11:11 夕星-ゆうづつ - / RADWIMPS")

    assert parsed is not None
    assert parsed.song == "夕星-ゆうづつ"
    assert parsed.artist == "RADWIMPS"


def test_generic_emote_stamp_is_not_a_song():
    title = ":_おつらてぃあ::_らてぃあ:"

    assert clean.is_obviously_non_song_text(title)
    assert clean.extract_plain_songs_from_source_timeline(f"1:16:25 {title}") == []
