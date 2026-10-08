"""Regression coverage for like_fans candidate deduplication logging."""

from __future__ import annotations

import ast
import contextlib
import io
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

def _load_candidate_gate(existing_review: dict) -> tuple[dict, object]:
    tree = ast.parse((ROOT / "like_fans.py").read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "review_statuses" in targets:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "add_review_candidate":
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "existing_review": existing_review,
        "review_candidates": {},
        "liked_set": set(),
        "root_id_by_rpid": {
            str(item["rpid"]): str(item.get("root_id") or "")
            for item in existing_review.get("candidates") or []
            if item.get("root_id")
        },
    }
    exec(compile(module, str(ROOT / "like_fans.py"), "exec"), namespace)
    return namespace["review_statuses"], namespace["add_review_candidate"]


def _load_process_items(add_result: bool):
    tree = ast.parse((ROOT / "like_fans.py").read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "process_items"
    )
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)

    def add_review_candidate(*args, **kwargs):
        return add_result

    namespace = {
        "OWNER_MID": "owner",
        "skipped_self": [],
        "liked_set": set(),
        "resolve_real_liked": lambda oid, rpid: False,
        "save_liked_set": lambda: None,
        "add_review_candidate": add_review_candidate,
        "_bvid_from_uri": lambda uri: "",
    }
    exec(compile(module, str(ROOT / "like_fans.py"), "exec"), namespace)
    return namespace["process_items"], namespace


def _feed(add_result: bool) -> tuple[int, str]:
    process_items, namespace = _load_process_items(add_result)
    item = {
        "user": {"mid": "fan"},
        "item": {
            "source_content": "spam",
            "source_id": 123,
            "subject_id": 456,
            "like_state": 0,
            "uri": "",
            "root_id": "",
        },
    }
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        count = process_items([item])
    assert namespace["skipped_self"] == []
    return count, output.getvalue()


def test_rejected_candidate_is_not_counted_or_logged():
    count, output = _feed(add_result=False)
    assert count == 0
    assert "123" not in output


def test_new_candidate_is_counted_and_logged():
    count, output = _feed(add_result=True)
    assert count == 1
    assert "123" in output

def test_stale_list_candidate_can_requeue_on_fresh_msgfeed():
    statuses, add_candidate = _load_candidate_gate(
        {
            "candidates": [
                {"rpid": 90, "status": "failed", "result": "stale_list"},
                {"rpid": 91, "status": "applied"},
            ]
        }
    )
    assert "90" not in statuses
    assert statuses["91"] == "applied"
    assert add_candidate(
        1, 90, "fresh", "msgfeed", bvid="BV1test", uri="", root_id=""
    ) is True

def _load_candidate_namespace(existing_review: dict) -> dict:
    tree = ast.parse((ROOT / "like_fans.py").read_text(encoding="utf-8"))
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "review_statuses" in targets:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "add_review_candidate":
            body.append(node)
    module = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "existing_review": existing_review,
        "review_candidates": {},
        "liked_set": set(),
        "root_id_by_rpid": {
            str(item["rpid"]): str(item.get("root_id") or "")
            for item in existing_review.get("candidates") or []
            if item.get("root_id")
        },
    }
    exec(compile(module, str(ROOT / "like_fans.py"), "exec"), namespace)
    return namespace

def test_existing_pending_refreshes_without_counting_as_new():
    namespace = _load_candidate_namespace(
        {"candidates": [
            {"rpid": 92, "status": "pending", "root_id": "77"},
            {"rpid": 91, "status": "applied"},
        ]}
    )
    assert namespace["add_review_candidate"](
        1, 92, "fresh", "msgfeed", bvid="BV1test", uri="", root_id=""
    ) is False
    assert namespace["review_candidates"]["92"]["content"] == "fresh"
    assert namespace["review_candidates"]["92"]["root_id"] == "77"
    assert namespace["add_review_candidate"](
        1, 91, "ignored", "msgfeed", bvid="BV1test", uri="", root_id=""
    ) is False
    assert "91" not in namespace["review_candidates"]
