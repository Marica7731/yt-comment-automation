#!/usr/bin/env python3
"""WDC-side 20-minute trigger and sync for the incremental YouTube Action."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yt_comment_automation import config, youtube_cache_sync, youtube_targets  # noqa: E402

DEFAULT_REPO = "Marica7731/yt-comment-automation"
CACHE_BRANCH = "youtube-action-cache"
PAYLOAD_PATH = "youtube-action-payload.json"
REPO_URL = "https://github.com/Marica7731/yt-comment-automation.git"
TOKEN_FILE = Path(os.environ.get("GITHUB_TOKEN_FILE", "/root/.secrets/github-token"))


def _token() -> str:
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"GitHub token file is empty: {TOKEN_FILE}")
    return token


def _git(args: list[str], timeout: float = 30.0) -> str:
    helper = f"!f() {{ echo username=Marica7731; echo password=$(cat {TOKEN_FILE}); }}; f"
    command = [
        "git",
        "-c",
        f"credential.helper={helper}",
        "-c",
        "credential.useHttpPath=true",
        *args,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git failed: {' '.join(args)}")
    return completed.stdout.decode("utf-8", errors="replace")


def _api(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "yt-comment-automation-wdc",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {method} {path} HTTP {err.code}: {detail[:300]}") from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"GitHub API {method} {path} network error: {err}") from err
    return json.loads(raw) if raw.strip() else {}


def _cache_head() -> str:
    output = _git(["ls-remote", REPO_URL, f"refs/heads/{CACHE_BRANCH}"], timeout=30)
    return output.split()[0] if output.split() else ""


def _dispatch(repo: str, video_ids: list[str]) -> None:
    _api(
        "POST",
        f"/repos/{repo}/dispatches",
        {
            "event_type": "youtube-fetch",
            "client_payload": {"video_ids": ",".join(video_ids)},
        },
    )


def _read_payload() -> dict:
    _git(["fetch", "--quiet", "--depth=1", REPO_URL, f"refs/heads/{CACHE_BRANCH}"], timeout=60)
    raw = _git(["show", f"FETCH_HEAD:{PAYLOAD_PATH}"], timeout=30)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("Action payload 不是 JSON object")
    return payload


def _wait_for_payload(
    previous_head: str,
    video_ids: list[str],
    timeout_seconds: float,
    poll_seconds: float,
) -> tuple[dict, str]:
    deadline = time.monotonic() + timeout_seconds
    last_seen = previous_head
    while time.monotonic() < deadline:
        head = _cache_head()
        if head and head != previous_head and head != last_seen:
            last_seen = head
            payload = _read_payload()
            if payload.get("video_ids") == video_ids:
                return payload, head
        time.sleep(poll_seconds)
    raise RuntimeError(f"{timeout_seconds:.0f} 秒内未读取到匹配 {len(video_ids)} 个目标的 Action payload")


def run(timeout_seconds: float, poll_seconds: float, refresh: bool) -> dict:
    videos = youtube_targets.due_targets(config.data_dir(), refresh=refresh)
    video_ids = list(dict.fromkeys(str(video_id) for video_id in videos if video_id))
    if not video_ids:
        return {"action": "skipped_no_targets", "video_ids": 0}

    previous_head = _cache_head()
    _dispatch(DEFAULT_REPO, video_ids)
    payload, cache_commit = _wait_for_payload(
        previous_head,
        video_ids,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False)
        temp_path = Path(handle.name)
    try:
        synced = youtube_cache_sync.sync(temp_path, config.data_dir())
    finally:
        temp_path.unlink(missing_ok=True)
    return {
        "action": "synced",
        "video_ids": len(video_ids),
        "fetched": len(payload.get("results") or {}),
        "failures": payload.get("failures") or [],
        "review_candidates": payload.get("review_candidates") or [],
        "cache_commit": cache_commit,
        "sync": synced,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--no-refresh", action="store_true")
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.poll_interval <= 0:
        parser.error("--timeout 和 --poll-interval 必须大于 0")
    summary = run(args.timeout, args.poll_interval, refresh=not args.no_refresh)
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary.get("failures") else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, json.JSONDecodeError) as err:
        print(json.dumps({"error": str(err)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
