"""Run the fan-reply liker without per-item Codex review.

The collection and action paths stay in ``like_fans.py``.  This wrapper only
turns the fresh pending candidates produced by a scan into a bounded approved
batch, then invokes the same ``--apply`` path used by reviewed runs.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yt_comment_automation import like_review  # noqa: E402


def select_pending(payload: dict, max_count: int) -> list[dict]:
    """Select the oldest pending candidates, capped to protect list freshness."""
    pending = [
        item
        for item in payload.get("candidates") or []
        if str(item.get("status") or "pending") == "pending"
    ]
    return pending[:max_count]


def run_like_auto(max_count: int, review_path: Path) -> int:
    scan = subprocess.run(
        [sys.executable, str(ROOT / "like_fans.py")],
        cwd=ROOT,
        check=False,
    )
    if scan.returncode != 0:
        return scan.returncode

    payload = like_review.load_review(review_path)
    selected = select_pending(payload, max_count)
    if not selected:
        print("点赞直跑: 无待处理候选", flush=True)
        return 0

    rpids = [item["rpid"] for item in selected]
    like_review.approve(
        rpids,
        review_path,
        reviewer="auto",
        note="用户启用的无人值守点赞批次",
        max_count=len(rpids),
    )
    print(f"点赞直跑: 自动批准 {len(rpids)} 条", flush=True)
    apply = subprocess.run(
        [sys.executable, str(ROOT / "like_fans.py"), "--apply", str(review_path)],
        cwd=ROOT,
        check=False,
    )
    return apply.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-count",
        type=int,
        default=10,
        help="单轮自动批准上限（默认 10，防止执行超过列表新鲜期）",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_count <= 20:
        parser.error("--max-count 必须在 1-20 之间")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    review_path = ROOT / "data" / "like_review.json"
    return run_like_auto(args.max_count, review_path)


if __name__ == "__main__":
    raise SystemExit(main())
