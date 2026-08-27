"""YouTube 评论区/简介原始文本抓取（无 cookie，纯 urllib）。

实现思路复刻自 song_serch_lyrics/app/songfind/comment_precheck.py 的抓取层
（该实现已在 8 个真实视频上实测稳定），代码自包含，不依赖外部仓库：
1. GET watch 页取 INNERTUBE_API_KEY / CLIENT_VERSION / ytInitialData
2. 从 ytInitialData 找评论 continuation token
3. POST youtubei/v1/next 翻页拉评论 + 楼中楼回复
4. 从 commentEntityPayload 提取评论文本；从 simpleText/runs 提取含时间戳的简介
5. 原始 JSON 落盘缓存，二次运行直接读缓存
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
WATCH_URL = "https://www.youtube.com/watch?v={video_id}&hl=ja&persist_hl=1"
YOUTUBEI_NEXT = "https://www.youtube.com/youtubei/v1/next?prettyPrint=false&key={api_key}"
TIMESTAMP_RE = re.compile(r"(^|[^\d])(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)")


class YtFetchError(RuntimeError):
    pass


def is_rate_limited_error(err: Exception) -> bool:
    """判断异常是否为 YouTube 限流（429）。urllib 对 429 抛 HTTPError，重试耗尽后原样上抛。"""
    import urllib.error

    if isinstance(err, urllib.error.HTTPError) and err.code == 429:
        return True
    lowered = str(err).lower()
    return "429" in lowered or "rate limit" in lowered or "too many request" in lowered


def _headers() -> dict[str, str]:
    return {
        "User-Agent": UA,
        "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    }


def _urlopen_with_retry(req: urllib.request.Request, retries: int = 2):
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            if attempt >= retries or exc.code not in {429, 500, 502, 503, 504}:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after:
                try:
                    time.sleep(min(max(float(retry_after), 0.0), 30.0))
                    continue
                except ValueError:
                    pass
            time.sleep(min(2.0 * (attempt + 1), 10.0))
    raise YtFetchError("unreachable urlopen retry state")


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers=_headers())
    with _urlopen_with_retry(req) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _http_post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {**_headers(), "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with _urlopen_with_retry(req) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        # YouTube 反爬/验证码时 youtubei 会返回 HTML 而非 JSON，带上响应头便于诊断
        snippet = text[:200].replace("\n", " ").strip()
        raise YtFetchError(
            f"youtubei 响应不是 JSON（可能是验证码/反爬 HTML）: {err}; 响应开头: {snippet!r}"
        ) from err


def _extract_re(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def _extract_json_after(text: str, marker: str) -> Any:
    idx = text.find(marker)
    if idx < 0:
        raise YtFetchError(f"{marker} not found")
    start = text.find("{", idx)
    if start < 0:
        raise YtFetchError(f"{marker} object start not found")
    depth = 0
    in_string = False
    escape = False
    for pos in range(start, len(text)):
        ch = text[pos]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                segment = text[start : pos + 1]
                try:
                    return json.loads(segment)
                except json.JSONDecodeError as err:
                    raise YtFetchError(
                        f"{marker} 内嵌 JSON 解析失败（可能页面被反爬/截断）: {err}; "
                        f"片段开头: {segment[:200].replace(chr(10), ' ')!r}"
                    ) from err
    raise YtFetchError(f"{marker} object end not found")


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _looks_like_comments_continuation(item: dict[str, Any]) -> bool:
    text = json.dumps(item, ensure_ascii=False)
    return "comment" in text.lower() or "コメント" in text


def _find_comments_continuation(data: Any) -> str:
    for item in _walk_dicts(data):
        endpoint = item.get("continuationEndpoint")
        if not isinstance(endpoint, dict):
            continue
        token = endpoint.get("continuationCommand", {}).get("token")
        if token and _looks_like_comments_continuation(item):
            return token
    for item in _walk_dicts(data):
        token = item.get("continuationCommand", {}).get("token")
        if token:
            return token
    return ""


def _fetch_youtube_continuation(api_key: str, client_version: str, continuation: str) -> dict[str, Any]:
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": client_version,
                "hl": "ja",
                "gl": "JP",
            }
        },
        "continuation": continuation,
    }
    return _http_post_json(YOUTUBEI_NEXT.format(api_key=api_key), payload)


def _extract_comment_texts(data: dict[str, Any]) -> list[str]:
    comments: list[str] = []
    for item in _walk_dicts(data):
        payload = item.get("commentEntityPayload")
        if not isinstance(payload, dict):
            continue
        content = payload.get("properties", {}).get("content", {}).get("content")
        if isinstance(content, str):
            comments.append(content)
    return comments


def _extract_comment_reply_continuation_tokens(data: Any) -> list[str]:
    tokens: list[str] = []
    for item in _walk_dicts(data):
        replies = item.get("commentRepliesRenderer")
        if not isinstance(replies, dict):
            continue
        contents = replies.get("contents")
        if not isinstance(contents, list):
            continue
        for content in contents:
            if not isinstance(content, dict):
                continue
            renderer = content.get("continuationItemRenderer")
            if not isinstance(renderer, dict):
                continue
            token = renderer.get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
            if token:
                tokens.append(token)
    return tokens


def _fetch_comment_reply_texts_with_responses(
    api_key: str,
    client_version: str,
    comments_response: dict[str, Any],
    max_continuations: int = 20,
) -> tuple[list[str], list[dict[str, Any]]]:
    comments: list[str] = []
    responses: list[dict[str, Any]] = []
    seen: set[str] = set()
    pending = _extract_comment_reply_continuation_tokens(comments_response)
    while pending and len(seen) < max_continuations:
        token = pending.pop(0)
        if token in seen:
            continue
        seen.add(token)
        response = _fetch_youtube_continuation(api_key, client_version, token)
        responses.append(response)
        comments.extend(_extract_comment_texts(response))
        for next_token in _extract_comment_reply_continuation_tokens(response):
            if next_token not in seen:
                pending.append(next_token)
    return comments, responses


def _is_timestamp_candidate_text(text: str) -> bool:
    value = (text or "").replace("\u00a0", " ").replace("\u200b", "")
    if not TIMESTAMP_RE.search(value):
        return False
    remainder = TIMESTAMP_RE.sub("", value)
    remainder = re.sub(
        r"[\s\u3000\[\]【】()（）<>＜＞:：;；,，.。~～\-—–−_/／|｜￤∣丨♪♫♬♩▶▷►▸▹・･●○◆◇■□]+",
        "",
        remainder,
    )
    return bool(re.search(r"[A-Za-zぁ-んァ-ヶ一-龯々]", remainder))


def _extract_description_candidates(data: Any) -> list[str]:
    texts: list[str] = []
    for item in _walk_dicts(data):
        simple_text = item.get("simpleText")
        if isinstance(simple_text, str) and _is_timestamp_candidate_text(simple_text):
            texts.append(simple_text)
        runs = item.get("runs")
        if isinstance(runs, list):
            joined = "".join(run.get("text", "") for run in runs if isinstance(run, dict))
            if _is_timestamp_candidate_text(joined):
                texts.append(joined)
    return list(dict.fromkeys(texts))


def fetch_youtube_raw(
    video_id: str,
    cache_dir: str | Path | None = None,
    force: bool = False,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """抓取视频评论区 + 简介原始 JSON，返回 dict。

    - video_id: YouTube 视频 ID（11 位）
    - cache_dir: 若提供，原始 JSON 落盘 <cache_dir>/<video_id>.info.json；再次调用直接读缓存
    - force: 忽略缓存强制重新抓取
    - max_age_seconds: 缓存文件年龄超过该秒数则强制重新抓取（默认 None=不检查年龄）
    """
    cache_dir = Path(cache_dir) if cache_dir else None
    if cache_dir and not force:
        cache_path = cache_dir / f"{video_id}.info.json"
        if cache_path.is_file():
            if max_age_seconds is None:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            age = time.time() - cache_path.stat().st_mtime
            if age < max_age_seconds:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            # 缓存过期，继续向下重新抓取

    url = WATCH_URL.format(video_id=video_id)
    html = _http_get(url)
    api_key = _extract_re(html, r'"INNERTUBE_API_KEY":"([^"]+)"')
    if not api_key:
        raise YtFetchError(f"未能从 watch 页解析 INNERTUBE_API_KEY: {video_id}")
    client_version = _extract_re(html, r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"') or "2.20260601.00.00"
    initial_data = _extract_json_after(html, "ytInitialData")

    continuation = _find_comments_continuation(initial_data)
    comments: list[str] = []
    comments_response: dict[str, Any] | None = None
    reply_responses: list[dict[str, Any]] = []
    if continuation:
        comments_response = _fetch_youtube_continuation(api_key, client_version, continuation)
        comments.extend(_extract_comment_texts(comments_response))
        reply_texts, reply_responses = _fetch_comment_reply_texts_with_responses(
            api_key,
            client_version,
            comments_response,
        )
        comments.extend(reply_texts)

    descriptions = _extract_description_candidates(initial_data)
    raw_info = {
        "id": video_id,
        "webpage_url": url,
        "description": "\n\n".join(descriptions),
        "comments": [{"text": text} for text in comments],
        "raw": {
            "initial_data": initial_data,
            "comments_response": comments_response,
            "reply_responses": reply_responses,
        },
    }

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{video_id}.info.json").write_text(
            json.dumps(raw_info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return raw_info


def extract_description_first_line_youtube_url(description: str) -> str:
    """从简介第一行提取 https://youtu.be/<id> 或 https://www.youtube.com/watch?v=<id>。"""
    if not description:
        return ""
    for line in description.splitlines():
        line = line.strip()
        m = re.match(r"^https?://(?:youtu\.be/|www\.youtube\.com/watch\?v=)([\w-]{11})", line)
        if m:
            return m.group(1)
    return ""
