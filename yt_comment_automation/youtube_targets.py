"""在 WDC 上计算下一轮应交给 GitHub Action 的 YouTube ID。"""
from __future__ import annotations

import argparse
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
    posted = pipeline.load_processed(data_dir) - review.deleted_bvids(data_dir)
    pending_bvids = {
        str(item.get("bvid") or "")
        for item in review.list_comments(data_dir=data_dir, status="pending")
    }
    ignored = config.ignore_bvids()
    upgrade_ids = pipeline.load_upgrade_targets(data_dir)
    now = time.time()
    ids: list[str] = []
    for video in videos:
        if (
            not video.yt_id
            or video.bvid in posted
            or video.bvid in ignored
            or not config.in_codex_scope(video.bvid, part_date=video.part_date)
        ):
            continue
        # 新视频豁免必须优先于 pending 12 小时节流：歌单常延迟出现，
        # 新视频进审核队列后若被节流，就会在 setlist 刚贴出时整轮错过。
        interval = 0.0
        if not pipeline._is_new_video(video.part_date):
            if video.bvid in pending_bvids:
                interval = 12 * 3600.0
            elif video.part_date:
                interval = pipeline.OLD_VIDEO_REFETCH_HOURS * 3600.0
        last = float(fetch_times.get(video.yt_id) or 0.0)
        if not last or now - last >= interval:
            ids.append(video.yt_id)

    # 升级复查候选：上面 `bvid in posted` 已把它们排除，但 WDC 是 cache_only、
    # force 无效，不走 Action 就永远读不到新鲜缓存。这组目标很小（仅「已发
    # 歌单不足阈值」的视频），且一旦歌单补足会由 pipeline 主动从台账摘除。
    ids.extend(upgrade_ids.keys())
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
