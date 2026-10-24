import json
from datetime import date

from yt_comment_automation import (
    collections,
    pipeline,
    youtube_cache_sync,
    youtube_targets,
)


def test_cache_only_defers_target_added_after_action_dispatch(tmp_path, monkeypatch):
    dispatched_id = "TkhHHPvGeTM"
    late_id = "R0H2LWuk4nM"
    dispatched = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1cVHP6iE1J",
        title="dispatched",
        part_date=date.today().isoformat(),
        yt_id=dispatched_id,
    )
    late = collections.CollectionVideo(
        collection="直播",
        section="歌枠",
        bvid="BV1AgHP6BEgh",
        title="added after dispatch",
        part_date=date.today().isoformat(),
        yt_id=late_id,
    )
    snapshot = collections.CollectionSnapshot(videos=[dispatched, late])
    data_dir = tmp_path / "data"
    cache_dir = data_dir / "yt_raw"
    cache_dir.mkdir(parents=True)
    (cache_dir / f"{dispatched_id}.info.json").write_text(
        json.dumps({"id": dispatched_id}),
        encoding="utf-8",
    )
    audit_dir = data_dir / "incremental_audit"
    audit_dir.mkdir()
    (audit_dir / "latest.json").write_text(
        json.dumps({"results": {dispatched_id: {"id": dispatched_id}}, "failures": []}),
        encoding="utf-8",
    )
    processed = []

    monkeypatch.setenv("YOUTUBE_FETCH_MODE", "cache_only")
    monkeypatch.setattr(pipeline.config, "data_dir", lambda: data_dir)
    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(
        pipeline.collections,
        "fetch_all_collections",
        lambda: [dispatched, late],
    )
    monkeypatch.setattr(pipeline.collections, "load_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        pipeline.collections,
        "detect_new_videos",
        lambda current, previous: [dispatched, late],
    )
    monkeypatch.setattr(pipeline, "load_processed", lambda data_dir: set())
    monkeypatch.setattr(pipeline.review, "deleted_bvids", lambda data_dir=None: set())
    monkeypatch.setattr(
        pipeline.review,
        "list_comments",
        lambda data_dir=None, status=None: [],
    )
    monkeypatch.setattr(pipeline.config, "in_codex_scope", lambda *args, **kwargs: True)
    monkeypatch.setattr(pipeline.config, "ignore_bvids", lambda: set())
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)

    def fake_process(candidate, cache_dir, dry_run):
        processed.append(candidate.yt_id)
        return pipeline.VideoResult(
            bvid=candidate.bvid,
            yt_id=candidate.yt_id,
            title=candidate.title,
            part_date=candidate.part_date,
            collection=candidate.collection,
            status="needs_codex_review",
        )

    monkeypatch.setattr(pipeline, "process_video", fake_process)
    record = pipeline.run_pipeline(mode="incremental", dry_run=True)

    assert record.total == 1
    assert processed == [dispatched_id]
    assert youtube_cache_sync.action_round_targets(data_dir) == {dispatched_id}

    monkeypatch.setattr(
        youtube_targets.collections,
        "load_snapshot",
        lambda path=None: snapshot,
    )
    monkeypatch.setattr(
        youtube_targets.pipeline,
        "load_processed",
        lambda data_dir: set(),
    )
    monkeypatch.setattr(
        youtube_targets.pipeline,
        "load_upgrade_targets",
        lambda data_dir: {},
    )
    monkeypatch.setattr(
        youtube_targets.pipeline,
        "_is_new_video",
        lambda part_date: True,
    )
    assert late_id in youtube_targets.due_targets(data_dir)
