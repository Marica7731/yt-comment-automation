import json
import time
from pathlib import Path

import pytest

from yt_comment_automation import (
    bili_comment,
    collections,
    pipeline,
    youtube_action,
    youtube_cache_sync,
    youtube_targets,
    yt_fetch,
)
from yt_comment_automation import incremental


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
    (data_dir / "yt_raw").mkdir(parents=True)
    stale = data_dir / "yt_raw" / "stale.info.json"
    stale.write_text("{}", encoding="utf-8")
    summary = youtube_cache_sync.sync(action_dir / "payload.json", data_dir)
    assert summary["results"] == 1
    stale = data_dir / "yt_raw" / "stale.info.json"
    assert not stale.exists()
    saved = json.loads((data_dir / "yt_raw" / f"{video_id}.info.json").read_text())
    assert saved == raw

    assert json.loads((data_dir / "yt_raw" / "fetch_times.json").read_text())[video_id] == 123.0
    assert youtube_cache_sync.is_pending_action(data_dir, video_id)
    youtube_cache_sync.mark_processed(data_dir, video_id)
    assert not youtube_cache_sync.is_pending_action(data_dir, video_id)


def test_action_rejects_transient_empty_snapshot_for_known_video(tmp_path, monkeypatch):
    video_id = "sWdaRFW8mNY"
    description = "⚠️リクエストについて\n\n・リクエストはいつでも大歓迎です"
    comments = [
        {
            "id": "UgylqwP8ceLETK3V6lh4AaABAg",
            "text": "1:53:54の『paranoia』は確立された歌い方がやはりいいなぁと思いました。",
        },
        {
            "id": "UgwaU_vrssEIAabS8VN4AaABAg",
            "text": "💜┈┈セットリスト┈┈🎼\n0:17:33 三日月\n1:53:54 paranoia",
        },
    ]
    nonempty = {
        "id": video_id,
        "description": description,
        "comments": [{"text": item["text"]} for item in comments],
        "comment_entries": comments,
    }
    empty = {
        "id": video_id,
        "description": description,
        "comments": [],
        "comment_entries": [],
    }
    samples = iter([nonempty, empty, nonempty])

    def fake_fetch(*args, **kwargs):
        return next(samples)

    monkeypatch.setattr(youtube_action.yt_fetch, "fetch_youtube_raw", fake_fetch)
    action_dir = tmp_path / "action"
    first = youtube_action.run([video_id], action_dir)
    assert not first["failures"]

    second = youtube_action.run([video_id], action_dir)
    assert video_id not in second["results"]
    assert second["review_candidates"] == []
    assert "empty comment snapshot for previously non-empty video" in (
        second["failures"][0]["error"]
    )

    saved = json.loads((action_dir / "state.json").read_text())
    saved_video = saved["videos"][video_id]
    assert saved_video["comment_count"] == len(comments)
    assert set(saved_video["comments"]) == {item["id"] for item in comments}

    third = youtube_action.run([video_id], action_dir)
    assert not third["failures"]
    assert third["review_candidates"] == []


def test_cache_only_pipeline_preserves_incoming_action_cache(tmp_path, monkeypatch):



    data_dir = tmp_path / "data"
    cache_dir = data_dir / "yt_raw"
    cache_dir.mkdir(parents=True)
    video_id = "abcdefghijk"
    raw_path = cache_dir / f"{video_id}.info.json"
    raw_path.write_text(json.dumps({"id": video_id}), encoding="utf-8")
    video = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1CacheOnly",
        title="cache only",
        part_date="2026-10-19",
        yt_id=video_id,
    )

    monkeypatch.setenv("YOUTUBE_FETCH_MODE", "cache_only")
    monkeypatch.setattr(pipeline.config, "data_dir", lambda: data_dir)
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(pipeline.collections, "fetch_all_collections", lambda: [video])
    monkeypatch.setattr(pipeline.collections, "load_snapshot", lambda: collections.CollectionSnapshot(videos=[video]))
    monkeypatch.setattr(pipeline.collections, "detect_new_videos", lambda current, previous: [video])
    monkeypatch.setattr(pipeline, "load_processed", lambda data_dir: set())
    monkeypatch.setattr(pipeline.review, "deleted_bvids", lambda data_dir=None: set())
    monkeypatch.setattr(pipeline.review, "list_comments", lambda data_dir=None, status=None: [])
    monkeypatch.setattr(pipeline.config, "in_codex_scope", lambda *args, **kwargs: True)
    monkeypatch.setattr(pipeline.config, "ignore_bvids", lambda: set())
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)

    def fake_process(candidate, cache_dir, dry_run):
        assert (cache_dir / f"{candidate.yt_id}.info.json").is_file()
        return pipeline.VideoResult(
            bvid=candidate.bvid,
            yt_id=candidate.yt_id,
            title=candidate.title,
            part_date=candidate.part_date,
            collection=candidate.collection,
            status="dry_run",
        )

    monkeypatch.setattr(pipeline, "process_video", fake_process)
    record = pipeline.run_pipeline(mode="incremental", dry_run=True)

    assert record.total == 1

def test_cache_only_process_video_uses_synced_raw(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    cache_dir = data_dir / "yt_raw"
    cache_dir.mkdir(parents=True)
    video_id = "abcdefghijk"
    (cache_dir / f"{video_id}.info.json").write_text(
        json.dumps({"id": video_id, "comments": [{"text": "hello"}]}),
        encoding="utf-8",
    )
    video = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1CacheOnlyProcess",
        title="cache only process",
        part_date="2026-10-19",
        yt_id=video_id,
    )
    seen = {}

    def fake_fetch(target, **kwargs):
        seen["target"] = target
        seen["cache_dir"] = kwargs.get("cache_dir")
        return json.loads((cache_dir / f"{target}.info.json").read_text())

    monkeypatch.setenv("YOUTUBE_FETCH_MODE", "cache_only")
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(pipeline.bili_comment, "find_own_comment", lambda bvid, cookies: None)
    monkeypatch.setattr(
        pipeline, "_fetch_bili_video_info", lambda bvid, cookies: (video_id, "", [])
    )
    monkeypatch.setattr(pipeline.yt_fetch, "fetch_youtube_raw", fake_fetch)
    monkeypatch.setattr(pipeline.config, "ignore_bvids", lambda: set())

    result = pipeline.process_video(video, cache_dir, dry_run=True)

    assert seen == {"target": video_id, "cache_dir": cache_dir}
    assert result.status == "skipped_no_songs"


def test_action_records_individual_failure(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("blocked")

    monkeypatch.setattr(youtube_action.yt_fetch, "fetch_youtube_raw", fail)
    payload = youtube_action.run(["abcdefghijk"], tmp_path / "action")
    assert payload["results"] == {}
    assert payload["failures"][0]["video_id"] == "abcdefghijk"
    assert "blocked" in payload["failures"][0]["error"]


def test_action_failure_for_matches_real_rate_limit_payload(tmp_path):
    data_dir = tmp_path / "data"
    audit_dir = data_dir / "incremental_audit"
    audit_dir.mkdir(parents=True)
    failures = [
        {
            "video_id": video_id,
            "error": "HTTPError: HTTP Error 429: Too Many Requests",
        }
        for video_id in (
            "hIXYLxmCsP4",
            "sWdaRFW8mNY",
            "mIWnyXUFZjQ",
            "IbP39N0kArg",
            "Q23YjKHdBC0",
        )
    ]
    (audit_dir / "latest.json").write_text(
        json.dumps({"results": {}, "failures": failures}),
        encoding="utf-8",
    )

    assert youtube_cache_sync.action_failure_for(data_dir, "hIXYLxmCsP4") == (
        "HTTPError: HTTP Error 429: Too Many Requests"
    )
    assert youtube_cache_sync.action_failure_for(data_dir, "notlisted00") == ""


def test_wdc_action_runner_treats_synced_fetch_failures_as_orchestration_success(
    monkeypatch, capsys
):
    from dev import wdc_run_youtube_action as runner

    monkeypatch.setattr(
        runner,
        "run",
        lambda *args, **kwargs: {
            "fetched": 0,
            "failures": [{'video_id': 'hIXYLxmCsP4', 'error': 'HTTP 429'}],
        },
    )

    assert runner.main(["--timeout", "1", "--poll-interval", "1"]) == 0
    assert "HTTP 429" in capsys.readouterr().out


def _cache_miss_video(video_id: str, bvid: str) -> collections.CollectionVideo:
    return collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid=bvid,
        title="rate limited target",
        part_date="2026-10-20",
        yt_id=video_id,
    )


def _prepare_cache_miss_process(monkeypatch) -> None:
    monkeypatch.setattr(pipeline.config, "ignore_bvids", lambda: set())
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(pipeline.bili_comment, "find_own_comment", lambda bvid, cookies: None)
    monkeypatch.setattr(
        pipeline,
        "_fetch_bili_video_info",
        lambda bvid, cookies: (None, "", []),
    )

    def cache_miss(*args, **kwargs):
        raise yt_fetch.YtCacheMissError("GitHub Action 缓存缺失")

    monkeypatch.setattr(pipeline.yt_fetch, "fetch_youtube_raw", cache_miss)
    pipeline._yt_fetch_failure_notified.clear()


def test_action_429_cache_miss_is_skipped_with_one_rate_limit_notification(
    tmp_path, monkeypatch
):
    data_dir = tmp_path / "data"
    audit_dir = data_dir / "incremental_audit"
    audit_dir.mkdir(parents=True)
    targets = [
        ("hIXYLxmCsP4", "BV1Rate429A"),
        ("sWdaRFW8mNY", "BV1Rate429B"),
    ]
    (audit_dir / "latest.json").write_text(
        json.dumps(
            {
                "results": {},
                "failures": [
                    {
                        "video_id": video_id,
                        "error": "HTTPError: HTTP Error 429: Too Many Requests",
                    }
                    for video_id, _ in targets
                ],
            }
        ),
        encoding="utf-8",
    )
    _prepare_cache_miss_process(monkeypatch)
    sent = []
    monkeypatch.setattr(pipeline.notify, "git_summary", lambda: "abc1234")
    monkeypatch.setattr(
        pipeline.notify,
        "build_yt_rate_limit_brief",
        lambda *args, **kwargs: "rate-limit-brief",
    )
    monkeypatch.setattr(
        pipeline.notify,
        "send_feishu_message",
        lambda brief: sent.append(brief) or (True, "ok"),
    )

    results = [
        pipeline.process_video(
            _cache_miss_video(video_id, bvid),
            data_dir / "yt_raw",
            dry_run=False,
        )
        for video_id, bvid in targets
    ]

    assert [result.status for result in results] == [
        "skipped_action_fetch_failed",
        "skipped_action_fetch_failed",
    ]
    assert all("429" in result.error for result in results)
    assert sent == ["rate-limit-brief"]


def test_unexplained_cache_miss_remains_production_error(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "incremental_audit").mkdir(parents=True)
    (data_dir / "incremental_audit" / "latest.json").write_text(
        json.dumps({"results": {}, "failures": []}),
        encoding="utf-8",
    )
    _prepare_cache_miss_process(monkeypatch)

    result = pipeline.process_video(
        _cache_miss_video("mIWnyXUFZjQ", "BV1Unexplained"),
        data_dir / "yt_raw",
        dry_run=False,
    )

    assert result.status == "error_cache_miss"
    assert "GitHub Action 缓存缺失" in result.error


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


@pytest.mark.parametrize("review_status", ["deleted", "pending"])
def test_recheck_video_returns_to_due_targets(tmp_path, monkeypatch, review_status):
    from datetime import date

    video = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1Deleted",
        title="deleted",
        part_date=date.today().isoformat(),
        yt_id="abcdefghijk",
    )
    snapshot = collections.CollectionSnapshot(videos=[video])
    raw_dir = tmp_path / "yt_raw"
    raw_dir.mkdir()
    (raw_dir / "fetch_times.json").write_text(
        json.dumps({"abcdefghijk": time.time()}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        youtube_targets.collections,
        "load_snapshot",
        lambda path=None: snapshot,
    )
    monkeypatch.setattr(
        youtube_targets.pipeline,
        "load_processed",
        lambda data_dir: {"BV1Deleted", "BV1Applied"},
    )
    monkeypatch.setattr(
        youtube_targets.review,
        "deleted_bvids",
        lambda data_dir=None: (
            {"BV1Deleted"} if review_status == "deleted" else set()
        ),
    )
    monkeypatch.setattr(
        youtube_targets.review,
        "list_comments",
        lambda data_dir=None, status=None: (
            [{"bvid": "BV1Deleted"}] if status == review_status else []
        ),
    )
    monkeypatch.setattr(
        youtube_targets.pipeline,
        "load_upgrade_targets",
        lambda data_dir: {},
    )
    monkeypatch.setattr(
        youtube_targets.config,
        "in_codex_scope",
        lambda *args, **kwargs: True,
    )

    assert youtube_targets.due_targets(tmp_path) == ["abcdefghijk"]


@pytest.mark.parametrize("review_status", ["deleted", "pending"])
def test_recheck_video_is_processed_without_auto_repost(
    tmp_path, monkeypatch, review_status
):
    video = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1Deleted",
        title="deleted",
        part_date="2026-10-09",
        yt_id="abcdefghijk",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    processed = []

    monkeypatch.setattr(pipeline.config, "data_dir", lambda: data_dir)
    monkeypatch.setattr(pipeline, "_remove_content_caches", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(
        pipeline.collections,
        "fetch_all_collections",
        lambda: [video],
    )
    monkeypatch.setattr(
        pipeline.collections,
        "load_snapshot",
        lambda path=None: collections.CollectionSnapshot(videos=[video]),
    )
    monkeypatch.setattr(
        pipeline.collections,
        "detect_new_videos",
        lambda current, previous: [],
    )
    monkeypatch.setattr(pipeline, "load_processed", lambda data_dir: {"BV1Deleted"})
    monkeypatch.setattr(
        pipeline.review,
        "deleted_bvids",
        lambda data_dir=None: (
            {"BV1Deleted"} if review_status == "deleted" else set()
        ),
    )
    monkeypatch.setattr(
        pipeline.review,
        "list_comments",
        lambda data_dir=None, status=None: (
            [{"bvid": "BV1Deleted"}] if status == review_status else []
        ),
    )
    monkeypatch.setattr(
        pipeline.config,
        "in_codex_scope",
        lambda *args, **kwargs: True,
    )

    def fake_process(candidate, cache_dir, dry_run):
        processed.append((candidate.bvid, dry_run))
        return pipeline.VideoResult(
            bvid=candidate.bvid,
            yt_id=candidate.yt_id,
            title=candidate.title,
            part_date=candidate.part_date,
            collection=candidate.collection,
            status="needs_codex_review",
        )

    monkeypatch.setattr(pipeline, "process_video", fake_process)
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)

    record = pipeline.run_pipeline(mode="incremental", dry_run=True)

    assert record.total == 1
    assert processed == [("BV1Deleted", True)]


def _raw_with_comments(*comments):
    return {
        "description": "",
        "comment_entries": [
            {"id": f"c{index}", "text": text}
            for index, text in enumerate(comments, start=1)
        ],
    }


def test_new_video_requires_timestamped_comment_increment():
    state = incremental.empty_state()
    next_state, changes = incremental.update_state(
        state,
        {"abcdefghijk": _raw_with_comments("0:01:00 Song A - Artist A")},
    )

    change = changes["abcdefghijk"]
    assert change["new_video"] is True
    assert change["timestamp_increment"] is True
    assert change["review_required"] is True
    assert next_state["videos"]["abcdefghijk"]["comments"]["c1"]["has_timestamp"]


def test_new_video_without_timestamp_is_not_reviewed():
    _, changes = incremental.update_state(
        incremental.empty_state(),
        {"abcdefghijk": _raw_with_comments("thanks for the stream")},
    )

    assert changes["abcdefghijk"]["review_required"] is False


def test_edited_timestamped_comment_triggers_review():
    state, _ = incremental.update_state(
        incremental.empty_state(),
        {"abcdefghijk": _raw_with_comments("0:01:00 Song A - Artist A")},
    )
    _, changes = incremental.update_state(
        state,
        {"abcdefghijk": _raw_with_comments("0:01:00 Song A - Artist B")},
    )

    change = changes["abcdefghijk"]
    assert "timestamped_comment_edited" in change["review_reasons"]
    assert change["review_required"] is True


def test_comment_becoming_timestamped_triggers_review():
    state, _ = incremental.update_state(
        incremental.empty_state(),
        {"abcdefghijk": _raw_with_comments("Song A - Artist A")},
    )
    _, changes = incremental.update_state(
        state,
        {"abcdefghijk": _raw_with_comments("0:01:00 Song A - Artist A")},
    )

    change = changes["abcdefghijk"]
    assert "comment_became_timestamped" in change["review_reasons"]
    assert change["review_required"] is True


def test_whole_comment_section_replacement_triggers_review():
    state, _ = incremental.update_state(
        incremental.empty_state(),
        {
            "abcdefghijk": _raw_with_comments(
                "old one", "old two", "old three", "old four"
            )
        },
    )
    _, changes = incremental.update_state(
        state,
        {
            "abcdefghijk": _raw_with_comments(
                "new one", "new two", "new three", "new four"
            )
        },
    )

    change = changes["abcdefghijk"]
    assert change["whole_section_changed"] is True
    assert "comment_section_changed" in change["review_reasons"]
    assert change["review_required"] is True
