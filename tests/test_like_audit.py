"""Regression coverage for the raw like JSON audit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dev._like_audit import collect_targets, recent_review_entries, summarize


def test_collect_targets_covers_msgfeed_and_recent_queue_entries():
    own = {"BV1abcdefghi"}
    msgfeed = [
        {
            "item": {
                "subject_id": 11,
                "uri": "https://www.bilibili.com/video/BV1abcdefghi",
            }
        },
        {
            "item": {
                "subject_id": 22,
                "uri": "https://www.bilibili.com/video/BV1foreign1234",
            }
        },
    ]
    review = [
        {"oid": 33, "bvid": "BV1abcdefghi"},
        {"oid": 44, "bvid": "BV1foreign1234"},
    ]

    targets = collect_targets(msgfeed, review, own)

    assert set(targets) == {11, 33}
    assert targets[11]["sources"] == {"msgfeed"}
    assert targets[33]["sources"] == {"review"}


def test_recent_review_entries_uses_newest_timestamp():
    now = datetime.now(timezone.utc)
    review = {
        "candidates": [
            {
                "rpid": 1,
                "queued_at": (now - timedelta(hours=40)).isoformat(),
                "executed_at": (now - timedelta(hours=1)).isoformat(),
            },
            {
                "rpid": 2,
                "queued_at": (now - timedelta(hours=40)).isoformat(),
                "executed_at": (now - timedelta(hours=30)).isoformat(),
            },
        ]
    }

    entries = recent_review_entries(review, now - timedelta(hours=24))

    assert [entry["rpid"] for entry in entries] == [1]


def test_summarize_flags_unliked_folded_reply_missing_from_queue():
    msgfeed_pages = []
    comments = {
        "11": [
            {
                "page": 1,
                "replies": [
                    {
                        "rpid": 101,
                        "member": {"mid": "999"},
                        "content": {"message": "folded reply"},
                        "action": 0,
                        "reaction": None,
                        "reply_control": {"fold_text": "已折叠"},
                    },
                    {
                        "rpid": 102,
                        "member": {"mid": "3546597260528367"},
                        "content": {"message": "own comment"},
                        "action": 0,
                    },
                ],
            }
        ]
    }

    summary = summarize(msgfeed_pages, comments, [], set())

    assert len(summary["potential_missing"]) == 1
    assert summary["potential_missing"][0]["rpid"] == "101"
    assert summary["potential_missing"][0]["folded"] is True
