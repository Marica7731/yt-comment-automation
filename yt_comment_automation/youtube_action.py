"""GitHub Action 内执行的 YouTube 抓取与结果打包。"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import yt_fetch


def run(video_ids: list[str], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "video_ids": video_ids,
        "results": {},
        "failures": [],
    }
    for video_id in video_ids:
        try:
            raw = yt_fetch.fetch_youtube_raw(video_id, cache_dir=cache_dir, force=True)
            payload["results"][video_id] = raw
        except Exception as err:  # noqa: BLE001
            payload["failures"].append(
                {"video_id": video_id, "error": f"{type(err).__name__}: {err}"}
            )
    for name in ("fetch_times.json", "yt_comment_ids.json"):
        path = cache_dir / name
        if path.is_file():
            payload[name] = json.loads(path.read_text(encoding="utf-8"))
    (output_dir / "payload.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GitHub Action YouTube 抓取")
    parser.add_argument("--video-ids", required=True, help="逗号分隔的 YouTube ID")
    parser.add_argument("--output-dir", default="/tmp/youtube-action")
    args = parser.parse_args(argv)
    video_ids = [item.strip() for item in args.video_ids.split(",") if item.strip()]
    payload = run(video_ids, Path(args.output_dir))
    print(json.dumps({"fetched": len(payload["results"]), "failures": payload["failures"]}, ensure_ascii=False))
    return 1 if payload["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
