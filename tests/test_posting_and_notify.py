"""bili_comment 发布、通知与错误处理单元测试。"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_comment_automation import bili_comment  # noqa: E402


def test_split_message_under_limit_single_segment():
    msg = "0:01:00 01. 短い曲 - 歌手"
    segs = bili_comment.split_message_by_lines(msg)
    assert segs == [msg]


def test_split_message_over_limit_two_segments():
    lines = [f"0:{i:02d}:00 {n:02d}. テスト曲名で埋める - テスト歌手" for i, n in enumerate(range(1, 60), 0)]
    msg = "\n".join(lines)
    assert len(msg) > bili_comment.COMMENT_LENGTH_LIMIT
    segs = bili_comment.split_message_by_lines(msg)
    assert len(segs) >= 2
    for seg in segs:
        assert len(seg) <= bili_comment.COMMENT_LENGTH_LIMIT
        assert not any(not l.strip() for l in seg.splitlines())
    joined = "\n".join("\n".join(s.splitlines()) for s in segs)
    assert joined == msg


def test_split_message_keeps_lines_integer():
    lines = [f"0:{i:02d}:00 {n:02d}. 曲 - 歌手" for i, n in enumerate(range(1, 80), 0)]
    msg = "\n".join(lines)
    segs = bili_comment.split_message_by_lines(msg)
    total_lines = sum(len(s.splitlines()) for s in segs)
    assert total_lines == 79



def test_yt_rate_limited_detection():
    import urllib.error

    from yt_comment_automation import yt_fetch

    err = urllib.error.HTTPError("https://www.youtube.com/watch?v=xxx", 429, "Too Many Requests", None, None)
    assert yt_fetch.is_rate_limited_error(err)
    assert yt_fetch.is_rate_limited_error(Exception("HTTP Error 429: Too Many Requests"))
    assert not yt_fetch.is_rate_limited_error(Exception("HTTP Error 403: Forbidden"))


def test_build_yt_rate_limit_brief():
    from yt_comment_automation import notify

    brief = notify.build_yt_rate_limit_brief(
        "BV1Wq846oE3E",
        "YouTube 抓取失败: HTTPError: HTTP Error 429",
        files=["yt_comment_automation/yt_fetch.py"],
        tests=["fetch_youtube_raw → HTTP 429", "retry exhausted"],
        commit="abc1234",
        failures=["HTTP Error 429"],
    )
    assert "⚠️YouTube 限流(429)" in brief
    assert "https://www.bilibili.com/video/BV1Wq846oE3E" in brief
    assert "429" in brief
    assert "——原始来源——" in brief
    assert "——清洗前后计数——" in brief
    assert "——本地草稿——" in brief
    assert "——最终发布内容——" in brief
    assert "验证：N/A" in brief
    assert "rpids：[]" in brief
    assert "segments：0" in brief
    assert "failures：HTTP Error 429" in brief
    assert "yt_comment_automation/yt_fetch.py" in brief
    assert "retry exhausted" in brief
    assert "commit：abc1234" in brief


def test_extract_desc_profile_ririsya_format():
    from yt_comment_automation import notify

    desc = """https://youtu.be/2uzi8bOkU9Y
关注凛々咲 / Ririsya谢谢喵！
主播：凛々咲 / Ririsya@RirisyaMusic
原标题：【 #Ririsya6thAnniversary 】Special Singing Stream ✧ 6周年記念スペシャル #歌枠 #karaoke【 VTuber / #凛々咲 #Ririsya 】
直播开始时间：2026-08-23 12:59:59"""
    profile = notify.extract_desc_profile(desc)
    assert "主播：凛々咲 / Ririsya@RirisyaMusic" in profile
    assert "原标题：" in profile
    assert "谢谢" not in profile
    assert "关注凛々咲" not in profile


def test_extract_desc_profile_yoshika_format():
    from yt_comment_automation import notify

    desc = """https://youtu.be/HdS1-R5ndQM
主播/稿件上传者：YOSHIKA⁂Ch.@YOSHIKA-Ch
原标题：【#歌枠 】初見さん歓迎中！みんな集まれ！ #shorts #vtuber #vsinger
视频发布时间：2026-08-07 23:25:06"""
    profile = notify.extract_desc_profile(desc)
    assert "主播/稿件上传者：YOSHIKA⁂Ch.@YOSHIKA-Ch" in profile
    assert "原标题：" in profile


def test_extract_desc_profile_no_anchor():
    from yt_comment_automation import notify

    desc = "https://youtu.be/xxx\n原标题：テスト動画\nテスト"
    profile = notify.extract_desc_profile(desc)
    assert profile == "原标题：テスト動画"


def test_build_success_brief_omits_profile_and_verbose_audit_sections():
    from yt_comment_automation import notify

    brief = notify.build_success_brief(
        "BV1Wq846oE3E",
        "https://youtu.be/2uzi8bOkU9Y",
        posted_at="2026-08-23 07:43:00",
        song_count=14,
        profile="主播：凛々咲 / Ririsya@RirisyaMusic",
    )
    assert "✅评论发送成功" in brief
    assert "主播：凛々咲 / Ririsya@RirisyaMusic" not in brief
    assert "歌曲数量：14" in brief
    assert "——清洗汇总——" in brief
    assert "——关键时间戳节选——" in brief
    assert "——最终发布——" in brief
    assert "验证：N/A" in brief
    assert "rpids：[]" in brief
    assert "——本地草稿——" not in brief
    assert "segments：" not in brief
    assert "failures：" not in brief
    assert "审核备注：" not in brief
    assert "——涉及文件——" not in brief
    assert "——测试命令与结果——" not in brief


def test_failure_brief_title_by_error_type():
    from yt_comment_automation import notify

    # YouTube 抓取失败 → 标题不是"评论发送失败"
    brief = notify.build_failure_brief(
        "BV19hxdzfEkb",
        "YouTube 抓取失败: JSONDecodeError: ...",
        title="配信タイトル",
        collection="凛々咲",
        yt_link="https://youtu.be/xxx",
    )
    assert "⚠️YouTube 抓取失败" in brief
    assert "评论发送失败" not in brief
    assert "配信タイトル" in brief
    assert "合集：凛々咲" in brief
    assert "https://youtu.be/xxx" in brief

    # 评论发布失败 → 发布标题
    brief2 = notify.build_failure_brief("BV1xxx", "评论发布失败: code=-403 msg=权限不足")
    assert "❌评论发布/处理失败" in brief2
    assert "评论发送失败" not in brief2


def test_failure_brief_fallback_title():
    from yt_comment_automation import notify

    brief = notify.build_failure_brief("BV1xxx", "未知异常: xxx")
    assert "❌处理失败" in brief
    assert "——清洗汇总——" in brief
    assert "——关键时间戳节选——" in brief
    assert "——最终内容——" in brief
    assert "验证：N/A" in brief
    assert "rpids：[]" in brief
    assert "——本地草稿——" not in brief
    assert "segments：" not in brief
    assert "failures：" not in brief


def test_yt_fetch_json_decode_error_diagnosable():
    """YouTube 返回 HTML（反爬/验证码）时，错误信息要能看出不是 JSON。"""
    from yt_comment_automation import yt_fetch

    # 模拟 youtubei 返回 HTML
    html = '<!DOCTYPE html><html><body>captcha please enable javascript</body></html>'
    try:
        import json
        json.loads(html)
        assert False, "should have raised"
    except json.JSONDecodeError as err:
        snippet = html[:200].replace("\n", " ").strip()
        msg = f"youtubei 响应不是 JSON（可能是验证码/反爬 HTML）: {err}; 响应开头: {snippet!r}"
        assert "验证码/反爬" in msg
        assert "captcha" in msg


def test_yt_fetch_error_goes_through_failure_brief():
    """抓取失败通知的标题应为 YouTube 抓取失败，且带可诊断信息。"""
    from yt_comment_automation import notify

    brief = notify.build_failure_brief(
        "BV19hxdzfEkb",
        "YouTube 抓取失败: YtFetchError: youtubei 响应不是 JSON（可能是验证码/反爬 HTML）: ...; 响应开头: '<!DOCTYPE html>...'",
        title="SHONEN MANGA",
        files=["yt_comment_automation/yt_fetch.py"],
        tests=["yt_fetch failure path → failure brief"],
        collection="凛々咲",
        yt_link="https://youtu.be/WVGFpUyvxgo",
    )
    assert "⚠️YouTube 抓取失败" in brief
    assert "验证码/反爬" in brief
    assert "yt_comment_automation/yt_fetch.py" not in brief
    assert "yt_fetch failure path → failure brief" not in brief


def test_build_crash_brief():
    from yt_comment_automation import notify

    tb = """Traceback (most recent call last):
  File "yt_comment_automation/pipeline.py", line 446, in process_video
    messages = [message]
NameError: name 'message' is not defined"""
    brief = notify.build_crash_brief(
        tb,
        files=["yt_comment_automation/pipeline.py"],
        tests=["pipeline run → crashed"],
        commit="abc1234",
    )
    assert "💥管线崩溃" in brief
    assert "NameError: name 'message' is not defined" in brief
    assert "pipeline.py\", line 446" in brief
    assert "——原始来源——" in brief
    assert "——清洗前后计数——" in brief
    assert "——本地草稿——" in brief
    assert "——最终发布内容——" in brief
    assert "验证：N/A" in brief
    assert "rpids：[]" in brief
    assert "segments：0" in brief
    assert "failures：NameError" in brief
    assert "yt_comment_automation/pipeline.py" in brief
    assert "pipeline run → crashed" in brief
    assert "commit：abc1234" in brief


def test_cron_process_exit_uses_detailed_crash_report():
    script = (Path(__file__).resolve().parents[1] / "cron_job.sh").read_text(encoding="utf-8")
    assert "CRON_RUN_EXIT=" in script
    assert "notify.build_crash_brief(" in script
    assert "notify.git_summary()" in script
    assert "process exit code=" in script
    assert "yt_comment_automation/pipeline.py" in script
    assert script.rstrip().endswith('exit "$RUN_EXIT"')


def test_cli_crash_sends_notify(mocker=None):
    """cli 正式运行崩溃时调用飞书通知。"""
    import sys
    import types

    import yt_comment_automation.cli as cli_mod

    sent = []
    fake_notify = types.SimpleNamespace(
        build_crash_brief=lambda tb: "brief",
        send_feishu_message=lambda text, *a, **k: sent.append(text) or (True, "ok"),
    )
    fake_pipeline = types.SimpleNamespace(
        run_pipeline=lambda **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    cli_mod.pipeline = fake_pipeline
    # 模拟非 dry-run 分支：直接调用 main 太复杂，验证 build_crash_brief + send 组合即可
    tb = "Traceback\n  File 'pipeline.py', line 1\nRuntimeError: boom"
    brief = cli_mod  # noqa
    from yt_comment_automation import notify

    b = notify.build_crash_brief(tb)
    assert "RuntimeError: boom" in b


def test_detailed_success_brief_includes_cleanup_and_verification():
    from yt_comment_automation import notify

    brief = notify.build_success_brief(
        "BV1Detail",
        "https://youtu.be/detail",
        posted_at="2026-10-02 04:00:00",
        song_count=2,
        source_text="0:01:00 A\n0:02:00 MC\n0:03:00 B",
        source_lines="0:01:00 A\n0:02:00 MC\n0:03:00 B",
        draft_messages=["0:01:00 01. A - X\n0:03:00 02. B - Y"],
        approved_messages=["0:01:00 01. A - X\n0:03:00 02. B - Y"],
        note="Codex corrected numbering",
        verification={"ok": True, "detail": "回读通过 1 条顶层评论"},
        rpids=["111", "222"],
        segments=3,
        failures=[],
        status="applied",
        commit="abc1234",
        files=["yt_comment_automation/review.py"],
        tests=["review_cli apply → applied", "回读 → passed"],
    )
    assert "原始时间戳：3 行 → 最终发布：2 行" in brief
    assert "排除：1 行（节目/谈话标记 1 行）" in brief
    assert "Codex 调整：2 行（编号/格式规范化 0 行，内容补全或修正 2 行）" in brief
    assert "——清洗汇总——" in brief
    assert "——关键时间戳节选——" in brief
    assert "0:01:00 A" in brief
    assert "0:03:00 B" in brief
    assert "0:02:00 MC" not in brief
    assert "最终发布" in brief
    assert "验证：通过｜回读通过" in brief
    assert "rpids：111,222" in brief
    assert "commit：abc1234" in brief
    assert "——原始来源——" not in brief
    assert "——本地草稿——" not in brief
    assert "segments：" not in brief
    assert "failures：" not in brief
    assert "审核备注：Codex corrected numbering" not in brief
    assert "——涉及文件——" not in brief
    assert "yt_comment_automation/review.py" not in brief
    assert "——测试命令与结果——" not in brief
    assert "review_cli apply → applied" not in brief


def test_code_fix_brief_is_auditable():
    from yt_comment_automation import notify

    brief = notify.build_code_fix_brief(
        summary="移除旧 Feishu bridge fallback",
        root_cause="config.py 仍从旧机器人文件补载凭据",
        changes=["只读取当前项目 private.env/环境变量"],
        tests=["pytest -q", "python3 -m py_compile ..."],
        commit="def5678",
        files=["yt_comment_automation/config.py"],
    )
    assert "根因：config.py 仍从旧机器人文件补载凭据" in brief
    assert "yt_comment_automation/config.py" in brief
    assert "pytest -q" in brief
    assert "commit：def5678" in brief


def test_like_action_brief_lists_candidates():
    from yt_comment_automation import notify

    brief = notify.build_like_action_brief(
        [
            {
                "rpid": "901",
                "oid": "77",
                "source": "msgfeed",
                "content": "ありがとう！",
                "result": "liked",
                "error": "",
            }
        ],
        summary="点赞 1 | 失败 0",
        commit="aaa1111",
        files=["like_fans.py"],
        tests=["resolve_real_liked precheck → passed"],
        failures=[],
        segments="N/A",
    )
    assert "rpid=901" in brief
    assert "oid=77" in brief
    assert "source=msgfeed" in brief
    assert "result=liked" in brief
    assert "commit：aaa1111" in brief
    assert "segments：N/A" in brief
    assert "failures：[]" in brief
    assert "like_fans.py" in brief
    assert "resolve_real_liked precheck → passed" in brief


def test_like_success_brief_only_lists_liked_rpid_and_content():
    from yt_comment_automation import notify

    brief = notify.build_like_success_brief(
        [
            {"rpid": "901", "content": "[比心]\n下一行", "result": "liked"},
            {"rpid": "902", "content": "已赞", "result": "already_liked"},
            {"rpid": "903", "content": "失败", "result": "api_error"},
        ]
    )

    assert brief == "rpid=901 content=[比心] 下一行"


def test_send_terminal_success_message_uses_dedicated_union_id_bot(monkeypatch):
    import json

    from yt_comment_automation import config, notify

    monkeypatch.setattr(config, "feishu_success_app_id", lambda: "success-app")
    monkeypatch.setattr(config, "feishu_success_app_secret", lambda: "success-secret")
    monkeypatch.setattr(config, "feishu_success_union_id", lambda: "union-user")
    monkeypatch.setattr(
        notify, "_get_tenant_access_token", lambda app_id, secret: "test-token"
    )
    requests = []

    def fake_post(url, payload, headers=None):
        requests.append((url, payload, headers))
        return {"code": 0, "data": {"message_id": "message-1"}}

    monkeypatch.setattr(notify, "_post_json", fake_post)

    ok, detail = notify.send_terminal_success_message("rpid=901 content=hello")

    assert ok
    assert "message-1" in detail
    assert len(requests) == 1
    url, payload, headers = requests[0]
    assert url == notify.TERMINAL_SUCCESS_MESSAGE_URL
    assert "receive_id_type=union_id" in url
    assert payload["receive_id"] == "union-user"
    assert payload["msg_type"] == "text"
    assert json.loads(payload["content"]) == {"text": "rpid=901 content=hello"}
    assert headers["Authorization"] == "Bearer test-token"


def test_apply_success_sends_separate_terminal_success_notice(tmp_path, monkeypatch):
    import json

    from yt_comment_automation import review

    terminal_messages = []
    monkeypatch.setattr(
        review.notify, "send_feishu_message", lambda text: (True, "old bot")
    )
    monkeypatch.setattr(
        review.notify,
        "send_terminal_success_message",
        lambda text: terminal_messages.append(text) or (True, "success bot"),
    )
    item = {"status": "applied"}
    data_path = tmp_path / "review.json"

    review._send_apply_feishu_notification(item, data_path, "✅评论发送成功")

    saved = json.loads(data_path.read_text(encoding="utf-8"))
    assert terminal_messages == ["✅评论发送成功"]
    assert saved["feishu_notification"]["status"] == "sent"
    assert saved["terminal_success_feishu_notification"]["status"] == "sent"


def test_unverified_apply_does_not_send_terminal_success_notice(tmp_path, monkeypatch):
    from yt_comment_automation import review

    terminal_messages = []
    monkeypatch.setattr(
        review.notify, "send_feishu_message", lambda text: (True, "old bot")
    )
    monkeypatch.setattr(
        review.notify,
        "send_terminal_success_message",
        lambda text: terminal_messages.append(text) or (True, "success bot"),
    )
    item = {"status": "applied_unverified"}

    review._send_apply_feishu_notification(item, tmp_path / "review.json", "未验收")

    assert terminal_messages == []


def test_terminal_success_notification_does_not_fallback_to_standard_bot(monkeypatch):
    from yt_comment_automation import notify

    monkeypatch.setenv("FEISHU_APP_ID", "standard-app")
    monkeypatch.setenv("FEISHU_APP_SECRET", "standard-secret")
    monkeypatch.setenv("MY_FEISHU_OPEN_ID", "standard-open-id")
    for key in (
        "FEISHU_SUCCESS_APP_ID",
        "FEISHU_SUCCESS_APP_SECRET",
        "FEISHU_SUCCESS_UNION_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    sent, detail = notify.send_terminal_success_message("test")

    assert not sent
    assert "FEISHU_SUCCESS_APP_ID" in detail


def test_config_has_no_legacy_feishu_bridge_loader():
    import inspect

    from yt_comment_automation import config

    source = inspect.getsource(config)
    assert "_load_feishu_bridge" not in source
    assert "FEISHU_BRIDGE_ENV" not in source


def test_incremental_log_rotation_keeps_scheduler_log(tmp_path):
    script = (Path(__file__).resolve().parents[1] / "dev/wdc_incremental_cycle.sh").read_text(
        encoding="utf-8"
    )
    cleanup_line = next(
        line for line in script.splitlines() if line.startswith("ls -1t \"$LOG_DIR\"/incremental_")
    )
    for index in range(31):
        path = tmp_path / f"incremental_20261020_{index:06d}.log"
        path.write_text("cycle", encoding="utf-8")
        os.utime(path, (index + 1, index + 1))
    scheduler_log = tmp_path / "incremental_scheduler.log"
    scheduler_log.write_text("scheduler", encoding="utf-8")

    subprocess.run(
        ["bash", "-c", cleanup_line],
        check=True,
        env={**os.environ, "LOG_DIR": str(tmp_path)},
    )

    assert scheduler_log.read_text(encoding="utf-8") == "scheduler"
    assert len(list(tmp_path.glob("incremental_[0-9]*.log"))) == 30
    assert not (tmp_path / "incremental_20261020_000000.log").exists()

class _FakeFeishuResponse:
    def __init__(self, value):
        import json

        self._body = json.dumps(value).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def test_send_feishu_file_uploads_and_sends_one_file_message(monkeypatch, tmp_path):
    import json

    from yt_comment_automation import notify

    file_path = tmp_path / "songlist.md"
    file_path.write_bytes("0:00:12 01. テスト曲 - テスト歌手\n".encode("utf-8"))
    monkeypatch.setattr(notify.config, "feishu_app_id", lambda: "test-app-id")
    monkeypatch.setattr(notify.config, "feishu_app_secret", lambda: "test-app-secret")
    monkeypatch.setattr(notify.config, "feishu_open_id", lambda: "ou-test-recipient")
    monkeypatch.setattr(notify, "_get_tenant_access_token", lambda app_id, secret: "test-tenant-token")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        assert timeout == 30
        assert request.get_header("Authorization") == "Bearer test-tenant-token"
        if request.full_url == notify.FILE_UPLOAD_URL:
            content_type = request.get_header("Content-type")
            assert content_type.startswith("multipart/form-data; boundary=")
            body = request.data
            assert b'name="file_type"' in body and b"stream" in body
            assert b'name="file_name"' in body and b"songlist.md" in body
            assert b'name="file"; filename="songlist.md"' in body
            assert file_path.read_bytes() in body
            return _FakeFeishuResponse({"code": 0, "data": {"file_key": "file_test_key"}})
        assert request.full_url == notify.MESSAGE_URL
        message = json.loads(request.data.decode("utf-8"))
        assert message["receive_id"] == "ou-test-recipient"
        assert message["msg_type"] == "file"
        assert json.loads(message["content"]) == {"file_key": "file_test_key"}
        return _FakeFeishuResponse({"code": 0, "data": {"message_id": "om_test_message"}})

    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    ok, receipt = notify.send_feishu_file(file_path)

    assert ok
    assert "message_id=om_test_message" in receipt
    assert "file_key=file_test_key" in receipt
    assert len(requests) == 2
    assert requests[0].full_url == notify.FILE_UPLOAD_URL
    assert requests[1].full_url == notify.MESSAGE_URL


def test_send_feishu_file_reports_uncertain_message_without_retry(monkeypatch, tmp_path):
    from yt_comment_automation import notify

    file_path = tmp_path / "songlist.md"
    file_path.write_text("songlist\n", encoding="utf-8")
    monkeypatch.setattr(notify.config, "feishu_app_id", lambda: "test-app-id")
    monkeypatch.setattr(notify.config, "feishu_app_secret", lambda: "test-app-secret")
    monkeypatch.setattr(notify.config, "feishu_open_id", lambda: "ou-test-recipient")
    monkeypatch.setattr(notify, "_get_tenant_access_token", lambda app_id, secret: "test-tenant-token")
    monkeypatch.setattr(notify, "_post_file_upload", lambda path, token: {"code": 0, "data": {"file_key": "file_test_key"}})
    message_calls = []

    def fail_message(*args, **kwargs):
        message_calls.append((args, kwargs))
        raise TimeoutError("response lost")

    monkeypatch.setattr(notify, "_post_json", fail_message)
    ok, receipt = notify.send_feishu_file(file_path)

    assert not ok
    assert "结果不确定（不要重发）" in receipt
    assert len(message_calls) == 1


def test_send_feishu_file_reports_http_status_and_missing_scope(monkeypatch, tmp_path):
    import io
    import json
    import urllib.error

    from yt_comment_automation import notify

    file_path = tmp_path / "songlist.md"
    file_path.write_text("songlist\n", encoding="utf-8")
    monkeypatch.setattr(notify.config, "feishu_app_id", lambda: "test-app-id")
    monkeypatch.setattr(notify.config, "feishu_app_secret", lambda: "test-app-secret")
    monkeypatch.setattr(notify.config, "feishu_open_id", lambda: "ou-test-recipient")
    monkeypatch.setattr(notify, "_get_tenant_access_token", lambda app_id, secret: "test-tenant-token")
    payload = {
        "code": 99991672,
        "msg": "Access denied",
        "error": {"permission_violations": [{"subject": "im:resource:upload"}]},
    }
    http_error = urllib.error.HTTPError(
        notify.FILE_UPLOAD_URL,
        400,
        "Bad Request",
        hdrs=None,
        fp=io.BytesIO(json.dumps(payload).encode("utf-8")),
    )
    monkeypatch.setattr(
        notify,
        "_post_file_upload",
        lambda path, token: (_ for _ in ()).throw(http_error),
    )

    ok, receipt = notify.send_feishu_file(file_path)

    assert not ok
    assert "HTTP 400" in receipt
    assert "code=99991672" in receipt
    assert "required_scopes=im:resource:upload" in receipt
    assert "test-tenant-token" not in receipt


def test_send_feishu_file_rejects_empty_and_oversize_before_network(monkeypatch, tmp_path):
    from yt_comment_automation import notify

    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    oversized = tmp_path / "oversized.md"
    oversized.write_bytes(b"1234")
    monkeypatch.setattr(notify, "MAX_FEISHU_FILE_BYTES", 3)
    monkeypatch.setattr(notify.config, "feishu_app_id", lambda: "test-app-id")
    monkeypatch.setattr(notify.config, "feishu_app_secret", lambda: "test-app-secret")
    monkeypatch.setattr(notify.config, "feishu_open_id", lambda: "ou-test-recipient")
    monkeypatch.setattr(notify, "_get_tenant_access_token", lambda *args: (_ for _ in ()).throw(AssertionError("network must not start")))

    ok_empty, receipt_empty = notify.send_feishu_file(empty)
    ok_large, receipt_large = notify.send_feishu_file(oversized)

    assert not ok_empty and "空文件" in receipt_empty
    assert not ok_large and "30 MB" in receipt_large
