"""Helpers for reading the current like state from Bilibili reply JSON."""

from __future__ import annotations

from typing import Any


def reply_is_liked(reply: dict[str, Any]) -> bool:
    """Return the live like flag without treating reply metadata as a like flag."""
    up_action = reply.get("up_action")
    if isinstance(up_action, dict) and "like" in up_action:
        return bool(up_action.get("like"))

    reaction = reply.get("reaction")
    if isinstance(reaction, dict) and reaction.get("status") is not None:
        return reaction.get("status") == 1

    if reply.get("like_state") is not None:
        return bool(reply.get("like_state"))

    return reply.get("action") == 1
