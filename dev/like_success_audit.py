#!/usr/bin/env python3
"""Audit unattended like queue health, freshness, and success accounting."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yt_comment_automation import config, like_review  # noqa: E402

RETRYABLE_RESULTS = {"stale_list", "verify_unavailable", "api_error", "exception"}


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def audit(data_dir: Path) -> dict[str, Any]:
    review = like_review.load_review(data_dir / "like_review.json")
    ledger_raw = _load_json(data_dir / "liked_rpids.json")
    if isinstance(ledger_raw, dict):
        ledger = {str(key) for key in ledger_raw}
    elif isinstance(ledger_raw, list):
        ledger = {str(item) for item in ledger_raw}
    else:
        ledger = set()

    counts: dict[str, int] = {}
    results: dict[str, int] = {}
    issues: list[str] = []
    seen: set[str] = set()
    now = datetime.now(timezone.utc)
    latest_activity: datetime | None = None
    for item in review.get("candidates") or []:
        rpid = str(item.get("rpid"))
        status = str(item.get("status") or "pending")
        result = str(item.get("result") or "")
        for field in ("queued_at", "fetched_at", "reviewed_at", "attempted_at", "executed_at"):
            parsed = like_review._parse_timestamp(item.get(field))
            if parsed and (latest_activity is None or parsed > latest_activity):
                latest_activity = parsed
        counts[status] = counts.get(status, 0) + 1
        if result:
            results[result] = results.get(result, 0) + 1
        if rpid in seen:
            issues.append(f"duplicate_rpid:{rpid}")
        seen.add(rpid)
        if status in {"pending", "approved"}:
            freshness = like_review._list_freshness_error(item, now=now)
            if freshness:
                issues.append(f"open_candidate_not_fresh:{rpid}:{freshness}")
        if status == "failed" and result not in RETRYABLE_RESULTS:
            issues.append(f"hard_failed_candidate:{rpid}:{result or 'unknown'}")
        if status == "applied" and result == "liked" and rpid not in ledger:
            issues.append(f"liked_ledger_missing:{rpid}")
    review_updated_at = like_review._parse_timestamp(review.get("updated_at"))
    if latest_activity and (review_updated_at is None or review_updated_at < latest_activity):
        updated_text = review.get("updated_at") or "missing"
        issues.append(f"review_updated_at_stale:{updated_text}:latest={latest_activity.isoformat()}")

    if isinstance(ledger_raw, dict):
        if ledger_raw.get("schema_version") not in {None, 1}:
            issues.append("liked_ledger_schema_unexpected")
    elif ledger_raw and not isinstance(ledger_raw, list):
        issues.append("liked_ledger_shape_invalid")

    return {
        "counts": counts,
        "results": results,
        "liked_rpids": len(ledger),
        "review_updated_at": review.get("updated_at") or None,
        "latest_candidate_at": latest_activity.isoformat() if latest_activity else None,
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
