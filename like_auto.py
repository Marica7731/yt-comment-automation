"""Run the fan-reply liker without per-item Codex review.

The collection and action paths stay in ``like_fans.py``. This wrapper turns
fresh candidates into bounded approved batches and retries transient failures
by rescanning the list before each round. Every action still passes through the
same freshness, real-state verification, ledger, and pacing gates.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yt_comment_automation import like_review  # noqa: E402

RETRYABLE_RESULTS = {"stale_list", "verify_unavailable", "api_error", "exception"}
DEFAULT_ROUNDS = 8
DEFAULT_SCAN_TIMEOUT = 240
DEFAULT_APPLY_TIMEOUT = 600
DEFAULT_PAUSE_SECONDS = 2.0


def select_work(payload: dict, max_count: int) -> list[dict]:
    """Select pending work plus retryable failures from the previous round."""
    selected: list[dict] = []
    for item in payload.get("candidates") or []:
        status = str(item.get("status") or "pending")
        result = str(item.get("result") or "")
        eligible = status in {"pending", "approved"} or (
            status == "failed" and result in RETRYABLE_RESULTS
        )
        if eligible and like_review._list_freshness_error(item) is None:
            selected.append(item)
        if len(selected) >= max_count:
            break
    return selected


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, cwd=ROOT, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"点赞直跑: 命令超时 {timeout:.0f}s: {' '.join(command)}", flush=True)
        return subprocess.CompletedProcess(command, 124)


def run_like_auto(
    max_count: int,
    review_path: Path,
    *,
    max_rounds: int = DEFAULT_ROUNDS,
    scan_timeout: float = DEFAULT_SCAN_TIMEOUT,
    apply_timeout: float = DEFAULT_APPLY_TIMEOUT,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
) -> int:
    scan_command = [sys.executable, str(ROOT / "like_fans.py")]
    apply_command = [
        sys.executable,
        str(ROOT / "like_fans.py"),
        "--apply",
        str(review_path),
    ]
    retryable_count = 0

    for round_index in range(max_rounds):
        scan = _run(scan_command, scan_timeout)
        if scan.returncode != 0:
            return scan.returncode

        payload = like_review.load_review(review_path)
        selected = select_work(payload, max_count)
        if not selected:
            if round_index == 0:
                print("点赞直跑: 无待处理候选", flush=True)
            else:
                print(f"点赞直跑: 第 {round_index + 1} 轮无待处理候选", flush=True)
            return 0

        rpids = [item["rpid"] for item in selected]
        if round_index:
            print(f"点赞直跑: 第 {round_index + 1} 轮重试 {len(rpids)} 条", flush=True)
        like_review.approve(
            rpids,
            review_path,
            reviewer="auto",
            note="用户启用的无人值守点赞批次",
            max_count=len(rpids),
        )
        print(f"点赞直跑: 自动批准 {len(rpids)} 条", flush=True)
        apply = _run(apply_command, apply_timeout)

        payload = like_review.load_review(review_path)
        by_key = {str(item.get("rpid")): item for item in payload.get("candidates") or []}
        retryable = [
            by_key.get(str(rpid), {})
            for rpid in rpids
            if by_key.get(str(rpid), {}).get("status") == "failed"
            and str(by_key.get(str(rpid), {}).get("result") or "") in RETRYABLE_RESULTS
        ]
        retryable_count = len(retryable)
        if not retryable:
            return apply.returncode
        if round_index + 1 < max_rounds:
            if pause_seconds:
                time.sleep(pause_seconds)
            continue
        break

    print(f"点赞直跑: {max_rounds} 轮后仍有 {retryable_count} 条可重试失败", flush=True)
    return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-count",
        type=int,
        default=10,
        help="单轮自动批准上限（默认 10，防止执行超过列表新鲜期）",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help=f"最多扫描/执行轮数（默认 {DEFAULT_ROUNDS}）",
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=DEFAULT_SCAN_TIMEOUT,
        help=f"单次扫描超时秒数（默认 {DEFAULT_SCAN_TIMEOUT}）",
    )
    parser.add_argument(
        "--apply-timeout",
        type=float,
        default=DEFAULT_APPLY_TIMEOUT,
        help=f"单次执行超时秒数（默认 {DEFAULT_APPLY_TIMEOUT}）",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=DEFAULT_PAUSE_SECONDS,
        help=f"重试前等待秒数（默认 {DEFAULT_PAUSE_SECONDS:g}）",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_count <= 20:
        parser.error("--max-count 必须在 1-20 之间")
    if not 1 <= args.rounds <= 20:
        parser.error("--rounds 必须在 1-20 之间")
    if args.scan_timeout <= 0 or args.apply_timeout <= 0 or args.pause_seconds < 0:
        parser.error("超时参数必须大于 0，pause-seconds 不得小于 0")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    review_path = ROOT / "data" / "like_review.json"
    return run_like_auto(
        args.max_count,
        review_path,
        max_rounds=args.rounds,
        scan_timeout=args.scan_timeout,
        apply_timeout=args.apply_timeout,
        pause_seconds=args.pause_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
