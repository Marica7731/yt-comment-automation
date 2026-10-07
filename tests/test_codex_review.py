"""Codex 审核队列的持久化、批准和执行测试。"""
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from yt_comment_automation import like_review, review, review_cli
from yt_comment_automation import pipeline


def test_like_review_merge_preserves_approval(tmp_path: Path):
    path = tmp_path / "like_review.json"
    like_review.merge_candidates(
        [{"oid": 1, "rpid": 10, "content": "hello"}, {"oid": 1, "rpid": 11, "content": "world"}],
        path,
    )
    like_review.approve(["10"], path, note="ok")
    like_review.merge_candidates([{"oid": 1, "rpid": 10, "content": "hello updated"}, {"oid": 1, "rpid": 12}], path)

    payload = like_review.load_review(path)
    by_rpid = {str(item["rpid"]): item for item in payload["candidates"]}
    assert by_rpid["10"]["status"] == "approved"
    assert by_rpid["10"]["content"] == "hello updated"
    assert by_rpid["11"]["status"] == "pending"
    assert by_rpid["12"]["status"] == "pending"


def test_like_review_apply_checks_state_before_action(tmp_path: Path):
    path = tmp_path / "like_review.json"
    liked: set[str] = set()
    saved: list[int] = []
    sent: list[tuple[int, int]] = []

    like_review.merge_candidates([{"oid": 7, "rpid": 77, "content": "ok"}], path)
    like_review.approve(["77"], path)

    result = like_review.apply_approved(
        lambda oid, rpid: False,
        lambda oid, rpid: (sent.append((oid, rpid)) or {"code": 0}),
        path,
        liked_set=liked,
        save_liked_set=lambda: saved.append(len(liked)),
        sleep=lambda _: None,
    )

    assert result["liked"] == 1
    assert result["failed"] == 0
    assert sent == [(7, 77)]
    assert liked == {"77"}
    assert saved == [1]
    assert like_review.load_review(path)["candidates"][0]["status"] == "applied"


def test_like_review_unavailable_state_never_posts(tmp_path: Path):
    path = tmp_path / "like_review.json"
    sent = []

    like_review.merge_candidates([{"oid": 7, "rpid": 78, "content": "ok"}], path)
    like_review.approve(["78"], path)
    result = like_review.apply_approved(
        lambda oid, rpid: None,
        lambda oid, rpid: sent.append((oid, rpid)) or {"code": 0},
        path,
        sleep=lambda _: None,
    )

    assert result["failed"] == 1
    assert sent == []
    assert like_review.load_review(path)["candidates"][0]["status"] == "failed"


def test_like_apply_rejects_stale_list_without_action(tmp_path: Path):
    path = tmp_path / "like_review.json"
    stale_at = (datetime.now(timezone.utc) - timedelta(seconds=181)).strftime("%Y-%m-%dT%H:%M:%S%z")
    like_review.merge_candidates(
        [{"oid": 9, "rpid": 90, "content": "fresh?", "queued_at": stale_at}], path
    )
    like_review.approve(["90"], path)
    sent = []
    resolved = []

    result = like_review.apply_approved(
        lambda oid, rpid: (resolved.append(rpid) or False),
        lambda oid, rpid: (sent.append(rpid) or {"code": 0}),
        path,
        sleep=lambda _: None,
    )

    assert result["liked"] == 0
    assert result["failed"] == 1
    assert result["stale"] == ["90"]
    assert resolved == []
    assert sent == []
    item = like_review.load_review(path)["candidates"][0]
    assert item["status"] == "failed"
    assert item["result"] == "stale_list"
    assert "列表已过期" in item["error"]


def test_like_approval_refreshes_batch_cap(tmp_path: Path):
    path = tmp_path / "like_review.json"
    like_review.merge_candidates(
        [{"oid": 10, "rpid": 100, "content": "a"}, {"oid": 11, "rpid": 101, "content": "b"}], path
    )
    payload = like_review.approve(["100"], path, max_count=1)
    payload = like_review.approve(["101"], path)
    assert payload["max_count"] == 2
    result = like_review.apply_approved(
        lambda oid, rpid: False,
        lambda oid, rpid: {"code": 0},
        path,
        sleep=lambda _: None,
    )
    assert result["liked"] == 2
    assert result["failed"] == 0


def test_comment_review_queue_does_not_overwrite_approved(tmp_path: Path):

    payload = {
        "bvid": "BV1Review",
        "yt_id": "yt",
        "title": "title",
        "draft_messages": ["0:01:00 01. A - B"],
        "draft_song_count": 1,
        "source_text": "raw",
    }
    path = review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1Review", ["0:01:00 01. A - B"], tmp_path)
    review.queue_comment({**payload, "draft_messages": ["changed"], "source_text": "changed"}, tmp_path)

    item = review.load_comment("BV1Review", tmp_path)
    assert item["status"] == "approved"
    assert item["approved_messages"] == ["0:01:00 01. A - B"]
    assert item["song_count"] == 1
    assert item["draft_messages"] == ["0:01:00 01. A - B"]
    assert path.is_file()


def test_publish_batches_merge_single_page_messages():
    messages = [
        "01:37 01. A - X",
        "04:09 02. B - Y",
        "08:55 03. C - Z",
    ]
    grouped = review._group_messages_by_pages(messages, [{"page": 1, "duration": 1891}])
    assert grouped == [chr(10).join(messages)]


def test_publish_batches_keep_existing_multi_page_comments():
    messages = ["P1\n0:01 01. A", "P2\n10:00:01 02. B"]
    pages = [{"page": 1, "duration": 36000}, {"page": 2, "duration": 600}]
    assert review._group_messages_by_pages(messages, pages) == messages


def test_publish_batches_split_flat_messages_by_page_duration():
    messages = ["0:01 01. A", "10:00:01 02. B"]
    pages = [{"page": 1, "duration": 36000}, {"page": 2, "duration": 600}]
    grouped = review._group_messages_by_pages(messages, pages)
    assert grouped == ["P1\n0:01 01. A", "P2\n10:00:01 02. B"]


def test_publish_batches_refuse_when_duration_missing(monkeypatch):
    monkeypatch.setattr(review, "_fetch_video_pages", lambda bvid, cookies: [])
    try:
        review._normalize_publish_batches("BV1NoDuration", ["0:01 A", "0:02 B"], {})
    except RuntimeError as err:
        assert "拒绝发布多条主评论" in str(err)
    else:
        raise AssertionError("缺少时长时应拒绝发布")


def test_review_cli_apply_exception_sends_detailed_failure(monkeypatch):
    item = {
        "bvid": "BV1ApplyFail",
        "yt_id": "yt-fail",
        "title": "失败测试",
        "collection": "测试",
        "status": "approved",
        "source_text": "0:01 A",
        "source_lines": "0:01 A",
        "draft_messages": ["0:01 01. A - B"],
        "approved_messages": ["0:01 01. A - B"],
        "note": "审核通过",
        "rpids": [],
        "segments": 0,
        "failures": [],
    }
    sent = []

    def fail_apply(bvid, dry_run=False):
        raise RuntimeError("发布批次校验失败: 拒绝发布多条主评论")

    monkeypatch.setattr(review, "load_comment", lambda bvid, data_dir=None: item)
    monkeypatch.setattr(review, "apply_comment", fail_apply)
    monkeypatch.setattr(
        review.notify,
        "send_feishu_message",
        lambda brief: sent.append(brief) or (True, "ok"),
    )

    with pytest.raises(RuntimeError, match="发布批次校验失败"):
        review_cli.main(["apply", "--bvid", "BV1ApplyFail"])

    assert len(sent) == 1
    brief = sent[0]
    assert "发布批次校验失败" in brief
    assert "yt_comment_automation/review_cli.py" not in brief
    assert "review_cli apply --bvid BV1ApplyFail" not in brief
    assert "rpids：[]" in brief
    assert "segments：" not in brief
    assert "failures：" not in brief
    assert "失败详情：发布批次校验失败" not in brief


def test_codex_review_reaches_queue_before_local_gate(tmp_path: Path, monkeypatch):
    """简介只有分钟级时间戳时也不能在 Codex 模式提前丢弃来源。"""
    source = "01 1:00 A\n02 2:00 B"
    video = type("Video", (), {"bvid": "BV1Gate", "yt_id": "yt-gate", "title": "t", "part_date": "2026-10-01", "collection": "c", "section": "s"})()
    queued = []

    monkeypatch.setattr(pipeline.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(pipeline.bili_comment, "find_own_comment", lambda bvid, cookies: None)
    monkeypatch.setattr(pipeline, "_fetch_bili_video_info", lambda bvid, cookie_map=None: ("yt-gate", source, []))
    monkeypatch.setattr(pipeline, "_refetch_gate", lambda cache_dir, yt_id, part_date: (0, 0))
    monkeypatch.setattr(pipeline.yt_fetch, "fetch_youtube_raw", lambda *args, **kwargs: {"comments": [], "description": source})
    monkeypatch.setattr(pipeline, "raw_has_timestamp_songlist", lambda raw: False)
    monkeypatch.setattr(pipeline.review, "queue_comment", lambda payload, data_dir: (queued.append(payload) or tmp_path / "queued.json"))

    result = pipeline.process_video(video, tmp_path, dry_run=False)

    assert result.status == "needs_codex_review"
    assert queued and queued[0]["source_text"] == source

def test_comment_apply_marks_processed_and_verifies(tmp_path: Path, monkeypatch):
    payload = {
        "bvid": "BV1Apply",
        "yt_id": "yt",
        "title": "title",
        "draft_messages": ["0:01:00 01. A - B"],
        "draft_song_count": 1,
        "source_text": "raw",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1Apply", payload["draft_messages"], tmp_path)

    class Own:
        def __init__(self, message):
            self.message = message
            self.rpid = "r1"
            self.mid = "3546597260528367"

    monkeypatch.setattr(review.bili_comment, "load_cookie_map", lambda: {"bili_jct": "csrf"})
    monkeypatch.setattr(
        review.bili_comment,
        "post_comment_with_replies",
        lambda bvid, message, cookies: [{"code": 0, "data": {"rpid": "r1"}}],
    )
    monkeypatch.setattr(
        review.bili_comment,
        "find_own_comments",
        lambda bvid, cookies: [Own(payload["draft_messages"][0])],
    )
    success_kwargs = {}

    def capture_success(**kwargs):
        success_kwargs.update(kwargs)
        return "brief"

    monkeypatch.setattr(review.notify, "build_success_brief", capture_success)
    monkeypatch.setattr(review.notify, "send_feishu_message", lambda brief: (True, "ok"))

    item = review.apply_comment("BV1Apply", tmp_path)

    assert item["status"] == "applied"
    assert item["verification"]["ok"] is True
    assert "BV1Apply" in (tmp_path / "processed.json").read_text(encoding="utf-8")
    assert "yt_comment_automation/review.py" in success_kwargs["files"]
    assert any("review_cli apply --bvid BV1Apply" in x for x in success_kwargs["tests"])
    assert success_kwargs["verification"]["ok"] is True
    assert success_kwargs["rpids"] == ["r1"]
    assert success_kwargs["segments"] == 1
    assert success_kwargs["song_count"] == 1
    assert success_kwargs["failures"] == []

def test_verify_own_comments_normalizes_bilibili_html_entities(monkeypatch):
    class Own:
        def __init__(self, message):
            self.message = message

    expected = '0:01:00 01. Don\'t say "lazy" - 桜高軽音部'
    encoded = "0:01:00 01. Don&#39;t say &#34;lazy&#34; - 桜高軽音部"
    monkeypatch.setattr(review.bili_comment, "find_own_comments", lambda bvid, cookies: [Own(encoded)])

    ok, detail = review.verify_own_comments("BV1Html", [expected], {})

    assert ok is True
    assert "回读通过" in detail


def test_verify_own_comments_normalizes_bilibili_fullwidth_brackets(monkeypatch):
    class Own:
        def __init__(self, message):
            self.message = message

    expected = "0:01:00 01. LEveL - SawanoHiroyuki[nZk]:Aimer"
    rendered = "0:01:00 01. LEveL - SawanoHiroyuki【nZk】:Aimer"
    monkeypatch.setattr(review.bili_comment, "find_own_comments", lambda bvid, cookies: [Own(rendered)])

    ok, detail = review.verify_own_comments("BV1Bracket", [expected], {})

    assert ok is True
    assert "回读通过" in detail


def test_reverify_applied_without_republish(tmp_path: Path, monkeypatch):
    payload = {
        "bvid": "BV1Reverify",
        "yt_id": "yt-reverify",
        "title": "reverify",
        "draft_messages": ["0:01:00 01. A - B"],
        "draft_song_count": 1,
        "source_text": "0:01:00 A / B",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1Reverify", payload["draft_messages"], tmp_path)
    item = review.load_comment("BV1Reverify", tmp_path)
    item.update(
        {
            "status": "applied_unverified",
            "rpids": ["r-reverify"],
            "verification": {"ok": False, "detail": "回读缺失", "checked_at": "old"},
        }
    )
    review._write_json(review.review_dir(tmp_path) / "BV1Reverify.json", item)

    class Own:
        message = payload["draft_messages"][0]

    publish_calls = []
    monkeypatch.setattr(review.bili_comment, "load_cookie_map", lambda: {"bili_jct": "csrf"})
    monkeypatch.setattr(review.bili_comment, "find_own_comments", lambda bvid, cookies: [Own()])
    monkeypatch.setattr(
        review.bili_comment,
        "post_comment_with_replies",
        lambda *args, **kwargs: publish_calls.append(args),
    )

    verified = review.reverify_applied("BV1Reverify", tmp_path)

    assert verified["status"] == "applied"
    assert verified["verification"]["ok"] is True
    assert verified["rpids"] == ["r-reverify"]
    assert publish_calls == []


def test_recover_missing_publishes_only_when_own_comments_absent(tmp_path: Path, monkeypatch):
    payload = {
        "bvid": "BV1Recover",
        "yt_id": "yt-recover",
        "title": "recover",
        "draft_messages": ["0:01:00 01. A - B"],
        "draft_song_count": 1,
        "source_text": "0:01:00 A / B",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1Recover", payload["draft_messages"], tmp_path)
    item = review.load_comment("BV1Recover", tmp_path)
    item.update({"status": "applied_unverified", "rpids": []})
    review._write_json(review.review_dir(tmp_path) / "BV1Recover.json", item)

    monkeypatch.setattr(review.bili_comment, "load_cookie_map", lambda: {"bili_jct": "csrf"})
    monkeypatch.setattr(review.bili_comment, "find_own_comments", lambda bvid, cookies: [])
    applied = []

    def fake_apply(bvid, data_dir=None, dry_run=False):
        current = review.load_comment(bvid, data_dir)
        assert current["status"] == "approved"
        applied.append(bvid)
        return {"bvid": bvid, "status": "applied", "verification": {"ok": True}}

    monkeypatch.setattr(review, "apply_comment", fake_apply)

    result = review.recover_missing_comment("BV1Recover", tmp_path)

    assert result["status"] == "applied"
    assert applied == ["BV1Recover"]


def test_recover_missing_never_republishes_existing_rpid(tmp_path: Path, monkeypatch):
    payload = {
        "bvid": "BV1NoDuplicate",
        "yt_id": "yt-no-duplicate",
        "title": "no duplicate",
        "draft_messages": ["0:01:00 01. A - B"],
        "draft_song_count": 1,
        "source_text": "0:01:00 A / B",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1NoDuplicate", payload["draft_messages"], tmp_path)
    item = review.load_comment("BV1NoDuplicate", tmp_path)
    item.update({"status": "applied_unverified", "rpids": ["existing-rpid"]})
    review._write_json(review.review_dir(tmp_path) / "BV1NoDuplicate.json", item)

    monkeypatch.setattr(review.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(review.bili_comment, "find_own_comments", lambda bvid, cookies: [])
    monkeypatch.setattr(
        review,
        "apply_comment",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not republish")),
    )

    result = review.recover_missing_comment("BV1NoDuplicate", tmp_path)

    assert result["status"] == "applied_unverified"
    assert "不重复发布" in result["error"]
    assert result["rpids"] == ["existing-rpid"]


def test_retry_without_artist_publishes_stripped_message_once(tmp_path: Path, monkeypatch):
    payload = {
        "bvid": "BV1ArtistRetry",
        "yt_id": "yt-artist-retry",
        "title": "artist retry",
        "draft_messages": ["0:01:00 01. A - Artist"],
        "draft_song_count": 1,
        "source_text": "0:01:00 A / Artist",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1ArtistRetry", payload["draft_messages"], tmp_path)
    item = review.load_comment("BV1ArtistRetry", tmp_path)
    item.update({"status": "applied_unverified", "rpids": ["hidden-rpid"]})
    review._write_json(review.review_dir(tmp_path) / "BV1ArtistRetry.json", item)

    captured = []

    def fake_apply(bvid, data_dir=None, dry_run=False):
        current = review.load_comment(bvid, data_dir)
        captured.append(current["approved_messages"])
        current.update({"status": "applied", "rpids": ["new-rpid"]})
        review._write_json(review.review_dir(data_dir) / f"{bvid}.json", current)
        return current

    monkeypatch.setattr(review, "apply_comment", fake_apply)

    result = review.retry_without_artist("BV1ArtistRetry", tmp_path)

    assert result["status"] == "applied"
    assert captured == [["0:01:00 01. A"]]
    assert result["previous_rpids"] == ["hidden-rpid"]
    assert result["without_artist_retried"] is True


def test_retry_with_artist_preserves_original_message_once(tmp_path: Path, monkeypatch):
    payload = {
        "bvid": "BV1ArtistOriginal",
        "yt_id": "yt-artist-original",
        "title": "artist original",
        "draft_messages": ["0:01:00 01. A - Artist"],
        "draft_song_count": 1,
        "source_text": "0:01:00 A / Artist",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1ArtistOriginal", payload["draft_messages"], tmp_path)
    item = review.load_comment("BV1ArtistOriginal", tmp_path)
    item.update({"status": "applied_unverified", "rpids": ["hidden-rpid"]})
    review._write_json(review.review_dir(tmp_path) / "BV1ArtistOriginal.json", item)

    captured = []

    def fake_apply(bvid, data_dir=None, dry_run=False):
        current = review.load_comment(bvid, data_dir)
        captured.append(current["approved_messages"])
        current.update({"status": "applied", "rpids": ["new-rpid"]})
        review._write_json(review.review_dir(data_dir) / f"{bvid}.json", current)
        return current

    monkeypatch.setattr(review, "apply_comment", fake_apply)

    result = review.retry_with_artist("BV1ArtistOriginal", tmp_path)

    assert result["status"] == "applied"
    assert captured == [payload["draft_messages"]]
    assert result["previous_rpids"] == ["hidden-rpid"]
    assert result["artist_retried"] is True


def test_cleanup_duplicates_then_retry_without_artist(tmp_path: Path, monkeypatch):
    payload = {
        "bvid": "BV1CleanupRetry",
        "yt_id": "yt-cleanup-retry",
        "title": "cleanup retry",
        "draft_messages": ["0:01:00 01. A - Artist"],
        "draft_song_count": 1,
        "source_text": "0:01:00 A / Artist",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1CleanupRetry", payload["draft_messages"], tmp_path)
    item = review.load_comment("BV1CleanupRetry", tmp_path)
    item.update({"status": "applied_unverified", "rpids": ["r-new"], "previous_rpids": ["r-old1", "r-old2"]})
    review._write_json(review.review_dir(tmp_path) / "BV1CleanupRetry.json", item)

    deleted = []
    monkeypatch.setattr(review.bili_comment, "load_cookie_map", lambda: {"bili_jct": "csrf"})
    monkeypatch.setattr(
        review.bili_comment,
        "delete_comment",
        lambda bvid, rpid, cookies: (deleted.append(rpid) or {"code": 0}),
    )
    captured = []

    def fake_apply(bvid, data_dir=None, dry_run=False):
        current = review.load_comment(bvid, data_dir)
        captured.append(current["approved_messages"])
        current.update({"status": "applied", "rpids": ["r-clean"]})
        review._write_json(review.review_dir(data_dir) / f"{bvid}.json", current)
        return current

    monkeypatch.setattr(review, "apply_comment", fake_apply)

    result = review.cleanup_duplicates_and_retry_without_artist("BV1CleanupRetry", tmp_path)

    assert deleted == ["r-new", "r-old1", "r-old2"]
    assert captured == [["0:01:00 01. A"]]
    assert result["status"] == "applied"
    assert result["deleted_rpids"] == ["r-new", "r-old1", "r-old2"]


def test_cleanup_delete_only_removes_comment_without_republish(tmp_path: Path, monkeypatch):
    message = "0:01:00 01. Not A Song"
    payload = {
        "bvid": "BV1DeleteOnly",
        "yt_id": "yt-delete-only",
        "title": "delete only",
        "draft_messages": [message],
        "draft_song_count": 1,
        "source_text": "0:01:00 Not A Song",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1DeleteOnly", [message], tmp_path)
    item = review.load_comment("BV1DeleteOnly", tmp_path)
    item.update({"status": "applied", "rpids": ["123456"], "verification": {"ok": True}})
    review._write_json(review.review_dir(tmp_path) / "BV1DeleteOnly.json", item)

    deleted = []
    monkeypatch.setattr(review.config, "owner_mid", lambda: "owner")
    monkeypatch.setattr(
        review.bili_comment,
        "load_cookie_map",
        lambda: {"bili_jct": "csrf", "DedeUserID": "owner"},
    )
    monkeypatch.setattr(review.bili_comment, "get_aid", lambda bvid, cookies: 42)

    class Comment:
        rpid = "123456"
        mid = "owner"

    monkeypatch.setattr(
        review.bili_comment,
        "list_comments",
        lambda bvid, cookies, max_pages=5: [Comment()],
    )
    monkeypatch.setattr(
        review.bili_comment,
        "find_comment_by_rpid",
        lambda bvid, rpid, cookies: (
            {"exists": False, "code": 12006}
            if deleted
            else {"exists": True, "mid": "owner", "message": message}
        ),
    )
    monkeypatch.setattr(
        review.bili_comment,
        "delete_comment",
        lambda bvid, rpid, cookies: (deleted.append(rpid) or {"code": 0, "message": ""}),
    )
    monkeypatch.setattr(
        review,
        "apply_comment",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("delete-only must not republish")),
    )

    result = review.cleanup_duplicates_and_retry_without_artist(
        "BV1DeleteOnly", tmp_path, delete_only=True
    )

    assert deleted == ["123456"]
    assert result["status"] == "deleted"
    assert result["deleted_rpids"] == ["123456"]
    assert result["verification"] == {
        "ok": True,
        "detail": "删除后回读确认目标不存在",
        "checked_at": result["verification"]["checked_at"],
    }
    assert result["rpids"] == []
    assert result["delete_results"] == [{"rpid": "123456", "response": {"code": 0, "message": ""}}]


def test_list_comments_ignores_messages_json_array(tmp_path: Path):
    review.review_dir(tmp_path).joinpath("notes.messages.json").write_text("[]", encoding="utf-8")
    payload = {
        "bvid": "BV1ListGuard",
        "title": "title",
        "part_date": "2026-10-03",
        "collection": "直播",
        "source_text": "raw",
        "draft_messages": ["0:01:00 01. A - B"],
        "draft_song_count": 1,
    }
    review.queue_comment(payload, tmp_path)

    assert [item["bvid"] for item in review.list_comments(data_dir=tmp_path)] == ["BV1ListGuard"]


def test_reverify_records_missing_rpid_without_republish(tmp_path: Path, monkeypatch):
    payload = {
        "bvid": "BV1MissingRpid",
        "yt_id": "yt-missing-rpid",
        "title": "missing rpid",
        "draft_messages": ["0:01:00 01. A - B"],
        "draft_song_count": 1,
        "source_text": "0:01:00 A / B",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1MissingRpid", payload["draft_messages"], tmp_path)
    item = review.load_comment("BV1MissingRpid", tmp_path)
    item.update(
        {
            "status": "applied_unverified",
            "rpids": ["316276398065"],
            "verification": {"ok": False, "detail": "回读缺失", "checked_at": "old"},
        }
    )
    review._write_json(review.review_dir(tmp_path) / "BV1MissingRpid.json", item)

    publish_calls = []
    monkeypatch.setattr(review.bili_comment, "load_cookie_map", lambda: {})
    monkeypatch.setattr(review, "verify_own_comments", lambda *args, **kwargs: (False, "回读缺失 1/1 条"))
    monkeypatch.setattr(
        review.bili_comment,
        "find_comment_by_rpid",
        lambda bvid, rpid, cookies: {
            "rpid": rpid,
            "exists": False,
            "code": 12006,
            "message": "没有该评论",
        },
    )
    monkeypatch.setattr(
        review.bili_comment,
        "post_comment_with_replies",
        lambda *args, **kwargs: publish_calls.append(args),
    )

    result = review.reverify_applied("BV1MissingRpid", tmp_path)

    assert result["status"] == "applied_unverified"
    assert result["verification"]["failure_kind"] == "recorded_rpid_missing"
    assert result["verification"]["rpid_checks"][0]["code"] == 12006
    assert "code 12006 没有该评论" in result["verification"]["detail"]
    assert publish_calls == []


def test_reapprove_rejected_repairs_invisible_comment_once(tmp_path: Path, monkeypatch):
    original = "3:26:22 01. シカせんべいのうた - 鹿乃子のこ(潘めぐみ), 虎視虎子(藤田咲)"
    corrected = "3:26:22 01. シカせんべいのうた - 潘めぐみ, 藤田咲"
    payload = {
        "bvid": "BV1RejectedRepost",
        "yt_id": "yt-rejected-repost",
        "title": "rejected repost",
        "draft_messages": [original],
        "draft_song_count": 1,
        "source_text": "3:26:22 シカせんべいのうた / 鹿乃子のこ(潘めぐみ), 虎視虎子(藤田咲)",
        "upgrade_mode": False,
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1RejectedRepost", [original], tmp_path)
    item = review.load_comment("BV1RejectedRepost", tmp_path)
    item.update(
        {
            "status": "applied_unverified",
            "rpids": ["rejected-rpid"],
            "verification": {
                "ok": False,
                "failure_kind": "recorded_rpid_not_in_readback",
                "detail": "顶层不可见",
            },
        }
    )
    review._write_json(review.review_dir(tmp_path) / "BV1RejectedRepost.json", item)

    captured = []

    def fake_apply(bvid, data_dir=None, dry_run=False):
        current = review.load_comment(bvid, data_dir)
        assert current["status"] == "approved"
        captured.append(current["approved_messages"])
        current.update({"status": "applied", "rpids": ["visible-rpid"]})
        review._write_json(review.review_dir(data_dir) / f"{bvid}.json", current)
        return current

    monkeypatch.setattr(review, "apply_comment", fake_apply)
    result = review.reapprove_rejected(
        "BV1RejectedRepost",
        [corrected],
        tmp_path,
    )

    assert result["status"] == "applied"
    assert captured == [[corrected]]
    assert result["rejected_rpids"] == ["rejected-rpid"]
    assert result["previous_rpids"] == ["rejected-rpid"]
    assert result["rejected_reapproved"] is True


def test_cleanup_rejected_duplicate_deletes_only_old_comment(tmp_path: Path, monkeypatch):
    original = "3:26:22 01. シカせんべいのうた - 鹿乃子のこ(潘めぐみ), 虎視虎子(藤田咲)"
    corrected = "3:26:22 01. シカせんべいのうた - 潘めぐみ, 藤田咲"
    payload = {
        "bvid": "BV1DeleteOldCredit",
        "title": "delete old credit",
        "draft_messages": [original],
        "draft_song_count": 1,
        "source_text": "3:26:22 シカせんべいのうた / 鹿乃子のこ(潘めぐみ), 虎視虎子(藤田咲)",
    }
    review.queue_comment(payload, tmp_path)
    review.approve_comment("BV1DeleteOldCredit", [corrected], tmp_path)
    item = review.load_comment("BV1DeleteOldCredit", tmp_path)
    item.update(
        {
            "status": "applied_unverified",
            "rpids": ["new-rpid"],
            "rejected_rpids": ["old-rpid"],
            "rejected_reapproved": True,
            "verification": {"ok": False, "failure_kind": "recorded_rpid_not_in_readback"},
        }
    )
    review._write_json(review.review_dir(tmp_path) / "BV1DeleteOldCredit.json", item)

    class Comment:
        def __init__(self, rpid):
            self.rpid = rpid
            self.mid = "owner"

    deleted = []
    monkeypatch.setattr(review.config, "owner_mid", lambda: "owner")
    monkeypatch.setattr(review.bili_comment, "load_cookie_map", lambda: {"bili_jct": "csrf", "DedeUserID": "owner"})
    monkeypatch.setattr(review.bili_comment, "get_aid", lambda bvid, cookies: 42)
    monkeypatch.setattr(
        review.bili_comment,
        "list_comments",
        lambda bvid, cookies, max_pages=5: [Comment("old-rpid"), Comment("new-rpid")],
    )
    monkeypatch.setattr(
        review.bili_comment,
        "find_comment_by_rpid",
        lambda bvid, rpid, cookies: {
            "exists": True,
            "mid": "owner",
            "message": original if rpid == "old-rpid" else corrected,
        },
    )
    monkeypatch.setattr(
        review.bili_comment,
        "delete_comment",
        lambda bvid, rpid, cookies: (deleted.append(rpid) or {"code": 0}),
    )

    def fake_reverify(bvid, data_dir=None):
        current = review.load_comment(bvid, data_dir)
        current.update({"status": "applied", "verification": {"ok": True}})
        return current

    monkeypatch.setattr(review, "reverify_applied", fake_reverify)

    result = review.cleanup_duplicates_and_retry_without_artist("BV1DeleteOldCredit", tmp_path)

    assert deleted == ["old-rpid"]
    assert result["status"] == "applied"
    assert result["rpids"] == ["new-rpid"]
    assert result["approved_messages"] == [corrected]
