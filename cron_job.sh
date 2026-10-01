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
  PYTHONPATH=/opt/yt-comment-automation python3 -c "
import sys
sys.path.insert(0, '/opt/yt-comment-automation')
from yt_comment_automation import notify
brief = '💥Codex 直接触发进程退出异常\n退出码：$RUN_EXIT\n日志：$LOGFILE\n时间：' + notify.beijing_now()
ok, note = notify.send_feishu_message(brief)
print('crash notify:', ok, note)
" >> "$LOGFILE" 2>&1
fi

# 保留最近 30 个日志
ls -1t "$LOG_DIR"/run_*.log 2>/dev/null | tail -n +31 | xargs -r rm -f
