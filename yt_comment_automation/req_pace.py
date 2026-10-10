"""跨进程请求节流：本机所有对外 API 请求共用一个时钟。

背景：歌单管线（YouTube 抓取）与 like_fans（B站点赞）是两个独立进程，
各自计时互不知晓，并发时出口 IP 的实际请求速率是两股叠加——风控看的是
总速率。这里用文件锁 + 共享时钟文件实现跨进程最小间隔。

- 锁内读时间戳→补足间隔→写新时间戳→解锁（短睡在锁内，串行即目的）
- fcntl 仅 POSIX 可用；Windows 开发环境退化为进程内锁（pytest 可跑）
- 生产脚本内部的更长间隔（如点赞 8 秒频控）在此之上叠加，互不冲突
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

DEFAULT_GAP_SECONDS = 2.0
_LOCK_PATH = "/tmp/yt_automation_req.lock"
_CLOCK_PATH = "/tmp/yt_automation_req.json"

try:  # POSIX：跨进程生效
    import fcntl  # noqa: F401

    _HAVE_FCNTL = True
except ImportError:  # Windows：退化为进程内
    _HAVE_FCNTL = False

_thread_lock = threading.Lock()


def pace(gap: float = DEFAULT_GAP_SECONDS) -> None:
    """阻塞直到距上一次 pace 调用（任意进程）至少 gap 秒。"""
    if _HAVE_FCNTL:
        _pace_posix(gap)
    else:
        _pace_thread(gap)


def _pace_posix(gap: float) -> None:

    lock = Path(_LOCK_PATH)
    lock.touch(exist_ok=True)
    with open(lock, "r+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            _wait_and_stamp(gap)
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _pace_thread(gap: float) -> None:
    with _thread_lock:
        _wait_and_stamp(gap)


def _wait_and_stamp(gap: float) -> None:
    last = 0.0
    try:
        last = float(json.loads(Path(_CLOCK_PATH).read_text(encoding="utf-8"))["t"])
    except (OSError, ValueError, KeyError):
        pass
    wait = gap - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    Path(_CLOCK_PATH).write_text(json.dumps({"t": time.time()}), encoding="utf-8")
