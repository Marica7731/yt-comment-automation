"""Codex 点赞审核命令行。

常用命令：
  python -m yt_comment_automation.like_review_cli list
  python -m yt_comment_automation.like_review_cli show --rpid 123
  python -m yt_comment_automation.like_review_cli approve --rpid 123 --max-count 5
  python -m yt_comment_automation.like_review_cli reject --rpid 123

真实 action 由 `python like_fans.py --apply data/like_review.json` 执行，
执行前会重新复核服务器点赞状态，避免 toggle 误取消。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config, like_review


def _rpids(values: list[str | int]) -> list[str]:
    return [str(value) for value in values]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex 点赞审核队列")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出点赞候选")
    p_list.add_argument(
        "--status",
        choices=["pending", "approved", "applied", "rejected", "failed", "all"],
        default="all",
    )

    p_show = sub.add_parser("show", help="显示一个点赞候选")
    p_show.add_argument("--rpid", required=True)

    p_approve = sub.add_parser("approve", help="批准点赞候选")
    p_approve.add_argument("--rpid", action="append", required=True)
    p_approve.add_argument("--max-count", type=int)
    p_approve.add_argument("--reviewer", default="codex")
    p_approve.add_argument("--note", default="")

    p_reject = sub.add_parser("reject", help="拒绝点赞候选")
    p_reject.add_argument("--rpid", action="append", required=True)
    p_reject.add_argument("--reviewer", default="codex")
    p_reject.add_argument("--note", default="")

    args = parser.parse_args(argv)
    path = Path(config.data_dir()) / "like_review.json"

    if args.command == "list":
        payload = like_review.load_review(path)
        items = payload.get("candidates") or []
        if args.status != "all":
            items = [item for item in items if str(item.get("status") or "pending") == args.status]
        for item in items:
            print(
                f"{str(item.get('status') or 'pending'):10} "
                f"rpid={item.get('rpid')} oid={item.get('oid')} "
                f"source={item.get('source', '')} {str(item.get('content', ''))[:60]}"
            )
        print("counts=" + json.dumps(like_review.summarize(payload), ensure_ascii=False))
        return 0

    if args.command == "show":
        payload = like_review.load_review(path)
        key = str(args.rpid)
        item = next((x for x in payload.get("candidates") or [] if str(x.get("rpid")) == key), None)
        if item is None:
            raise FileNotFoundError(f"审核文件中不存在 rpid={key}")
        print(json.dumps(item, ensure_ascii=False, indent=2))
        return 0

    if args.command == "approve":
        payload = like_review.approve(
            _rpids(args.rpid),
            path,
            reviewer=args.reviewer,
            note=args.note,
            max_count=args.max_count,
        )
        print(json.dumps({"approved": _rpids(args.rpid), "counts": like_review.summarize(payload)}, ensure_ascii=False))
        return 0

    if args.command == "reject":
        payload = like_review.reject(_rpids(args.rpid), path, reviewer=args.reviewer, note=args.note)
        print(json.dumps({"rejected": _rpids(args.rpid), "counts": like_review.summarize(payload)}, ensure_ascii=False))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
