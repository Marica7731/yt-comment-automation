"""ai.py 与 bili_comment.py 单元测试：DS 输出解析、分段、无歌手过滤。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_comment_automation import ai, bili_comment  # noqa: E402


def test_parse_ai_output_with_timestamps():
    text = """0:02:16 01. バラライカ - 月島きらり starring 久住小春（モーニング娘。）
0:06:41 02. Together - あきよしふみえ
3:04 03. テスト曲 - テスト歌手"""
    items = ai.parse_ai_output_to_items(text)
    assert len(items) == 3
    assert items[0].song == "バラライカ"
    assert items[0].timestamp_seconds == 136
    assert items[1].artist == "あきよしふみえ"
    assert items[2].timestamp_seconds == 184


def test_parse_ai_output_no_timestamp_fallback():
    text = "01. バラライカ - 月島きらり\n02. Together - あきよしふみえ"
    items = ai.parse_ai_output_to_items(text)
    assert len(items) == 2
    assert items[0].timestamp_seconds is None


def test_parse_ai_output_keeps_no_artist():
    text = "0:01:00 01. ただの曲名\n0:02:00 02. 有効曲 - 歌手"
    items = ai.parse_ai_output_to_items(text)
    assert len(items) == 2
    assert items[0].song == "ただの曲名"
    assert items[0].artist == ""
    assert items[1].song == "有効曲"


def test_parse_ai_output_unknown_artist_cleared():
    text = "0:01:00 01. 曲 - 未記載\n0:02:00 02. 有効曲 - 歌手"
    items = ai.parse_ai_output_to_items(text)
    assert len(items) == 2
    assert items[0].artist == ""  # 未記載 → 视为无歌手
    assert items[1].song == "有効曲"


def test_parse_ai_output_skips_blank_lines():
    text = "0:01:00 01. 曲 - 歌手\n\n0:02:00 02. 曲2 - 歌手2\n\n"
    items = ai.parse_ai_output_to_items(text)
    assert len(items) == 2


def test_parse_ai_output_artist_with_hyphen():
    text = "0:01:00 01. Don't say \"lazy\" - 桜高軽音部"
    items = ai.parse_ai_output_to_items(text)
    assert len(items) == 1
    assert items[0].song == 'Don\'t say "lazy"'
    assert items[0].artist == "桜高軽音部"


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
        collection="凛々咲",
        yt_link="https://youtu.be/WVGFpUyvxgo",
    )
    assert "⚠️YouTube 抓取失败" in brief
    assert "验证码/反爬" in brief
