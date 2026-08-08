"""配置加载：全部敏感信息走环境变量或本地私有文件，仓库内只保留 .example。

敏感配置：
- BILI_COOKIE_FILE: biliup 格式 cookie JSON（SESSDATA/bili_jct/DedeUserID）
- FEISHU_APP_ID / FEISHU_APP_SECRET / MY_FEISHU_OPEN_ID: 飞书自建应用
- DEEPSEEK_API_KEY: DeepSeek API Key（可选，仅在需要 AI 兜底时使用）
- SONG_SERCH_LYRICS_ROOT: song_serch_lyrics 仓库根目录（复用其评论抓取实现）

优先从环境变量读取；未设置时尝试读取同目录私有文件 ../private.env（gitignore）。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def deepseek_api_key() -> str:
    return get("DEEPSEEK_API_KEY")


def song_serch_lyrics_root() -> str:
    return get("SONG_SERCH_LYRICS_ROOT")


def collection_anchors() -> list[str]:
    return [a for a in get("COLLECTION_ANCHORS", "BV13ege65Es5,BV1ZYNT6hEEe").split(",") if a]


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


def data_dir() -> Path:
    path = Path(get("DATA_DIR", str(ROOT / "data")))
    path.mkdir(parents=True, exist_ok=True)
    return path
