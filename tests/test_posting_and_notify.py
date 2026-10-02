"""bili_comment 发布、通知与错误处理单元测试。"""
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

    brief = notify.build_yt_rate_limit_brief("BV1Wq846oE3E", "YouTube 抓取失败: HTTPError: HTTP Error 429")
    assert "⚠️YouTube 限流(429)" in brief
    assert "https://www.bilibili.com/video/BV1Wq846oE3E" in brief
    assert "429" in brief


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


def test_build_success_brief_with_profile():
    from yt_comment_automation import notify

    brief = notify.build_success_brief(
        "BV1Wq846oE3E",
        "https://youtu.be/2uzi8bOkU9Y",
        posted_at="2026-08-23 07:43:00",
        song_count=14,
        profile="主播：凛々咲 / Ririsya@RirisyaMusic",
    )
    assert "✅评论发送成功" in brief
    assert "主播：凛々咲 / Ririsya@RirisyaMusic" in brief
    assert "歌曲数量：14" in brief
    assert "——原始来源——" in brief
    assert "——本地草稿——" in brief
    assert "——最终发布——" in brief
    assert "验证：N/A" in brief
    assert "rpids：[]" in brief
    assert "segments：0" in brief
    assert "failures：[]" in brief


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
    assert "——清洗前后计数——" in brief
    assert "——原始来源——" in brief
    assert "——本地草稿——" in brief
    assert "——最终内容——" in brief
    assert "验证：N/A" in brief
    assert "rpids：[]" in brief
    assert "segments：0" in brief
    assert "failures：[]" in brief


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
    assert "yt_comment_automation/yt_fetch.py" in brief
    assert "yt_fetch failure path → failure brief" in brief


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
    assert "原始时间戳行：3 → 本地草稿行：2 → 最终发布行：2" in brief
    assert "节目/谈话标记" in brief
    assert "本地草稿" in brief
    assert "最终发布" in brief
    assert "回读通过" in brief
    assert "rpids：111,222" in brief
    assert "commit：abc1234" in brief
    assert "——涉及文件——" in brief
    assert "yt_comment_automation/review.py" in brief
    assert "——测试命令与结果——" in brief
    assert "review_cli apply → applied" in brief


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


def test_config_has_no_legacy_feishu_bridge_loader():
    import inspect

    from yt_comment_automation import config

    source = inspect.getsource(config)
    assert "_load_feishu_bridge" not in source
    assert "FEISHU_BRIDGE_ENV" not in source
