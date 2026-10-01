"""Codex 审核队列的持久化、批准和执行测试。"""
from pathlib import Path

from yt_comment_automation import like_review, review
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
    assert item["draft_messages"] == ["0:01:00 01. A - B"]
    assert path.is_file()


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
    monkeypatch.setattr(review.notify, "build_success_brief", lambda **kwargs: "brief")
    monkeypatch.setattr(review.notify, "send_feishu_message", lambda brief: (True, "ok"))

    item = review.apply_comment("BV1Apply", tmp_path)

    assert item["status"] == "applied"
    assert item["verification"]["ok"] is True
    assert "BV1Apply" in (tmp_path / "processed.json").read_text(encoding="utf-8")
