import json

from dev import notify_wdc_action_failure, wdc_run_youtube_action


def test_wdc_action_wait_default_covers_long_fetch(monkeypatch, capsys):
    captured = {}

    def fake_run(timeout_seconds, poll_seconds, refresh):
        captured.update(
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
            refresh=refresh,
        )
        return {"action": "synced"}

    monkeypatch.setattr(wdc_run_youtube_action, "run", fake_run)

    assert wdc_run_youtube_action.main([]) == 0
    assert captured == {
        "timeout_seconds": 1740.0,
        "poll_seconds": 5.0,
        "refresh": True,
    }
    assert json.loads(capsys.readouterr().out) == {"action": "synced"}


def test_action_failure_notice_redacts_credentials_and_explains_skip(
    tmp_path, monkeypatch, capsys
):
    log_path = tmp_path / "incremental.log"
    log_path.write_text(
        '{"error": "GitHub API token=gho_examplesecret failed"}\n',
        encoding="utf-8",
    )
    sent = []
    monkeypatch.setattr(notify_wdc_action_failure.notify, "git_summary", lambda: "abc1234")
    monkeypatch.setattr(
        notify_wdc_action_failure.notify,
        "send_feishu_message",
        lambda message: sent.append(message) or (True, "sent"),
    )

    assert notify_wdc_action_failure.main([str(log_path)]) == 0
    output = capsys.readouterr().out
    assert "True sent" in output
    assert len(sent) == 1
    assert "YouTube 评论抓取未完成" in sent[0]
    assert "本轮评论清洗已跳过" in sent[0]
    assert "[redacted]" in sent[0]
    assert "gho_examplesecret" not in sent[0]


def test_incremental_cycle_skips_pipeline_when_action_payload_failed():
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[1] / "dev" / "wdc_incremental_cycle.sh"
    ).read_text(encoding="utf-8")
    assert "--timeout 1740 --poll-interval 10" in script
    assert 'if [ "$ACTION_RC" -eq 0 ]; then' in script
    assert script.index('if [ "$ACTION_RC" -eq 0 ]; then') < script.index(
        "timeout 1800s bash cron_job.sh"
    )
    assert "pipeline_skipped=action_failure" in script
    assert "notify_wdc_action_failure.py" in script
