import json
from pathlib import Path

from yt_comment_automation import notify


def _write_latest(data_dir, failures):
    audit = Path(data_dir) / "incremental_audit"
    audit.mkdir(parents=True)
    (audit / "latest.json").write_text(
        json.dumps({"failures": failures}), encoding="utf-8"
    )
    return data_dir


def test_summarize_action_failures_names_rate_limit(tmp_path):
    data = _write_latest(
        tmp_path,
        [
            {"video_id": "5ZLfVpCmfBA", "error": "HTTPError: HTTP Error 429: Too Many Requests"},
            {"video_id": "ypzrTOOdP28", "error": "HTTPError: HTTP Error 429: Too Many Requests"},
        ],
    )

    assert notify.summarize_action_failures(data) == [
        "5ZLfVpCmfBA: HTTPError: HTTP Error 429: Too Many Requests",
        "ypzrTOOdP28: HTTPError: HTTP Error 429: Too Many Requests",
    ]


def test_summarize_action_failures_caps_rows(tmp_path):
    data = _write_latest(
        tmp_path,
        [{"video_id": f"vid{i}", "error": "HTTP Error 429"} for i in range(5)],
    )

    assert notify.summarize_action_failures(data, limit=2) == [
        "vid0: HTTP Error 429",
        "vid1: HTTP Error 429",
        "...另有 3 条失败",
    ]


def test_summarize_action_failures_missing_file_is_quiet(tmp_path):
    assert notify.summarize_action_failures(tmp_path) == []
