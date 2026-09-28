"""mock 测 like_fans 游标翻页：页有新赞→继续翻页；整页已赞→停。"""
import io
import json
import sys
import types
from contextlib import redirect_stdout

fake_pkg = types.ModuleType("yt_comment_automation")
fake_bili = types.ModuleType("yt_comment_automation.bili_comment")
fake_notify = types.ModuleType("yt_comment_automation.notify")
FEISHU_BRIEF = None

fake_bili.load_cookie_map = lambda: {"bili_jct": "t"}
fake_bili.cookie_header = lambda c: "bili_jct=t"
fake_bili.find_own_comment = lambda bvid, cookies: None
fake_notify.beijing_now = lambda: "T"


def _send(brief):
    global FEISHU_BRIEF
    FEISHU_BRIEF = brief
    return True, "ok"


fake_notify.send_feishu_message = _send
fake_pkg.bili_comment = fake_bili
fake_pkg.notify = fake_notify
sys.modules["yt_comment_automation"] = fake_pkg
sys.modules["yt_comment_automation.bili_comment"] = fake_bili
sys.modules["yt_comment_automation.notify"] = fake_notify

fake_pace_mod = types.ModuleType("yt_comment_automation.req_pace")
fake_pace_mod.pace = lambda gap=2.0: None
sys.modules["yt_comment_automation.req_pace"] = fake_pace_mod


def _item(sid, content, state):
    return {
        "user": {"mid": str(880 + sid)},
        "item": {"source_id": sid, "source_content": content, "subject_id": 100,
                 "uri": "/video/BV1x", "like_state": state},
    }


# 页1：2 条新赞 → 继续翻页；页2：1 新赞（触发翻页）+1 已赞；页3：全已赞 → 停
PAGES = [
    [_item(1, "新1", 0), _item(2, "新2", 0)],
    [_item(3, "翻页新1", 0), _item(4, "已赞旧", 1)],
    [_item(5, "全旧A", 1), _item(6, "全旧B", 1)],
]
STATE = {"page": 0}
ACTIONS = []


def fake_urlopen(req, timeout=30):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    body = getattr(req, "data", None)
    if "msgfeed/reply" in url:
        i = min(STATE["page"], len(PAGES) - 1)
        STATE["page"] += 1
        resp = {"code": 0, "data": {"items": PAGES[i],
                 "cursor": {"is_end": STATE["page"] >= len(PAGES), "id": 1, "time": 2}}}
    elif "reply/action" in url:
        payload = dict(p.split("=") for p in body.decode().split("&"))
        ACTIONS.append(int(payload["rpid"]))
        resp = {"code": 0, "message": "OK"}
    else:
        resp = {"code": 0, "data": {"replies": []}}

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(resp).encode()

    return R()


import time as _time
import urllib.request
urllib.request.urlopen = fake_urlopen
_time.sleep = lambda *a: None  # type: ignore

import importlib.util
spec = importlib.util.spec_from_file_location("like_fans_paginated", r"G:/codex-work/yt-comment-automation/like_fans.py")
mod = importlib.util.module_from_spec(spec)
buf = io.StringIO()
with redirect_stdout(buf):
    spec.loader.exec_module(mod)
out = buf.getvalue()
print(out)
print("======== 断言 ========")
failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


check("页1两条新回复被赞", ACTIONS[:2] == [1, 2])
check("页2新赞触发翻页并赞到第3条", ACTIONS == [1, 2, 3])
check("页3全旧→停止翻页（只处理3页）", mod.page == 3)
check("已赞跳过进日志", "=已赞跳过" in out or "?复核不到按跳过" in out)
check("飞书含翻页新赞明细", FEISHU_BRIEF is not None and "翻页新1" in FEISHU_BRIEF)
check("飞书仅标题一个👍", FEISHU_BRIEF is not None and FEISHU_BRIEF.count("👍") == 1)

print()
print("ACTIONS =", ACTIONS)
if failures:
    print(f"\n{len(failures)} 项断言失败")
    sys.exit(1)
print("\n全部断言通过")
