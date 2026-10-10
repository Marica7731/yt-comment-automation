"""Audit the WDC codex_review queue: status counts + every non-terminal entry."""

import glob
import json
import os
import sys
from collections import Counter

QUEUE_DIR = sys.argv[1] if len(sys.argv) > 1 else "data/codex_review"


def load(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as exc:
        return {"status": "UNREADABLE", "error": str(exc)}
    if isinstance(d, list):
        if not d:
            return {"status": "EMPTY_LIST"}
        d = d[-1]
    if not isinstance(d, dict):
        return {"status": "BAD_TYPE", "type": type(d).__name__}
    return d


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(QUEUE_DIR, "*.json"))):
        bvid = os.path.basename(f)[:-5]
        d = load(f)
        rows.append(
            (
                bvid,
                d.get("status", "?"),
                d.get("title", "") or "",
                d.get("queued_at", ""),
                d.get("rpid") or d.get("rpids") or "",
            )
        )
    counts = Counter(r[1] for r in rows)
    print(f"TOTAL {len(rows)}  {dict(counts)}")
    print()
    for bvid, status, title, queued, rpid in rows:
        if status != "applied":
            print(f"{status:12} {bvid:16} queued={queued[:19]:19} rpid={rpid}  {title[:60]}")
    print()
    bad = [r for r in rows if r[1] not in {"applied", "pending", "approved", "applying", "applied_unverified", "deleted", "rejected", "failed"}]
    if bad:
        print("UNEXPECTED STATUS:")
        for r in bad:
            print("  ", r[0], r[1])


if __name__ == "__main__":
    main()
