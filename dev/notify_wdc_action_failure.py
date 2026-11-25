#!/usr/bin/env python3
"""Send one concise alert when the current YouTube Action payload is unavailable."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yt_comment_automation import notify  # noqa: E402


def _action_error(log_path: Path) -> str:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "Action payload 未同步，且本轮日志不可读"

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        error = entry.get("error") if isinstance(entry, dict) else None
        if isinstance(error, str) and error.strip():
            value = re.sub(
                r"(?i)(authorization\s*[:=]\s*bearer)\s+\S+",
                r"\1 [redacted]",
                error,
            )
            value = re.sub(
                r"(?i)(token|secret|password)(\s*[:=]\s*)[^\s,;]+",
                r"\1\2[redacted]",
                value,
            )
            value = re.sub(r"\bgh[pousr]_[A-Za-z0-9_]+\b", "[redacted]", value)
            return value[:300]
    return "Action payload 未在等待期限内同步，详见本轮日志"


def build_brief(error: str, log_path: Path) -> str:
    try:
        log_label = str(log_path.relative_to(ROOT))
    except ValueError:
        log_label = log_path.name
    return "\n".join(
        [
            "⚠️ YouTube 评论抓取未完成",
            f"原因：{error}",
            "本轮评论清洗已跳过，避免使用旧轮缓存；下一周期会重新抓取。",
            f"日志：{log_label}",
            f"commit：{notify.git_summary()}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path", type=Path)
    args = parser.parse_args(argv)
    brief = build_brief(_action_error(args.log_path), args.log_path)
    sent, note = notify.send_feishu_message(brief)
    print("Action failure notify:", sent, note)
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
