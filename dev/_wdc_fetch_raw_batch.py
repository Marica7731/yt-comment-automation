"""Forced no-cache raw fetch for a batch of YouTube IDs on WDC.

Calls yt_fetch.fetch_youtube_raw(yt_id, cache_dir=None, force=True) per ID and
dumps description + comments + fetch timestamps to /tmp/raw_<id>.json.
"""

import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/opt/yt-comment-automation")

from yt_comment_automation import yt_fetch  # noqa: E402

OUT_DIR = Path("/tmp")


def fetch_one(yt_id):
    started = time.time()
    started_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime(started))
    raw = yt_fetch.fetch_youtube_raw(yt_id, cache_dir=None, force=True, early_stop=False)
    done = time.time()
    done_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime(done))
    if not isinstance(raw, dict):
        raise TypeError(f"raw is {type(raw).__name__}, not dict")
    comments = raw.get("comments") or []
    description = raw.get("description") or ""
    payload = {
        "yt_id": yt_id,
        "fetch_start_utc": started_iso,
        "fetch_done_utc": done_iso,
        "elapsed_s": round(done - started, 2),
        "raw_keys": sorted(raw.keys()),
        "description": description,
        "comment_count": len(comments),
        "comments": [
            c["text"] if isinstance(c, dict) else c for c in comments
        ],
    }
    target = OUT_DIR / f"raw_{yt_id}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload, target


def main():
    ids = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not ids:
        print("usage: python3 fetch_raw_batch.py <yt_id> [<yt_id> ...]")
        return 2
    failures = []
    for yt_id in ids:
        try:
            payload, target = fetch_one(yt_id)
            ts_comments = sum(
                1
                for c in payload["comments"]
                if any(tok in c for tok in (":", "："))
            )
            print(
                f"OK   {yt_id}  elapsed={payload['elapsed_s']}s  "
                f"desc_len={len(payload['description'])}  "
                f"comments={payload['comment_count']}  -> {target}"
            )
        except Exception as exc:
            failures.append(yt_id)
            print(f"FAIL {yt_id}  {type(exc).__name__}: {exc}")
            traceback.print_exc()
    if failures:
        print(f"\nFAILURES: {failures}")
        return 1
    print(f"\nALL {len(ids)} OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
