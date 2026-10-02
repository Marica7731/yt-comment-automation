"""配置加载：全部敏感信息走环境变量或本地私有文件，仓库内只保留 .example。

敏感配置：
- BILI_COOKIE_FILE: biliup 格式 cookie JSON（SESSDATA/bili_jct/DedeUserID）
- FEISHU_APP_ID / FEISHU_APP_SECRET / MY_FEISHU_OPEN_ID: 当前项目飞书机器人
- 发布和点赞均走 Codex 审核队列；生产不读取任何外部模型凭据
- 飞书凭据只从当前进程环境或本项目 private.env 读取，禁止回退旧机器人/桥接文件
- SONG_SERCH_LYRICS_ROOT: song_serch_lyrics 仓库根目录（复用其评论抓取实现）

优先从环境变量读取；未设置时尝试读取同目录私有文件 ../private.env（gitignore）。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Codex 接手日期：只处理该日期及之后发布的视频，避免每轮重扫历史存量。
CODEX_SCOPE_START_DATE_DEFAULT = "2026-10-02"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# 私有环境文件（不进 git）
_load_dotenv(ROOT / "private.env")


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def require(key: str) -> str:
    value = get(key)
    if not value:
        raise RuntimeError(f"缺少必要配置 {key}（可通过环境变量或 private.env 提供）")
    return value


def cookie_file() -> str:
    return get("BILI_COOKIE_FILE", str(ROOT / "runtime" / "biliup_cookies.json"))


def feishu_app_id() -> str:
    return get("FEISHU_APP_ID")


def feishu_app_secret() -> str:
    return get("FEISHU_APP_SECRET")


def feishu_open_id() -> str:
    return get("MY_FEISHU_OPEN_ID", get("FEISHU_OPEN_ID"))




def song_serch_lyrics_root() -> str:
    return get("SONG_SERCH_LYRICS_ROOT")


def collection_anchors() -> list[str]:
    return [a for a in get("COLLECTION_ANCHORS", "BV1e4TV6mE9R,BV15zbv6YE7j,BV11Zbv6HEEt,BV1ntuo6XESr").split(",") if a]


def collection_names() -> list[str]:
    """与 collection_anchors 一一对应；缺省用 anchor bvid。"""
    names = [n for n in get("COLLECTION_NAMES", "").split(",") if n]
    anchors = collection_anchors()
    if len(names) == len(anchors):
        return names
    return [f"collection-{a}" for a in anchors]


def owner_mid() -> str:
    return get("OWNER_MID", "3546597260528367")


def dry_run() -> bool:
    return get("DRY_RUN", "1") == "1"


def require_artist() -> bool:
    """是否强制要求歌手字段（默认 0=允许只有歌名）。

    插件场景（油猴）强制必须有歌手；B 站评论场景用户确认"只有歌名无所谓的"，可放宽。
    """
    return get("REQUIRE_ARTIST", "0") == "1"


def ignore_bvids() -> set[str]:
    """忽略列表：这些视频不写评论、不播报（如标题带歌但实际非歌枠的投稿）。"""
    return {b.strip() for b in get("IGNORE_BVIDS", "").split(",") if b.strip()}


def codex_scope_start_date() -> str:
    """Codex 接手后的视频范围起始日期（含当日）。"""
    return get("CODEX_SCOPE_START_DATE", CODEX_SCOPE_START_DATE_DEFAULT)


def codex_scope_bvids() -> set[str]:
    """手工点名、必须纳入 Codex 范围的 B 站视频。"""
    return {b.strip() for b in get("CODEX_SCOPE_BVIDS", "").split(",") if b.strip()}


def in_codex_scope(bvid: str, part_date: str = "", queued_at: str = "") -> bool:
    """判断视频是否属于接手后的新视频范围。

    优先使用投稿日期；投稿日期为空时使用入队日期，便于处理没有
    `[YYYY-MM-DD]` 前缀的手工目标。显式点名的 BVID 永远在范围内。
    """
    if bvid and bvid in codex_scope_bvids():
        return True
    scope_date = (part_date or "").strip()[:10]
    if not scope_date:
        scope_date = (queued_at or "").strip()[:10]
    return bool(scope_date) and scope_date >= codex_scope_start_date()


def data_dir() -> Path:
    path = Path(get("DATA_DIR", str(ROOT / "data")))
    path.mkdir(parents=True, exist_ok=True)
    return path
