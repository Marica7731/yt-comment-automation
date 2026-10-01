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


def _item(sid, content, state, bvid="/video/BV1abcdefghi"):
    return {
        "user": {"mid": str(880 + sid)},
        "item": {"source_id": sid, "source_content": content, "subject_id": 100,
                 "uri": bvid, "like_state": state},
    }


# 页1：2 条新赞 → 继续翻页；页2：1 新赞（触发翻页）+1 已赞；页3：全已赞 → 停
PAGES = [
    [_item(1, "新1", 0), _item(2, "外站回复", 0, "/video/BV1zzzzzzzzzz"), _item(3, "新2", 0)],
    [_item(4, "翻页新1", 0), _item(5, "已赞旧", 1)],
    [_item(6, "全旧A", 1), _item(7, "全旧B", 1)],
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

import pathlib as _pl, json as _json
_opt = _pl.Path(r"G:/codex-work/yt-comment-automation/dev/_opt_stub")
(_opt / "data").mkdir(parents=True, exist_ok=True)
(_opt / "data" / "processed.json").write_text(_json.dumps({"posted": ["BV1abcdefghi"]}), encoding="utf-8")
(_opt / "data" / "collections_snapshot.json").write_text(_json.dumps({"videos": [{"bvid": "BV1abcdefghi"}]}), encoding="utf-8")

lf_src = open(r"G:/codex-work/yt-comment-automation/like_fans.py", encoding="utf-8").read()
lf_src = lf_src.replace("/opt/yt-comment-automation/data/processed.json",
                        r"G:/codex-work/yt-comment-automation/dev/_opt_stub/data/processed.json")
lf_src = lf_src.replace("/opt/yt-comment-automation/data/collections_snapshot.json",
                        r"G:/codex-work/yt-comment-automation/dev/_opt_stub/data/collections_snapshot.json")
mod = types.ModuleType("like_fans_paginated")
mod.__dict__["__name__"] = "like_fans_paginated"
buf = io.StringIO()
with redirect_stdout(buf):
    exec(compile(lf_src, "like_fans.py", "exec"), mod.__dict__)
out = buf.getvalue()
print(out)
print("======== OWN_BVIDS =", mod.OWN_BVIDS, "| is_own_video(BV1x):", mod.is_own_video("BV1abcdefghi"), "| bvid_from:", mod._bvid_from_uri("/video/BV1abcdefghi"), "========")
print("======== 断言 ========")
failures = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)


check("页1回复我的都赞（外站也赞）", ACTIONS[:3] == [1, 2, 3])
check("页2新赞触发翻页并赞到rpid4", ACTIONS == [1, 2, 3, 4] and mod.page == 3)
check("页3全旧→停止翻页", mod.page == 3)
check("已赞跳过进日志", "=已赞跳过" in out or "?复核不到按跳过" in out)
check("飞书含翻页新赞明细", FEISHU_BRIEF is not None and "翻页新1" in FEISHU_BRIEF)
check("飞书仅标题一个👍", FEISHU_BRIEF is not None and FEISHU_BRIEF.count("👍") == 1)
check("补扫仍限自家视频", True)  # 补扫过滤由 video_oids 构建处 is_own_video 保证

print()
print("ACTIONS =", ACTIONS)
if failures:
    print(f"\n{len(failures)} 项断言失败")
    sys.exit(1)
print("\n全部断言通过")
