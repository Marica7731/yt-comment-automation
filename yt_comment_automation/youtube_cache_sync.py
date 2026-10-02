"""把 GitHub Action 上传的 payload 合并到 WDC 本地 YouTube 缓存。"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import config


def sync(payload_path: Path, data_dir: Path) -> dict:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    cache_dir = data_dir / "yt_raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for video_id, raw in (payload.get("results") or {}).items():
        (cache_dir / f"{video_id}.info.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    for name in ("fetch_times.json", "yt_comment_ids.json"):
        incoming = payload.get(name)
        if not isinstance(incoming, dict):
            continue
        path = cache_dir / name
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
        if name == "fetch_times.json":
            current.update(incoming)
            if len(current) > 500:
                current = dict(sorted(current.items(), key=lambda kv: float(kv[1]), reverse=True)[:500])
        else:
            for video_id, ids in incoming.items():
                old = list(current.get(video_id) or [])
                current[video_id] = list(dict.fromkeys(list(ids) + old))[:500]
        path.write_text(json.dumps(current), encoding="utf-8")
    return {
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": len(payload.get("results") or {}),
        "failures": payload.get("failures") or [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="合并 GitHub Action YouTube 缓存")
    parser.add_argument("payload")
    parser.add_argument("--data-dir", default=str(config.data_dir()))
    args = parser.parse_args(argv)
    print(json.dumps(sync(Path(args.payload), Path(args.data_dir)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
