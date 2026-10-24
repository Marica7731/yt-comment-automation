#!/usr/bin/env python3
"""Audit before/after GitHub Action raw payloads and open review queues."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yt_comment_automation import config, incremental  # noqa: E402

OPEN_REVIEW_STATUSES = {"pending", "approved", "applying", "applied_unverified"}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _review_queue(
    data_dir: Path,
    now: datetime,
    max_pending_minutes: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    queue_dir = data_dir / "codex_review"
    rows: list[dict[str, Any]] = []
    issues: list[str] = []
    if not queue_dir.is_dir():
        return rows, issues
    for path in sorted(queue_dir.glob("*.json")):
        item = _load_json(path)
        if not item:
            issues.append(f"review_queue_invalid:{path.name}")
            continue
        status = str(item.get("status") or "")
        if status not in OPEN_REVIEW_STATUSES:
            continue
        bvid = str(item.get("bvid") or path.stem)
        anchor_name = "queued_at" if status == "pending" else "updated_at"
        anchor_value = item.get(anchor_name)
        if not anchor_value and anchor_name != "queued_at":
            anchor_name = "queued_at"
            anchor_value = item.get(anchor_name)
        queued = _parse_timestamp(anchor_value)
        age_minutes: int | None = None
        if queued is None:
            issues.append(f"review_queue_missing_time:{status}:{bvid}")
        else:
            age_minutes = max(0, int((now - queued).total_seconds() // 60))
            if age_minutes > max_pending_minutes:
                issues.append(f"review_queue_overdue:{status}:{bvid}:{age_minutes}m")
        rows.append(
            {
                "bvid": bvid,
                "status": status,
                "age_from": anchor_name,
                "age_minutes": age_minutes,
            }
        )
    return rows, issues


def _raw_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, dict):
        return {}
    return {
        str(video_id): raw
        for video_id, raw in results.items()
        if isinstance(raw, dict)
    }


def audit(
    data_dir: Path,
    *,
    now: datetime | None = None,
    max_pending_minutes: int | None = None,
) -> dict[str, Any]:
    audit_dir = data_dir / "incremental_audit"
    latest = _load_json(audit_dir / "latest.json")
    previous = _load_json(audit_dir / "previous.json")
    state = incremental.load_state(data_dir / "incremental_state.json")
    latest_results = _raw_results(latest)
    previous_results = _raw_results(previous)
    issues: list[str] = []

    if not latest:
        issues.append("missing_or_invalid_latest_payload")
    if latest and not latest.get("fetched_at"):
        issues.append("latest_payload_missing_fetched_at")

    declared_changes = latest.get("changes")
    if not isinstance(declared_changes, dict):
        declared_changes = {}
        if latest:
            issues.append("latest_payload_missing_changes")

    for video_id, raw in latest_results.items():
        current = incremental.build_video_snapshot(raw)
        stored = (state.get("videos") or {}).get(video_id)
        if not isinstance(stored, dict):
            issues.append(f"{video_id}:state_missing")
        else:
            for field in ("description_hash", "description_has_timestamp", "comment_count", "comments"):
                if stored.get(field) != current.get(field):
                    issues.append(f"{video_id}:state_mismatch:{field}")

        declared = declared_changes.get(video_id)
        if not isinstance(declared, dict):
            issues.append(f"{video_id}:change_missing")
            continue
        previous_raw = previous_results.get(video_id)
        if isinstance(previous_raw, dict):
            baseline = incremental.build_video_snapshot(previous_raw)
            recomputed = incremental.diff_video(baseline, current)
            expected_review = incremental.should_review(recomputed, new_video=False)
        elif declared.get("new_video") is False:
            # A rejected empty snapshot is omitted from the next payload's prior
            # results; the persisted state check above is the available baseline.
            continue
        else:
            recomputed = incremental.diff_video(None, current)
            expected_review = incremental.should_review(recomputed, new_video=True)
        if recomputed["review_reasons"] != declared.get("review_reasons"):
            issues.append(f"{video_id}:review_reason_mismatch")
        if expected_review != bool(declared.get("review_required")):
            issues.append(f"{video_id}:review_decision_mismatch")

    expected_candidates = incremental.review_candidates(declared_changes)
    if expected_candidates != list(latest.get("review_candidates") or []):
        issues.append("review_candidates_mismatch")

    if max_pending_minutes is None:
        try:
            max_pending_minutes = int(os.environ.get("CODEX_PENDING_ALERT_MINUTES", "60"))
        except ValueError:
            max_pending_minutes = 60
    review_queue, review_issues = _review_queue(
        data_dir,
        now or datetime.now(timezone.utc),
        max(0, max_pending_minutes),
    )
    issues.extend(review_issues)

    return {
        "latest_fetched_at": latest.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at"),
        "videos": len(latest_results),
        "failures": latest.get("failures") or [],
        "review_candidates": latest.get("review_candidates") or [],
        "review_queue": review_queue,
        "max_pending_minutes": max_pending_minutes,
        "issues": issues,
        "ok": not issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(config.data_dir()))
    args = parser.parse_args(argv)
    result = audit(Path(args.data_dir))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
