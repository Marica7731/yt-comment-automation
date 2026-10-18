# Current operations

This file records the user-approved operational split as of 2026-10-19.

## Fan-reply likes

The WDC cron runs `like_auto.py` every 20 minutes. It is a direct, unattended
wrapper around the existing collection and action paths:

1. Run `like_fans.py` to scan fresh msgfeed entries and eligible own-video
   comment replies.
2. Approve at most 10 fresh pending candidates per run.
3. Run `like_fans.py --apply data/like_review.json`.

The wrapper does not bypass toggle safety: every action still requires a real
"not liked" read, the 180-second list freshness gate, the liked-rpid ledger,
and the 8-second post-action pacing. `Codex` does not approve individual likes;
its heartbeat only checks cron health, recent logs, queue state, and failure
counts.

## Comment publishing

Codex handles comment content review and publishing in fixed non-peak windows.
The current Beijing-time windows are:

- 03:10
- 09:10
- 13:10
- 19:10
- 23:10

All weekday windows avoid the 14:00-18:00 GLM Coding Plan peak. The scheduling
constraint belongs in Codex scheduling decisions, not in a task's execution
prompt. Every content round still uses a same-round WDC forced YouTube fetch,
direct reading of the returned raw description/comments, deterministic cleanup
rules, explicit AI-authored final messages, verified posting, and Bilibili
read-back.
