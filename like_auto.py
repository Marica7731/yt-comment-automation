"""Run the fan-reply liker without per-item Codex review.

Scan once, then process the resulting queue in bounded batches. Every action
rechecks the live like state; the 8-second action pacing applies across batch
boundaries too. Transient failures are retried from the ledger without another
full feed and comment scan. Unavailable live-state checks are attempted once
per run and remain visible for the next scheduled scan.
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
DEFAULT_PAUSE_SECONDS = 8.0


def select_work(
    payload: dict,
    max_count: int,
    *,
    exclude_rpids: set[str] | None = None,
) -> list[dict]:
    """Select pending work plus retryable failures, including old candidates.

    apply_approved revalidates the live like state before acting, so age alone
    should not strand a candidate or force another full scan.
    """
    selected: list[dict] = []
    excluded = exclude_rpids or set()
    for item in payload.get("candidates") or []:
        if str(item.get("rpid")) in excluded:
            continue
        status = str(item.get("status") or "pending")
        result = str(item.get("result") or "")
        eligible = status in {"pending", "approved"} or (
            status == "failed" and result in RETRYABLE_RESULTS
        )
        if eligible:
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
    scan = _run(scan_command, scan_timeout)
    if scan.returncode != 0:
        return scan.returncode

    retryable_count = 0
    remaining_count = 0
    verification_unavailable_this_run: set[str] = set()

    for batch_index in range(max_rounds):
        payload = like_review.load_review(review_path)
        selected = select_work(
            payload,
            max_count,
            exclude_rpids=verification_unavailable_this_run,
        )
        if not selected:
            open_work = [
                item
                for item in payload.get("candidates") or []
                if (
                    item.get("status") in {"pending", "approved"}
                    or (
                        item.get("status") == "failed"
                        and str(item.get("result") or "") in RETRYABLE_RESULTS
                    )
                )
                and str(item.get("rpid")) not in verification_unavailable_this_run
            ]
            if open_work:
                print(
                    f"点赞直跑: 有 {len(open_work)} 条待处理，但无法组批；本轮失败退出",
                    flush=True,
                )
                return 1
            if verification_unavailable_this_run:
                print(
                    "点赞直跑: "
                    f"{len(verification_unavailable_this_run)} 条实时状态无法复核，留待下次扫描；本轮失败退出",
                    flush=True,
                )
                return 1
            if batch_index == 0:
                print("点赞直跑: 无待处理候选", flush=True)
            else:
                print(f"点赞直跑: 第 {batch_index + 1} 批后队列已清空", flush=True)
            return 0

        rpids = [item["rpid"] for item in selected]
        if batch_index:
            print(f"点赞直跑: 第 {batch_index + 1} 批处理 {len(rpids)} 条", flush=True)
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
        verification_unavailable_this_run.update(
            str(rpid)
            for rpid in rpids
            if by_key.get(str(rpid), {}).get("status") == "failed"
            and str(by_key.get(str(rpid), {}).get("result") or "") == "verify_unavailable"
        )
        retryable = [
            by_key.get(str(rpid), {})
            for rpid in rpids
            if by_key.get(str(rpid), {}).get("status") == "failed"
            and str(by_key.get(str(rpid), {}).get("result") or "") in RETRYABLE_RESULTS
            and str(rpid) not in verification_unavailable_this_run
        ]
        retryable_count = len(retryable)
        open_work = [
            item
            for item in payload.get("candidates") or []
            if (
                item.get("status") in {"pending", "approved"}
                or (
                    item.get("status") == "failed"
                    and str(item.get("result") or "") in RETRYABLE_RESULTS
                )
            )
            and str(item.get("rpid")) not in verification_unavailable_this_run
        ]
        remaining_count = len(open_work) + len(verification_unavailable_this_run)
        if not retryable and not open_work:
            return 1 if verification_unavailable_this_run else apply.returncode
        if batch_index + 1 < max_rounds:
            if open_work:
                print(f"点赞直跑: 本批后仍有 {len(open_work)} 条待处理，继续下一批", flush=True)
            if pause_seconds:
                time.sleep(pause_seconds)
            continue
        break

    print(
        f"点赞直跑: {max_rounds} 批后仍有 {remaining_count} 条待处理、{retryable_count} 条可重试失败",
        flush=True,
    )
    return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-count",
        type=int,
        default=10,
        help="单批自动批准上限（默认 10）",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=DEFAULT_ROUNDS,
        help=f"最多处理批次数（默认 {DEFAULT_ROUNDS}）",
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
        help=f"批次之间等待秒数（默认 {DEFAULT_PAUSE_SECONDS:g}）",
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
