#!/usr/bin/env python3
"""Audit before/after GitHub Action raw payloads without trusting summaries."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yt_comment_automation import config, incremental  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _raw_results(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, dict):
        return {}
    return {
        str(video_id): raw
        for video_id, raw in results.items()
        if isinstance(raw, dict)
    }


def audit(data_dir: Path) -> dict[str, Any]:
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

    return {
        "latest_fetched_at": latest.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at"),
        "videos": len(latest_results),
        "failures": latest.get("failures") or [],
        "review_candidates": latest.get("review_candidates") or [],
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
