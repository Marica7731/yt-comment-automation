"""bili_comment 跳过判定单元测试：本账号已有评论即跳过，不看条数/格式。"""
import sys
from pathlib import Path

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
