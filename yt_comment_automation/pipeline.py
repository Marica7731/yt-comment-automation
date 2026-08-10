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

# 本地规则结果可信的下限：低于此数量时触发 DeepSeek 兜底
MIN_CONFIDENT_SONGS = 5


@dataclass
class VideoResult:
    bvid: str
    yt_id: str
    title: str
    part_date: str
    collection: str
    status: str = ""  # already_posted / posted / skipped_no_songs / error / no_yt_link / dry_run
    song_count: int = 0
    source: str = ""  # local / ai
    message: str = ""
    error: str = ""
    detail: str = ""


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


def _fetch_youtube_id_for_bvid(bvid: str) -> str:
    """从 B 站简介第一行取 YouTube 链接 ID。"""
    cookies = bili_comment.load_cookie_map()
    try:
        aid = bili_comment.get_aid(bvid, cookies)
    except Exception:  # noqa: BLE001
        return ""
    url = f"https://api.bilibili.com/x/web-interface/view?aid={aid}"
    data = bili_comment._request_json(url, cookies, "https://www.bilibili.com/")  # noqa: SLF001
    desc = ((data.get("data") or {}).get("desc")) or ""
    return yt_fetch.extract_description_first_line_youtube_url(desc)


def _extract_yt_id_from_part(part: str) -> str:
    m = re.match(r"^\[(\d{4}-\d{2}-\d{2})\]\[([\w-]{11})\](.*)$", part or "")
    return m.group(2) if m else ""


# 非歌曲时间戳标记词：开始/MC/章节/杂谈/告知 等（带时间戳但不是歌单）
_NON_SONG_TS_MARKERS = re.compile(
    r"(?:開始|开始|start|終了|end|opening|open|closing|close|mc|雑談|talk|感想|告知|お知らせ|"
    r"チャプター|chapter|セトリ|setlist|タイムスタンプ|timestamp|スクショ|挨拶|自己紹介|コメント|"
    r"おつ|お疲れ|ありがとう|宣伝|休憩|トイレ|お水|スパチャ読み|リクエスト募集)",
    re.IGNORECASE,
)

# 歌名/歌手分隔特征：时间戳行里出现这些才算"歌曲行"
_SONG_LINE_SEPARATORS = re.compile(r"[\/／|｜￤∣丨＠@]|\s-\s|\s–\s")


def _line_is_song_line(line: str) -> bool:
    """时间戳行是否像歌曲行（含歌名/歌手分隔特征，且不是纯标记）。"""
    line = line.strip()
    if not line:
        return False
    if _NON_SONG_TS_MARKERS.search(line):
        return False
    # 时间戳行 + 分隔特征 + 有内容
    return bool(_SONG_LINE_SEPARATORS.search(line))


def has_any_timestamp_songlist(comments: list[str]) -> bool:
    """评论区是否已有**真正的歌曲**时间戳歌单（任何作者）。

    判定：
    - 单条评论含 ≥2 个时间戳
    - 且至少 2 个时间戳行具备歌名/歌手特征（含 /、／、|、＠、- 等分隔符）
    - 纯标记（開始/MC/章节/雑談/告知 等）不算歌单，不跳过，让 DS 继续提取
    """
    ts_re = re.compile(r"(?:^|[^\d:])(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)")
    for text in comments:
        if not text or len(text) < 30:
            continue
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        song_ts_lines = 0
        for line in lines:
            if not ts_re.search(line):
                continue
            # 去掉时间戳后剩余部分
            rest = ts_re.sub("", line)
            # 时间戳行 + 歌名/歌手特征 + 非纯标记
            if _SONG_LINE_SEPARATORS.search(rest) and not _NON_SONG_TS_MARKERS.search(rest):
                song_ts_lines += 1
        if song_ts_lines >= 2:
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

    # 1. 已有评论跳过（本账号已发布过歌单评论）
    try:
        existing = bili_comment.find_own_timestamp_comment(video.bvid, cookies)
    except Exception as err:  # noqa: BLE001
        logger.warning("[%s] 检查已有评论失败: %s", video.bvid, err)
        existing = None
    if existing:
        result.status = "already_posted"
        result.detail = f"rpid={existing.rpid} 已发布"
        return result
    # 2. 确定 YouTube ID（part 字段优先，简介首行校验）
    yt_id = video.yt_id
    if not yt_id:
        yt_id = _fetch_youtube_id_for_bvid(video.bvid)
    desc_url_id = ""
    try:
        desc_url_id = _fetch_youtube_id_for_bvid(video.bvid)
    except Exception:  # noqa: BLE001
        desc_url_id = ""
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

    # 3. 抓取 YouTube 评论 + 简介
    try:
        raw = yt_fetch.fetch_youtube_raw(yt_id, cache_dir=cache_dir)
    except Exception as err:  # noqa: BLE001
        result.status = "error"
        result.error = f"YouTube 抓取失败: {type(err).__name__}: {err}"
        return result

    comments = [c.get("text", "") for c in raw.get("comments", [])]
    description = raw.get("description", "")

    # 3b. 已有时间戳歌单评论跳过（任何作者，含他人写的；≥2 个时间戳即视为歌单）
    if has_any_timestamp_songlist(comments):
        result.status = "already_posted"
        result.detail = "YouTube 评论区已有时间戳歌单评论（非本账号）"
        return result

    # 4. 本地规则清洗（作为无 DS 时的兜底，以及 DS 输出的时间戳参考）
    local_items = clean.build_comment_songlist(comments, description)

    # 5. DS 优先整理（实测准确率高，能处理本地规则漏掉的方括号/＠/全角格式）
    items: list = []
    source = ""
    ai_detail = ""
    if config.deepseek_api_key():
        candidate_texts = [
            t for t in comments if re.search(r"\d{1,2}:\d{2}", t) or "歌" in t or "/" in t or " - " in t or "＠" in t or "@" in t
        ]
        user_text = "\n\n---\n\n".join(candidate_texts)
        ai_text, ai_err = ai.call_deepseek(user_text)
        if ai_err:
            ai_detail = f"AI 整理失败: {ai_err}"
            logger.warning("[%s] %s", video.bvid, ai_detail)
        elif ai.is_special_no_artist_response(ai_text):
            ai_detail = "AI 判定缺歌手"
        else:
            items = ai.parse_ai_output_to_items(ai_text)
            source = "ai"
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
        result.status = "skipped_no_songs"
        result.detail = f"未提取到有效歌曲（{result.detail or '本地与 AI 均无结果'}）"
        return result

    # 7. 格式化 + 发布（无空行，统一时间戳 NN. 歌名 - 歌手；超长自动楼中楼续写）
    message = clean.format_song_items(items, include_timestamps=True)
    if dry_run:
        result.status = "dry_run"
        result.message = message
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
    if followup_fail:
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
            }
            for r in results
        ],
    )
    (data_dir / f"run_{run_record.run_at.replace(':', '').replace('+', '_')}.json").write_text(
        json.dumps(run_record.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_record
