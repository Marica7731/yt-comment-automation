"""Regression coverage for msgfeed fallback and root-id verification."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_function(name: str, namespace: dict) -> callable:
    tree = ast.parse((ROOT / "like_fans.py").read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == name
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(ROOT / "like_fans.py"), "exec"), namespace)
    return namespace[name]


def test_msgfeed_fallback_reads_folded_like_state_across_pages():
    calls = []

    def fetch(cursor_id=None, cursor_time=None):
        calls.append((cursor_id, cursor_time))
        if cursor_id is None:
            return [], {"id": 1, "time": 2, "is_end": False}
        return (
            [
                {
                    "item": {
                        "subject_id": 11,
                        "source_id": 101,
                        "like_state": 1,
                    }
                }
            ],
            {"is_end": True},
        )

    resolve = _load_function(
        "resolve_from_msgfeed",
        {"fetch_msgfeed_page": fetch},
    )

    assert resolve(11, 101) is True
    assert calls == [(None, None), (1, 2)]


def test_process_items_passes_msgfeed_root_id_to_state_check():
    seen = []

    def resolve(oid, rpid, root_id=None):
        seen.append((oid, rpid, root_id))
        return False

    tree = ast.parse((ROOT / "like_fans.py").read_text(encoding="utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "process_items"
    )
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "OWNER_MID": "owner",
        "skipped_self": [],
        "liked_set": {"123"},
        "review_statuses": {},
        "resolve_real_liked": resolve,
        "save_liked_set": lambda: None,
        "add_review_candidate": lambda *args, **kwargs: False,
        "_bvid_from_uri": lambda uri: "",
    }
    exec(compile(module, str(ROOT / "like_fans.py"), "exec"), namespace)

    namespace["process_items"](
        [
            {
                "user": {"mid": "fan"},
                "item": {
                    "source_content": "candidate",
                    "source_id": 123,
                    "subject_id": 456,
                    "like_state": 0,
                    "root_id": 789,
                    "uri": "",
                },
            }
        ]
    )

    assert seen == [(456, 123, 789)]
