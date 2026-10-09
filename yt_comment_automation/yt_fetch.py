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
import urllib.parse
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

# 用户确认该频道发布的歌单不可信；channel ID 稳定，不受改名影响。
BLOCKED_COMMENT_AUTHOR_CHANNEL_IDS = frozenset({"UC5efbPKzrDaVfMaH5ghB8Bg"})


def _is_blocked_comment_author(author_id: str) -> bool:
    return str(author_id or "").strip() in BLOCKED_COMMENT_AUTHOR_CHANNEL_IDS


class YtFetchError(RuntimeError):
    pass


class YtCacheMissError(YtFetchError):
    """cache_only 模式下没有 Action 回传缓存；调用方应跳过而不是直连 YouTube。"""


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


# 全局请求节流：任意两次对 YouTube 的请求之间至少隔这个秒数。
# 风控看的是请求突发速率——之前视频内 7 个请求、视频之间零间隔连发，
# 100 秒 50-70 发必触发 429。
REQUEST_MIN_GAP_SECONDS = 2.0
_last_request_at = [0.0]


def _throttle():
    # 跨进程共用时钟：与 like_fans（B站点赞）等并发时共用同一个最小间隔，
    # 出口 IP 的对外请求总速率受控（风控看的是叠加速率，不是单进程速率）
    from .req_pace import pace
    from . import config

    try:
        configured_gap = float(config.get("YOUTUBE_REQUEST_MIN_GAP_SECONDS", str(REQUEST_MIN_GAP_SECONDS)))
    except ValueError:
        configured_gap = REQUEST_MIN_GAP_SECONDS
    pace(max(configured_gap, 0.5))


def _urlopen_with_retry(req: urllib.request.Request, retries: int = 5):
    """请求前全局节流；429/5xx 最多重试 retries 次，任一次成功直接放行。

    退避：有 Retry-After 按它（上限 60 秒），否则指数 2/4/8/16/30 秒。
    重试次数用尽仍失败 → 抛出最后一个异常（该视频本轮报错，不连坐其他视频）。
    """
    backoff = [2.0, 4.0, 8.0, 16.0, 30.0]
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        _throttle()
        try:
            return urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                raise
            last_exc = exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = None
            if retry_after:
                try:
                    delay = min(max(float(retry_after), 0.0), 60.0)
                except ValueError:
                    delay = None
            if delay is None:
                delay = backoff[min(attempt, len(backoff) - 1)]
            time.sleep(delay)
        except urllib.error.URLError as exc:  # noqa: PERF203
            # 网络抖动也纳入重试预算
            if attempt >= retries:
                raise
            last_exc = exc
            time.sleep(backoff[min(attempt, len(backoff) - 1)])
    raise last_exc if last_exc else YtFetchError("unreachable urlopen retry state")


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
    """提取 `marker` 后的 JSON 对象（如 `ytInitialData = {...}`、`ytInitialData:{...}`）。

    用正则精确定位 marker 后 [等号或冒号] 紧跟左花括号，
    避免页面里 `marker` 出现多次时 `find("{", idx)` 误命中 JS 里的其他对象
    （如 `window['ytPageType']=...;window['ytCommand']={...}`）。
    第一个候选解析失败时继续找下一个出现点，直到成功或耗尽。
    """
    import re

    pattern = re.compile(re.escape(marker) + r"\s*[=:]\s*({)")
    for m in pattern.finditer(text):
        start = m.start(1)
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
                    except json.JSONDecodeError:
                        # 该出现点解析失败（可能被截断），尝试下一个 marker 出现点
                        break
    # 没有成功解析：给出尽量可诊断的错误
    with_brace = re.search(re.escape(marker) + r"\s*[=:]", text)
    if with_brace:
        start = with_brace.end()
        snippet = text[start : start + 200].replace("\n", " ").strip()
        raise YtFetchError(
            f"未能解析 {marker} 后 JSON（找到 {marker} 赋值但内容异常）: "
            f"赋值后片段开头: {snippet!r}"
        )
    raise YtFetchError(f"{marker} not found")


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


def _find_newest_comments_continuation(data: Any) -> str:
    """返回评论区「新しい順（最新）」排序的 continuation token。

    YouTube 评论默认初始 token 是「人気順（热门）」，置顶歌单评论在热门排序下
    经常不被纳入前面的样本，导致抓不到歌单。改用「新しい順」能稳定抓到置顶歌单。
    找不到「新しい順」选项时返回空串，由上层回退到默认（热门）排序。
    """
    for item in _walk_dicts(data):
        sfr = item.get("sortFilterSubMenuRenderer")
        if not isinstance(sfr, dict):
            continue
        for sub in sfr.get("subMenuItems", []) or []:
            title = sub.get("title")
            if isinstance(title, dict):
                title = title.get("simpleText") or title.get("runs")
            if title != "新しい順" and title != "最新":
                continue
            token = (
                sub.get("serviceEndpoint", {})
                .get("continuationCommand", {})
                .get("token")
            )
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
    return [e["text"] for e in _extract_comment_entries(data)]


def _extract_comment_entries(data: dict[str, Any]) -> list[dict[str, str]]:
    """提取评论条目 [{id, text}]。id 优先 commentId，缺失回退文本哈希（保证跨抓取可对账）。"""
    import hashlib

    entries: list[dict[str, str]] = []
    for item in _walk_dicts(data):
        payload = item.get("commentEntityPayload")
        if not isinstance(payload, dict):
            continue
        content = payload.get("properties", {}).get("content", {}).get("content")
        if not isinstance(content, str) or not content:
            continue
        author = payload.get("author") or {}
        if _is_blocked_comment_author(author.get("channelId")):
            continue
        cid = payload.get("properties", {}).get("commentId") or payload.get("key") or ""
        if not cid:
            cid = "sha1:" + hashlib.sha1(content.encode("utf-8")).hexdigest()
        entries.append({"id": cid, "text": content})
    return entries


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


def _extract_comment_page_continuation_tokens(data: Any) -> list[str]:
    """评论区「下一页」的 continuation token（区别于楼中楼翻页）。

    楼中楼的 token 嵌在 commentRepliesRenderer 里；评论列表分页的 token 在
    评论 section 层的 continuationItemRenderer。这里只取后者，避免混淆。
    """
    tokens: list[str] = []
    for item in _walk_dicts(data):
        renderer = item.get("continuationItemRenderer")
        if not isinstance(renderer, dict):
            continue
        endpoint = renderer.get("continuationEndpoint") or {}
        token = (endpoint.get("continuationCommand") or {}).get("token")
        if not token:
            continue
        text = json.dumps(item, ensure_ascii=False)
        # 评论列表分页 token 不含 commentRepliesRenderer（那是楼中楼）
        if "commentRepliesRenderer" in text:
            continue
        tokens.append(token)
    return tokens


def _load_known_comment_ids(cache_dir: Path | None, video_id: str) -> set[str]:
    """读评论 id 账本（fetch_times 同款思路：与主缓存解耦，无歌单抓取也有对账依据）。"""
    if not cache_dir:
        return set()
    try:
        data = json.loads((Path(cache_dir) / "yt_comment_ids.json").read_text(encoding="utf-8"))
        return set(data.get(video_id) or [])
    except (OSError, ValueError):
        return set()


def _save_comment_ids(cache_dir: Path | None, video_id: str, ids_in_order: list[str]) -> None:
    """账本按 encounter 顺序（最新在前）合并去重，每视频保留最近 500 条。"""
    if not cache_dir:
        return
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = Path(cache_dir) / "yt_comment_ids.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        merged = list(dict.fromkeys(ids_in_order + list(data.get(video_id) or [])))[:500]
        data[video_id] = merged
        if len(data) > 1000:  # 防账本无限增长：最多留 1000 个视频
            data = dict(sorted(data.items(), key=lambda kv: len(kv[1]), reverse=True)[:1000])
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _fetch_comment_pages(
    api_key: str,
    client_version: str,
    first_response: dict[str, Any],
    max_pages: int = 5,
    known_ids: set[str] | None = None,
    seen_ids: list[str] | None = None,
    early_stop: bool = False,
) -> tuple[list[str], list[dict[str, Any]]]:
    """翻评论区「下一页」（自适应）。

    第一页评论已由调用方从 first_response 提取；从每页响应里找下一页
    continuation token 继续抓。**某页贡献 0 条新评论（id 全部见过）即停**——
    最新排序下整页都是旧评论说明已追平，后续页不可能有新歌单；
    有新评论期间继续翻（歌单可能被闲聊顶到后面页）。上限仍 max_pages。
    """
    known = known_ids or set()
    comments: list[str] = []
    responses: list[dict[str, Any]] = []
    seen: set[str] = set()
    pending = _extract_comment_page_continuation_tokens(first_response)
    while pending and len(responses) < max_pages:
        token = pending.pop(0)
        if token in seen:
            continue
        seen.add(token)
        response = _fetch_youtube_continuation(api_key, client_version, token)
        responses.append(response)
        entries = _extract_comment_entries(response)
        new_count = 0
        for e in entries:
            comments.append(e["text"])
            if seen_ids is not None:
                seen_ids.append(e["id"])
            if e["id"] not in known:
                new_count += 1
        if new_count == 0 and early_stop:
            # 提前停仅用于已发布视频的升级复查（新内容必在第1页）；
            # 未发布视频必须抓满——歌单被闲聊顶到后面页时，第1页全旧
            # 但歌单在第2页，提前停会让它永远抓不回来
            break
        for next_token in _extract_comment_page_continuation_tokens(response):
            if next_token not in seen:
                pending.append(next_token)
    return comments, responses


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
    bodies: list[str] = []
    for item in _walk_dicts(data):
        # 视频简介主体（YT 新版结构：attributedDescription.content）
        for key in ("attributedDescription", "attributedDescriptionBodyText"):
            body = item.get(key)
            if isinstance(body, dict):
                content = body.get("content")
                if isinstance(content, str):
                    # 简介正文必须原样返回；没有时间戳也属于有效 raw，
                    # 否则管线会把“无歌单”误判为 raw_fetch_invalid。
                    bodies.append(content)
    # 找到完整正文时禁止再拼页面碎片：推荐视频标题也可能含时间戳，
    # 会跨视频污染简介并伪造 SETLIST 候选。
    if bodies:
        return list(dict.fromkeys(bodies))

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
    # 仅在页面没有完整正文时使用结构相近的时间戳碎片兜底
    return list(dict.fromkeys(texts))


def _fetch_youtube_innertube_raw(
    video_id: str,
    cache_dir: str | Path | None = None,
    force: bool = False,
    max_age_seconds: int | None = None,
    early_stop: bool = False,
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

    # 优先用「新しい順（最新）」抓评论，置顶歌单在热门排序下常被算法排除、抓不到；
    # 找不到最新排序 token 时回退默认（热门）排序。
    continuation = _find_newest_comments_continuation(initial_data) or _find_comments_continuation(initial_data)
    comments: list[str] = []
    comments_response: dict[str, Any] | None = None
    reply_responses: list[dict[str, Any]] = []
    # 自适应翻页：id 账本记录见过的评论，某页全旧即停（追平后每轮只花 1 个请求）
    known_ids = _load_known_comment_ids(cache_dir, video_id)
    fetched_ids: list[str] = []
    if continuation:
        comments_response = _fetch_youtube_continuation(api_key, client_version, continuation)
        first_entries = _extract_comment_entries(comments_response)
        for e in first_entries:
            comments.append(e["text"])
            fetched_ids.append(e["id"])
        first_new = sum(1 for e in first_entries if e["id"] not in known_ids)
        if first_new > 0:
            # 评论列表分页：第一页有新评论才继续翻「下一页」
            more_comments, _page_responses = _fetch_comment_pages(
                api_key, client_version, comments_response, known_ids=known_ids,
                seen_ids=fetched_ids, early_stop=early_stop,
            )
            comments.extend(more_comments)
        # 楼中楼回复（每页的回复折叠区）
        reply_texts, reply_responses = _fetch_comment_reply_texts_with_responses(
            api_key,
            client_version,
            comments_response,
        )
        comments.extend(reply_texts)
    _save_comment_ids(cache_dir, video_id, fetched_ids)

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

    # 抓取时间账本：无歌单的抓取不落主缓存（见下），但"同一视频重抓间隔"
    # 需要知道上次真实抓取时刻——与缓存文件是否存在解耦。
    if cache_dir:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            ledger = cache_dir / "fetch_times.json"
            try:
                times = json.loads(ledger.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                times = {}
            times[video_id] = time.time()
            if len(times) > 500:  # 防无限增长：只留最近 500 个
                times = dict(sorted(times.items(), key=lambda kv: kv[1], reverse=True)[:500])
            ledger.write_text(json.dumps(times), encoding="utf-8")
        except OSError:
            pass

    # 抓取结果无歌单时不落缓存：存了也会被判"有歌单"而长期不重抓（死循环根源）；
    # 调用方每轮会重新抓最新评论区，直到出现歌单为止。
    if not any(c.get("text") for c in raw_info["comments"]):
        return raw_info

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{video_id}.info.json"
        # 短期留存：覆盖前把旧缓存轮转到 history（回看"cron 当时抓到了什么"用于排查）
        if cache_path.is_file():
            hist_dir = cache_dir / "history" / video_id
            hist_dir.mkdir(parents=True, exist_ok=True)
            olds = sorted(hist_dir.glob("*.info.json"))
            while len(olds) >= 3:
                olds.pop(0).unlink()
            cache_path.rename(hist_dir / f"{time.strftime('%Y%m%d_%H%M%S')}.info.json")
        cache_path.write_text(json.dumps(raw_info, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_info


def _youtube_api_get(resource: str, params: dict[str, Any]) -> dict[str, Any]:
    """调用 YouTube Data API v3；key 只从当前进程环境/private.env 读取。"""
    from . import config

    api_key = config.get("YOUTUBE_API_KEY")
    if not api_key:
        raise YtFetchError("official 主路径缺少 YOUTUBE_API_KEY，拒绝隐式降级")
    query = urllib.parse.urlencode({**params, "key": api_key})
    url = f"https://www.googleapis.com/youtube/v3/{resource}?{query}"
    request = urllib.request.Request(url, headers=_headers())
    try:
        with _urlopen_with_retry(request) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace"))
            detail = str((body.get("error") or {}).get("message") or "")
        except (ValueError, AttributeError):
            detail = ""
        raise YtFetchError(
            f"YouTube Data API {resource} HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise YtFetchError(
            f"YouTube Data API {resource} 网络错误: {exc.reason}"
        ) from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise YtFetchError(f"YouTube Data API {resource} 返回非 JSON 响应") from exc
    if isinstance(data, dict) and data.get("error"):
        error = data["error"] if isinstance(data["error"], dict) else {}
        raise YtFetchError(
            f"YouTube Data API {resource} 错误: {error.get('message') or data['error']}"
        )
    if not isinstance(data, dict):
        raise YtFetchError(f"YouTube Data API {resource} 返回结构异常")
    return data


def _official_comment_entries(items: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if not isinstance(items, list):
        return entries
    for thread in items:
        if not isinstance(thread, dict):
            continue
        top = ((thread.get("snippet") or {}).get("topLevelComment")) or {}
        replies = ((thread.get("replies") or {}).get("comments")) or []
        comments = [top, *replies] if isinstance(replies, list) else [top]
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            snippet = comment.get("snippet") or {}
            author = snippet.get("authorChannelId") or {}
            if _is_blocked_comment_author(author.get("value")):
                continue
            text = snippet.get("textOriginal") or snippet.get("textDisplay") or ""
            cid = str(comment.get("id") or "")
            if text and cid:
                entries.append({"id": cid, "text": str(text)})
    return entries


def _fetch_youtube_official_raw(
    video_id: str,
    cache_dir: Path | None,
    force: bool,
    max_age_seconds: int | None,
    early_stop: bool,
) -> dict[str, Any]:
    """已验证的官方 API 主路径；可显式启用，也可在 Innertube 429 后恢复。"""
    if cache_dir and not force:
        cache_path = cache_dir / f"{video_id}.info.json"
        if cache_path.is_file():
            if max_age_seconds is None:
                return json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - cache_path.stat().st_mtime < max_age_seconds:
                return json.loads(cache_path.read_text(encoding="utf-8"))

    video_response = _youtube_api_get("videos", {"part": "snippet", "id": video_id})
    video_items = video_response.get("items") or []
    description = ""
    if video_items:
        description = str((video_items[0].get("snippet") or {}).get("description") or "")

    known_ids = _load_known_comment_ids(cache_dir, video_id)
    fetched_ids: list[str] = []
    comments: list[str] = []
    responses: list[dict[str, Any]] = []
    page_token = ""
    while len(responses) < 5:
        params: dict[str, Any] = {
            "part": "snippet,replies",
            "videoId": video_id,
            "order": "time",
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token
        response = _youtube_api_get("commentThreads", params)
        responses.append(response)
        page_entries = _official_comment_entries(response.get("items"))
        page_new = 0
        for entry in page_entries:
            comments.append(entry["text"])
            fetched_ids.append(entry["id"])
            if entry["id"] not in known_ids:
                page_new += 1
        next_token = str(response.get("nextPageToken") or "")
        if not next_token or (early_stop and page_new == 0):
            break
        page_token = next_token

    _save_comment_ids(cache_dir, video_id, fetched_ids)
    raw_info = {
        "id": video_id,
        "webpage_url": WATCH_URL.format(video_id=video_id),
        "description": description,
        "comments": [{"text": text} for text in comments],
        "raw": {
            "videos_response": video_response,
            "comments_responses": responses,
        },
    }

    if cache_dir:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            ledger = cache_dir / "fetch_times.json"
            try:
                times = json.loads(ledger.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                times = {}
            times[video_id] = time.time()
            if len(times) > 500:
                times = dict(sorted(times.items(), key=lambda kv: kv[1], reverse=True)[:500])
            ledger.write_text(json.dumps(times), encoding="utf-8")
        except OSError:
            pass

    if not any(c.get("text") for c in raw_info["comments"]):
        return raw_info

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{video_id}.info.json"
        if cache_path.is_file():
            hist_dir = cache_dir / "history" / video_id
            hist_dir.mkdir(parents=True, exist_ok=True)
            olds = sorted(hist_dir.glob("*.info.json"))
            while len(olds) >= 3:
                olds.pop(0).unlink()
            cache_path.rename(hist_dir / f"{time.strftime('%Y%m%d_%H%M%S')}.info.json")
        cache_path.write_text(json.dumps(raw_info, ensure_ascii=False, indent=2), encoding="utf-8")
    return raw_info


def fetch_youtube_raw(
    video_id: str,
    cache_dir: str | Path | None = None,
    force: bool = False,
    max_age_seconds: int | None = None,
    early_stop: bool = False,
) -> dict[str, Any]:
    """抓取视频评论区和简介；支持 Action 缓存、Innertube 和已验证官方 API。"""
    resolved_cache_dir = Path(cache_dir) if cache_dir else None
    from . import config

    fetch_mode = config.get("YOUTUBE_FETCH_MODE", "auto").lower()
    if fetch_mode == "cache_only":
        if not resolved_cache_dir:
            raise YtCacheMissError("cache_only 模式必须提供 cache_dir")
        cache_path = resolved_cache_dir / f"{video_id}.info.json"
        if not cache_path.is_file():
            raise YtCacheMissError(
                f"GitHub Action 缓存缺失: {video_id}.info.json"
            )
        return json.loads(cache_path.read_text(encoding="utf-8"))
    if fetch_mode not in {"auto", ""}:
        raise YtFetchError(f"不支持的 YOUTUBE_FETCH_MODE: {fetch_mode}")

    backend = config.get("YOUTUBE_FETCH_BACKEND", "auto").lower()
    if backend == "official":
        return _fetch_youtube_official_raw(
            video_id, resolved_cache_dir, force, max_age_seconds, early_stop
        )
    if backend not in {"auto", ""}:
        raise YtFetchError(f"不支持的 YOUTUBE_FETCH_BACKEND: {backend}")
    try:
        return _fetch_youtube_innertube_raw(
            video_id, resolved_cache_dir, force, max_age_seconds, early_stop
        )
    except Exception as err:
        rate_limited = is_rate_limited_error(err)
        page_structure_error = "ytInitialData not found" in str(err)
        if not (rate_limited or page_structure_error):
            raise
        if not config.get("YOUTUBE_API_KEY"):
            raise
        reason = "YouTube 429" if rate_limited else "Innertube 页面结构异常"
        try:
            return _fetch_youtube_official_raw(
                video_id, resolved_cache_dir, force, max_age_seconds, early_stop
            )
        except Exception as fallback_err:
            raise YtFetchError(
                f"{reason}; 已验证 official 恢复路径失败: "
                f"{type(fallback_err).__name__}: {fallback_err}"
            ) from err


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
