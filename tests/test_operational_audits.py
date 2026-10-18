import json
from pathlib import Path

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
