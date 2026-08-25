"""管道编排：合集检测 → 评论抓取 → 本地规则清洗 → AI 兜底 → 发布 → 飞书通知。

运行策略：
1. 抓取合集全部视频（view API，无 cookie）
2. 对比上次快照，检测新增视频（增量模式）或全量扫描
3. 对每个候选视频：
   a. 检查本账号是否已发布时间戳歌轴评论 → 已发布跳过
   b. 从 B 站简介第一行取 YouTube 链接（与 part 字段互相校验）
   c. 抓取 YouTube 评论 + 简介原始 JSON
   d. 本地规则清洗出歌曲列表
   e. 若本地结果为空或过少 → DeepSeek 兜底整理
   f. 格式化评论内容 → 发布 → 飞书通知
4. 保存合集快照与处理记录（幂等，可重跑）
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import ai, bili_comment, clean, collections, config, notify, yt_fetch

logger = logging.getLogger("yt_comment_automation")

# 质量升级阈值：已发歌单首数 + 该阈值以上，YouTube 出现更全歌单时才升级（避免 1→2 首抖动刷屏）
UPGRADE_THRESHOLD = 3
# 已发视频的缓存复查 TTL（秒）：缓存超过该时间才 force 重抓检查是否有更全歌单，控制已发视频流量
UPGRADE_CHECK_TTL = 3600

# 本地规则结果可信的下限：低于此数量时触发 DeepSeek 兜底
MIN_CONFIDENT_SONGS = 5

# 本次运行已发过 YouTube 429 通知的 bvid（多个视频同时限流时只提醒一次，避免刷屏）
_yt_rate_limited_notified: set[str] = set()


@dataclass
class VideoResult:
    bvid: str
    yt_id: str
    title: str
    part_date: str
    collection: str
    status: str = ""  # already_posted / posted / skipped_no_songs / skipped_low_confidence / error / no_yt_link / dry_run
    song_count: int = 0
    source: str = ""  # local / ai
    message: str = ""
    error: str = ""
    detail: str = ""
    desc_profile: str = ""  # 简介提取的「主播 + 原标题」，随成功通知发送


@dataclass
class RunRecord:
    run_at: str
    total: int
    results: list[dict] = field(default_factory=list)


def load_processed(data_dir: Path) -> set[str]:
    """已处理（成功发布）的 bvid 集合。"""
    path = data_dir / "processed.json"
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return set(payload.get("posted", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_processed(data_dir: Path, posted: set[str]) -> None:
    path = data_dir / "processed.json"
    payload = {"updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "posted": sorted(posted)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_bili_video_info(bvid: str) -> tuple[str, str]:
    """一次 view API 调用返回 (简介首行 YouTube ID, 完整简介)。"""
    cookies = bili_comment.load_cookie_map()
    try:
        aid = bili_comment.get_aid(bvid, cookies)
    except Exception:  # noqa: BLE001
        return "", ""
    url = f"https://api.bilibili.com/x/web-interface/view?aid={aid}"
    data = bili_comment._request_json(url, cookies, "https://www.bilibili.com/")  # noqa: SLF001
    desc = ((data.get("data") or {}).get("desc")) or ""
    return yt_fetch.extract_description_first_line_youtube_url(desc), desc


def _fetch_youtube_id_for_bvid(bvid: str) -> str:
    """从 B 站简介第一行取 YouTube 链接 ID（兼容旧调用）。"""
    yt_id, _ = _fetch_bili_video_info(bvid)
    return yt_id


def _extract_yt_id_from_part(part: str) -> str:
    m = re.match(r"^\[(\d{4}-\d{2}-\d{2})\]\[([\w-]{11})\](.*)$", part or "")
    return m.group(2) if m else ""


# 非歌曲时间戳标记词（带时间戳但内容不是歌：开始/MC/章节/杂谈/告知/截图等）
_NON_SONG_TS_MARKERS = re.compile(
    r"(?:開始|开始|start|終了|end|opening|open|closing|close|mc|雑談|talk|感想|告知|お知らせ|"
    r"チャプター|chapter|セトリ|setlist|タイムスタンプ|timestamp|スクショ|挨拶|自己紹介|コメント|"
    r"おつ|お疲れ|ありがとう|宣伝|休憩|トイレ|お水|スパチャ読み|リクエスト募集|あくび|助かる|てぇてぇ)",
    re.IGNORECASE,
)

# 歌名/歌手分隔特征（时间戳行里出现这些才算"歌曲行"）
_SONG_LINE_SEPARATORS = re.compile(r"[\/／|｜￤∣丨＠@]|\s-\s|\s–\s|\s-\s")


def _is_songlist_comment(text: str) -> bool:
    """判定一条评论是否「结构化歌单」而非零散感想。

    核心区分（不是看条数，是看时间戳行密度 + 内容）：
    - 歌单：密集的时间戳行（如 Setlist 每行「时间戳 歌名/歌手」），
      或「歌名 + 时间戳」无分隔符格式（如「ライラック 11:10」）
    - 感想：零星 1 个时间戳夹在聊天里（如「1:30:53 つかさくんの『悪ノ召使』めっちゃ良い」）
    - 纯标记：全是開始/MC/雑談/あくび 等标记行，不算歌单

    判定：≥2 个「歌曲时间戳行」（时间戳行去掉时间戳后非空、且不含纯标记词）。
    不设密度阈值（避免把「半歌单半感想」的评论一刀砍掉）。
    """
    ts_re = re.compile(r"(?:^|[^\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)")
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if len(lines) < 2:
        return False
    song_ts_lines = 0
    for line in lines:
        if not ts_re.search(line):
            continue
        rest = ts_re.sub("", line).strip()
        if not rest:
            continue
        if _NON_SONG_TS_MARKERS.search(rest):
            continue
        song_ts_lines += 1
    return song_ts_lines >= 2


def _count_own_songlist_lines(message: str) -> int:
    """数本账号已发评论的歌单首数。

    我们发布的格式每行一首：`时间戳 NN. 歌名 - 歌手`（编号 NN. 紧跟时间戳）。
    统计带「时间戳 + 编号 + 点」的行数即为首数。
    """
    if not message:
        return 0
    ts_idx_re = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?\s+\d{2,3}\.")
    count = 0
    for line in message.splitlines():
        if ts_idx_re.search(line.strip()):
            count += 1
    return count


def raw_has_timestamp_songlist(raw: dict) -> bool:
    """抓取到的原始 JSON 里，评论区是否已有结构化歌单评论。

    用途：决定是否信任缓存。缓存里有歌单 → 直接用；没歌单 → 每次 cron 重新抓
    YouTube（直到评论区出现歌单为止）。
    """
    for c in raw.get("comments", []) or []:
        text = c.get("text", "") if isinstance(c, dict) else str(c)
        if _is_songlist_comment(text):
            return True
    return False


def process_video(video: collections.CollectionVideo, cache_dir: Path, dry_run: bool) -> VideoResult:
    result = VideoResult(
        bvid=video.bvid,
        yt_id=video.yt_id,
        title=video.title,
        part_date=video.part_date,
        collection=video.collection,
    )
    try:
        cookies = bili_comment.load_cookie_map()
    except Exception as err:  # noqa: BLE001
        result.status = "error"
        result.error = f"cookie 加载失败: {err}"
        return result

    # 0. 忽略列表：标题带歌但实际非歌枠的投稿，不写评论、不播报
    if video.bvid in config.ignore_bvids():
        result.status = "ignored"
        result.detail = "忽略列表（用户指定）"
        return result

    # 1. 本账号已有评论：不是"直接跳过"，而是区分两种情况
    #    - 已发"足量"歌单（≥阈值）→ 直接跳过
    #    - 已发"低质量"歌单（<阈值，可能是 1 首/错误）→ 进入升级模式：
    #      继续抓 YouTube，若出现更全歌单则删旧发新（质量升级），否则保留原样
    try:
        existing = bili_comment.find_own_comment(video.bvid, cookies)
    except Exception as err:  # noqa: BLE001
        logger.warning("[%s] 检查已有评论失败: %s", video.bvid, err)
        existing = None
    upgrade_mode = False
    existing_rpid = ""
    if existing:
        existing_count = _count_own_songlist_lines(existing.message)
        if existing_count >= UPGRADE_THRESHOLD:
            result.status = "already_posted"
            result.detail = f"rpid={existing.rpid} 已发 {existing_count} 首（足量）"
            return result
        # 已发歌单很少 → 升级候选
        upgrade_mode = True
        existing_rpid = existing.rpid
        logger.info("[%s] 已发仅 %d 首（<阈值），进入质量升级检查", video.bvid, existing_count)
    # 2. 确定 YouTube ID（part 字段优先，简介首行校验）；顺带拿完整简介供通知提取主播/标题
    yt_id = video.yt_id
    desc = ""
    if not yt_id:
        yt_id, desc = _fetch_bili_video_info(video.bvid)
    desc_url_id = ""
    if not desc:
        try:
            desc_url_id, desc = _fetch_bili_video_info(video.bvid)
        except Exception:  # noqa: BLE001
            desc_url_id = ""
    else:
        desc_url_id = yt_fetch.extract_description_first_line_youtube_url(desc)
    if yt_id and desc_url_id and yt_id != desc_url_id:
        logger.warning("[%s] part 与简介 YouTube ID 不一致: %s vs %s，采用简介", video.bvid, yt_id, desc_url_id)
        yt_id = desc_url_id
    if not yt_id and desc_url_id:
        yt_id = desc_url_id
    if not yt_id:
        result.status = "no_yt_link"
        result.detail = "B 站简介首行没有 YouTube 链接"
        return result
    result.yt_id = yt_id
    # 简介提取「主播 + 原标题」，随成功通知发送
    result.desc_profile = notify.extract_desc_profile(desc)

    # 3. 抓取 YouTube 评论 + 简介
    #    缓存策略：
    #    - 未发布：读缓存 → 无歌单则 force 重抓（直到评论区出现歌单）
    #    - 升级模式：缓存按 TTL 过期（避免每次 cron 都重抓已发视频）
    try:
        if upgrade_mode:
            raw = yt_fetch.fetch_youtube_raw(yt_id, cache_dir=cache_dir, max_age_seconds=UPGRADE_CHECK_TTL)
        else:
            raw = yt_fetch.fetch_youtube_raw(yt_id, cache_dir=cache_dir)
            if not raw_has_timestamp_songlist(raw):
                logger.info("[%s] 缓存无歌单，强制重新抓取 YouTube", video.bvid)
                raw = yt_fetch.fetch_youtube_raw(yt_id, cache_dir=cache_dir, force=True)
    except Exception as err:  # noqa: BLE001
        result.status = "error"
        result.error = f"YouTube 抓取失败: {type(err).__name__}: {err}"
        # YouTube 限流（429）→ 飞书提醒；同一次运行只提醒一次，避免多个视频同时限流刷屏
        if yt_fetch.is_rate_limited_error(err) and video.bvid not in _yt_rate_limited_notified:
            _yt_rate_limited_notified.add(video.bvid)
            try:
                brief = notify.build_yt_rate_limit_brief(video.bvid, result.error)
                ok, note = notify.send_feishu_message(brief)
                logger.info("[%s] 飞书 YouTube 429 通知: %s %s", video.bvid, ok, note)
            except Exception as notify_err:  # noqa: BLE001
                logger.warning("[%s] 飞书 YouTube 429 通知失败: %s", video.bvid, notify_err)
        return result

    comments = [c.get("text", "") for c in raw.get("comments", [])]
    description = raw.get("description", "")

    # 3b. 只保留「结构化歌单评论」，零散感想评论（夹 1 个时间戳的聊天）不喂给 DS/本地，
    #    避免 DS 把「1:30:53 つかさくんの『悪ノ召使』めっちゃ良い」这类感想当歌单、
    #    还把 UP 主昵称当歌手（BV1eYgV6WEq3 的错误根源）。
    songlist_comments = [t for t in comments if _is_songlist_comment(t)]

    # 4. 本地规则清洗（作为无 DS 时的兜底，以及 DS 输出的时间戳参考）
    local_items = clean.build_comment_songlist(songlist_comments, description)

    # 5. DS 优先整理（实测准确率高，能处理本地规则漏掉的方括号/＠/全角格式）
    items: list = []
    source = ""
    ai_detail = ""
    if config.deepseek_api_key() and songlist_comments:
        # 只喂结构化歌单评论；无歌单评论则不调 DS（防从感想提取/幻觉）
        user_text = "\n\n---\n\n".join(songlist_comments)
        ai_text, ai_err = ai.call_deepseek(user_text)
        if ai_err:
            ai_detail = f"AI 整理失败: {ai_err}"
            logger.warning("[%s] %s", video.bvid, ai_detail)
        elif ai.is_special_no_artist_response(ai_text):
            ai_detail = "AI 判定缺歌手"
        else:
            items = ai.parse_ai_output_to_items(ai_text)
            source = "ai"
    else:
        ai_detail = "评论区无结构化歌单（不调 DS）"
    if not items:
        items = local_items
        source = "local"
        if ai_detail:
            ai_detail = f"本地兜底（{ai_detail}）"

    # 6. 过滤条目：必须有时间戳；歌手字段按配置（默认放宽=允许只有歌名）
    if config.require_artist():
        items = [it for it in items if it.artist and it.timestamp_seconds is not None]
    else:
        items = [it for it in items if it.timestamp_seconds is not None]
    result.song_count = len(items)
    result.source = source
    if ai_detail:
        result.detail = ai_detail

    # 6b. 无歌曲
    if not items:
        if upgrade_mode:
            # 已发过低质量评论，但 YouTube 当前也没歌单 → 保留原样
            result.status = "already_posted"
            result.detail = f"rpid={existing_rpid} 升级检查：YouTube 无更全歌单，保留原评论"
            return result
        result.status = "skipped_no_songs"
        result.detail = f"未提取到有效歌曲（{result.detail or '本地与 AI 均无结果'}）"
        return result

    # 6c. 升级判定：已发低质量评论时，只有"更全"才升级（避免 1→2 首抖动刷屏）
    if upgrade_mode:
        existing_count = _count_own_songlist_lines(existing.message) if existing else 0
        if len(items) < existing_count + UPGRADE_THRESHOLD:
            result.status = "already_posted"
            result.detail = (
                f"rpid={existing_rpid} 升级检查：新提取 {len(items)} 首 vs 已发 {existing_count} 首，"
                f"未达升级阈值（需 +{UPGRADE_THRESHOLD}），保留原评论"
            )
            return result
        logger.info(
            "[%s] 质量升级：已发 %d 首 → 新歌单 %d 首，删旧发新",
            video.bvid, existing_count, len(items),
        )

    # 7. 格式化 + 发布（无空行，统一时间戳 NN. 歌名 - 歌手；超长自动楼中楼续写）
    message = clean.format_song_items(items, include_timestamps=True)
    if dry_run:
        result.status = "dry_run"
        result.message = message
        if upgrade_mode:
            result.detail = f"升级：删 rpid={existing_rpid} 后发 {len(items)} 首（dry-run 不执行）"
        return result

    # 升级模式：先删旧评论，再发新评论
    if upgrade_mode and existing_rpid:
        try:
            del_resp = bili_comment.delete_comment(video.bvid, existing_rpid, cookies)
            if del_resp.get("code") != 0:
                result.status = "error"
                result.error = f"删除旧评论失败: code={del_resp.get('code')} msg={del_resp.get('message')}"
                return result
            logger.info("[%s] 已删除旧评论 rpid=%s", video.bvid, existing_rpid)
        except Exception as err:  # noqa: BLE001
            result.status = "error"
            result.error = f"删除旧评论异常: {err}"
            return result

    responses = bili_comment.post_comment_with_replies(video.bvid, message, cookies)
    if not responses:
        result.status = "error"
        result.error = "评论发布无响应"
        return result

    main_resp = responses[0]
    if main_resp.get("code") != 0:
        result.status = "error"
        result.error = f"评论发布失败: code={main_resp.get('code')} msg={main_resp.get('message')}"
        return result

    # 主评论成功即视为已发布；楼中楼续写失败仅警告（缺失段可后续补发）
    followup_fail = next((r for r in responses[1:] if r.get("code") != 0), None)
    result.status = "posted"
    result.message = message
    rpids = [str(r.get("data", {}).get("rpid", "")) for r in responses if r.get("data")]
    if upgrade_mode:
        result.detail = f"升级成功：删旧 rpid={existing_rpid}，发新 rpids={'/'.join(rpids)} segments={len(responses)}"
    elif followup_fail:
        result.detail = (
            f"rpids={'/'.join(rpids)} segments={len(responses)} "
            f"楼中楼续写失败: code={followup_fail.get('code')} msg={followup_fail.get('message')}"
        )
    else:
        result.detail = f"rpids={'/'.join(rpids)} segments={len(responses)}"
    return result


def run_pipeline(
    mode: str = "incremental",
    dry_run: bool = True,
    limit: int = 0,
    specific_bvids: Optional[list[str]] = None,
) -> RunRecord:
    """执行管道。

    mode:
      - incremental: 只处理相对上次快照新增的视频 + 已处理集合之外且快照内的视频
      - full: 处理快照内所有未发布视频
      - specific: 只处理指定 bvid
    dry_run: True 时不真实发布（也不发飞书）
    limit: 最多处理 N 个视频（0=不限）
    """
    data_dir = config.data_dir()
    cache_dir = data_dir / "yt_raw"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cookies = bili_comment.load_cookie_map()
    posted = load_processed(data_dir)

    # 每次运行重置限流通知去重（跨 cron 周期每个视频可再提醒）
    _yt_rate_limited_notified.clear()

    # 抓取合集
    logger.info("抓取合集视频列表...")
    videos = collections.fetch_all_collections()
    logger.info("合集共 %d 个视频", len(videos))

    if mode == "specific" and specific_bvids:
        wanted = set(specific_bvids)
        candidates = [v for v in videos if v.bvid in wanted]
    elif mode == "incremental":
        snapshot = collections.load_snapshot()
        new_videos = collections.detect_new_videos(videos, snapshot)
        # 快照内但尚未发布过的也纳入（历史存量）
        known_bvids = snapshot.bvids()
        pending = [v for v in videos if v.bvid not in posted]
        candidates = new_videos + [v for v in pending if v.bvid in known_bvids and v.bvid not in {n.bvid for n in new_videos}]
        seen = set()
        deduped = []
        for v in candidates:
            if v.bvid in seen:
                continue
            seen.add(v.bvid)
            deduped.append(v)
        candidates = deduped
    else:  # full
        candidates = [v for v in videos if v.bvid not in posted]

    candidates.sort(key=lambda v: v.part_date, reverse=True)
    if limit > 0:
        candidates = candidates[:limit]
    logger.info("本轮候选 %d 个视频", len(candidates))

    results: list[VideoResult] = []
    for idx, video in enumerate(candidates, 1):
        logger.info("[%d/%d] 处理 %s (%s)", idx, len(candidates), video.bvid, video.part_date)
        result = process_video(video, cache_dir, dry_run)
        results.append(result)
        logger.info("  → %s (%d 首, %s)", result.status, result.song_count, result.detail or result.error)
        if result.status in {"posted", "ignored"} and not dry_run:
            posted.add(result.bvid)
            if result.status == "posted":
                # 飞书通知（仅新投稿发布时；无新增/缺歌单不播报）
                brief = notify.build_success_brief(
                    bvid=result.bvid,
                    yt_link=f"https://youtu.be/{result.yt_id}",
                    posted_at=notify.beijing_now(),
                    song_count=result.song_count,
                    profile=result.desc_profile,
                )
                ok, note = notify.send_feishu_message(brief)
                logger.info("  飞书通知: %s %s", ok, note)
        elif result.status == "error" and not dry_run:
            brief = notify.build_failure_brief(bvid=result.bvid, reason=result.error)
            try:
                notify.send_feishu_message(brief)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1)

    # 保存快照与处理记录
    if not dry_run:
        collections.save_snapshot(videos)
        save_processed(data_dir, posted)
    run_record = RunRecord(
        run_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        total=len(candidates),
        results=[
            {
                "bvid": r.bvid,
                "yt_id": r.yt_id,
                "title": r.title,
                "part_date": r.part_date,
                "collection": r.collection,
                "status": r.status,
                "song_count": r.song_count,
                "source": r.source,
                "detail": r.detail,
                "error": r.error,
                "desc_profile": r.desc_profile,
            }
            for r in results
        ],
    )
    (data_dir / f"run_{run_record.run_at.replace(':', '').replace('+', '_')}.json").write_text(
        json.dumps(run_record.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_record
