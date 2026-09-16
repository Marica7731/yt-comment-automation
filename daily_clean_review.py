"""每日清洗复盘：对比「源时间戳行（缓存原始抓取，未过滤）」与「实际发布内容」，
把被清理管线洗掉的源时间戳行原文列出，供人工判断是否误杀（如 BV1pGeN6uEys 的「奏」）。

数据来源（零 YouTube 抓取）：
- 源时间戳行：data/yt_raw/<ytid>.info.json（含 history 轮转合并），与管线同款正则提取；
- 发布内容：优先 run json 的 message 字段（66332f0 起落盘），旧数据回退读自己 B 站评论。
每天跑一次（cron：北京时间 8 点 = UTC 0 点），结果发飞书。
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/opt/yt-comment-automation")
from yt_comment_automation import bili_comment
from yt_comment_automation import notify

DATA_DIR = "/opt/yt-comment-automation/data"
TS_RE = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
MAX_SHOW = 20  # 单视频最多列出的缺失行数，防飞书刷屏


def ts_to_seconds(ts: str) -> int:
    parts = [int(x) for x in ts.split(":")]
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


def msg_seconds_set(message: str) -> set[int]:
    return {ts_to_seconds(m) for m in TS_RE.findall(message or "")}


def load_source_lines(yt_id: str) -> list[str]:
    """从缓存（含 history 轮转）重建源时间戳行，逻辑与 pipeline 一致。"""
    texts: list[str] = []
    main = os.path.join(DATA_DIR, "yt_raw", f"{yt_id}.info.json")
    if os.path.exists(main):
        try:
            raw = json.load(open(main, encoding="utf-8"))
            texts.extend(c.get("text", "") for c in raw.get("comments", []) if c.get("text"))
            if raw.get("description"):
                texts.append(raw["description"])
        except (OSError, ValueError):
            pass
    for hist in sorted(glob.glob(os.path.join(DATA_DIR, "yt_raw", "history", yt_id, "*.info.json"))):
        try:
            raw = json.load(open(hist, encoding="utf-8"))
            texts.extend(c.get("text", "") for c in raw.get("comments", []) if c.get("text"))
            if raw.get("description"):
                texts.append(raw["description"])
        except (OSError, ValueError):
            pass
    lines: list[str] = []
    for src in dict.fromkeys(texts):
        for ln in (src or "").splitlines():
            ln = ln.strip()
            if ln and TS_RE.search(ln):
                lines.append(ln)
    return list(dict.fromkeys(lines))


def dropped_source_lines(source_lines: list[str], message: str) -> list[str]:
    """源行的时间戳与行内文字都未出现在发布内容中 → 视为被洗掉。"""
    if not message:
        return []
    msg_ts = msg_seconds_set(message)
    msg_flat = re.sub(r"\s+", "", message)
    dropped = []
    for ln in source_lines:
        m = TS_RE.search(ln)
        rest = TS_RE.sub("", ln, count=1)
        rest = re.sub(r"^\s*\d{1,3}[.．。、)]\s*", "", rest).strip()  # 去序号
        rest_flat = re.sub(r"\s+", "", rest)
        ts_hit = m and ts_to_seconds(m.group()) in msg_ts
        text_hit = len(rest_flat) >= 2 and rest_flat in msg_flat
        short_hit = len(rest_flat) < 2 and rest_flat and rest_flat in msg_flat  # 单字歌名按字面找
        if not ts_hit and not text_hit and not short_hit:
            dropped.append(ln)
    return dropped


def main() -> int:
    since = datetime.now() - timedelta(hours=24)
    posted_rows: dict[str, dict] = {}  # bvid → 最新一条 posted 记录
    checked, run_files = 0, 0
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "run_*.json"))):
        try:
            rec = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            run_at = datetime.strptime(rec.get("run_at", ""), "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            continue
        if run_at.tzinfo is None:
            continue
        run_files += 1
        for r in rec.get("results", []):
            if r.get("status") != "posted":
                continue
            ra = run_at
            # 同视频跨轮保留最新一条
            prev = posted_rows.get(r.get("bvid"))
            if prev is None or prev["_run_at"] <= ra:
                posted_rows[r.get("bvid")] = {**r, "_run_at": ra}
    for bvid, row in list(posted_rows.items()):
        if row["_run_at"] < since.replace(tzinfo=row["_run_at"].tzinfo):
            del posted_rows[bvid]
        else:
            checked += 1

    cookies = bili_comment.load_cookie_map()
    issues, cleans = [], []
    for bvid, row in sorted(posted_rows.items(), key=lambda kv: kv[1]["_run_at"]):
        yt_id = row.get("yt_id") or ""
        message = row.get("message") or ""
        if not message:
            try:
                own = bili_comment.find_own_comment(bvid, cookies)
                message = own.message if own else ""
            except Exception as err:  # noqa: BLE001
                message = ""
                print(f"⚠️ {bvid} 读自己评论失败: {err}", flush=True)
        src = load_source_lines(yt_id) if yt_id else []
        dropped = dropped_source_lines(src, message)
        head = f"[{bvid}] {row.get('title', '')[:40]}（源{len(src)}行 → 发{row.get('song_count', '?')}首）"
        if dropped:
            issues.append((head, dropped))
            print(f"⚠️ {head} 缺失 {len(dropped)} 行", flush=True)
            for ln in dropped[:MAX_SHOW]:
                print(f"   · {ln}", flush=True)
        else:
            cleans.append(head)
            print(f"✅ {head}", flush=True)

    now = notify.beijing_now()
    lines = [f"🔍每日清洗复盘（近24h posted {checked} 个 / 扫描 run {run_files} 份）"]
    if not issues:
        lines.append("✅ 全部源时间戳行都在发布内容中，无误删")
    for head, dropped in issues:
        lines.append(f"⚠️{head} 缺失 {len(dropped)} 行：")
        lines.extend(f"　· {ln}" for ln in dropped[:MAX_SHOW])
    lines.append(f"时间：{now}")
    brief = chr(10).join(lines)
    print(flush=True)
    print(brief, flush=True)
    try:
        ok, note = notify.send_feishu_message(brief)
        print(f"飞书: {ok} {note}", flush=True)
    except Exception as err:  # noqa: BLE001
        print(f"飞书通知失败: {err}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
