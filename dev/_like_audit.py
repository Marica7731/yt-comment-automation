"""Audit raw msgfeed and comment JSON without approving or sending likes."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yt_comment_automation import bili_comment, config  # noqa: E402
from yt_comment_automation.req_pace import pace  # noqa: E402

OWNER_MID = "3546597260528367"
BASE_MSGFEED = (
    "https://api.bilibili.com/x/msgfeed/reply"
    "?platform=web&build=0&mobi_app=web&web_location=0.0"
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Referer": "https://message.bilibili.com/",
}


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def snapshot_bvids(snapshot: Any) -> set[str]:
    videos = (
        snapshot
        if isinstance(snapshot, list)
        else (snapshot.get("videos") if isinstance(snapshot, dict) else [])
    ) or []
    return {
        str(video["bvid"])
        for video in videos
        if isinstance(video, dict) and video.get("bvid")
    }


def bvid_from_uri(uri: Any) -> str | None:
    match = re.search(r"/video/(BV[0-9A-Za-z]{10})", str(uri or ""))
    return match.group(1) if match else None


def load_own_bvids(data_dir: Path) -> set[str]:
    processed = load_json(data_dir / "processed.json", {})
    snapshot = load_json(data_dir / "collections_snapshot.json", [])
    own = set(processed.get("posted") or []) if isinstance(processed, dict) else set()
    return own | snapshot_bvids(snapshot)


def recent_review_entries(
    review: dict[str, Any],
    cutoff: datetime,
) -> list[dict[str, Any]]:
    entries = []
    for item in review.get("candidates") or []:
        timestamps = [
            item.get("executed_at"),
            item.get("queued_at"),
            item.get("fetched_at"),
        ]
        valid = []
        for timestamp in timestamps:
            if not timestamp:
                continue
            try:
                valid.append(datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")))
            except ValueError:
                continue
        if valid and max(valid) >= cutoff:
            entries.append(item)
    return entries


def collect_targets(
    msgfeed_items: list[dict[str, Any]],
    review_entries: list[dict[str, Any]],
    own_bvids: set[str],
) -> dict[int, dict[str, Any]]:
    targets: dict[int, dict[str, Any]] = {}

    def add(oid: Any, bvid: str | None, source: str) -> None:
        if oid is None or not bvid or bvid not in own_bvids:
            return
        target = targets.setdefault(int(oid), {"bvids": set(), "sources": set()})
        target["bvids"].add(bvid)
        target["sources"].add(source)

    for item in msgfeed_items:
        inner = item.get("item") or {}
        add(
            inner.get("subject_id"),
            bvid_from_uri(inner.get("uri")),
            "msgfeed",
        )
    for item in review_entries:
        add(item.get("oid"), item.get("bvid"), "review")
    return targets


def fetch_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_msgfeed_pages(headers: dict[str, str], max_pages: int) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    cursor_id = cursor_time = None
    for page_number in range(1, max_pages + 1):
        pace(1.0)
        url = BASE_MSGFEED
        if cursor_id:
            url += f"&id={cursor_id}&reply_time={cursor_time}"
        raw = fetch_json(url, headers)
        data = raw.get("data") or {}
        cursor = data.get("cursor") or {}
        pages.append(
            {
                "page": page_number,
                "url": url,
                "raw": raw,
                "items": data.get("items") or [],
                "cursor": cursor,
            }
        )
        if cursor.get("is_end") or not data.get("items"):
            break
        cursor_id, cursor_time = cursor.get("id"), cursor.get("time")
    return pages


def fetch_comment_pages(
    oid: int,
    headers: dict[str, str],
    max_pages: int,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page_number in range(1, max_pages + 1):
        pace(1.0)
        url = (
            f"https://api.bilibili.com/x/v2/reply?type=1&oid={oid}"
            f"&sort=2&ps=20&pn={page_number}"
        )
        raw = fetch_json(url, headers)
        replies = ((raw.get("data") or {}).get("replies")) or []
        pages.append(
            {
                "page": page_number,
                "url": url,
                "raw": raw,
                "replies": replies,
            }
        )
        if len(replies) < 20:
            break
    return pages


def summarize(
    msgfeed_pages: list[dict[str, Any]],
    comments: dict[str, list[dict[str, Any]]],
    review_entries: list[dict[str, Any]],
    liked_rpids: set[str],
) -> dict[str, Any]:
    queue = {
        str(item.get("rpid")): item.get("status") or "pending"
        for item in review_entries
    }
    msgfeed_rows = []
    for page in msgfeed_pages:
        for item in page["items"]:
            inner = item.get("item") or {}
            rpid = str(inner.get("source_id") or "")
            msgfeed_rows.append(
                {
                    "page": page["page"],
                    "oid": inner.get("subject_id"),
                    "rpid": rpid,
                    "content": inner.get("source_content") or "",
                    "bvid": bvid_from_uri(inner.get("uri")),
                    "like_state": inner.get("like_state"),
                    "root_id": inner.get("root_id") or "",
                    "queue_status": queue.get(rpid),
                    "in_liked_set": rpid in liked_rpids,
                }
            )

    comment_rows = []
    for oid_text, pages in comments.items():
        for page in pages:
            for reply in page["replies"]:
                rpid = str(reply.get("rpid") or "")
                content = ((reply.get("content") or {}).get("message")) or ""
                comment_rows.append(
                    {
                        "oid": int(oid_text),
                        "page": page["page"],
                        "rpid": rpid,
                        "mid": str(((reply.get("member") or {}).get("mid")) or ""),
                        "content": content,
                        "action": reply.get("action"),
                        "reaction_status": ((reply.get("reaction") or {}).get("status")),
                        "folded": bool((reply.get("reply_control") or {}).get("fold_text"))
                        or bool((reply.get("folder") or {}).get("is_folded")),
                        "queue_status": queue.get(rpid),
                        "in_liked_set": rpid in liked_rpids,
                    }
                )

    potential_missing = [
        row
        for row in comment_rows
        if row["mid"] != OWNER_MID
        and row["action"] != 1
        and not row["in_liked_set"]
        and row["queue_status"] not in {"applied", "rejected"}
    ]
    return {
        "msgfeed_items": len(msgfeed_rows),
        "comment_replies": len(comment_rows),
        "targets": len(comments),
        "potential_missing": potential_missing,
        "msgfeed": msgfeed_rows,
        "comments": comment_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/like_audit_latest.json")
    parser.add_argument("--msgfeed-pages", type=int, default=10)
    parser.add_argument("--comment-pages", type=int, default=3)
    parser.add_argument("--lookback-hours", type=int, default=24)
    args = parser.parse_args()

    data_dir = Path(config.data_dir())
    started_at = datetime.now(timezone.utc)
    cookies = bili_comment.load_cookie_map()
    headers = {
        **HEADERS,
        "Cookie": bili_comment.cookie_header(cookies),
    }
    own_bvids = load_own_bvids(data_dir)
    review = load_json(data_dir / "like_review.json", {})
    cutoff = started_at - timedelta(hours=args.lookback_hours)
    review_entries = recent_review_entries(review, cutoff)
    liked_rpids = {
        str(value)
        for value in load_json(data_dir / "liked_rpids.json", [])
    }

    msgfeed_pages = fetch_msgfeed_pages(headers, args.msgfeed_pages)
    all_items = [item for page in msgfeed_pages for item in page["items"]]
    targets = collect_targets(all_items, review_entries, own_bvids)
    comments = {
        str(oid): fetch_comment_pages(oid, headers, args.comment_pages)
        for oid in sorted(targets)
    }
    finished_at = datetime.now(timezone.utc)
    summary = summarize(msgfeed_pages, comments, review_entries, liked_rpids)
    payload = {
        "schema": 1,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "owner_mid": OWNER_MID,
        "own_bvid_count": len(own_bvids),
        "target_oids": sorted(targets),
        "msgfeed_pages": msgfeed_pages,
        "comments": comments,
        "review_entries": review_entries,
        "liked_rpids": sorted(liked_rpids),
        "summary": summary,
    }

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "started_at": payload["started_at"],
                "finished_at": payload["finished_at"],
                "msgfeed_pages": len(msgfeed_pages),
                "msgfeed_items": summary["msgfeed_items"],
                "comment_targets": summary["targets"],
                "comment_replies": summary["comment_replies"],
                "potential_missing_count": len(summary["potential_missing"]),
                "potential_missing": summary["potential_missing"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
