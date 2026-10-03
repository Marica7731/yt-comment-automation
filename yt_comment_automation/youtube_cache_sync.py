"""把 GitHub Action 上传的 payload 合并到 WDC 本地 YouTube 缓存。"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import config


PENDING_NAME = "action_pending_ids.json"


def _pending_path(data_dir: Path) -> Path:
    return data_dir / "yt_raw" / PENDING_NAME


def load_pending(data_dir: Path) -> set[str]:
    try:
        payload = json.loads(_pending_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(payload, list):
        return set()
    return {str(item) for item in payload}


def is_pending_action(data_dir: Path, video_id: str) -> bool:
    return str(video_id) in load_pending(data_dir)


def mark_processed(data_dir: Path, video_id: str) -> None:
    pending = load_pending(data_dir)
    key = str(video_id)
    if key not in pending:
        return
    pending.remove(key)
    path = _pending_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(pending)), encoding="utf-8")


def _save_pending(data_dir: Path, video_ids: set[str]) -> None:
    if not video_ids:
        return
    path = _pending_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(video_ids)), encoding="utf-8")


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
    result_ids = set(payload.get("results") or {})
    if result_ids:
        pending = load_pending(data_dir) | result_ids
        _save_pending(data_dir, pending)

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
