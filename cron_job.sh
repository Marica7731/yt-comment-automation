#!/bin/bash
# B站合集评论区时间戳歌轴：由 Codex heartbeat 直接触发，增量抓取并写入审核队列（flock 单实例锁防并发重复）
LOCKFILE=/tmp/yt-comment-automation.lock
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') 已有实例在运行，本次跳过" >> /opt/yt-comment-automation/logs/skip.log
  exit 0
fi

export DRY_RUN=0
export DATA_DIR=/opt/yt-comment-automation/data
cd /opt/yt-comment-automation
LOG_DIR=/opt/yt-comment-automation/logs
mkdir -p "$LOG_DIR"
LOGFILE="$LOG_DIR/run_$(date +%Y%m%d_%H%M%S).log"
timeout 3600 bash run.sh run --mode incremental >> "$LOGFILE" 2>&1
RUN_EXIT=$?

# 运行异常（Python 崩溃已由 cli 发飞书；这里兜底 timeout 超时/SIGTERM 等进程级退出）
if [ $RUN_EXIT -ne 0 ]; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') run exited with $RUN_EXIT" >> "$LOGFILE"
  CRON_RUN_EXIT="$RUN_EXIT" CRON_LOGFILE="$LOGFILE" PYTHONPATH=/opt/yt-comment-automation python3 - >> "$LOGFILE" 2>&1 <<'PY'
import os
import sys

sys.path.insert(0, "/opt/yt-comment-automation")
from yt_comment_automation import notify

exit_code = os.environ.get("CRON_RUN_EXIT", "unknown")
log_file = os.environ.get("CRON_LOGFILE", "")
brief = notify.build_crash_brief(
    f"ProcessExitError: cron_job.sh exited with {exit_code}",
    files=[
        "cron_job.sh",
        "run.sh",
        "yt_comment_automation/cli.py",
        "yt_comment_automation/pipeline.py",
    ],
    tests=[
        f"cron_job.sh → process exit {exit_code}",
        f"log={log_file}",
    ],
    commit=notify.git_summary(),
    failures=[
        f"process exit code={exit_code}",
        f"log={log_file}",
    ],
)
ok, note = notify.send_feishu_message(brief)
print("crash notify:", ok, note)
PY
fi

# 保留最近 30 个日志
ls -1t "$LOG_DIR"/run_*.log 2>/dev/null | tail -n +31 | xargs -r rm -f
