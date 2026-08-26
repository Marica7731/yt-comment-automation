"""飞书消息发送（自包含，走开放平台 tenant_access_token + im message）。

环境变量：
- FEISHU_APP_ID / FEISHU_APP_SECRET：自建应用凭据
- MY_FEISHU_OPEN_ID（或 FEISHU_OPEN_ID）：接收人 open_id
"""
from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import config

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
UA = "yt-comment-automation/0.1"

# 通知时间统一用北京时间（UTC+8）；B 站简介/YouTube 用日本时间（UTC+9）
BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _post_json(url: str, payload: dict, headers: Optional[dict] = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA, **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_tenant_access_token(app_id: str, app_secret: str) -> str:
    resp = _post_json(TOKEN_URL, {"app_id": app_id, "app_secret": app_secret})
    if resp.get("code") != 0:
        raise RuntimeError(f"飞书 token 获取失败: {resp.get('msg')}")
    return resp["tenant_access_token"]


def send_feishu_message(text: str, dry_run: bool = False) -> tuple[bool, str]:
    """发送文本消息到配置的 open_id。返回 (成功, 说明)。"""
    app_id = config.feishu_app_id()
    app_secret = config.feishu_app_secret()
    open_id = config.feishu_open_id()
    if not (app_id and app_secret and open_id):
        return False, "缺少 FEISHU_APP_ID/FEISHU_APP_SECRET/MY_FEISHU_OPEN_ID"
    if dry_run:
        return True, "[dry-run] 飞书消息:\n" + text
    try:
        token = _get_tenant_access_token(app_id, app_secret)
    except Exception as err:  # noqa: BLE001
        return False, f"飞书 token 失败: {err}"
    resp = _post_json(
        MESSAGE_URL,
        {"receive_id": open_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.get("code") != 0:
        return False, f"飞书发送失败: code={resp.get('code')} msg={resp.get('msg')}"
    return True, f"飞书已发送 message_id={resp.get('data', {}).get('message_id', '')}"


def build_success_brief(bvid: str, yt_link: str, posted_at: str = "", song_count: int = 0, profile: str = "") -> str:
    """发送成功通知：B站链接、油管链接、评论时间、歌曲数量，中间都用回车。时间用北京时间。"""
    bili_link = f"https://www.bilibili.com/video/{bvid}"
    lines = [
        "✅评论发送成功",
        bili_link,
        yt_link,
        posted_at or beijing_now(),
        f"歌曲数量：{song_count}",
    ]
    if profile:
        lines.append(profile)
    return "\n".join(lines)


def _error_title(reason: str) -> str:
    """按错误原因生成通知标题（区分抓取失败/发布失败等，不误导）。"""
    if "YouTube 抓取失败" in reason or "YouTube" in reason and ("抓取" in reason or "解析" in reason):
        return "⚠️YouTube 抓取失败"
    if "评论发布" in reason or "发布失败" in reason or "发布无响应" in reason or "删除旧评论" in reason:
        return "❌评论发布/处理失败"
    if "cookie" in reason.lower():
        return "⚠️Cookie 配置异常"
    return "❌处理失败"


def build_failure_brief(
    bvid: str,
    reason: str,
    title: str = "",
    collection: str = "",
    yt_link: str = "",
) -> str:
    """失败通知：按错误类型给标题，附视频标题、合集、B站/油管链接、原因、时间。"""
    bili_link = f"https://www.bilibili.com/video/{bvid}"
    lines = [_error_title(reason), bili_link]
    if title:
        lines.append(title)
    if collection:
        lines.append(f"合集：{collection}")
    if yt_link:
        lines.append(yt_link)
    lines.append(f"原因：{reason}")
    lines.append(f"时间：{beijing_now()}")
    return "\n".join(lines)


def build_yt_rate_limit_brief(bvid: str, reason: str) -> str:
    """YouTube 页面抓取限流（429）通知：提醒及时关注抓取频率/IP 风控。"""
    bili_link = f"https://www.bilibili.com/video/{bvid}"
    return "\n".join(
        [
            "⚠️YouTube 限流(429)",
            bili_link,
            f"原因：{reason}",
            f"时间：{beijing_now()}",
        ]
    )


def extract_desc_profile(desc: str) -> str:
    """从 B 站简介提取「主播 + 原标题」两行，供成功通知展示。

    跳过首行 YouTube 链接、寒暄行（关注/谢谢/喵 等），只保留：
    - 主播行：`主播：xxx` 或 `主播/稿件上传者：xxx`
    - 原标题行：`原标题：xxx`
    找不到对应行则省略；全部找不到返回空串。
    """
    lines = [ln.strip() for ln in (desc or "").splitlines() if ln.strip()]
    parts: list[str] = []
    for ln in lines:
        if ln.startswith("http://") or ln.startswith("https://"):
            continue
        if "谢谢" in ln or "关注" in ln or "感谢" in ln or "喵" in ln:
            continue
        if ln.startswith("主播") or ln.startswith("主播/稿件上传者"):
            parts.append(ln)
        elif ln.startswith("原标题") or ln.startswith("原標題"):
            parts.append(ln)
    return "\n".join(parts)
