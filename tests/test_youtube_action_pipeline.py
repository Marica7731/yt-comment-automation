import json
from pathlib import Path

import pytest

from yt_comment_automation import (
    bili_comment,
    collections,
    pipeline,
    youtube_action,
    youtube_cache_sync,
    yt_fetch,
)


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


def test_already_sufficient_comment_consumes_action_pending(tmp_path, monkeypatch):
    video_id = "abcdefghijk"
    data_dir = tmp_path / "data"
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(
        json.dumps(
            {
                "results": {video_id: {"id": video_id, "comments": []}},
                "failures": [],
                "fetch_times.json": {video_id: 123.0},
                "yt_comment_ids.json": {},
            }
        ),
        encoding="utf-8",
    )
    youtube_cache_sync.sync(payload_path, data_dir)
    assert youtube_cache_sync.is_pending_action(data_dir, video_id)

    video = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1ActionDone",
        title="action done",
        part_date="2026-10-01",
        yt_id=video_id,
    )
    existing = bili_comment.BiliComment(
        rpid="315000000001",
        mid="3546597260528367",
        uname="owner",
        ctime=0,
        like=0,
        message=("0:01:00 01. Song A - Artist A\n0:02:00 02. Song B - Artist B\n0:03:00 03. Song C - Artist C"),
    )
    monkeypatch.setattr(pipeline.config, "ignore_bvids", lambda: set())
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(pipeline.bili_comment, "find_own_comment", lambda bvid, cookies: existing)

    result = pipeline.process_video(video, data_dir / "yt_raw", dry_run=False)

    assert result.status == "already_posted"
    assert not youtube_cache_sync.is_pending_action(data_dir, video_id)
    assert not (data_dir / "yt_raw" / "action_pending_ids.json").exists()
