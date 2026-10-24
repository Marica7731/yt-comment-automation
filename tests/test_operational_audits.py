import json
from pathlib import Path
from datetime import datetime, timezone

from dev import incremental_audit, like_success_audit
from yt_comment_automation import incremental, like_review


def _raw(text: str) -> dict:
    return {
        "description": "",
        "comment_entries": [{"id": "c1", "text": text}],
    }


def test_incremental_audit_accepts_consistent_raw_and_state(tmp_path: Path):
    data_dir = tmp_path / "data"
    audit_dir = data_dir / "incremental_audit"
    audit_dir.mkdir(parents=True)
    raw = _raw("0:01:00 Song - Artist")
    state, changes = incremental.update_state(incremental.empty_state(), {"abcdefghijk": raw})
    latest = {
        "fetched_at": "2026-10-19T04:00:00+0800",
        "results": {"abcdefghijk": raw},
        "changes": changes,
        "review_candidates": incremental.review_candidates(changes),
        "incremental_state": state,
    }
    (audit_dir / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    incremental.save_state(state, data_dir / "incremental_state.json")

    result = incremental_audit.audit(data_dir)

    assert result["ok"] is True
    assert result["review_candidates"] == ["abcdefghijk"]


def test_incremental_audit_accepts_recovery_after_rejected_empty_snapshot(tmp_path: Path):
    data_dir = tmp_path / "data"
    audit_dir = data_dir / "incremental_audit"
    audit_dir.mkdir(parents=True)
    video_id = "sWdaRFW8mNY"
    raw = _raw("💜┈┈セットリスト┈┈🎼\n0:17:33 三日月\n0:23:15 カワキチアメク")
    state, _ = incremental.update_state(incremental.empty_state(), {video_id: raw})
    state, changes = incremental.update_state(state, {video_id: raw})
    latest = {
        "fetched_at": "2026-10-21T14:00:14+0000",
        "results": {video_id: raw},
        "changes": changes,
        "review_candidates": incremental.review_candidates(changes),
        "failures": [],
    }
    previous = {
        "fetched_at": "2026-10-21T13:40:14+0000",
        "results": {},
        "changes": {},
        "review_candidates": [],
        "failures": [
            {"video_id": video_id, "error": "YtFetchError: empty comment snapshot"}
        ],
    }
    (audit_dir / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    (audit_dir / "previous.json").write_text(json.dumps(previous), encoding="utf-8")
    incremental.save_state(state, data_dir / "incremental_state.json")

    result = incremental_audit.audit(data_dir)

    assert result["ok"] is True
    assert result["review_candidates"] == []


def test_incremental_audit_detects_state_mismatch(tmp_path: Path):
    data_dir = tmp_path / "data"
    audit_dir = data_dir / "incremental_audit"
    audit_dir.mkdir(parents=True)
    raw = _raw("0:01:00 Song - Artist")
    state, changes = incremental.update_state(incremental.empty_state(), {"abcdefghijk": raw})
    state["videos"]["abcdefghijk"]["description_hash"] = "tampered"
    latest = {
        "fetched_at": "2026-10-19T04:00:00+0800",
        "results": {"abcdefghijk": raw},
        "changes": changes,
        "review_candidates": incremental.review_candidates(changes),
    }
    (audit_dir / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    incremental.save_state(state, data_dir / "incremental_state.json")

    result = incremental_audit.audit(data_dir)

    assert result["ok"] is False
    assert "abcdefghijk:state_mismatch:description_hash" in result["issues"]


def test_incremental_audit_flags_stale_open_review(tmp_path: Path):
    data_dir = tmp_path / "data"
    audit_dir = data_dir / "incremental_audit"
    queue_dir = data_dir / "codex_review"
    audit_dir.mkdir(parents=True)
    queue_dir.mkdir(parents=True)
    raw = _raw("0:01:00 Song - Artist")
    state, changes = incremental.update_state(incremental.empty_state(), {"abcdefghijk": raw})
    latest = {
        "fetched_at": "2026-10-24T12:41:30+0000",
        "results": {"abcdefghijk": raw},
        "changes": changes,
        "review_candidates": incremental.review_candidates(changes),
    }
    (audit_dir / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
    incremental.save_state(state, data_dir / "incremental_state.json")
    queue_item = {
        "bvid": "BV1Stale",
        "status": "pending",
        "queued_at": "2026-10-24T10:00:00+0000",
        "updated_at": "2026-10-24T13:00:00+0000",
    }
    (queue_dir / "BV1Stale.json").write_text(json.dumps(queue_item), encoding="utf-8")

    result = incremental_audit.audit(
        data_dir,
        now=datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc),
        max_pending_minutes=60,
    )

    assert result["ok"] is False
    assert "review_queue_overdue:pending:BV1Stale:240m" in result["issues"]
    assert result["review_queue"][0]["age_from"] == "queued_at"


def test_like_audit_accepts_applied_ledger_entry(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    like_review.save_review(
        {
            "candidates": [
                {
                    "rpid": 1,
                    "status": "applied",
                    "result": "liked",
                    "fetched_at": like_review._now(),
                }
            ]
        },
        data_dir / "like_review.json",
    )
    (data_dir / "liked_rpids.json").write_text(json.dumps(["1"]), encoding="utf-8")

    result = like_success_audit.audit(data_dir)

    assert result["ok"] is True
    assert result["counts"]["applied"] == 1


def test_like_audit_flags_stale_open_candidate(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    like_review.save_review(
        {
            "candidates": [
                {
                    "rpid": 1,
                    "status": "pending",
                    "fetched_at": "2000-01-01T00:00:00+0000",
                }
            ]
        },
        data_dir / "like_review.json",
    )

    result = like_success_audit.audit(data_dir)

    assert result["ok"] is False
    assert any(issue.startswith("open_candidate_not_fresh:1") for issue in result["issues"])
