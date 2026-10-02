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


def _timestamp_lines(value: Any) -> list[str]:
    text = _as_text(value)
    ts_re = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
    return [line.strip() for line in text.splitlines() if line.strip() and ts_re.search(line)]


def _clean_diff_reason(line: str, draft_lines: set[str], final_lines: set[str]) -> str:
    if line not in draft_lines:
        if not re.search(r"\d{1,2}:\d{2}(?::\d{2})?", line):
            return "非歌单标记（无有效时间戳）"
        if re.search(r"MC|開場|エンディング|エンドカード|話|トーク|掃除|声入り|开始|結束", line, re.I):
            return "节目/谈话标记，不属于歌曲"
        return "本地规则未识别为歌单"
    if line not in final_lines:
        return "Codex 审核删除或改写"
    return "格式规范化"


def build_cleanup_report(
    source_text: str = "",
    source_lines: str = "",
    draft_messages: Any = None,
    approved_messages: Any = None,
    note: str = "",
) -> tuple[str, str, str, str]:
    """Build counts plus deterministic removed/changed explanations."""
    raw_lines = _timestamp_lines(source_lines or source_text)
    draft_lines = _timestamp_lines(draft_messages)
    final_lines = _timestamp_lines(approved_messages)
    draft_set, final_set = set(draft_lines), set(final_lines)
    removed = [line for line in raw_lines if line not in draft_set and line not in final_set]
    changed = [
        (old, new)
        for old, new in zip(raw_lines, final_lines)
        if old != new and old in draft_set or old not in draft_set and new in final_set
    ]
    added = [line for line in final_lines if line not in raw_lines]
    details: list[str] = []
    for line in removed:
        details.append(f"- 删除：{line}\n  原因：{_clean_diff_reason(line, draft_set, final_set)}")
    for old, new in changed:
        reason = "格式规范化" if re.sub(r"\s+", "", old) == re.sub(r"\s+", "", new) else "Codex 审核修正"
        details.append(f"- 修改：{old}\n  改为：{new}\n  原因：{reason}")
    for line in added:
        details.append(f"- 新增：{line}\n  原因：Codex 审核补充")
    if not details:
        details.append("- 无删除、修改或新增；原始时间戳行全部保留")
    counts = (
        f"原始时间戳行：{len(raw_lines)} → 本地草稿行：{len(draft_lines)} → 最终发布行：{len(final_lines)}\n"
        f"删除 {len(removed)} 行，修改 {len(changed)} 行，新增 {len(added)} 行"
    )
    if note:
        details.append(f"- 审核备注：{note}")
    return counts, "\n".join(details), _as_text(source_text), _as_text(source_lines)


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
    """Detailed success report with source/draft/final content and verification."""
    bili_link = f"https://www.bilibili.com/video/{bvid}"
    lines = [
        "✅评论发送成功（Codex 详细报告）",
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
    if profile:
        lines.append(profile)
    counts, diff_report, raw_source, raw_lines = build_cleanup_report(
        source_text=source_text,
        source_lines=source_lines,
        draft_messages=draft_messages,
        approved_messages=approved_messages or final_message,
        note=note,
    )
    lines.extend(["——清洗前后计数——", counts, "——清洗差异与原因——", diff_report])
    lines.extend(["——原始来源——", raw_source or raw_lines or "（未提供）"])
    if draft_messages is not None:
        lines.extend(["——本地草稿——", _as_text(draft_messages) or "（空）"])
    lines.extend(["——最终发布——", _as_text(approved_messages or final_message) or "（空）"])
    if verification is not None:
        lines.append(f"验证：{verification}")
    rpids_text = ",".join(str(x) for x in rpids) if not isinstance(rpids, str) else rpids
    failure_text = "; ".join(str(x) for x in failures) if not isinstance(failures, str) else failures
    lines.append(f"rpids：{rpids_text or '[]'}")
    lines.append(f"segments：{segments if segments not in (None, '') else 0}")
    lines.append(f"failures：{failure_text or '[]'}")
    if note:
        lines.append(f"审核备注：{note}")
    file_text = _as_multiline(files)
    test_text = _as_multiline(tests)
    lines.extend(["——涉及文件——", file_text or "（未提供）"])
    lines.extend(["——测试命令与结果——", test_text or "（未提供）"])
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
    lines.append(f"原因：{reason}")
    if source_text or source_lines or draft_messages is not None or approved_messages is not None:
        counts, diff_report, raw_source, raw_lines = build_cleanup_report(
            source_text=source_text,
            source_lines=source_lines,
            draft_messages=draft_messages,
            approved_messages=approved_messages,
            note=note,
        )
        lines.extend(["——清洗前后计数——", counts, "——清洗差异与原因——", diff_report])
        lines.extend(["——原始来源——", raw_source or raw_lines or "（未提供）"])
        if draft_messages is not None:
            lines.extend(["——本地草稿——", _as_text(draft_messages) or "（空）"])
        if approved_messages is not None:
            lines.extend(["——最终内容——", _as_text(approved_messages) or "（空）"])
    if verification is not None:
        lines.append(f"验证：{verification}")
    rpids_text = ",".join(str(x) for x in rpids) if not isinstance(rpids, str) else rpids
    failure_text = "; ".join(str(x) for x in failures) if not isinstance(failures, str) else failures
    lines.append(f"rpids：{rpids_text or '[]'}")
    lines.append(f"segments：{segments if segments not in (None, '') else 0}")
    lines.append(f"failures：{failure_text or '[]'}")
    if note:
        lines.append(f"审核备注：{note}")
    file_text = _as_multiline(files)
    test_text = _as_multiline(tests)
    lines.extend(["——涉及文件——", file_text or "（未提供）"])
    lines.extend(["——测试命令与结果——", test_text or "（未提供）"])
    lines.append(f"时间：{beijing_now()}")
    return "\n".join(lines)


def build_yt_rate_limit_brief(bvid: str, reason: str) -> str:
    """YouTube 页面抓取限流（429）通知：提醒及时关注抓取频率/IP 风控。"""
    bili_link = f"https://www.bilibili.com/video/{bvid}"
    return "\n".join(
        [
            "⚠️YouTube 限流(429)",
            bili_link,
            f"原因：{reason}",
            f"时间：{beijing_now()}",
        ]
    )


def build_crash_brief(traceback_text: str) -> str:
    """整轮管线崩溃通知：任何未捕获异常都提醒，避免"很久没发"才发现。"""
    lines = (traceback_text or "").splitlines()
    # 提炼调用链（File "...", line N, in func）与最终异常
    frames = [ln.strip() for ln in lines if ln.strip().startswith("File ") and ", in " in ln]
    err_line = next((ln.strip() for ln in reversed(lines) if ln.strip() and not ln.strip().startswith(("Traceback", "File ", "    "))), "未知异常")
    frames_str = "\n".join(frames[-3:]) if frames else "（无堆栈）"
    return "\n".join(
        [
            "💥管线崩溃",
            f"异常：{err_line}",
            frames_str,
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
