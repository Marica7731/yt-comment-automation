from yt_comment_automation import youtube_cache_sync


def test_mark_processed_removes_empty_pending_file(tmp_path):
    pending = tmp_path / "yt_raw" / "action_pending_ids.json"
    pending.parent.mkdir(parents=True)
    pending.write_text("[]", encoding="utf-8")

    youtube_cache_sync.mark_processed(tmp_path, "unknown")

    assert not pending.exists()
