"""bili_comment 跳过判定单元测试：本账号已有评论即跳过，不看条数/格式。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yt_comment_automation import bili_comment  # noqa: E402


class FakeComment:
    def __init__(self, mid, rpid, message):
        self.mid = mid
        self.rpid = rpid
        self.message = message


def test_find_own_comment_any_message(monkeypatch):
    """本账号任一评论（哪怕 1 行）都算已发过。"""
    comments = [
        FakeComment("3546597260528367", "rpid1", "0:05:57 \tワールドイズマイン / ryo(supercell)"),
        FakeComment("12345", "rpid2", "普通观众评论"),
    ]
    monkeypatch.setattr(bili_comment, "list_comments", lambda bvid, cookies: comments)
    found = bili_comment.find_own_comment("BV1xxx", {})
    assert found is not None
    assert found.rpid == "rpid1"


def test_find_own_comment_not_found(monkeypatch):
    """本账号无评论 → 返回 None（应继续处理）。"""
    comments = [FakeComment("12345", "rpid2", "普通观众评论")]
    monkeypatch.setattr(bili_comment, "list_comments", lambda bvid, cookies: comments)
    found = bili_comment.find_own_comment("BV1xxx", {})
    assert found is None


def test_find_own_comment_single_song(monkeypatch):
    """只有 1 首歌的评论也算已发过（不死循环）。"""
    comments = [FakeComment("3546597260528367", "rpid1", "0:12:11 Tokimeki / Vaundy")]
    monkeypatch.setattr(bili_comment, "list_comments", lambda bvid, cookies: comments)
    found = bili_comment.find_own_comment("BV1xxx", {})
    assert found is not None


def test_delete_comment_rejects_invalid_input_before_network(monkeypatch):
    def fail_get_aid(*args, **kwargs):
        raise AssertionError("非法入参不得触发网络请求")

    monkeypatch.setattr(bili_comment, "get_aid", fail_get_aid)
    cookies = {"bili_jct": "csrf", "DedeUserID": "3546597260528367"}

    with pytest.raises(ValueError):
        bili_comment.delete_comment("not-a-bvid", "123456", cookies)
    with pytest.raises(ValueError):
        bili_comment.delete_comment("BV1ybHt6kELs", "not-a-rpid", cookies)


def test_delete_comment_rejects_cookie_owner_mismatch_before_network(monkeypatch):
    def fail_get_aid(*args, **kwargs):
        raise AssertionError("账号不匹配不得触发网络请求")

    monkeypatch.setattr(bili_comment, "get_aid", fail_get_aid)
    monkeypatch.setattr(bili_comment.config, "owner_mid", lambda: "3546597260528367")
    cookies = {"bili_jct": "csrf", "DedeUserID": "999999"}

    with pytest.raises(RuntimeError, match="不一致"):
        bili_comment.delete_comment("BV1ybHt6kELs", "123456", cookies)


def test_delete_comment_rejects_foreign_rpid_before_delete_request(monkeypatch):
    deleted = []

    def unexpected_request(*args, **kwargs):
        deleted.append(args)
        raise AssertionError("非本账号评论不得调用删除接口")

    monkeypatch.setattr(bili_comment.config, "owner_mid", lambda: "3546597260528367")
    monkeypatch.setattr(bili_comment, "get_aid", lambda bvid, cookies: 99)
    monkeypatch.setattr(
        bili_comment,
        "list_comments",
        lambda bvid, cookies, max_pages: [FakeComment("888888", "123456", "别人评论")],
    )
    monkeypatch.setattr(bili_comment, "_request_json", unexpected_request)
    cookies = {"bili_jct": "csrf", "DedeUserID": "3546597260528367"}

    with pytest.raises(RuntimeError, match="拒绝删除"):
        bili_comment.delete_comment("BV1ybHt6kELs", "123456", cookies)
    assert deleted == []


def test_delete_comment_allows_verified_own_rpid(monkeypatch):
    calls = []

    def request_json(url, cookies, referer, data=None):
        calls.append({"url": url, "referer": referer, "data": data})
        return {"code": 0}

    monkeypatch.setattr(bili_comment.config, "owner_mid", lambda: "3546597260528367")
    monkeypatch.setattr(bili_comment, "get_aid", lambda bvid, cookies: 99)
    monkeypatch.setattr(
        bili_comment,
        "list_comments",
        lambda bvid, cookies, max_pages: [FakeComment("3546597260528367", "123456", "本账号评论")],
    )
    monkeypatch.setattr(bili_comment, "_request_json", request_json)
    cookies = {"bili_jct": "csrf", "DedeUserID": "3546597260528367"}

    response = bili_comment.delete_comment("BV1ybHt6kELs", "123456", cookies)

    assert response == {"code": 0}
    assert len(calls) == 1
    assert calls[0]["url"] == bili_comment.REPLY_DEL_API
    assert calls[0]["data"] == {
        "type": 1,
        "oid": 99,
        "rpid": "123456",
        "csrf": "csrf",
    }
