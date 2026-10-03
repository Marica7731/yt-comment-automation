import json
from pathlib import Path

import pytest

from yt_comment_automation import youtube_action, youtube_cache_sync, yt_fetch


def test_cache_only_reads_action_cache_without_network(tmp_path, monkeypatch):
    video_id = "abcdefghijk"
    cache_dir = tmp_path / "yt_raw"
    cache_dir.mkdir()
    expected = {"id": video_id, "comments": [{"text": "0:01:00 Song"}]}
    (cache_dir / f"{video_id}.info.json").write_text(json.dumps(expected), encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_FETCH_MODE", "cache_only")
    monkeypatch.setattr(
        yt_fetch,
        "_fetch_youtube_innertube_raw",
        lambda *args, **kwargs: pytest.fail("cache_only must not request YouTube"),
    )

    assert yt_fetch.fetch_youtube_raw(video_id, cache_dir=cache_dir) == expected


def test_cache_only_missing_cache_raises_for_pipeline_skip(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_FETCH_MODE", "cache_only")
    with pytest.raises(yt_fetch.YtCacheMissError, match="GitHub Action"):
        yt_fetch.fetch_youtube_raw("abcdefghijk", cache_dir=tmp_path)


def test_action_payload_and_wdc_sync(tmp_path, monkeypatch):
    video_id = "abcdefghijk"
    raw = {"id": video_id, "comments": [{"text": "0:01:00 Song"}]}

    def fake_fetch(*args, **kwargs):
        cache_dir = Path(kwargs["cache_dir"])
        (cache_dir / "fetch_times.json").write_text(json.dumps({video_id: 123.0}))
        return raw

    monkeypatch.setattr(youtube_action.yt_fetch, "fetch_youtube_raw", fake_fetch)
    action_dir = tmp_path / "action"
    payload = youtube_action.run([video_id], action_dir)
    assert payload["results"][video_id] == raw
    assert not payload["failures"]

    data_dir = tmp_path / "data"
    summary = youtube_cache_sync.sync(action_dir / "payload.json", data_dir)
    assert summary["results"] == 1
    saved = json.loads((data_dir / "yt_raw" / f"{video_id}.info.json").read_text())
    assert saved == raw
    assert json.loads((data_dir / "yt_raw" / "fetch_times.json").read_text())[video_id] == 123.0
    assert youtube_cache_sync.is_pending_action(data_dir, video_id)
    youtube_cache_sync.mark_processed(data_dir, video_id)
    assert not youtube_cache_sync.is_pending_action(data_dir, video_id)


def test_action_records_individual_failure(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr(youtube_action.yt_fetch, "fetch_youtube_raw", fail)
    payload = youtube_action.run(["abcdefghijk"], tmp_path / "action")
    assert payload["results"] == {}
    assert payload["failures"][0]["video_id"] == "abcdefghijk"
    assert "blocked" in payload["failures"][0]["error"]
