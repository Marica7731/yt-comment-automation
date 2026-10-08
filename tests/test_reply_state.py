"""Regression coverage for live Bilibili reply like state."""

from __future__ import annotations

from dev._like_audit import summarize
from yt_comment_automation.reply_state import reply_is_liked


def test_reply_is_liked_prefers_up_action_like():
    assert reply_is_liked({"action": 0, "up_action": {"like": True}}) is True
    assert reply_is_liked({"action": 1, "up_action": {"like": False}}) is False


def test_reply_is_liked_falls_back_to_legacy_schema():
    assert reply_is_liked({"action": 1}) is True
    assert reply_is_liked({"action": 0}) is False
    assert reply_is_liked({"like_state": 1}) is True


def test_audit_uses_live_like_flag_instead_of_reply_metadata():
    comments = {
        "11": [
            {
                "page": 1,
                "replies": [
                    {
                        "rpid": 301,
                        "member": {"mid": "999"},
                        "content": {"message": "already liked"},
                        "action": 0,
                        "up_action": {"like": True, "reply": False},
                    }
                ],
            }
        ]
    }

    summary = summarize([], comments, [], set())

    assert summary["potential_missing"] == []
    assert summary["comments"][0]["action"] == 1
    assert summary["comments"][0]["raw_action"] == 0
