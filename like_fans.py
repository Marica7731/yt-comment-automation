"""给消息中心「回复我的」第一页粉丝回复点赞。

规则（用户规格）：
- 只取 msgfeed 第一页；已赞跳过（跳过明细只进日志，不发飞书）；自己的回复排除。
- reply/action 是 toggle：只有确认「当前未赞」才发 action，绝不盲发（盲发会把赞取消）。
- 接口里 mid 是字符串：比较一律 str() 归一，否则自己排除永不生效。
- 飞书通知只有标题一个 👍，明细行纯文本。
"""
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, '/opt/yt-comment-automation')
from yt_comment_automation import bili_comment

OWNER_MID = "3546597260528367"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

cookies = bili_comment.load_cookie_map()
csrf = cookies.get("bili_jct", "")

# 本地已赞集合：点赞成功即落盘，防重复。
STATE_PATH = pathlib.Path("/opt/yt-comment-automation/data/liked_rpids.json")
try:
    liked_set = set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
except (OSError, ValueError):
    liked_set = set()

headers = {
    "User-Agent": UA,
    "Referer": "https://message.bilibili.com/",
    "Cookie": bili_comment.cookie_header(cookies),
}
our_root_rpid_cache = {}  # oid → 我们主评论 rpid（查楼中楼真实状态的 root）


def save_liked_set():
    try:
        STATE_PATH.write_text(json.dumps(sorted(liked_set)), encoding="utf-8")
    except OSError as err:
        print(f"  ⚠️已赞集合写盘失败（不影响本次点赞）: {err}", flush=True)


def resolve_real_liked(oid, rpid):
    """读该条评论的真实点赞状态。

    粉丝回复多为视频顶层评论（msgfeed 聚合只显示最新一条），所以先查视频
    顶层评论列表（action/reaction 是活字段），查不到再兜底查我们主评论楼中楼。
    返回 True=已赞 False=未赞 None=两处都查不到（复核失败宁漏勿撤）。
    """
    try:
        for pn in (1, 2, 3):
            list_url = (
                f"https://api.bilibili.com/x/v2/reply?type=1&oid={oid}"
                f"&sort=2&ps=20&pn={pn}"
            )
            req_d = urllib.request.Request(list_url, headers=headers)
            with urllib.request.urlopen(req_d, timeout=30) as resp_d:
                dd = json.loads(resp_d.read().decode("utf-8"))
            replies = (dd.get("data") or {}).get("replies") or []
            for rp in replies:
                if rp.get("rpid") == rpid:
                    return ((rp.get("reaction") or {}).get("status") == 1) or (rp.get("action") == 1)
            if len(replies) < 20:
                break
        root = our_root_rpid_cache.get(oid)
        if not root:
            m_bv = re.search(r"/video/(BV[0-9A-Za-z]{10})", item_uri.get(oid, ""))
            if m_bv:
                own_c = bili_comment.find_own_comment(m_bv.group(1), cookies)
                if own_c:
                    root = our_root_rpid_cache[oid] = own_c.rpid
        if root:
            detail_url = (
                f"https://api.bilibili.com/x/v2/reply/reply?type=1"
                f"&oid={oid}&root={root}&ps=49&pn=1"
            )
            req_d = urllib.request.Request(detail_url, headers=headers)
            with urllib.request.urlopen(req_d, timeout=30) as resp_d:
                dd = json.loads(resp_d.read().decode("utf-8"))
            for rp in ((dd.get("data") or {}).get("replies")) or []:
                if rp.get("rpid") == rpid:
                    return ((rp.get("reaction") or {}).get("status") == 1) or (rp.get("action") == 1)
        return None
    except Exception as detail_err:  # noqa: BLE001
        print(f"  ⚠️状态复核失败 rpid={rpid}: {detail_err}", flush=True)
        return None


def send_like(oid, rpid):
    payload = {"oid": oid, "type": 1, "rpid": rpid, "action": 1, "csrf": csrf}
    body = urllib.parse.urlencode(payload).encode()
    req2 = urllib.request.Request(
        "https://api.bilibili.com/x/v2/reply/action",
        data=body,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req2, timeout=30) as resp2:
        return json.loads(resp2.read().decode("utf-8"))


try:
    from yt_comment_automation import notify
    RUN_TS = notify.beijing_now()
except Exception:  # noqa: BLE001
    RUN_TS = time.strftime("%Y-%m-%d %H:%M:%S")
print(f"==== 点赞任务 run {RUN_TS} ====", flush=True)

# 1. 消息中心「回复我的」第一页
req = urllib.request.Request(
    "https://api.bilibili.com/x/msgfeed/reply?platform=web&build=0&mobi_app=web&web_location=0.0",
    headers=headers,
)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode("utf-8"))
items = (data.get("data") or {}).get("items") or []
print(f"第一页消息: {len(items)} 条", flush=True)

item_uri = {}
for it in items:
    ii = it.get("item") or {}
    if ii.get("subject_id") is not None:
        item_uri[ii["subject_id"]] = ii.get("uri", "")

liked, skipped_liked, skipped_self, failed = [], [], [], []
for it in items:
    replyer = str((it.get("user") or {}).get("mid") or "")
    item = it.get("item") or {}
    content = item.get("source_content", "")
    rpid = item.get("source_id")
    oid = item.get("subject_id")

    # 自己的回复：排除并落日志（mid 一律按字符串比较）
    if replyer == OWNER_MID:
        skipped_self.append(content)
        print(f"  ⊘自己排除 mid={replyer} {content[:30]!r}", flush=True)
        continue

    if rpid in liked_set or item.get("like_state", 0) != 0:
        # 可能已赞：先复核真实状态，确认未赞才补，其余跳过（绝不盲发 action）
        real = resolve_real_liked(oid, rpid)
        if real is True:
            skipped_liked.append(content)
            if rpid not in liked_set:
                liked_set.add(rpid)
                save_liked_set()
            print(f"  =已赞跳过 rpid={rpid} {content[:30]!r}", flush=True)
            continue
        if real is None:
            skipped_liked.append(content)
            print(f"  ?复核不到按跳过(宁漏勿撤) rpid={rpid} {content[:30]!r}", flush=True)
            continue
        print(f"  ↻复核确认未赞，补赞 rpid={rpid} {content[:30]!r}", flush=True)

    # 真正点赞（新回复，或复核确认未赞）
    try:
        r = send_like(oid, rpid)
        if r.get("code") == 0:
            liked.append((rpid, content[:40]))
            liked_set.add(rpid)
            save_liked_set()
            print(f"  ✓赞 rpid={rpid} {content[:30]!r}", flush=True)
        else:
            failed.append((rpid, r.get("code"), r.get("message")))
            print(f"  ✗失败 rpid={rpid} code={r.get('code')} {r.get('message')}", flush=True)
    except Exception as err:  # noqa: BLE001
        failed.append((rpid, "EXC", str(err)[:60]))
        print(f"  ✗异常 {err}", flush=True)
    time.sleep(8)  # 频控：每个真实点赞间隔 8 秒（跳过的不消耗间隔）

print(flush=True)

# 2. 评论区补扫：折叠评论（纯表情等）可能不进消息列表，msgfeed 聚合也只显示
#    同会话最新一条——对涉及视频的评论区直接扫一遍，未赞的粉丝评论补赞。
video_oids = {}
for it in items:
    ii = it.get("item") or {}
    m_bv = re.search(r"/video/(BV[0-9A-Za-z]{10})", ii.get("uri", ""))
    if m_bv and ii.get("subject_id") is not None:
        video_oids[m_bv.group(1)] = ii["subject_id"]
for bvid, oid in video_oids.items():
    for pn in (1, 2, 3):
        try:
            sweep_url = (
                f"https://api.bilibili.com/x/v2/reply?type=1&oid={oid}"
                f"&sort=2&ps=20&pn={pn}"
            )
            req3 = urllib.request.Request(sweep_url, headers=headers)
            with urllib.request.urlopen(req3, timeout=30) as resp3:
                d3 = json.loads(resp3.read().decode("utf-8"))
        except Exception as sweep_err:  # noqa: BLE001
            print(f"  ⚠️评论区读取失败 {bvid} pn={pn}: {sweep_err}", flush=True)
            break
        replies = (d3.get("data") or {}).get("replies") or []
        for rp in replies:
            mid2 = str((rp.get("member") or {}).get("mid") or "")
            rpid2 = rp.get("rpid")
            content2 = (rp.get("content") or {}).get("message", "")
            if mid2 == OWNER_MID:
                continue
            if rpid2 in liked_set or rp.get("action") == 1:
                continue
            try:
                r = send_like(oid, rpid2)
            except Exception as err2:  # noqa: BLE001
                failed.append((rpid2, "EXC", str(err2)[:60]))
                print(f"  ✗异常(评论区补扫 {bvid}) {err2}", flush=True)
                time.sleep(8)
                continue
            if r.get("code") == 0:
                liked.append((rpid2, content2[:40]))
                liked_set.add(rpid2)
                save_liked_set()
                print(f"  ✓赞(评论区补扫 {bvid}) rpid={rpid2} {content2[:30]!r}", flush=True)
            else:
                failed.append((rpid2, r.get("code"), r.get("message")))
                print(f"  ✗失败(评论区补扫 {bvid}) rpid={rpid2} code={r.get('code')} {r.get('message')}", flush=True)
            time.sleep(8)
        if len(replies) < 20:
            break

summary = f"汇总: 点赞 {len(liked)} | 已赞跳过 {len(skipped_liked)} | 自己排除 {len(skipped_self)} | 失败 {len(failed)}"
print(summary, flush=True)
print("-- 已赞跳过明细（仅日志）--", flush=True)
for c in skipped_liked:
    print(f"   {c[:40]!r}", flush=True)
print("-- 自己排除明细（仅日志）--", flush=True)
for c in skipped_self:
    print(f"   {c[:40]!r}", flush=True)

# 飞书通知（有点赞动作才发；纯跳过不打扰）
if liked:
    try:
        detail = chr(10).join(c for _, c in liked)
        if failed:
            detail += chr(10) + f"⚠️失败 {len(failed)} 条"
        brief = chr(10).join([
            "👍粉丝回复点赞",
            summary,
            detail,
            f"时间：{notify.beijing_now()}",
        ])
        ok, note = notify.send_feishu_message(brief)
        print(f"飞书: {ok} {note}", flush=True)
    except Exception as err:  # noqa: BLE001
        print(f"飞书通知失败: {err}", flush=True)
