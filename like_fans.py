"""给消息中心「回复我的」第一页粉丝回复点赞（已赞跳过，自己回复排除）。"""
import json
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, '/opt/yt-comment-automation')
from yt_comment_automation import bili_comment

OWNER_MID = 3546597260528367
MY_MID = OWNER_MID  # 排除自己
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

cookies = bili_comment.load_cookie_map()
csrf = cookies.get("bili_jct", "")

# 本地已赞集合：reply/action 是 toggle，重复发会把赞取消；like_state 有缓存延迟不可靠。
# 点赞成功即落盘，硬防重复。
import pathlib as _pl
STATE_PATH = _pl.Path("/opt/yt-comment-automation/data/liked_rpids.json")
try:
    liked_set = set(json.loads(STATE_PATH.read_text(encoding="utf-8")))
except (OSError, ValueError):
    liked_set = set()
headers = {
    "User-Agent": UA,
    "Referer": "https://message.bilibili.com/",
    "Cookie": bili_comment.cookie_header(cookies),
}

# 1. 消息中心「回复我的」第一页
req = urllib.request.Request(
    "https://api.bilibili.com/x/msgfeed/reply?platform=web&build=0&mobi_app=web&web_location=0.0",
    headers=headers,
)
with urllib.request.urlopen(req, timeout=30) as resp:
    data = json.loads(resp.read().decode("utf-8"))
items = (data.get("data") or {}).get("items") or []
print(f"第一页消息: {len(items)} 条", flush=True)

liked, skipped_liked, skipped_self, failed = [], [], [], []
for it in items:
    replyer = (it.get("user") or {}).get("mid")
    item = it.get("item") or {}
    if replyer == MY_MID:
        skipped_self.append(item.get("source_content", ""))
        continue
    rpid = item.get("source_id")
    if item.get("like_state", 0) != 0 or rpid in liked_set:
        skipped_liked.append(item.get("source_content", ""))
        continue
    payload = {
        "oid": item.get("subject_id"),
        "type": 1,
        "rpid": rpid,
        "action": 1,
        "csrf": csrf,
    }
    body = urllib.parse.urlencode(payload).encode()
    req2 = urllib.request.Request(
        "https://api.bilibili.com/x/v2/reply/action",
        data=body,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req2, timeout=30) as resp2:
            r = json.loads(resp2.read().decode("utf-8"))
        if r.get("code") == 0:
            liked.append((payload["rpid"], item.get("source_content", "")[:40]))
            liked_set.add(payload["rpid"])
            STATE_PATH.write_text(json.dumps(sorted(liked_set)), encoding="utf-8")
            print(f"  ✓赞 rpid={payload['rpid']} {item.get('source_content','')[:30]!r}", flush=True)
        else:
            failed.append((payload["rpid"], r.get("code"), r.get("message")))
            print(f"  ✗失败 rpid={payload['rpid']} code={r.get('code')} {r.get('message')}", flush=True)
    except Exception as err:  # noqa: BLE001
        failed.append((payload.get("rpid"), "EXC", str(err)[:60]))
        print(f"  ✗异常 {err}", flush=True)
    time.sleep(6)  # 频控：每分钟最多 10 个点赞，6 秒/个最稳

print(flush=True)
print(f"汇总: 点赞 {len(liked)} | 已赞跳过 {len(skipped_liked)} | 自己排除 {len(skipped_self)} | 失败 {len(failed)}", flush=True)
