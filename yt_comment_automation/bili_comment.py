"""B站评论相关：cookie 加载、检测已有评论、发布评论。"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import config

VIEW_API = "https://api.bilibili.com/x/web-interface/view"
REPLY_LIST_API = "https://api.bilibili.com/x/v2/reply"
REPLY_ADD_API = "https://api.bilibili.com/x/v2/reply/add"
REPLY_DEL_API = "https://api.bilibili.com/x/v2/reply/del"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class BiliComment:
    rpid: str
    mid: str
    uname: str
    ctime: int
    like: int
    message: str


def load_cookie_map(path: str | None = None) -> dict[str, str]:
    """读取 biliup 格式 cookie JSON 或 Cookie 头文本。"""
    path = path or config.cookie_file()
    raw = open(path, encoding="utf-8").read().strip()
    if not raw:
        raise RuntimeError(f"cookie 文件为空: {path}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return parse_cookie_header(raw)
    cookies: dict[str, str] = {}
    items = None
    if isinstance(data, dict):
        items = ((data.get("cookie_info") or {}).get("cookies")) or data.get("cookies")
        if isinstance(data.get("cookie"), str):
            cookies.update(parse_cookie_header(data["cookie"]))
    elif isinstance(data, list):
        items = data
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("name") and item.get("value"):
                cookies[str(item["name"])] = str(item["value"])
    elif isinstance(items, dict):
        cookies = {str(k): str(v) for k, v in items.items() if v}
    missing = [k for k in ("SESSDATA", "bili_jct", "DedeUserID") if not cookies.get(k)]
    if missing:
        raise RuntimeError(f"cookie 缺少必要字段: {', '.join(missing)}")
    return cookies


def parse_cookie_header(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in text.split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip()
        if name and value:
            out[name] = value
    return out


def cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _request_json(url: str, cookies: dict[str, str], referer: str, data: dict | None = None) -> dict:
    headers = {
        "User-Agent": UA,
        "Referer": referer,
        "Cookie": cookie_header(cookies),
    }
    body = None
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_aid(bvid: str, cookies: dict[str, str]) -> int:
    data = _request_json(f"{VIEW_API}?bvid={bvid}", cookies, "https://www.bilibili.com/")
    if data.get("code") != 0:
        raise RuntimeError(f"view 接口异常 {bvid}: {data.get('message')}")
    return int(data["data"]["aid"])


def list_comments(bvid: str, cookies: dict[str, str], max_pages: int = 3) -> list[BiliComment]:
    """拉取视频顶层评论（不包含楼中楼）。"""
    aid = get_aid(bvid, cookies)
    out: list[BiliComment] = []
    for page in range(1, max_pages + 1):
        url = f"{REPLY_LIST_API}?type=1&oid={aid}&sort=2&pn={page}&ps=20"
        data = _request_json(url, cookies, f"https://www.bilibili.com/video/{bvid}")
        if data.get("code") != 0:
            break
        replies = ((data.get("data") or {}).get("replies")) or []
        if not replies:
            break
        for rep in replies:
            out.append(
                BiliComment(
                    rpid=str(rep.get("rpid", "")),
                    mid=str((rep.get("member") or {}).get("mid", "")),
                    uname=(rep.get("member") or {}).get("uname", ""),
                    ctime=int(rep.get("ctime", 0)),
                    like=int(rep.get("like", 0)),
                    message=(rep.get("content") or {}).get("message", "") or "",
                )
            )
    return out


def find_own_comment(bvid: str, cookies: dict[str, str]) -> BiliComment | None:
    """检查本账号（owner）是否已在视频下发布过评论。

    判定：只要评论来自 owner mid 即视为已发过（不管内容、条数、格式）。
    因为自动化只会发歌单评论，rpid 存在 = 已发过 → 跳过，绝无死循环。
    """
    owner_mid = config.owner_mid()
    for comment in list_comments(bvid, cookies):
        if comment.mid == owner_mid:
            return comment
    return None


def post_comment(bvid: str, message: str, cookies: dict[str, str]) -> dict:
    """发布评论到视频。返回接口响应 dict。"""
    aid = get_aid(bvid, cookies)
    bili_jct = cookies.get("bili_jct", "")
    if not bili_jct:
        raise RuntimeError("cookie 缺少 bili_jct，无法发布")
    payload = {
        "type": 1,
        "oid": aid,
        "message": message,
        "plat": 1,
        "csrf": bili_jct,
    }
    return _request_json(REPLY_ADD_API, cookies, f"https://www.bilibili.com/video/{bvid}", payload)


def delete_comment(bvid: str, rpid: str, cookies: dict[str, str]) -> dict:
    """删除本账号在视频下的评论（用于低质量歌单升级为高质量歌单时替换）。"""
    aid = get_aid(bvid, cookies)
    bili_jct = cookies.get("bili_jct", "")
    if not bili_jct:
        raise RuntimeError("cookie 缺少 bili_jct，无法删除")
    payload = {
        "type": 1,
        "oid": aid,
        "rpid": rpid,
        "csrf": bili_jct,
    }
    return _request_json(REPLY_DEL_API, cookies, f"https://www.bilibili.com/video/{bvid}", payload)


# B站评论长度上限（字符）。官方限制约 1000，保守取 900 留缓冲；
# 参考已发布成功的最长评论 889 字符。超过则自动切分为主评论 + 楼中楼续写。
COMMENT_LENGTH_LIMIT = 900


def split_message_by_lines(message: str, limit: int = COMMENT_LENGTH_LIMIT) -> list[str]:
    """把完整歌单按行切分为不超过 limit 字符的若干段。

    以行（歌曲条目）为单位切割，保持每行完整，不出现半行。
    """
    lines = [line for line in message.splitlines() if line.strip()]
    if not lines:
        return []
    segments: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line)
        if current_len + line_len + 1 > limit and current:
            segments.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len + 1
    if current:
        segments.append("\n".join(current))
    return segments


def post_comment_with_replies(bvid: str, message: str, cookies: dict[str, str]) -> list[dict]:
    """发布评论；若超长则第一条发主评论，后续段以楼中楼（回复）形式续写。

    返回每段的接口响应 dict 列表。
    注意：B 站对主评论发布后立即回复有限制（12006 没有该评论），
    楼中楼段发布前需延时并重试。
    """
    import time as _time

    segments = split_message_by_lines(message)
    if not segments:
        raise RuntimeError("评论内容为空")
    results: list[dict] = []
    root_rpid = ""
    for idx, segment in enumerate(segments):
        if idx == 0:
            resp = post_comment(bvid, segment, cookies)
        else:
            # 楼中楼回复：root/parent 指向主评论 rpid；发布前等待主评论生效
            aid = get_aid(bvid, cookies)
            bili_jct = cookies.get("bili_jct", "")
            payload = {
                "type": 1,
                "oid": aid,
                "message": segment,
                "root": root_rpid,
                "parent": root_rpid,
                "plat": 1,
                "csrf": bili_jct,
            }
            resp = None
            last_err = ""
            for attempt in range(3):
                _time.sleep(2 * (attempt + 1))  # 主评论刚发出，等待其生效
                resp = _request_json(REPLY_ADD_API, cookies, f"https://www.bilibili.com/video/{bvid}", payload)
                if resp.get("code") == 0:
                    break
                last_err = f"code={resp.get('code')} msg={resp.get('message')}"
                if resp.get("code") in {12006, -101, -403}:  # 可重试错误
                    continue
                break
            if resp is None:
                resp = {"code": -1, "message": f"楼中楼发布失败: {last_err}"}
        results.append(resp)
        if resp.get("code") != 0:
            break
        if idx == 0:
            root_rpid = str((resp.get("data") or {}).get("rpid", ""))
    return results
