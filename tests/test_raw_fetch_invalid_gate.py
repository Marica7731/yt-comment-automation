from pathlib import Path

import pytest

from yt_comment_automation import collections, pipeline, review, review_cli


def test_mark_raw_fetch_invalid_updates_only_unpublished_queue(tmp_path: Path):
    payload = {
        "bvid": "BV1RawInvalid",
        "yt_id": "rawinvalid",
        "title": "raw invalid",
        "draft_messages": ["chat"],
        "source_text": "old audit only",
    }
    review.queue_comment(payload, tmp_path)

    item = review.mark_raw_fetch_invalid(
        payload["bvid"],
        "raw_fetch_invalid: empty",
        data_dir=tmp_path,
        started_at="2026-10-09T11:47:08+00:00",
        finished_at="2026-10-09T11:47:13+00:00",
    )

    assert item["status"] == "failed"
    assert item["result"] == "raw_fetch_invalid"
    assert item["raw_fetch"] == {
        "started_at": "2026-10-09T11:47:08+00:00",
        "finished_at": "2026-10-09T11:47:13+00:00",
        "cache_used": False,
        "force": True,
    }
    assert review.load_comment(payload["bvid"], tmp_path)["status"] == "failed"

    review.approve_comment(payload["bvid"], ["0:01:00 01. Song - Artist"], tmp_path)
    with pytest.raises(RuntimeError, match="不允许标记"):
        review.mark_raw_fetch_invalid(payload["bvid"], "late invalid", data_dir=tmp_path)


def test_review_cli_marks_raw_fetch_invalid(monkeypatch, capsys):
    seen = {}

    def fake_mark(bvid, reason, data_dir=None, started_at="", finished_at=""):
        seen.update(
            bvid=bvid,
            reason=reason,
            started_at=started_at,
            finished_at=finished_at,
        )
        return {
            "bvid": bvid,
            "status": "failed",
            "result": "raw_fetch_invalid",
            "error": reason,
        }

    monkeypatch.setattr(review, "mark_raw_fetch_invalid", fake_mark)
    code = review_cli.main(
        [
            "mark-raw-fetch-invalid",
            "--bvid",
            "BV1CliInvalid",
            "--reason",
            "raw_fetch_invalid: empty",
            "--started-at",
            "start",
            "--finished-at",
            "finish",
        ]
    )

    assert code == 0
    assert seen == {
        "bvid": "BV1CliInvalid",
        "reason": "raw_fetch_invalid: empty",
        "started_at": "start",
        "finished_at": "finish",
    }
    assert '"result": "raw_fetch_invalid"' in capsys.readouterr().out


def test_pipeline_marks_existing_queue_failed_on_empty_raw(tmp_path: Path, monkeypatch):
    video = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1PipelineRawInvalid",
        title="empty raw",
        part_date="2026-10-09",
        yt_id="pipelineemptyraw",
    )
    cache_dir = tmp_path / "yt_raw"
    cache_dir.mkdir()
    review.queue_comment(
        {
            "bvid": video.bvid,
            "yt_id": video.yt_id,
            "title": video.title,
            "draft_messages": [],
            "source_text": "old audit only",
        },
        tmp_path,
    )
    monkeypatch.setattr(pipeline.config, "ignore_bvids", lambda: set())
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(pipeline.bili_comment, "find_own_comment", lambda bvid, cookies: None)
    monkeypatch.setattr(
        pipeline,
        "_fetch_bili_video_info",
        lambda bvid, cookie_map=None: (video.yt_id, f"https://youtu.be/{video.yt_id}", []),
    )
    monkeypatch.setattr(
        pipeline.yt_fetch,
        "fetch_youtube_raw",
        lambda *args, **kwargs: {"comments": [], "description": ""},
    )

    result = pipeline.process_video(video, cache_dir, dry_run=False)

    assert result.status == "raw_fetch_invalid"
    item = review.load_comment(video.bvid, tmp_path)
    assert item["status"] == "failed"
    assert item["result"] == "raw_fetch_invalid"
    assert item["raw_fetch"]["cache_used"] is False
