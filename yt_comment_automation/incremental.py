"""Stable YouTube comment snapshots and review-trigger detection.

The state file contains hashes and timestamps only.  Raw descriptions and
comments stay in the Action payload/audit file so a reviewer can inspect the
before/after JSON without mistaking the state file for source content.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable

from . import yt_fetch

STATE_VERSION = 1


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def has_timestamp(text: str) -> bool:
    return bool(yt_fetch.TIMESTAMP_RE.search(text or ""))


def _comment_rows(raw: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, Any]] = []
    entries = raw.get("comment_entries")
    if isinstance(entries, list) and entries:
        rows = [item for item in entries if isinstance(item, dict)]
    else:
        comments = raw.get("comments")
        if isinstance(comments, list):
            rows = [item for item in comments if isinstance(item, dict)]
    out: list[dict[str, str]] = []
    for item in rows:
        text = str(item.get("text") or "")
        if not text:
            continue
        comment_id = str(
            item.get("id")
            or item.get("comment_id")
            or f"sha1:{hashlib.sha1(text.encode('utf-8')).hexdigest()}"
        )
        out.append({"id": comment_id, "text": text})
    return out


def build_video_snapshot(raw: dict[str, Any], video: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a content-free state entry for one YouTube video."""
    video = video or {}
    description = str(raw.get("description") or "")
    comments: dict[str, dict[str, Any]] = {}
    for row in _comment_rows(raw):
        comments[row["id"]] = {
            "text_hash": _text_hash(row["text"]),
            "has_timestamp": has_timestamp(row["text"]),
        }
    return {
        "bvid": str(video.get("bvid") or ""),
        "title": str(video.get("title") or ""),
        "part_date": str(video.get("part_date") or ""),
        "collection": str(video.get("collection") or ""),
        "description_hash": _text_hash(description),
        "description_has_timestamp": has_timestamp(description),
        "comment_count": len(comments),
        "comments": comments,
        "last_seen_at": _now(),
    }


def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "updated_at": "", "videos": {}}


def load_state(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        return empty_state()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(payload, dict) or not isinstance(payload.get("videos"), dict):
        return empty_state()
    payload["version"] = STATE_VERSION
    return payload


def save_state(state: dict[str, Any], path: Path | str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["version"] = STATE_VERSION
    payload["updated_at"] = _now()
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def _comment_identity_set(entry: dict[str, Any]) -> set[str]:
    comments = entry.get("comments") if isinstance(entry, dict) else {}
    if not isinstance(comments, dict):
        return set()
    return {
        f"{comment_id}:{item.get('text_hash', '')}"
        for comment_id, item in comments.items()
        if isinstance(item, dict) and item.get("text_hash")
    }


def diff_video(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Compare two state entries and return the four review triggers explicitly."""
    previous = previous or {}
    old_comments = previous.get("comments") if isinstance(previous.get("comments"), dict) else {}
    new_comments = current.get("comments") if isinstance(current.get("comments"), dict) else {}
    added = [str(key) for key in new_comments if key not in old_comments]
    removed = [str(key) for key in old_comments if key not in new_comments]
    edited = [
        str(key)
        for key in new_comments
        if key in old_comments
        and old_comments[key].get("text_hash") != new_comments[key].get("text_hash")
    ]
    timestamp_added = [
        key for key in added if bool((new_comments.get(key) or {}).get("has_timestamp"))
    ]
    timestamp_edited = [
        key
        for key in edited
        if bool((old_comments.get(key) or {}).get("has_timestamp"))
        or bool((new_comments.get(key) or {}).get("has_timestamp"))
    ]
    became_timestamped = [
        key
        for key in new_comments
        if key in old_comments
        and not bool((old_comments.get(key) or {}).get("has_timestamp"))
        and bool((new_comments.get(key) or {}).get("has_timestamp"))
    ]

    old_hashes = _comment_identity_set(previous)
    new_hashes = _comment_identity_set(current)
    if old_hashes and new_hashes:
        same = len(old_hashes & new_hashes)
        change_ratio = 1.0 - (same / max(len(old_hashes), len(new_hashes)))
    else:
        change_ratio = 1.0 if old_hashes != new_hashes else 0.0
    whole_section_changed = (
        len(old_comments) >= 3
        and len(new_comments) >= 3
        and change_ratio >= 0.75
    )

    old_desc_ts = bool(previous.get("description_has_timestamp"))
    new_desc_ts = bool(current.get("description_has_timestamp"))
    desc_changed = previous.get("description_hash") != current.get("description_hash")
    description_timestamp_added = desc_changed and not old_desc_ts and new_desc_ts
    description_timestamp_edited = desc_changed and (old_desc_ts or new_desc_ts)

    reasons: list[str] = []
    if timestamp_added:
        reasons.append("timestamped_comment_added")
    if whole_section_changed:
        reasons.append("comment_section_changed")
    if timestamp_edited:
        reasons.append("timestamped_comment_edited")
    if became_timestamped:
        reasons.append("comment_became_timestamped")
    if description_timestamp_added:
        reasons.append("timestamped_description_added")
    if description_timestamp_edited:
        reasons.append("timestamped_description_edited")

    timestamp_increment = bool(
        timestamp_added
        or timestamp_edited
        or became_timestamped
        or description_timestamp_added
        or description_timestamp_edited
    )
    return {
        "added": added,
        "removed": removed,
        "edited": edited,
        "timestamped_added": timestamp_added,
        "timestamped_edited": timestamp_edited,
        "became_timestamped": became_timestamped,
        "whole_section_changed": whole_section_changed,
        "change_ratio": round(change_ratio, 4),
        "description_changed": desc_changed,
        "description_has_timestamp": new_desc_ts,
        "timestamp_increment": timestamp_increment,
        "review_reasons": reasons,
    }


def should_review(change: dict[str, Any], *, new_video: bool) -> bool:
    """Return whether a change is strong enough to spend an AI review round."""
    if new_video:
        return bool(change.get("timestamp_increment"))
    return bool(change.get("review_reasons"))


def update_state(
    state: dict[str, Any],
    raw_results: dict[str, dict[str, Any]],
    video_meta: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge a payload into state and return ``(new_state, changes)``."""
    video_meta = video_meta or {}
    videos = dict(state.get("videos") or {})
    changes: dict[str, Any] = {}
    for video_id, raw in raw_results.items():
        if not isinstance(raw, dict):
            continue
        previous = videos.get(video_id)
        current = build_video_snapshot(raw, video_meta.get(video_id))
        change = diff_video(previous, current)
        new_video = previous is None
        change["new_video"] = new_video
        change["review_required"] = should_review(change, new_video=new_video)
        changes[video_id] = change
        videos[video_id] = current
    result = dict(state)
    result["videos"] = videos
    result["last_diff_at"] = _now()
    return result, changes


def review_candidates(changes: dict[str, Any]) -> list[str]:
    return sorted(
        video_id
        for video_id, change in changes.items()
        if isinstance(change, dict) and change.get("review_required")
    )


def state_video_ids(state: dict[str, Any]) -> set[str]:
    return {str(key) for key in (state.get("videos") or {})}


def iter_comments(raw: dict[str, Any]) -> Iterable[dict[str, str]]:
    """Small public helper for audits and tests."""
    yield from _comment_rows(raw)
