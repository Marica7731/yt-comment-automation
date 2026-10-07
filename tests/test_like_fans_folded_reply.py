"""Regression coverage for folded msgfeed replies and external like state."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_functions(names: set[str], namespace: dict):
    tree = ast.parse((ROOT / "like_fans.py").read_text(encoding="utf-8"))
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == names
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(ROOT / "like_fans.py"), "exec"), namespace)
    return namespace


def test_collect_video_oids_keeps_videos_from_earlier_pages():
    namespace = _load_functions(
        {"collect_video_oids"},
        {
            "_bvid_from_uri": lambda uri: "BV1first1234" if "BV1first1234" in uri else "",
            "is_own_video": lambda bvid: bvid == "BV1first1234",
        },
    )
    first_page = [
        {"item": {"uri": "https://www.bilibili.com/video/BV1first1234", "subject_id": 11}},
        {"item": {"uri": "https://www.bilibili.com/video/BV1foreign1234", "subject_id": 22}},
    ]
    final_page = [
        {"item": {"uri": "https://www.bilibili.com/video/BV1foreign1234", "subject_id": 33}},
    ]

    assert namespace["collect_video_oids"]([*first_page, *final_page]) == {
        "BV1first1234": 11,
    }


def test_external_like_is_written_to_dedup_state_once():
    state = set()
    saved = []
    namespace = _load_functions(
        {"remember_liked"},
        {
            "liked_set": state,
            "save_liked_set": lambda: saved.append(tuple(sorted(state))),
        },
    )

    namespace["remember_liked"](316395831537)
    namespace["remember_liked"](316395831537)

    assert namespace["liked_set"] == {"316395831537"}
    assert saved == [("316395831537",)]
