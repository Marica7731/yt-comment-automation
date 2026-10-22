from yt_comment_automation import clean


def test_oxr_znmnh3q_event_hours_are_not_songs():
    """OXr_znmnh3Q: event admission/start clock times must not become songs."""
    description = (
        "3rdワンマンライブ『未知』\n"
        "https://react-event.zaiko.io/ja/e/suu-3rd-onemanshow\n"
        "開場 18:15 開演 19:00\n\n"
        "主催ナイトイベント『𝒚𝒐𝒖'𝒓𝒆 𝒏𝒊𝒈𝒉𝒕 vol.2』\n"
        "https://react-event.zaiko.io/ja/e/suu-youre-night-vol2\n"
        "開場 24:00 開演 25:00\n\n"
        "00:00:00 START"
    )

    assert clean.is_obviously_non_song_text("開場 18:15 開演 19:00") is True
    assert clean.is_obviously_non_song_text("開演") is True
    assert clean.extract_plain_songs_from_source_timeline(description) == []
    assert clean.build_comment_songlist_ranked([], description) == []
