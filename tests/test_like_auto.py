import subprocess
from pathlib import Path

import pytest

import like_auto
from yt_comment_automation import like_review


def test_select_pending_caps_batch_and_skips_terminal_states():
    payload = {
        "candidates": [
            {"rpid": 1, "status": "applied"},
            {"rpid": 2, "status": "pending"},
            {"rpid": 3, "status": "pending"},
            {"rpid": 4, "status": "rejected"},
            {"rpid": 5, "status": "pending"},
        ]
    }

    selected = like_auto.select_pending(payload, 2)

    assert [item["rpid"] for item in selected] == [2, 3]


def test_parse_args_rejects_oversized_batch():
    with pytest.raises(SystemExit):
        like_auto.parse_args(["--max-count", "21"])


def test_run_like_auto_approves_only_selected_batch(tmp_path: Path, monkeypatch):
    review_path = tmp_path / "like_review.json"
    like_review.merge_candidates(
        [
            {"oid": 1, "rpid": 11, "content": "first"},
            {"oid": 2, "rpid": 12, "content": "second"},
        ],
        review_path,
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(like_auto.subprocess, "run", fake_run)
    code = like_auto.run_like_auto(1, review_path)

    assert code == 0
    assert calls == [
        [str(like_auto.sys.executable), str(like_auto.ROOT / "like_fans.py")],
        [
            str(like_auto.sys.executable),
            str(like_auto.ROOT / "like_fans.py"),
            "--apply",
            str(review_path),
        ],
    ]
    payload = like_review.load_review(review_path)
    statuses = {str(item["rpid"]): item["status"] for item in payload["candidates"]}
    assert statuses == {"11": "approved", "12": "pending"}
    assert payload["max_count"] == 1


def test_run_like_auto_does_not_apply_after_scan_failure(tmp_path: Path, monkeypatch):
    review_path = tmp_path / "like_review.json"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(like_auto.subprocess, "run", fake_run)
    code = like_auto.run_like_auto(10, review_path)

    assert code == 1
    assert len(calls) == 1
