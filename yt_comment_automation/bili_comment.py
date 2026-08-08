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
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


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


def find_own_timestamp_comment(bvid: str, cookies: dict[str, str]) -> BiliComment | None:
    """检查本账号（owner）是否已在视频下发布过时间戳歌轴评论。

    判定：评论来自 owner mid，且内容包含「数字:数字」时间戳 + 「数字. 歌名 - 歌手」结构。
    """
    owner_mid = config.owner_mid()
    for comment in list_comments(bvid, cookies):
        if comment.mid != owner_mid:
            continue
        if looks_like_timestamp_songlist(comment.message):
            return comment
    return None


def looks_like_timestamp_songlist(message: str) -> bool:
    import re

    if not message or len(message) < 30:
        return False
    ts_count = len(re.findall(r"\d{1,2}:\d{2}(?::\d{2})?\s*\d{2}\.\s", message))
    return ts_count >= 3


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
