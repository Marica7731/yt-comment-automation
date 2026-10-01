#!/bin/bash
# Run the Codex-only pipeline. Feishu credentials come exclusively from the
# process environment or this project's gitignored private.env.
set -euo pipefail
cd /opt/yt-comment-automation
exec python3 -m yt_comment_automation.cli "$@"
