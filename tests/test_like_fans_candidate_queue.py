"""Regression coverage for like_fans candidate deduplication logging."""

from __future__ import annotations

import ast
import contextlib
import io
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
