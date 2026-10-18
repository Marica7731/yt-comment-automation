#!/bin/bash
# WDC 20-minute cycle: dispatch the GitHub Action, sync its raw payload, then
# turn same-round results into the Codex review queue.
set -uo pipefail

ROOT=/opt/yt-comment-automation
cd "$ROOT" || exit 1
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

LOCKFILE=/tmp/yt-comment-incremental-cycle.lock
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') incremental cycle already running" >> "$LOG_DIR/skip.log"
  exit 0
fi

LOGFILE="$LOG_DIR/incremental_$(date +%Y%m%d_%H%M%S).log"
{
  echo "===== incremental cycle start $(date '+%Y-%m-%d %H:%M:%S %z') ====="
  timeout 1200s python3 dev/wdc_run_youtube_action.py --timeout 900 --poll-interval 10
  ACTION_RC=$?
  echo "action_exit=$ACTION_RC"

  timeout 1800s bash cron_job.sh
  PIPELINE_RC=$?
  echo "pipeline_exit=$PIPELINE_RC"
  echo "===== incremental cycle end $(date '+%Y-%m-%d %H:%M:%S %z') ====="
} >> "$LOGFILE" 2>&1

ls -1t "$LOG_DIR"/incremental_*.log 2>/dev/null | tail -n +31 | xargs -r rm -f

if [ "$ACTION_RC" -ne 0 ] || [ "$PIPELINE_RC" -ne 0 ]; then
  exit 1
fi
exit 0
