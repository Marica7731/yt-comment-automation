"""Codex 内容审核队列。

生产管线只负责抓取、生成候选和落盘；歌单文本由 Codex 审核并通过本模块
显式应用到 WDC。审核文件保留原始来源与审核元数据，确保只有 Codex 批准内容进入
发布接口。
"""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path
from typing import Any

from . import bili_comment, clean, config, notify


def review_dir(data_dir: Path | None = None) -> Path:
    path = (data_dir or config.data_dir()) / "codex_review"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def queue_comment(payload: dict[str, Any], data_dir: Path | None = None) -> Path:
    """写入或更新一个待审核歌单；已审核/已应用的文件不被 cron 覆盖。"""
    bvid = str(payload.get("bvid") or "").strip()
    if not bvid:
        raise ValueError("审核队列缺少 bvid")
    path = review_dir(data_dir) / f"{bvid}.json"
    if path.exists():
        try:
            current = _load(path)
        except (OSError, ValueError):
            current = {}
        if current.get("status") in {"approved", "applying", "applied", "applied_unverified"}:
            return path
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    payload = dict(payload)
    payload.update({"bvid": bvid, "status": "pending", "queued_at": now, "updated_at": now})
    _write_json(path, payload)
    return path


def load_comment(bvid: str, data_dir: Path | None = None) -> dict[str, Any]:
    path = review_dir(data_dir) / f"{bvid}.json"
    if not path.is_file():
        raise FileNotFoundError(f"没有该视频的审核文件: {path}")
    return _load(path)


def notify_apply_failure(
    bvid: str,
    reason: str,
    data_dir: Path | None = None,
) -> tuple[bool, str]:
    """为 apply 异常生成并发送详细失败报告；通知失败不覆盖原始异常。"""
    try:
        item = load_comment(bvid, data_dir=data_dir)
    except Exception as load_err:  # noqa: BLE001
        item = {"bvid": bvid, "title": "", "collection": ""}
        reason = f"{reason}；读取审核文件失败: {load_err}"

    failures = [str(x) for x in item.get("failures") or [] if str(x).strip()]
    if reason not in failures:
        failures.append(reason)
    approved = [str(x) for x in item.get("approved_messages") or []]
    try:
        segments = int(item.get("segments") or 0)
    except (TypeError, ValueError):
        segments = 0
    status = str(item.get("status") or "failed")
    brief = notify.build_failure_brief(
        bvid=bvid,
        reason=reason,
        title=str(item.get("title") or ""),
        collection=str(item.get("collection") or ""),
        yt_link=f"https://youtu.be/{item.get('yt_id', '')}" if item.get("yt_id") else "",
        source_text=str(item.get("source_text") or ""),
        source_lines=str(item.get("source_lines") or ""),
        draft_messages=item.get("draft_messages", []),
        approved_messages=approved,
        note=str(item.get("note") or ""),
        verification=item.get("verification"),
        rpids=item.get("rpids") or [],
        segments=segments,
        failures=failures,
        status=status,
        commit=notify.git_summary(),
        files=[
            "yt_comment_automation/review.py",
            "yt_comment_automation/review_cli.py",
            "yt_comment_automation/bili_comment.py",
            f"data/codex_review/{bvid}.json",
        ],
        tests=[
            f"review_cli apply --bvid {bvid} → exception: {reason}",
            f"status={status}",
        ],
    )
    try:
        return notify.send_feishu_message(brief)
    except Exception as notify_err:  # noqa: BLE001
        return False, f"失败报告发送异常: {notify_err}"


def list_comments(data_dir: Path | None = None, status: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(review_dir(data_dir).glob("*.json")):
        try:
            item = _load(path)
        except (OSError, ValueError):
            continue
        if status is None or item.get("status") == status:
            if status == "pending" and not config.in_codex_scope(
                str(item.get("bvid") or ""),
                part_date=str(item.get("part_date") or ""),
                queued_at=str(item.get("queued_at") or ""),
            ):
                continue
            out.append(item)
    return out


def approve_comment(
    bvid: str,
    messages: list[str],
    data_dir: Path | None = None,
    reviewer: str = "codex",
    note: str = "",
) -> dict[str, Any]:
    """保存 Codex 审核通过的评论内容；此处不执行网络发布。"""
    cleaned = [m.strip() for m in messages if m and m.strip()]
    if not cleaned:
        raise ValueError("审核通过的评论内容为空")
    item = load_comment(bvid, data_dir)
    if item.get("status") in {"applied", "applied_unverified"}:
        raise RuntimeError(f"{bvid} 已经发布，不能重复审核")
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    item.update(
        {
            "status": "approved",
            "approved_messages": cleaned,
            "reviewer": reviewer,
            "note": note,
            "reviewed_at": now,
            "updated_at": now,
        }
    )
    _write_json(review_dir(data_dir) / f"{bvid}.json", item)
    return item


def _mark_processed(data_dir: Path, bvid: str) -> None:
    path = data_dir / "processed.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    posted = set(payload.get("posted") or [])
    posted.add(bvid)
    payload = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "posted": sorted(posted)}
    _write_json(path, payload)


def _fetch_video_pages(bvid: str, cookies: dict[str, str]) -> list[dict[str, Any]]:
    """读取 B 站分 P 和时长；多条主评论发布前必须有可验证的批次依据。"""
    data = bili_comment._request_json(
        f"{bili_comment.VIEW_API}?bvid={bvid}",
        cookies,
        f"https://www.bilibili.com/video/{bvid}",
    )
    if data.get("code") != 0:
        raise RuntimeError(f"读取视频时长失败: {data.get('message')}")
    body = data.get("data") or {}
    pages = [
        {"page": p.get("page"), "duration": int(p.get("duration") or 0)}
        for p in (body.get("pages") or [])
        if isinstance(p, dict)
    ]
    if not pages and int(body.get("duration") or 0) > 0:
        pages = [{"page": 1, "duration": int(body["duration"])}]
    return pages


def _group_messages_by_pages(messages: list[str], pages: list[dict[str, Any]]) -> list[str]:
    """单 P 合并成一条；多 P 按页面时长边界切分，禁止按歌曲条数拆顶层评论。"""
    lines = [line.strip() for message in messages for line in str(message).splitlines() if line.strip()]
    if not lines:
        raise ValueError("待发布评论为空")
    if len(pages) <= 1:
        return [chr(10).join(lines)]

    if len(messages) == len(pages):
        first_lines = [str(message).splitlines()[0].strip() for message in messages if str(message).splitlines()]
        if all(re.fullmatch(r"P\d+", line or "") for line in first_lines):
            return [chr(10).join(str(message).splitlines()) for message in messages]

    durations = [max(0, int(page.get("duration") or 0)) for page in pages]
    if not durations or sum(durations) <= 0:
        raise RuntimeError("视频分 P 时长无效，拒绝猜测发布批次")
    bounds = [0]
    for duration in durations:
        bounds.append(bounds[-1] + duration)
    page_lines: list[list[str]] = [[] for _ in durations]
    for line in lines:
        timestamp = clean.extract_first_timestamp_info(line)
        seconds = timestamp.get("seconds")
        if seconds is None:
            raise RuntimeError(f"多 P 歌单缺少可解析时间戳，拒绝发布: {line}")
        page_index = len(durations) - 1
        for index in range(len(durations)):
            if bounds[index] <= int(seconds) < bounds[index + 1]:
                page_index = index
                break
        page_lines[page_index].append(line)
    grouped = []
    for index, group in enumerate(page_lines, 1):
        if group:
            grouped.append(f"P{index}{chr(10)}{chr(10).join(group)}")
    if not grouped:
        raise RuntimeError("按视频时长切分后没有可发布内容")
    return grouped


def _normalize_publish_batches(
    bvid: str, messages: list[str], cookies: dict[str, str]
) -> list[str]:
    cleaned = [str(message).strip() for message in messages if str(message).strip()]
    if len(cleaned) <= 1:
        return cleaned
    pages = _fetch_video_pages(bvid, cookies)
    if not pages:
        raise RuntimeError("无法读取视频分 P/时长，拒绝发布多条主评论")
    return _group_messages_by_pages(cleaned, pages)


def verify_own_comments(bvid: str, messages: list[str], cookies: dict[str, str]) -> tuple[bool, str]:
    """回读评论区，确认每个已审核主评论的第一段确实可见。"""
    try:
        own = bili_comment.find_own_comments(bvid, cookies)
        actual = [_normalize_comment_for_compare(cm.message) for cm in own]
        expected = []
        for message in messages:
            segments = bili_comment.split_message_by_lines(message)
            if segments:
                expected.append(segments[0])
        expected = [_normalize_comment_for_compare(text) for text in expected]
        missing = [text for text in expected if text not in actual]
        if missing:
            return False, f"回读缺失 {len(missing)}/{len(expected)} 条: {missing[0][:80]}"
        if len(own) != len(expected):
            return False, f"回读顶层评论数 {len(own)} != 预期 {len(expected)}"
        return True, f"回读通过 {len(expected)} 条顶层评论"
    except Exception as err:  # noqa: BLE001
        return False, f"评论区回读失败: {err}"


def apply_comment(
    bvid: str,
    data_dir: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """把已审核歌单交给 WDC 的 B 站接口发布，回读评论区并记录结果。"""
    item = load_comment(bvid, data_dir)
    messages = [str(m) for m in item.get("approved_messages") or [] if str(m).strip()]
    if item.get("status") != "approved" or not messages:
        raise RuntimeError(f"{bvid} 尚未通过审核或没有已审核内容")
    if dry_run:
        return {"bvid": bvid, "status": "dry_run", "messages": messages}

    data_path = review_dir(data_dir) / f"{bvid}.json"
    cookies = bili_comment.load_cookie_map()
    try:
        messages = _normalize_publish_batches(bvid, messages, cookies)
    except Exception as err:  # noqa: BLE001
        error = f"发布批次校验失败: {err}"
        item.update({"status": "approved", "error": error, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        _write_json(data_path, item)
        raise RuntimeError(error) from err
    item["approved_messages"] = messages
    item["status"] = "applying"
    item["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _write_json(data_path, item)

    if bool(item.get("upgrade_mode")):
        for cm in bili_comment.find_own_comments(bvid, cookies):
            resp = bili_comment.delete_comment(bvid, cm.rpid, cookies)
            if resp.get("code") != 0:
                error = f"删除旧评论失败: rpid={cm.rpid} code={resp.get('code')}"
                item.update({"status": "approved", "error": error, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
                _write_json(data_path, item)
                raise RuntimeError(error)

    rpids: list[str] = []
    failures: list[str] = []
    segments = 0
    for idx, message in enumerate(messages, 1):
        responses = bili_comment.post_comment_with_replies(bvid, message, cookies)
        if not responses:
            failures.append(f"P{idx}:无响应")
            continue
        main = responses[0]
        if main.get("code") != 0:
            failures.append(f"P{idx}:code={main.get('code')} msg={main.get('message')}")
            continue
        rpids.extend(str(r.get("data", {}).get("rpid", "")) for r in responses if r.get("data"))
        segments += len(responses)
        bad = next((r for r in responses[1:] if r.get("code") != 0), None)
        if bad:
            failures.append(f"P{idx}楼中楼:code={bad.get('code')}")

    if not rpids:
        error = "评论发布失败: " + ("; ".join(failures) or "无响应")
        item.update({"status": "approved", "error": error, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        _write_json(data_path, item)
        raise RuntimeError(error)

    verified, verify_detail = verify_own_comments(bvid, messages, cookies)
    item.update(
        {
            "status": "applied" if verified else "applied_unverified",
            "rpids": rpids,
            "segments": segments,
            "failures": failures,
            "verification": {
                "ok": verified,
                "detail": verify_detail,
                "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            "applied_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    )
    item.pop("error", None)
    _write_json(data_path, item)
    _mark_processed(Path(data_dir or config.data_dir()), bvid)

    try:
        commit = notify.git_summary()
        if verified:
            brief = notify.build_success_brief(
                files=[
                    "yt_comment_automation/review.py",
                    "yt_comment_automation/bili_comment.py",
                    f"data/review/{bvid}.json",
                ],
                tests=[
                    f"review_cli apply --bvid {bvid} → status={item.get('status', '')}",
                    f"verification → {verify_detail}",
                ],
                bvid=bvid,
                yt_link=f"https://youtu.be/{item.get('yt_id', '')}" if item.get("yt_id") else "",
                posted_at=notify.beijing_now(),
                song_count=int(item.get("song_count") or 0),
                profile=item.get("desc_profile", ""),
                source_lines=item.get("source_lines", ""),
                final_message="\n---\n".join(messages),
                source_text=item.get("source_text", ""),
                draft_messages=item.get("draft_messages", []),
                approved_messages=messages,
                note=item.get("note", ""),
                verification=item.get("verification"),
                rpids=rpids,
                segments=segments,
                failures=failures,
                status=item.get("status", ""),
                commit=commit,
                title=item.get("title", ""),
                collection=item.get("collection", ""),
            )
        else:
            brief = notify.build_failure_brief(
                bvid=bvid,
                reason=f"评论已发布但回读验收失败：{verify_detail}",
                title=item.get("title", ""),
                collection=item.get("collection", ""),
                files=[
                    "yt_comment_automation/review.py",
                    "yt_comment_automation/bili_comment.py",
                    f"data/review/{bvid}.json",
                ],
                tests=[
                    f"review_cli apply --bvid {bvid} → status={item.get('status', '')}",
                    f"verification → {verify_detail}",
                ],
                yt_link=f"https://youtu.be/{item.get('yt_id', '')}" if item.get("yt_id") else "",
                source_text=item.get("source_text", ""),
                source_lines=item.get("source_lines", ""),
                draft_messages=item.get("draft_messages", []),
                approved_messages=messages,
                note=item.get("note", ""),
                verification=item.get("verification"),
                rpids=rpids,
                segments=segments,
                failures=failures,
                status=item.get("status", ""),
                commit=commit,
            )
        notify.send_feishu_message(brief)
    except Exception:  # noqa: BLE001
        pass
    return item
def _normalize_comment_for_compare(text: str) -> str:
    """Normalize Bilibili HTML entities and line endings before comparison."""
    return html.unescape(text or "").replace("\r\n", "\n").strip()
