"""飞书消息发送（自包含，走开放平台 tenant_access_token + im message）。

环境变量：
- FEISHU_APP_ID / FEISHU_APP_SECRET：自建应用凭据
- MY_FEISHU_OPEN_ID（或 FEISHU_OPEN_ID）：接收人 open_id
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from . import config

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
UA = "yt-comment-automation/0.1"

# 通知时间统一用北京时间（UTC+8）；B 站简介/YouTube 用日本时间（UTC+9）
BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _post_json(url: str, payload: dict, headers: Optional[dict] = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA, **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_tenant_access_token(app_id: str, app_secret: str) -> str:
    resp = _post_json(TOKEN_URL, {"app_id": app_id, "app_secret": app_secret})
    if resp.get("code") != 0:
        raise RuntimeError(f"飞书 token 获取失败: {resp.get('msg')}")
    return resp["tenant_access_token"]


def send_feishu_message(text: str, dry_run: bool = False) -> tuple[bool, str]:
    """发送文本消息到配置的 open_id。返回 (成功, 说明)。"""
    app_id = config.feishu_app_id()
    app_secret = config.feishu_app_secret()
    open_id = config.feishu_open_id()
    if not (app_id and app_secret and open_id):
        return False, "缺少 FEISHU_APP_ID/FEISHU_APP_SECRET/MY_FEISHU_OPEN_ID"
    if dry_run:
        return True, "[dry-run] 飞书消息:\n" + text
    try:
        token = _get_tenant_access_token(app_id, app_secret)
    except Exception as err:  # noqa: BLE001
        return False, f"飞书 token 失败: {err}"
    resp = _post_json(
        MESSAGE_URL,
        {"receive_id": open_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.get("code") != 0:
        return False, f"飞书发送失败: code={resp.get('code')} msg={resp.get('msg')}"
    return True, f"飞书已发送 message_id={resp.get('data', {}).get('message_id', '')}"


def git_summary() -> str:
    """Return the current short commit and dirty marker for audit reports."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(config.ROOT),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(config.ROOT),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return f"{commit}{'+dirty' if dirty else ''}"
    except Exception:  # noqa: BLE001
        return "unknown"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n---\n".join(str(item) for item in value if str(item).strip())
    return str(value)


def _as_multiline(value: Iterable[str] | str) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return "\n".join(str(item) for item in value if str(item).strip())


_TIMESTAMP_RE = re.compile(r"(?<![\d:])(\d{1,3}:\d{2}(?::\d{2})?)(?![\d:])")
_PROGRAM_MARKER_RE = re.compile(
    r"MC|开场|开场白|開始|开始|終了|结束|エンディング|エンドカード|片頭|片尾|"
    r"トーク|トークタイム|話|掃除|声入り|セットリスト|歌枠|配信開始|校对|修正",
    re.I,
)
_EXCLUDED_REASON_ORDER = ("节目/谈话标记", "非歌单内容")


def _timestamp_lines(value: Any) -> list[str]:
    text = _as_text(value)
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and _TIMESTAMP_RE.search(line)
    ]


def _timestamp_key(line: str) -> str:
    match = _TIMESTAMP_RE.search(line)
    return match.group(1) if match else ""


def _song_text(line: str) -> str:
    text = _TIMESTAMP_RE.sub("", str(line), count=1).strip()
    text = re.sub(r"^\d{1,3}\s*[.．、]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _excluded_reason(line: str) -> str:
    return "节目/谈话标记" if _PROGRAM_MARKER_RE.search(line) else "非歌单内容"


def _timestamp_excerpt(lines: list[str], limit: int = 10) -> str:
    if not lines:
        return "（无可节选的时间戳）"
    if len(lines) <= limit:
        return "\n".join(lines)
    head_count = limit // 2
    tail_count = limit - head_count
    omitted = len(lines) - limit
    return "\n".join([
        *lines[:head_count],
        f"… 中间省略 {omitted} 行 …",
        *lines[-tail_count:],
    ])


def _verification_text(value: Any) -> str:
    if isinstance(value, dict):
        ok = "通过" if value.get("ok") else "未通过"
        detail = str(value.get("detail") or value.get("message") or "").strip()
        return f"{ok}｜{detail}" if detail else ok
    return str(value) if value not in (None, "") else "N/A"


def build_cleanup_report(
    source_text: str = "",
    source_lines: str = "",
    draft_messages: Any = None,
    approved_messages: Any = None,
    note: str = "",
) -> tuple[str, str, str]:
    """Return a compact cleanup summary, a source excerpt, and raw source lines."""
    del draft_messages, note
    raw_lines = _timestamp_lines(source_lines or source_text)
    final_lines = _timestamp_lines(approved_messages)

    final_by_key = {_timestamp_key(line): line for line in final_lines if _timestamp_key(line)}
    raw_keys = {_timestamp_key(line) for line in raw_lines if _timestamp_key(line)}
    excluded = [line for line in raw_lines if _timestamp_key(line) not in final_by_key]
    added = [line for line in final_lines if _timestamp_key(line) not in raw_keys]
    formatted = 0
    content_changed = 0
    for raw_line in raw_lines:
        key = _timestamp_key(raw_line)
        final_line = final_by_key.get(key)
        if not key or not final_line or raw_line == final_line:
            continue
        if _song_text(raw_line) == _song_text(final_line):
            formatted += 1
        else:
            content_changed += 1

    if not raw_lines and not final_lines:
        summary = "无可对比的时间戳。"
    else:
        summary_lines = [f"原始时间戳：{len(raw_lines)} 行 → 最终发布：{len(final_lines)} 行"]
        if excluded:
            reason_counts: dict[str, int] = {}
            for line in excluded:
                reason = _excluded_reason(line)
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            reason_text = "、".join(
                f"{reason} {reason_counts[reason]} 行"
                for reason in _EXCLUDED_REASON_ORDER
                if reason_counts.get(reason)
            )
            summary_lines.append(f"排除：{len(excluded)} 行（{reason_text}）")
        else:
            summary_lines.append("排除：0 行")
        if added:
            summary_lines.append(f"新增时间戳：{len(added)} 行")
        adjusted = formatted + content_changed
        summary_lines.append(
            f"Codex 调整：{adjusted} 行（编号/格式规范化 {formatted} 行，"
            f"内容补全或修正 {content_changed} 行）"
        )
        summary = "\n".join(summary_lines)

    matched_source_lines = [line for line in raw_lines if _timestamp_key(line) in final_by_key]
    excerpt_lines = matched_source_lines or raw_lines
    return summary, _timestamp_excerpt(excerpt_lines), _as_text(source_lines or source_text)


def build_code_fix_brief(
    summary: str,
    root_cause: str,
    changes: Iterable[str] | str,
    tests: Iterable[str] | str,
    commit: str = "",
    files: Iterable[str] | str = (),
) -> str:
    """Detailed code-fix report: cause, files, behavior change, tests, commit."""
    change_text = "\n".join(str(x) for x in changes) if not isinstance(changes, str) else changes
    test_text = "\n".join(str(x) for x in tests) if not isinstance(tests, str) else tests
    file_text = "\n".join(str(x) for x in files) if not isinstance(files, str) else files
    lines = [
        "🛠代码修复完成",
        f"摘要：{summary}",
        f"根因：{root_cause}",
    ]
    if file_text:
        lines.extend(["——变更文件——", file_text])
    if change_text:
        lines.extend(["——行为变更——", change_text])
    if test_text:
        lines.extend(["——测试——", test_text])
    lines.append(f"commit：{commit or git_summary()}")
    lines.append(f"时间：{beijing_now()}")
    return "\n".join(lines)


def build_like_action_brief(
    results: Iterable[dict[str, Any]],
    summary: str = "",
    commit: str = "",
    files: Iterable[str] | str = (),
    tests: Iterable[str] | str = (),
    failures: Iterable[str] | str = (),
    segments: int | str = "",
) -> str:
    """Detailed like action report with candidate identity and result."""
    rows = list(results)
    lines = ["👍Codex 审核点赞执行"]
    if summary:
        lines.append(summary)
    lines.append(f"执行条数：{len(rows)}")
    for row in rows:
        lines.append(
            "- rpid={rpid} oid={oid} source={source} result={result} error={error}\n"
            "  content={content}".format(
                rpid=row.get("rpid", ""),
                oid=row.get("oid", ""),
                source=row.get("source", ""),
                result=row.get("result", row.get("status", "")),
                error=row.get("error", ""),
                content=str(row.get("content", "")).replace("\n", " ")[:240],
            )
        )
    if not rows:
        lines.append("- 无可执行候选")
    lines.append(f"segments：{segments if segments not in (None, '') else 'N/A（点赞动作无评论分段）'}")
    failure_text = _as_multiline(failures)
    lines.append(f"failures：{failure_text or '[]'}")
    file_text = _as_multiline(files)
    test_text = _as_multiline(tests)
    lines.extend(["——涉及文件——", file_text or "（未提供）"])
    lines.extend(["——测试命令与结果——", test_text or "（未提供）"])
    lines.append(f"commit：{commit or git_summary()}")
    lines.append(f"时间：{beijing_now()}")
    return "\n".join(lines)


def build_like_review_brief(
    candidates: Iterable[dict[str, Any]],
    commit: str = "",
) -> str:
    rows = list(candidates)
    lines = ["👍点赞候选待 Codex 审核", f"新增候选：{len(rows)}"]
    for row in rows:
        lines.append(
            "- rpid={rpid} oid={oid} source={source}\n  content={content}".format(
                rpid=row.get("rpid", ""),
                oid=row.get("oid", ""),
                source=row.get("source", ""),
                content=str(row.get("content", "")).replace("\n", " ")[:240],
            )
        )
    lines.append(f"commit：{commit or git_summary()}")
    lines.append(f"时间：{beijing_now()}")
    return "\n".join(lines)


def build_success_brief(
    bvid: str,
    yt_link: str,
    posted_at: str = "",
    song_count: int = 0,
    profile: str = "",
    source_lines: str = "",
    final_message: str = "",
    source_text: str = "",
    draft_messages: Any = None,
    approved_messages: Any = None,
    note: str = "",
    verification: Any = None,
    rpids: Iterable[str] | str = (),
    segments: int | str = 0,
    failures: Iterable[str] | str = (),
    status: str = "",
    commit: str = "",
    title: str = "",
    collection: str = "",
    files: Iterable[str] | str = (),
    tests: Iterable[str] | str = (),
) -> str:
    """Compact success report with cleanup summary, source excerpt, and verification."""
    del profile, note, segments, failures, files, tests
    bili_link = f"https://www.bilibili.com/video/{bvid}"
    lines = [
        "✅评论发送成功",
        bili_link,
        yt_link,
        posted_at or beijing_now(),
        f"状态：{status or 'applied'}",
        f"歌曲数量：{song_count}",
        f"commit：{commit or git_summary()}",
    ]
    if title:
        lines.append(f"标题：{title}")
    if collection:
        lines.append(f"合集：{collection}")
    cleanup_summary, source_excerpt, _ = build_cleanup_report(
        source_text=source_text,
        source_lines=source_lines,
        draft_messages=draft_messages,
        approved_messages=approved_messages or final_message,
    )
    lines.extend(["——清洗汇总——", cleanup_summary, "——关键时间戳节选——", source_excerpt])
    lines.extend(["——最终发布——", _as_text(approved_messages or final_message) or "（空）"])
    lines.append(f"验证：{_verification_text(verification)}")
    rpids_text = ",".join(str(x) for x in rpids) if not isinstance(rpids, str) else rpids
    lines.append(f"rpids：{rpids_text or '[]'}")
    lines.append(f"报告时间：{beijing_now()}")
    return "\n".join(lines)


def _error_title(reason: str) -> str:
    """按错误原因生成通知标题（区分抓取失败/发布失败等，不误导）。"""
    if "YouTube 抓取失败" in reason or "YouTube" in reason and ("抓取" in reason or "解析" in reason):
        return "⚠️YouTube 抓取失败"
    if "评论发布" in reason or "发布失败" in reason or "发布无响应" in reason or "删除旧评论" in reason:
        return "❌评论发布/处理失败"
    if "cookie" in reason.lower():
        return "⚠️Cookie 配置异常"
    return "❌处理失败"


def build_failure_brief(
    bvid: str,
    reason: str,
    title: str = "",
    collection: str = "",
    yt_link: str = "",
    source_text: str = "",
    source_lines: str = "",
    draft_messages: Any = None,
    approved_messages: Any = None,
    note: str = "",
    verification: Any = None,
    rpids: Iterable[str] | str = (),
    segments: int | str = 0,
    failures: Iterable[str] | str = (),
    status: str = "",
    commit: str = "",
    files: Iterable[str] | str = (),
    tests: Iterable[str] | str = (),
) -> str:
    """失败通知：按错误类型给标题，附视频标题、合集、B站/油管链接、原因、时间。"""
    del note, segments, files, tests
    bili_link = f"https://www.bilibili.com/video/{bvid}"
    lines = [_error_title(reason), bili_link]
    if title:
        lines.append(title)
    if collection:
        lines.append(f"合集：{collection}")
    if yt_link:
        lines.append(yt_link)
    if status:
        lines.append(f"状态：{status}")
    lines.append(f"commit：{commit or git_summary()}")
    failure_items = [str(x).strip() for x in failures if str(x).strip()] if not isinstance(failures, str) else [failures.strip()]
    failure_items = [x for x in failure_items if x and x != reason]
    reason_text = f"原因：{reason}"
    if failure_items:
        reason_text += f"；失败详情：{'; '.join(failure_items)}"
    lines.append(reason_text)
    cleanup_summary, source_excerpt, _ = build_cleanup_report(
        source_text=source_text,
        source_lines=source_lines,
        draft_messages=draft_messages,
        approved_messages=approved_messages,
    )
    lines.extend(["——清洗汇总——", cleanup_summary, "——关键时间戳节选——", source_excerpt])
    lines.extend(["——最终内容——", _as_text(approved_messages) or "（未提供）"])
    lines.append(f"验证：{_verification_text(verification)}")
    rpids_text = ",".join(str(x) for x in rpids) if not isinstance(rpids, str) else rpids
    lines.append(f"rpids：{rpids_text or '[]'}")
    lines.append(f"时间：{beijing_now()}")
    return "\n".join(lines)


def build_yt_rate_limit_brief(
    bvid: str,
    reason: str,
    *,
    files: Iterable[str] | str = (),
    tests: Iterable[str] | str = (),
    commit: str = "",
    verification: Any = None,
    rpids: Iterable[str] | str = (),
    segments: int | str = 0,
    failures: Iterable[str] | str = (),
) -> str:
    """YouTube 页面抓取限流（429）通知：提醒及时关注抓取频率/IP 风控。"""
    bili_link = f"https://www.bilibili.com/video/{bvid}"
    rpids_text = ",".join(str(x) for x in rpids) if not isinstance(rpids, str) else rpids
    failure_text = "; ".join(str(x) for x in failures) if not isinstance(failures, str) else failures
    file_text = _as_multiline(files)
    test_text = _as_multiline(tests)
    return "\n".join(
        [
            "⚠️YouTube 限流(429)",
            bili_link,
            f"原因：{reason}",
            "——原始来源——",
            "N/A（抓取失败，无发布内容）",
            "——清洗前后计数——",
            "N/A / N/A / N/A",
            "——本地草稿——",
            "N/A",
            "——最终发布内容——",
            "N/A",
            f"验证：{verification if verification is not None else 'N/A'}",
            f"rpids：{rpids_text or '[]'}",
            f"segments：{segments if segments not in (None, '') else 0}",
            f"failures：{failure_text or reason}",
            "——涉及文件——",
            file_text or "（未提供）",
            "——测试命令与结果——",
            test_text or "（未提供）",
            f"commit：{commit or git_summary()}",
            f"时间：{beijing_now()}",
        ]
    )


def build_crash_brief(
    traceback_text: str,
    *,
    files: Iterable[str] | str = (),
    tests: Iterable[str] | str = (),
    commit: str = "",
    verification: Any = None,
    rpids: Iterable[str] | str = (),
    segments: int | str = 0,
    failures: Iterable[str] | str = (),
) -> str:
    """整轮管线崩溃通知：任何未捕获异常都提醒，避免"很久没发"才发现。"""
    lines = (traceback_text or "").splitlines()
    # 提炼调用链（File "...", line N, in func）与最终异常
    frames = [ln.strip() for ln in lines if ln.strip().startswith("File ") and ", in " in ln]
    err_line = next((ln.strip() for ln in reversed(lines) if ln.strip() and not ln.strip().startswith(("Traceback", "File ", "    "))), "未知异常")
    frames_str = "\n".join(frames[-3:]) if frames else "（无堆栈）"
    rpids_text = ",".join(str(x) for x in rpids) if not isinstance(rpids, str) else rpids
    failure_text = "; ".join(str(x) for x in failures) if not isinstance(failures, str) else failures
    file_text = _as_multiline(files)
    test_text = _as_multiline(tests)
    return "\n".join(
        [
            "💥管线崩溃",
            f"异常：{err_line}",
            frames_str,
            "——原始来源——",
            "N/A（管线异常，无单条发布内容）",
            "——清洗前后计数——",
            "N/A / N/A / N/A",
            "——本地草稿——",
            "N/A",
            "——最终发布内容——",
            "N/A",
            f"验证：{verification if verification is not None else 'N/A'}",
            f"rpids：{rpids_text or '[]'}",
            f"segments：{segments if segments not in (None, '') else 0}",
            f"failures：{failure_text or err_line}",
            "——涉及文件——",
            file_text or "（未提供）",
            "——测试命令与结果——",
            test_text or "（未提供）",
            f"commit：{commit or git_summary()}",
            f"时间：{beijing_now()}",
        ]
    )


def extract_desc_profile(desc: str) -> str:
    """从 B 站简介提取「主播 + 原标题」两行，供成功通知展示。

    跳过首行 YouTube 链接、寒暄行（关注/谢谢/喵 等），只保留：
    - 主播行：`主播：xxx` 或 `主播/稿件上传者：xxx`
    - 原标题行：`原标题：xxx`
    找不到对应行则省略；全部找不到返回空串。
    """
    lines = [ln.strip() for ln in (desc or "").splitlines() if ln.strip()]
    parts: list[str] = []
    for ln in lines:
        if ln.startswith("http://") or ln.startswith("https://"):
            continue
        if "谢谢" in ln or "关注" in ln or "感谢" in ln or "喵" in ln:
            continue
        if ln.startswith("主播") or ln.startswith("主播/稿件上传者"):
            parts.append(ln)
        elif ln.startswith("原标题") or ln.startswith("原標題"):
            parts.append(ln)
    return "\n".join(parts)
