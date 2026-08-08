#!/usr/bin/env python3
"""yt-comment-automation CLI。

用法：
  python -m yt_comment_automation.cli scan            # 只列出合集视频与新增，不抓评论不发布
  python -m yt_comment_automation.cli dry-run [--limit N] [--bvid BV1xxx]   # 干跑（不发布不通知）
  python -m yt_comment_automation.cli run [--mode incremental|full] [--limit N] [--bvid BV1xxx]  # 正式运行
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import collections, config


def main() -> int:
    parser = argparse.ArgumentParser(description="B站合集视频评论区时间戳歌轴自动发布")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="只列出合集视频与新增，不抓评论不发布")
    p_dry = sub.add_parser("dry-run", help="干跑（不发布不通知）")
    p_dry.add_argument("--limit", type=int, default=0, help="最多处理 N 个视频（0=不限）")
    p_dry.add_argument("--bvid", action="append", default=[], help="只处理指定 bvid（可重复）")

    p_run = sub.add_parser("run", help="正式运行（发布 + 飞书通知）")
    p_run.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    p_run.add_argument("--limit", type=int, default=0, help="最多处理 N 个视频（0=不限）")
    p_run.add_argument("--bvid", action="append", default=[], help="只处理指定 bvid（可重复）")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    if args.command == "scan":
        videos = collections.fetch_all_collections()
        print(f"合集视频总数: {len(videos)}")
        snapshot = collections.load_snapshot()
        new_videos = collections.detect_new_videos(videos, snapshot)
        print(f"相对上次快照新增: {len(new_videos)}")
        for v in videos:
            mark = " [NEW]" if v.bvid in {n.bvid for n in new_videos} else ""
            print(f"  {v.part_date} {v.bvid} {v.yt_id or '(无YT)'} [{v.collection}/{v.section}]{mark} {v.title[:50]}")
        return 0

    from . import pipeline

    # dry-run 命令强制不发布；run 命令默认遵守 DRY_RUN 环境变量（未设置时默认 1=干跑，避免误发）
    if args.command == "dry-run":
        dry_run = True
    else:
        dry_run = config.dry_run()
        if dry_run:
            print("DRY_RUN=1：仅干跑不发布（如要真实发布请 export DRY_RUN=0）")
    bvids = args.bvid or None
    if bvids:
        mode = "specific"
    else:
        mode = "incremental"

    record = pipeline.run_pipeline(mode=mode, dry_run=dry_run, limit=args.limit, specific_bvids=bvids)

    print("\n===== 本轮结果 =====")
    for r in record.results:
        print(
            f"  {r['bvid']} {r['part_date']} → {r['status']} "
            f"({r['song_count']} 首, source={r['source']}) {r.get('detail') or r.get('error') or ''}"
        )
    posted = [r for r in record.results if r["status"] == "posted"]
    print(f"\n本轮成功发布: {len(posted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
