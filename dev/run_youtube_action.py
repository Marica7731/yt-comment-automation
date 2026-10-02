#!/usr/bin/env python3
"""在本地触发 GitHub Action，并把结果缓存同步回 WDC。"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = "Marica7731/yt-comment-automation"
WORKFLOW = "fetch-youtube.yml"


def _ssh(*args: str, input_bytes: bytes | None = None) -> bytes:
    command = ["ssh", "-o", "BatchMode=yes", "vps-wdc", *args]
    result = subprocess.run(command, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "ssh failed")
    return result.stdout


def _github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    for line in result.stdout.splitlines():
        if line.startswith("password="):
            value = line.partition("=")[2].strip()
            if value:
                return value
    raise RuntimeError("缺少 GITHUB_TOKEN/GH_TOKEN，且 git credential 中没有 GitHub password")


def _request(url: str, token: str, payload: dict | None = None, method: str | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method or ("POST" if data is not None else "GET"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
        if not body:
            return None
        return json.loads(body.decode("utf-8"))


def _dispatch(video_ids: list[str], token: str) -> str:
    started = datetime.now(timezone.utc)
    _request(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches",
        token,
        {"ref": "master", "inputs": {"video_ids": ",".join(video_ids)}},
    )
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], text=True, stdout=subprocess.PIPE, check=True
    ).stdout.strip()
    deadline = time.time() + 120
    while time.time() < deadline:
        runs = _request(
            f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&head_sha={head_sha}&per_page=20",
            token,
        )
        for run in (runs or {}).get("workflow_runs", []):
            created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if created >= started:
                return str(run["id"])
        time.sleep(3)
    raise RuntimeError("GitHub Action dispatch 已提交，但 120 秒内未找到 run")


def _wait_and_download(run_id: str, token: str) -> dict:
    deadline = time.time() + 1800
    while time.time() < deadline:
        run = _request(f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}", token)
        status = str((run or {}).get("status") or "")
        conclusion = str((run or {}).get("conclusion") or "")
        if status == "completed":
            if conclusion not in {"success", "failure"}:
                raise RuntimeError(f"GitHub Action completed with {conclusion or 'unknown'}")
            artifacts = _request(
                f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/artifacts", token
            )
            artifact = next(
                (
                    item
                    for item in (artifacts or {}).get("artifacts", [])
                    if str(item.get("name") or "").startswith("youtube-cache-")
                ),
                None,
            )
            if not artifact:
                raise RuntimeError("GitHub Action 没有产出 youtube-cache artifact")
            return _download_zip(artifact["archive_download_url"], token)
        time.sleep(5)
    raise RuntimeError("GitHub Action 等待超时")


def _download_zip(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        archive_bytes = response.read()
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "artifact.zip"
        archive.write_bytes(archive_bytes)
        with zipfile.ZipFile(archive) as zf:
            payload_name = next(name for name in zf.namelist() if name.endswith("payload.json"))
            return json.loads(zf.read(payload_name).decode("utf-8"))


def _sync(payload: dict) -> dict:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _ssh("cat > /tmp/youtube-action-payload.json", input_bytes=encoded)
    output = _ssh(
        "cd /opt/yt-comment-automation && DATA_DIR=/opt/yt-comment-automation/data "
        "python3 -m yt_comment_automation.youtube_cache_sync /tmp/youtube-action-payload.json"
    )
    return json.loads(output.decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="触发 GitHub Action 抓取 YouTube 并同步 WDC 缓存")
    parser.add_argument("--no-refresh", action="store_true", help="不刷新 WDC 的 B 站合集快照")
    args = parser.parse_args(argv)
    target_command = (
        "cd /opt/yt-comment-automation && DATA_DIR=/opt/yt-comment-automation/data "
        "python3 -m yt_comment_automation.youtube_targets"
    )
    if not args.no_refresh:
        target_command += " --refresh"
    target_output = _ssh(target_command)
    video_ids = json.loads(target_output.decode("utf-8"))
    if not video_ids:
        print(json.dumps({"video_ids": 0, "action": "skipped"}, ensure_ascii=False))
        return 0
    token = _github_token()
    run_id = _dispatch(video_ids, token)
    payload = _wait_and_download(run_id, token)
    synced = _sync(payload)
    summary = {
        "run_id": run_id,
        "video_ids": len(video_ids),
        "fetched": len(payload.get("results") or {}),
        "failures": payload.get("failures") or [],
        "sync": synced,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
