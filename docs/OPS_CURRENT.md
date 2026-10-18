# Current operations

This file records the user-approved operational split as of 2026-10-19.

## YouTube incremental fetch

WDC runs `dev/wdc_incremental_cycle.sh` every 20 minutes. The cycle:

1. Computes due YouTube IDs from the current Bilibili collection snapshot.
2. Dispatches the `youtube-fetch` GitHub Action with `repository_dispatch`.
3. Waits for the single-commit `youtube-action-cache` payload branch.
4. Syncs the same-round raw description/comments, content hashes, and change
   decisions into WDC.
5. Runs the cache-only pipeline so deterministic cleaning creates review
   candidates without making a second YouTube request.

GitHub's own schedule is not used because its start times are not precise enough
for a 20-minute loop. WDC is the scheduler and the sole dispatcher.

The Action keeps:

- `data/incremental_audit/latest.json`: latest raw payload.
- `data/incremental_audit/previous.json`: immediately previous raw payload.
- `data/incremental_state.json`: comment/description hashes and timestamps only.

The payload cache branch is force-replaced on every run so raw API bodies do not
accumulate as an unbounded Git history.

## Comment review windows

Codex checks the WDC result approximately every 10 minutes. It does not create a
new review just because a cycle ran.

A candidate is reviewed when a video increment is paired with a timestamped
song-list increment. For an already known video, the explicit re-review triggers
are:

- a new comment containing timestamps;
- a near-total replacement of the previous comment section;
- an edit to a previously timestamped comment;
- an existing comment becoming timestamped;
- an equivalent timestamp change in the description.

The reviewer must inspect the Action's actual `latest.json` and
`previous.json`, not only hashes, counts, or pipeline summaries. Only a
structured song list may be published. Missing-artist rows require authorized
archive evidence or another reliable confirmation.

Publication still uses `review_cli approve --messages-file` followed by
`review_cli apply`; success requires `verification.ok=true` and a live Bilibili
read-back.

## Fan-reply likes

WDC runs `like_auto.py` every 20 minutes. It is a direct unattended wrapper:

1. Rescan fresh msgfeed and eligible own-video comments.
2. Approve at most 10 fresh candidates.
3. Apply through the existing real-state, ledger, 180-second freshness, and
   8-second pacing gates.
4. Rescan the list and retry transient failures for up to 8 bounded rounds.

Codex does not approve individual likes. Its heartbeat checks scheduling,
freshness, queue state, success accounting, and unrecoverable failures.

## Daily audit

At 22:00 and 04:00 Beijing time, Codex audits both sides:

- Read the actual before/after Action JSON and run `dev/incremental_audit.py`.
- Inspect cleaning inputs/outputs, review queue, publish verification, and raw
  or history residue.
- Run `dev/like_success_audit.py`, inspect recent `like_auto` runs, and compare
  queue results with `liked_rpids.json`.
- Fix reproducible code or gate defects, add regression coverage, deploy, and
  report material failures through the project Feishu bot.

Quiet operation is the default: no action and no unexplained anomaly means no
notification.
