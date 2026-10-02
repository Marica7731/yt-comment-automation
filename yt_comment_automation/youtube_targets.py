"""在 WDC 上计算下一轮应交给 GitHub Action 的 YouTube ID。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

from . import collections, config, pipeline, review


def due_targets(data_dir: Path, refresh: bool = False) -> list[str]:
    if refresh:
        videos = collections.fetch_all_collections()
        collections.save_snapshot(videos, path=data_dir / "collections_snapshot.json")
    else:
        videos = collections.load_snapshot(path=data_dir / "collections_snapshot.json").videos

    try:
        fetch_times = json.loads((data_dir / "yt_raw" / "fetch_times.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fetch_times = {}
    posted = pipeline.load_processed(data_dir)
    pending_bvids = {
        str(item.get("bvid") or "")
        for item in review.list_comments(data_dir=data_dir, status="pending")
    }
    ignored = config.ignore_bvids()
    now = time.time()
    ids: list[str] = []
    for video in videos:
        if not video.yt_id or video.bvid in posted or video.bvid in ignored:
            continue
        interval = 0.0
        if video.bvid in pending_bvids:
            interval = 12 * 3600.0
        elif video.part_date:
            try:
                age_days = (dt.date.today() - dt.date.fromisoformat(video.part_date)).days
            except ValueError:
                age_days = 999
            if age_days > pipeline.NEW_VIDEO_DAYS:
                interval = pipeline.OLD_VIDEO_REFETCH_HOURS * 3600.0
        last = float(fetch_times.get(video.yt_id) or 0.0)
        if not last or now - last >= interval:
            ids.append(video.yt_id)
    return list(dict.fromkeys(ids))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="列出 GitHub Action 待抓 YouTube ID")
    parser.add_argument("--data-dir", default=str(config.data_dir()))
    parser.add_argument("--refresh", action="store_true", help="先在 WDC 刷新 B 站合集快照")
    parser.add_argument("--format", choices=["json", "lines"], default="json")
    args = parser.parse_args(argv)
    ids = due_targets(Path(args.data_dir), refresh=args.refresh)
    if args.format == "lines":
        print("\n".join(ids))
    else:
        print(json.dumps(ids, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
