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
            {"rpid": 3, "status": "approved"},
            {"rpid": 4, "status": "rejected"},
            {"rpid": 5, "status": "pending"},
        ]
    }
    fresh_at = like_review._now()
    for item in payload["candidates"]:
        item["fetched_at"] = fresh_at

    selected = like_auto.select_work(payload, 2)

    assert [item["rpid"] for item in selected] == [2, 3]


def test_select_work_keeps_stale_candidates_for_live_revalidation():
    payload = {
        "candidates": [
            {"rpid": 1, "status": "pending", "fetched_at": "2000-01-01T00:00:00+0000"},
        ]
    }

    assert [item["rpid"] for item in like_auto.select_work(payload, 10)] == [1]


def test_select_work_includes_retryable_failures_only():
    payload = {
        "candidates": [
            {"rpid": 1, "status": "failed", "result": "stale_list"},
            {"rpid": 2, "status": "failed", "result": "verify_unavailable"},
            {"rpid": 3, "status": "failed", "result": "permanent"},
            {"rpid": 4, "status": "applied"},
        ]
    }
    fresh_at = like_review._now()
    for item in payload["candidates"]:
        item["fetched_at"] = fresh_at

    selected = like_auto.select_work(payload, 10)

    assert [item["rpid"] for item in selected] == [1, 2]


def test_select_work_can_defer_unavailable_state_until_next_run():
    payload = {
        "candidates": [
            {"rpid": 1, "status": "failed", "result": "verify_unavailable"},
            {"rpid": 2, "status": "pending"},
        ]
    }
    fresh_at = like_review._now()
    for item in payload["candidates"]:
        item["fetched_at"] = fresh_at

    selected = like_auto.select_work(payload, 10, exclude_rpids={"1"})

    assert [item["rpid"] for item in selected] == [2]


def test_parse_args_rejects_oversized_batch():
    with pytest.raises(SystemExit):
        like_auto.parse_args(["--max-count", "21"])


def test_run_like_auto_processes_remaining_pending_batches(tmp_path: Path, monkeypatch):
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
        if "--apply" in command:
            payload = like_review.load_review(review_path)
            for item in payload["candidates"]:
                if item.get("status") == "approved":
                    item.update({"status": "applied", "result": "liked"})
            like_review.save_review(payload, review_path)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(like_auto.subprocess, "run", fake_run)
    code = like_auto.run_like_auto(1, review_path, max_rounds=2, pause_seconds=0)

    assert code == 0
    assert calls == [
        [str(like_auto.sys.executable), str(like_auto.ROOT / "like_fans.py")],
        [
            str(like_auto.sys.executable),
            str(like_auto.ROOT / "like_fans.py"),
            "--apply",
            str(review_path),
        ],
        [
            str(like_auto.sys.executable),
            str(like_auto.ROOT / "like_fans.py"),
            "--apply",
            str(review_path),
        ],
    ]
    payload = like_review.load_review(review_path)
    statuses = {str(item["rpid"]): item["status"] for item in payload["candidates"]}
    assert statuses == {"11": "applied", "12": "applied"}
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


def test_run_like_auto_fails_instead_of_hiding_unresolved_candidate(
    tmp_path: Path, monkeypatch, capsys
):
    review_path = tmp_path / "like_review.json"
    like_review.save_review(
        {
            "candidates": [
                {
                    "oid": 1,
                    "rpid": 77,
                    "status": "pending",
                    "fetched_at": "2000-01-01T00:00:00+0000",
                }
            ]
        },
        review_path,
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append([str(part) for part in command])
        if "--apply" not in command:
            return subprocess.CompletedProcess(command, 0)
        payload = like_review.load_review(review_path)
        payload["candidates"][0].update(
            {"status": "failed", "result": "verify_unavailable"}
        )
        like_review.save_review(payload, review_path)
        return subprocess.CompletedProcess(command, 1)

    monkeypatch.setattr(like_auto.subprocess, "run", fake_run)
    code = like_auto.run_like_auto(
        10,
        review_path,
        max_rounds=1,
        pause_seconds=0,
    )

    assert code == 1
    assert len(calls) == 2
    assert "留待下次扫描" in capsys.readouterr().out
    assert like_review.load_review(review_path)["candidates"][0]["result"] == "verify_unavailable"


def test_run_like_auto_does_not_repeat_unavailable_state_in_same_run(tmp_path: Path, monkeypatch):
    review_path = tmp_path / "like_review.json"
    like_review.merge_candidates(
        [
            {"oid": 1, "rpid": 71, "content": "unreadable old reply"},
            {"oid": 2, "rpid": 72, "content": "next reply"},
        ],
        review_path,
    )
    calls = []
    apply_rounds = 0

    def fake_run(command, **kwargs):
        nonlocal apply_rounds
        calls.append([str(part) for part in command])
        if "--apply" not in command:
            return subprocess.CompletedProcess(command, 0)
        apply_rounds += 1
        payload = like_review.load_review(review_path)
        by_rpid = {str(item["rpid"]): item for item in payload["candidates"]}
        if apply_rounds == 1:
            by_rpid["71"].update(
                {"status": "failed", "result": "verify_unavailable"}
            )
        else:
            by_rpid["72"].update({"status": "applied", "result": "liked"})
        like_review.save_review(payload, review_path)
        return subprocess.CompletedProcess(command, 1 if apply_rounds == 1 else 0)

    monkeypatch.setattr(like_auto.subprocess, "run", fake_run)
    code = like_auto.run_like_auto(
        1,
        review_path,
        max_rounds=4,
        pause_seconds=0,
    )

    assert code == 1
    assert apply_rounds == 2
    assert len(calls) == 3
    payload = like_review.load_review(review_path)
    by_rpid = {str(item["rpid"]): item for item in payload["candidates"]}
    assert by_rpid["71"]["result"] == "verify_unavailable"
    assert by_rpid["72"]["status"] == "applied"


def test_run_like_auto_retries_transient_failure_and_finishes(tmp_path: Path, monkeypatch):
    review_path = tmp_path / "like_review.json"
    like_review.merge_candidates([{"oid": 1, "rpid": 11, "content": "first"}], review_path)
    calls = []
    apply_rounds = 0

    def fake_run(command, **kwargs):
        nonlocal apply_rounds
        calls.append([str(part) for part in command])
        if "--apply" not in command:
            return subprocess.CompletedProcess(command, 0)
        apply_rounds += 1
        payload = like_review.load_review(review_path)
        item = payload["candidates"][0]
        if apply_rounds == 1:
            item.update({"status": "failed", "result": "api_error"})
            like_review.save_review(payload, review_path)
            return subprocess.CompletedProcess(command, 1)
        item.update({"status": "applied", "result": "liked"})
        like_review.save_review(payload, review_path)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(like_auto.subprocess, "run", fake_run)
    code = like_auto.run_like_auto(
        10,
        review_path,
        max_rounds=2,
        pause_seconds=0,
    )

    assert code == 0
    assert apply_rounds == 2
    assert len(calls) == 3
    payload = like_review.load_review(review_path)
    assert payload["candidates"][0]["status"] == "applied"
