"""B站合集（ugc_season）抓取：读取合集内全部视频，检测新增/变化。

接口：https://api.bilibili.com/x/web-interface/view?bvid=<anchor>
返回 data.ugc_season.sections[].episodes[].bvid / title / page.part
part 字段内嵌 [YYYY-MM-DD][YouTubeID] 前缀，可解析出投稿日期与油管视频 ID。
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass, field

from . import config

VIEW_API = "https://api.bilibili.com/x/web-interface/view"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}

PART_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})\]\[([\w-]{11})\](.*)$", re.S)


@dataclass
class CollectionVideo:
    collection: str
    section: str
    bvid: str
    title: str
    part_date: str = ""
    yt_id: str = ""
    raw_part: str = ""

    def key(self) -> str:
        return self.bvid


@dataclass
class CollectionSnapshot:
    videos: list[CollectionVideo] = field(default_factory=list)

    def bvids(self) -> set[str]:
        return {v.key() for v in self.videos}


def _fetch_json(url: str, retries: int = 3) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as err:  # noqa: BLE001
            last_err = err
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"接口请求失败: {url}: {last_err}")


def fetch_collection_videos(anchor_bvid: str, collection_name: str) -> list[CollectionVideo]:
    data = _fetch_json(f"{VIEW_API}?bvid={anchor_bvid}")
    if data.get("code") != 0:
        raise RuntimeError(f"合集接口异常 {anchor_bvid}: {data.get('message')}")
    season = (data.get("data") or {}).get("ugc_season") or {}
    videos: list[CollectionVideo] = []
    for section in season.get("sections", []) or []:
        for ep in section.get("episodes", []) or []:
            bvid = ep.get("bvid") or ""
            title = ep.get("title") or ""
            raw_part = ((ep.get("page") or {}).get("part")) or ""
            m = PART_RE.match(raw_part)
            if m:
                part_date, yt_id = m.group(1), m.group(2)
            else:
                part_date, yt_id = "", ""
            videos.append(
                CollectionVideo(
                    collection=collection_name,
                    section=section.get("title", ""),
                    bvid=bvid,
                    title=title,
                    part_date=part_date,
                    yt_id=yt_id,
                    raw_part=raw_part,
                )
            )
    return videos


def fetch_all_collections() -> list[CollectionVideo]:
    videos: list[CollectionVideo] = []
    anchors = config.collection_anchors()
    names = config.collection_names()
    for idx, anchor in enumerate(anchors):
        name = names[idx] if idx < len(names) else f"collection-{anchor}"
        videos.extend(fetch_collection_videos(anchor, name))
    return videos


def save_snapshot(videos: list[CollectionVideo], path=None) -> None:
    path = path or (config.data_dir() / "collections_snapshot.json")
    payload = [
        {
            "collection": v.collection,
            "section": v.section,
            "bvid": v.bvid,
            "title": v.title,
            "part_date": v.part_date,
            "yt_id": v.yt_id,
        }
        for v in videos
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_snapshot(path=None) -> CollectionSnapshot:
    path = path or (config.data_dir() / "collections_snapshot.json")
    if not path.is_file():
        return CollectionSnapshot()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return CollectionSnapshot()
    videos = [
        CollectionVideo(
            collection=item.get("collection", ""),
            section=item.get("section", ""),
            bvid=item.get("bvid", ""),
            title=item.get("title", ""),
            part_date=item.get("part_date", ""),
            yt_id=item.get("yt_id", ""),
        )
        for item in payload
    ]
    return CollectionSnapshot(videos=videos)


def detect_new_videos(current: list[CollectionVideo], previous: CollectionSnapshot) -> list[CollectionVideo]:
    """返回相比上次快照新增的视频（按 part_date 降序）。"""
    known = previous.bvids()
    new = [v for v in current if v.key() not in known]
    new.sort(key=lambda v: v.part_date, reverse=True)
    return new
