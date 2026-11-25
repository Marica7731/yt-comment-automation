#!/bin/bash
# WDC incremental cycle: dispatch the GitHub Action, sync its raw payload, then
# turn same-round results into the Codex review queue.
set -uo pipefail

ROOT=/opt/yt-comment-automation
cd "$ROOT" || exit 1
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
SCHEDULER_LOG="$LOG_DIR/incremental_scheduler.log"

LOCKFILE=/tmp/yt-comment-incremental-cycle.lock
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  summary="$(date '+%Y-%m-%d %H:%M:%S') incremental cycle skipped: already running"
  echo "$summary" >> "$LOG_DIR/skip.log"
  echo "$summary" >> "$SCHEDULER_LOG"
  exit 0
fi

LOGFILE="$LOG_DIR/incremental_$(date +%Y%m%d_%H%M%S).log"
{
  echo "===== incremental cycle start $(date '+%Y-%m-%d %H:%M:%S %z') ====="
  timeout 1800s python3 dev/wdc_run_youtube_action.py --timeout 1740 --poll-interval 10
  ACTION_RC=$?
  echo "action_exit=$ACTION_RC"

  if [ "$ACTION_RC" -eq 0 ]; then
    timeout 1800s bash cron_job.sh
    PIPELINE_RC=$?
    echo "pipeline_exit=$PIPELINE_RC"
  else
    # Never let cache-only cleanup consume an older payload after this round failed.
    PIPELINE_RC=0
    echo "pipeline_skipped=action_failure"
    timeout 60s python3 dev/notify_wdc_action_failure.py "$LOGFILE" || \
      echo "action_failure_notify_exit=$?"
  fi
  echo "===== incremental cycle end $(date '+%Y-%m-%d %H:%M:%S %z') ====="
} >> "$LOGFILE" 2>&1

printf '%s action_exit=%s pipeline_exit=%s log=%s\n' \
  "$(date '+%Y-%m-%d %H:%M:%S %z')" "$ACTION_RC" "$PIPELINE_RC" "$(basename "$LOGFILE")" \
  >> "$SCHEDULER_LOG"

ls -1t "$LOG_DIR"/incremental_[0-9]*.log 2>/dev/null | tail -n +31 | xargs -r rm -f

if [ "$ACTION_RC" -ne 0 ] || [ "$PIPELINE_RC" -ne 0 ]; then
  exit 1
fi
exit 0
