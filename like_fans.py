"""给消息中心「回复我的」粉丝回复点赞（带游标翻页）。

规则（用户规格）：
- 从 msgfeed 第一页开始；**整页都是已赞/重复才停止翻页**，页内出现新赞就继续
  请求下一页（游标参数 id/reply_time 来自用户 HAR 实录），安全上限 10 页；
- 已赞跳过（跳过明细只进日志，不发飞书）；自己的回复排除；
- reply/action 是 toggle：只有确认「当前未赞」才发 action，绝不盲发（盲发会把赞取消）；
- 接口里 mid 是字符串：比较一律 str() 归一，否则自己排除永不生效；
- 飞书通知只有标题一个 👍，明细行纯文本；另含评论区补扫（折叠评论不进 msgfeed）。
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, '/opt/yt-comment-automation')
from yt_comment_automation import bili_comment, config
from yt_comment_automation import like_review
from yt_comment_automation.req_pace import pace

OWNER_MID = "3546597260528367"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

cookies = bili_comment.load_cookie_map()
csrf = cookies.get("bili_jct", "")

# 本地已赞集合：点赞成功即落盘，防重复。
DATA_DIR = config.data_dir()
STATE_PATH = DATA_DIR / "liked_rpids.json"
REVIEW_PATH = DATA_DIR / "like_review.json"
try:
    liked_set = set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
except (OSError, ValueError):
    liked_set = set()
liked_set = {str(value) for value in liked_set}
existing_review = like_review.load_review(REVIEW_PATH)
review_statuses = {
    str(item.get("rpid")): str(item.get("status") or "pending")
    for item in existing_review.get("candidates") or []
}
review_candidates: dict[str, dict] = {}

def add_review_candidate(oid, rpid, content, source, bvid="", uri=""):
    key = str(rpid)
    if key in liked_set or key in review_candidates or key in review_statuses:
        return False
    review_candidates[key] = {
        "oid": oid,
        "rpid": rpid,
        "content": content[:200],
        "source": source,
        "bvid": bvid or "",
        "uri": uri or "",
    }
    return True

headers = {
    "User-Agent": UA,
    "Referer": "https://message.bilibili.com/",
    "Cookie": bili_comment.cookie_header(cookies),
}
our_root_rpid_cache = {}  # oid → 我们主评论 rpid（查楼中楼真实状态的 root）
item_uri = {}  # oid → 视频页 uri（楼中楼兜底时反查 bvid 用）

# 自家视频集合：自动发布记录 ∪ 合集快照。仅用于评论区补扫的范围限制——
# 补扫扫的是整个评论区，外人视频（我们只是观众）绝不能扫（10-01 误赞
# 死了啦😭/转生踢我 事故）。msgfeed 点赞不限视频：回复我们的都赞。
OWN_BVIDS: set[str] = set()
try:
    _p = json.loads((DATA_DIR / "processed.json").read_text(encoding="utf-8"))
    OWN_BVIDS.update(_p.get("posted") or [])
except (OSError, ValueError):
    pass
try:
    _snap = json.loads((DATA_DIR / "collections_snapshot.json").read_text(encoding="utf-8"))
    for _v in (_snap.get("videos") if isinstance(_snap, dict) else []) or []:
        if isinstance(_v, dict) and _v.get("bvid"):
            OWN_BVIDS.add(_v["bvid"])
except (OSError, ValueError):
    pass


def _bvid_from_uri(uri: str) -> str | None:
    m = re.search(r"/video/(BV[0-9A-Za-z]{10})", uri or "")
    return m.group(1) if m else None


def is_own_video(bvid: str | None) -> bool:
    return bool(bvid) and bvid in OWN_BVIDS

BASE_MSGFEED = (
    "https://api.bilibili.com/x/msgfeed/reply?platform=web&build=0&mobi_app=web&web_location=0.0"
)


def save_liked_set():
    try:
        STATE_PATH.write_text(json.dumps(sorted(liked_set)), encoding="utf-8")
    except OSError as err:
        print(f"  ⚠️已赞集合写盘失败（不影响本次点赞）: {err}", flush=True)


def fetch_msgfeed_page(cursor_id=None, cursor_time=None):
    """拉一页「回复我的」；带游标参数即翻下一页（参数名来自用户 HAR 实录）。"""
    pace(2.0)
    url = BASE_MSGFEED
    if cursor_id:
        url += f"&id={cursor_id}&reply_time={cursor_time}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    d = data.get("data") or {}
    return d.get("items") or [], d.get("cursor") or {}


def resolve_real_liked(oid, rpid):
    """读该条评论的真实点赞状态。

    粉丝回复多为视频顶层评论（msgfeed 聚合只显示最新一条），所以先查视频
    顶层评论列表（action/reaction 是活字段），查不到再兜底查我们主评论楼中楼。
    返回 True=已赞 False=未赞 None=两处都查不到（复核失败宁漏勿撤）。
    """
    try:
        for pn in (1, 2, 3):
            pace(2.0)
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
            pace(2.0)
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
    pace(2.0)
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
    def save_review_candidates() -> dict:
        payload = like_review.merge_candidates(review_candidates.values(), REVIEW_PATH)
        counts = like_review.summarize(payload)
        return {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "count": counts.get("pending", 0),
            "total": counts.get("total", 0),
            "counts": counts,
            "candidates": list(review_candidates.values()),
        }

    def apply_approved_likes(path: str) -> dict:
        """执行 Codex 审核通过的点赞；每次 action 前重新确认当前未赞。"""
        return like_review.apply_approved(
            resolve_real_liked,
            send_like,
            path,
            liked_set=liked_set,
            save_liked_set=save_liked_set,
            sleep=time.sleep,
        )

    RUN_TS = notify.beijing_now()
except Exception:  # noqa: BLE001
    RUN_TS = time.strftime("%Y-%m-%d %H:%M:%S")
if len(sys.argv) >= 3 and sys.argv[1] == "--apply":
    apply_result = apply_approved_likes(sys.argv[2])
    liked_n = apply_result.get("liked", 0)
    skipped_n = apply_result.get("skipped", 0)
    failed_n = apply_result.get("failed", 0)
    summary = f"汇总: 点赞 {liked_n} | 已赞跳过 {skipped_n} | 失败 {failed_n}"
    print(summary, flush=True)
    if liked_n or failed_n:
        try:
            notify.send_feishu_message(
                notify.build_like_action_brief(
                    apply_result.get("executed", []),
                    summary=summary,
                )
            )
        except Exception as err:  # noqa: BLE001
            print(f"飞书通知失败: {err}", flush=True)
    raise SystemExit(0 if failed_n == 0 else 1)

print(f"==== 点赞任务 run {RUN_TS} ====", flush=True)

liked, skipped_liked, skipped_self, failed = [], [], [], []


def process_items(items):
    """处理一页 msgfeed 条目，返回本页新增点赞数。"""
    new_likes = 0
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

        if str(rpid) in liked_set or item.get("like_state", 0) != 0:
            # 可能已赞：先复核真实状态，确认未赞才补，其余跳过（绝不盲发 action）
            real = resolve_real_liked(oid, rpid)
            if real is True:
                skipped_liked.append(content)
                if str(rpid) not in liked_set:
                    liked_set.add(str(rpid))
                    save_liked_set()
                print(f"  =已赞跳过 rpid={rpid} {content[:30]!r}", flush=True)
                continue
            if real is None:
                skipped_liked.append(content)
                print(f"  ?复核不到按跳过(宁漏勿撤) rpid={rpid} {content[:30]!r}", flush=True)
                continue
            print(f"  ↻复核确认未赞，补赞 rpid={rpid} {content[:30]!r}", flush=True)

        add_review_candidate(
            oid,
            rpid,
            content,
            "msgfeed",
            _bvid_from_uri(item.get("uri", "")) or "",
            item.get("uri", ""),
        )
        new_likes += 1
        print(f"  ⋯待审核 rpid={rpid} {content[:30]!r}", flush=True)
    return new_likes


# 1. 游标翻页：整页都是已赞/重复才停；页内有新赞就继续下一页（安全上限 10 页）
cursor_id = cursor_time = None
page = 0
total_items = 0
while True:
    items, cursor = fetch_msgfeed_page(cursor_id, cursor_time)
    page += 1
    total_items += len(items)
    print(f"第{page}页消息: {len(items)} 条", flush=True)
    for it in items:
        ii = it.get("item") or {}
        if ii.get("subject_id") is not None:
            item_uri[ii["subject_id"]] = ii.get("uri", "")
    new_likes = process_items(items)
    cur = cursor or {}
    if new_likes == 0:
        print(f"第{page}页无新增点赞，停止翻页", flush=True)
        break
    if cur.get("is_end"):
        print("已到末页", flush=True)
        break
    if page >= 10:
        print("达安全页数上限（10 页），停止", flush=True)
        break
    cursor_id, cursor_time = cur.get("id"), cur.get("time")
    time.sleep(2)

# 2. 评论区补扫：折叠评论（纯表情等）可能不进 msgfeed，msgfeed 聚合也只显示
#    同会话最新一条——对涉及视频的评论区直接扫一遍，未赞的粉丝评论补赞。
video_oids = {}
for it in items:
    ii = it.get("item") or {}
    bvid = _bvid_from_uri(ii.get("uri", ""))
    if bvid and is_own_video(bvid) and ii.get("subject_id") is not None:
        video_oids[bvid] = ii["subject_id"]
for bvid, oid in video_oids.items():
    for pn in (1, 2, 3):
        try:
            pace(2.0)
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
            if str(rpid2) in liked_set or rp.get("action") == 1:
                continue
            add_review_candidate(oid, rpid2, content2, f"sweep:{bvid}", bvid)
            print(f"  ⋯待审核(评论区补扫 {bvid}) rpid={rpid2} {content2[:30]!r}", flush=True)
        if len(replies) < 20:
            break

review_payload = save_review_candidates()
review_summary = f"点赞候选待 Codex 审核: {review_payload['count']} 条，文件: {REVIEW_PATH}"
print(review_summary, flush=True)
print(f"翻页: {page} 页 / {total_items} 条", flush=True)
if review_payload["count"]:
    try:
        notify.send_feishu_message(
            notify.build_like_review_brief(review_payload.get("candidates", []))
        )
    except Exception as err:  # noqa: BLE001
        print(f"飞书通知失败: {err}", flush=True)
