#!/usr/bin/env python3
"""Send one local file through this repository's configured Feishu app."""
import argparse
from pathlib import Path

from yt_comment_automation.notify import send_feishu_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="local file to attach")
    parser.add_argument("--dry-run", action="store_true", help="validate only; do not call Feishu")
    args = parser.parse_args()
    ok, receipt = send_feishu_file(args.file, dry_run=args.dry_run)
    print(receipt)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
