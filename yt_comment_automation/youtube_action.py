"""GitHub Action 内执行的 YouTube 抓取与结果打包。"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import yt_fetch

from . import incremental


def _has_comment_text(raw: dict) -> bool:
    entries = raw.get("comment_entries")
    if not isinstance(entries, list) or not entries:
        entries = raw.get("comments")
    if not isinstance(entries, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("text") or "").strip()
        for item in entries
    )


def _empty_snapshot_for_known_video(raw: dict, previous: dict | None) -> bool:
    if not isinstance(previous, dict):
        return False
    try:
        previous_count = int(previous.get("comment_count") or 0)
    except (TypeError, ValueError):
        previous_count = 0
    return previous_count > 0 and not _has_comment_text(raw)


def run(video_ids: list[str], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "state.json"
    previous_state = incremental.load_state(state_path)
    payload = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "video_ids": video_ids,
        "results": {},
        "failures": [],
    }
    for video_id in video_ids:
        try:
            raw = yt_fetch.fetch_youtube_raw(video_id, cache_dir=cache_dir, force=True)
            if _empty_snapshot_for_known_video(raw, previous_state["videos"].get(video_id)):
                previous_count = previous_state["videos"][video_id].get("comment_count", 0)
                raise yt_fetch.YtFetchError(
                    "empty comment snapshot for previously non-empty video "
                    f"(previous_count={previous_count})"
                )
            payload["results"][video_id] = raw
        except Exception as err:  # noqa: BLE001
            payload["failures"].append(
                {"video_id": video_id, "error": f"{type(err).__name__}: {err}"}
            )
    next_state, changes = incremental.update_state(previous_state, payload["results"])
    payload["state_version"] = incremental.STATE_VERSION
    payload["changes"] = changes
    payload["review_candidates"] = incremental.review_candidates(changes)
    payload["incremental_state"] = next_state
    for name in ("fetch_times.json", "yt_comment_ids.json"):
        path = cache_dir / name
        if path.is_file():
            payload[name] = json.loads(path.read_text(encoding="utf-8"))
    incremental.save_state(next_state, state_path)
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
