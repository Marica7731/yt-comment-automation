"""Codex 审核队列命令行。

常用命令：
  python -m yt_comment_automation.review_cli list
  python -m yt_comment_automation.review_cli show --bvid BV1xxx
  python -m yt_comment_automation.review_cli approve --bvid BV1xxx --messages-file /tmp/msg.json
  python -m yt_comment_automation.review_cli apply --bvid BV1xxx
  python -m yt_comment_automation.review_cli verify --bvid BV1xxx
  python -m yt_comment_automation.review_cli recover-missing --bvid BV1xxx
  python -m yt_comment_automation.review_cli retry-with-artist --bvid BV1xxx
  python -m yt_comment_automation.review_cli retry-without-artist --bvid BV1xxx
  python -m yt_comment_automation.review_cli cleanup-retry-without-artist --bvid BV1xxx
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import review


def _messages_from_file(path: str) -> list[str]:
    raw = Path(path).read_text(encoding="utf-8")
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError("messages JSON 必须是字符串数组")
        return [str(x) for x in data]
    if stripped.startswith("{"):
        data = json.loads(stripped)
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return [str(x) for x in data["messages"]]
        raise ValueError("messages JSON 对象必须包含 messages 数组")
    return [part.strip() for part in raw.split("\n---\n") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex 歌单审核队列")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出审核队列")
    p_list.add_argument(
        "--status",
        choices=["pending", "approved", "applying", "applied", "applied_unverified", "deleted", "all"],
        default="all",
    )

    p_show = sub.add_parser("show", help="显示一个审核文件")
    p_show.add_argument("--bvid", required=True)

    p_approve = sub.add_parser("approve", help="保存 Codex 审核通过的评论")
    p_approve.add_argument("--bvid", required=True)
    source_group = p_approve.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--messages-file", help="审核后的 messages JSON/分隔文本")
    source_group.add_argument("--use-draft", action="store_true", help="直接批准当前 draft_messages")
    p_approve.add_argument("--reviewer", default="codex")
    p_approve.add_argument("--note", default="")

    p_apply = sub.add_parser("apply", help="由 WDC 发布已审核评论并回读验收")
    p_apply.add_argument("--bvid", required=True)
    p_apply.add_argument("--dry-run", action="store_true")

    p_verify = sub.add_parser("verify", help="只回读已发布评论，不重复发布")
    p_verify.add_argument("--bvid", required=True)

    p_recover = sub.add_parser("recover-missing", help="确认评论不存在后补发一次")
    p_recover.add_argument("--bvid", required=True)

    p_reapprove = sub.add_parser(
        "reapprove-rejected",
        help="顶层不可见按驳回处理，保存修正文案后重发一次",
    )
    p_reapprove.add_argument("--bvid", required=True)
    p_reapprove.add_argument("--messages-file", required=True)
    p_reapprove.add_argument("--reviewer", default="codex")
    p_reapprove.add_argument("--note", default="")

    p_retry = sub.add_parser("retry-without-artist", help="被隐藏时去歌手重试一次")
    p_retry.add_argument("--bvid", required=True)

    p_retry_artist = sub.add_parser("retry-with-artist", help="未发出时带歌手原文重试一次")
    p_retry_artist.add_argument("--bvid", required=True)

    p_cleanup_retry = sub.add_parser("cleanup-retry-without-artist", help="删除重复评论后发布无歌手版本")
    p_cleanup_retry.add_argument("--bvid", required=True)
    p_cleanup_retry.add_argument(
        "--delete-only",
        action="store_true",
        help="按完整归属门禁删除已发布评论，不重发",
    )

    p_mark_invalid = sub.add_parser(
        "mark-raw-fetch-invalid", help="将未发布候选标记为本轮强制抓取无效"
    )
    p_mark_invalid.add_argument("--bvid", required=True)
    p_mark_invalid.add_argument(
        "--reason", default="raw_fetch_invalid: forced raw returned empty description/comments"
    )
    p_mark_invalid.add_argument("--started-at", default="")
    p_mark_invalid.add_argument("--finished-at", default="")

    args = parser.parse_args(argv)
    if args.command == "list":
        items = review.list_comments(status=None if args.status == "all" else args.status)
        for item in items:
            print(
                f"{item.get('status', '?'):20} {item.get('bvid', '?'):14} "
                f"draft={item.get('draft_song_count', 0):>3} "
                f"approved={len(item.get('approved_messages') or []):>3} "
                f"{item.get('title', '')[:48]}"
            )
        print(f"total={len(items)}")
        return 0
    if args.command == "show":
        print(json.dumps(review.load_comment(args.bvid), ensure_ascii=False, indent=2))
        return 0
    if args.command == "approve":
        messages = (
            [str(m) for m in review.load_comment(args.bvid).get("draft_messages") or []]
            if args.use_draft
            else _messages_from_file(args.messages_file)
        )
        item = review.approve_comment(
            args.bvid,
            messages,
            reviewer=args.reviewer,
            note=args.note,
        )
        print(json.dumps({"bvid": item["bvid"], "status": item["status"], "messages": len(item["approved_messages"])}, ensure_ascii=False))
        return 0
    if args.command == "apply":
        try:
            item = review.apply_comment(args.bvid, dry_run=args.dry_run)
        except Exception as err:
            review.notify_apply_failure(args.bvid, str(err))
            raise
        print(json.dumps({"bvid": item["bvid"], "status": item.get("status"), "verification": item.get("verification")}, ensure_ascii=False))
        return 0 if item.get("status") in {"applied", "dry_run"} else 1
    if args.command == "verify":
        item = review.reverify_applied(args.bvid)
        print(json.dumps({"bvid": item["bvid"], "status": item.get("status"), "verification": item.get("verification")}, ensure_ascii=False))
        return 0 if item.get("status") == "applied" else 1
    if args.command == "recover-missing":
        item = review.recover_missing_comment(args.bvid)
        print(json.dumps({"bvid": item["bvid"], "status": item.get("status"), "verification": item.get("verification")}, ensure_ascii=False))
        return 0 if item.get("status") == "applied" else 1
    if args.command == "retry-without-artist":
        item = review.retry_without_artist(args.bvid)
        print(json.dumps({"bvid": item["bvid"], "status": item.get("status"), "verification": item.get("verification")}, ensure_ascii=False))
        return 0 if item.get("status") == "applied" else 1
    if args.command == "retry-with-artist":
        item = review.retry_with_artist(args.bvid)
        print(json.dumps({"bvid": item["bvid"], "status": item.get("status"), "verification": item.get("verification")}, ensure_ascii=False))
        return 0 if item.get("status") == "applied" else 1
    if args.command == "cleanup-retry-without-artist":
        item = review.cleanup_duplicates_and_retry_without_artist(
            args.bvid, delete_only=args.delete_only
        )
        print(json.dumps({"bvid": item["bvid"], "status": item.get("status"), "verification": item.get("verification"), "deleted_rpids": item.get("deleted_rpids")}, ensure_ascii=False))
        return 0 if item.get("status") in {"applied", "deleted"} else 1
    if args.command == "reapprove-rejected":
        item = review.reapprove_rejected(
            args.bvid,
            _messages_from_file(args.messages_file),
            reviewer=args.reviewer,
            note=args.note,
        )
        print(
            json.dumps(
                {
                    "bvid": item["bvid"],
                    "status": item.get("status"),
                    "verification": item.get("verification"),
                    "previous_rpids": item.get("previous_rpids"),
                    "rpids": item.get("rpids"),
                },
                ensure_ascii=False,
            )
        )
        return 0 if item.get("status") == "applied" else 1
    if args.command == "mark-raw-fetch-invalid":
        item = review.mark_raw_fetch_invalid(
            args.bvid,
            args.reason,
            started_at=args.started_at,
            finished_at=args.finished_at,
        )
        print(
            json.dumps(
                {
                    "bvid": item["bvid"],
                    "status": item.get("status"),
                    "result": item.get("result"),
                    "error": item.get("error"),
                },
                ensure_ascii=False,
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
