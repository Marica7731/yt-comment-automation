"""Replay the two real repro cases through the fixed candidate ranking path.

Confirms: (a) the performer-schedule description no longer outranks a real
songlist comment, (b) entrance/talk lines are dropped, (c) head/tail duplicate
entries collapse.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_comment_automation.clean import build_comment_songlist_ranked, is_obviously_non_song_text
from yt_comment_automation.pipeline import _is_songlist_comment


def replay(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    comments = d["comments"]
    comments = [c["text"] if isinstance(c, dict) else c for c in d["comments"]]
    description = d["description"]
    songlist_comments = [t for t in comments if _is_songlist_comment(t)]

    # Mirror pipeline.py: description only competes when no songlist comment.
    desc_source = "" if songlist_comments else (description or "")
    sources = build_comment_songlist_ranked(songlist_comments, desc_source)

    print(f"\n=== {d['yt_id']} ===")
    print(f"songlist comments: {len(songlist_comments)} | ranked sources: {len(sources)}")
    for idx, src in enumerate(sources):
        print(f"  [{idx}] items={len(src)}")
    if not sources:
        print("  NO SOURCES")
        return

    best = sources[0]
    best = [it for it in best if it.timestamp_seconds is not None]
    print(f"chosen source items: {len(best)}")
    for it in best:
        print(f"  {it.timestamp_label}  {it.song}  /  {it.artist or '-'}")

    # Ranking signal check
    if songlist_comments:
        desc_cands = build_comment_songlist_ranked([], description or "")
        if desc_cands:
            print(f"  (description would have produced {len(desc_cands[0])} items - now excluded)")

    # Non-song filter spot checks
    for probe in ("00:02:06 夜羽咲クロネ登場", "00:30:08 座って休憩＆トーク", "00:31:15 カットアウトの感想"):
        print(f"  non-song[{is_obviously_non_song_text(probe)}] {probe}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        replay(p)
