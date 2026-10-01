"""Codex 点赞审核队列。

cron 只合并候选；Codex 显式批准后才执行 action。执行过程逐条落盘，
避免下一轮扫描覆盖批准状态，也避免中断后重复点赞。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from . import config

OPEN_STATUSES = {"pending", "approved"}
DONE_STATUSES = {"applied", "rejected"}


def review_path(data_dir: Path | str | None = None) -> Path:
    base = Path(data_dir) if data_dir else config.data_dir()
    return base / "like_review.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_review(path: Path | str | None = None) -> dict[str, Any]:
    target = Path(path) if path else review_path()
    if not target.is_file():
        return {"version": 1, "updated_at": "", "candidates": []}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise ValueError(f"点赞审核文件损坏: {target}: {err}") from err
    if not isinstance(payload, dict):
        raise ValueError(f"点赞审核文件必须是 JSON 对象: {target}")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError(f"点赞审核文件缺少 candidates 数组: {target}")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in candidates:
        if not isinstance(entry, dict) or entry.get("rpid") is None:
            continue
        item = dict(entry)
        item["status"] = str(item.get("status") or "pending")
        key = str(item["rpid"])
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    payload["version"] = 1
    payload["candidates"] = normalized
    return payload


def save_review(payload: dict[str, Any], path: Path | str | None = None) -> Path:
    target = Path(path) if path else review_path()
    payload = dict(payload)
    payload["version"] = 1
    payload["updated_at"] = _now()
    _write(target, payload)
    return target


def _candidate_key(candidate: dict[str, Any]) -> str:
    return str(candidate.get("rpid") or "")


def merge_candidates(
    candidates: Iterable[dict[str, Any]],
    path: Path | str | None = None,
) -> dict[str, Any]:
    """合并本轮新候选，保留已批准、已执行和已拒绝状态。"""
    target = Path(path) if path else review_path()
    payload = load_review(target)
    by_key = {_candidate_key(item): item for item in payload.get("candidates") or []}
    for raw in candidates:
        candidate = dict(raw)
        key = _candidate_key(candidate)
        if not key or key == "None":
            continue
        existing = by_key.get(key)
        if existing is None:
            candidate.setdefault("status", "pending")
            candidate.setdefault("queued_at", _now())
            by_key[key] = candidate
            continue
        if existing.get("status") in DONE_STATUSES:
            continue
        # 审核中的候选只补充内容，不降级状态。
        candidate.setdefault("status", existing.get("status", "pending"))
        candidate.setdefault("queued_at", existing.get("queued_at") or _now())
        candidate["reviewed_at"] = existing.get("reviewed_at", "")
        by_key[key] = candidate
    payload["candidates"] = list(by_key.values())
    _write(target, payload)
    return payload


def _select(payload: dict[str, Any], rpids: Iterable[str | int]) -> list[dict[str, Any]]:
    by_key = {_candidate_key(item): item for item in payload.get("candidates") or []}
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    for value in rpids:
        key = str(value)
        item = by_key.get(key)
        if item is None:
            missing.append(key)
        else:
            selected.append(item)
    if missing:
        raise KeyError("审核文件中不存在 rpid: " + ",".join(missing))
    return selected


def approve(
    rpids: Iterable[str | int],
    path: Path | str | None = None,
    reviewer: str = "codex",
    note: str = "",
    max_count: int | None = None,
) -> dict[str, Any]:
    target = Path(path) if path else review_path()
    payload = load_review(target)
    selected = _select(payload, rpids)
    for item in selected:
        if item.get("status") == "applied":
            raise RuntimeError(f"rpid={item['rpid']} 已执行，不能重复批准")
        if item.get("status") == "rejected":
            raise RuntimeError(f"rpid={item['rpid']} 已拒绝，不能直接批准")
        item["status"] = "approved"
        item["reviewer"] = reviewer
        item["note"] = note
        item["reviewed_at"] = _now()
    if max_count is not None:
        if max_count < 1:
            raise ValueError("max_count 必须大于 0")
        payload["max_count"] = max_count
    _write(target, payload)
    return payload


def reject(
    rpids: Iterable[str | int],
    path: Path | str | None = None,
    reviewer: str = "codex",
    note: str = "",
) -> dict[str, Any]:
    target = Path(path) if path else review_path()
    payload = load_review(target)
    selected = _select(payload, rpids)
    for item in selected:
        if item.get("status") == "applied":
            raise RuntimeError(f"rpid={item['rpid']} 已执行，不能拒绝")
        item["status"] = "rejected"
        item["reviewer"] = reviewer
        item["note"] = note
        item["reviewed_at"] = _now()
        item.pop("error", None)
    _write(target, payload)
    return payload


def summarize(payload: dict[str, Any]) -> dict[str, int]:
    counts = {"pending": 0, "approved": 0, "applied": 0, "rejected": 0, "failed": 0}
    for item in payload.get("candidates") or []:
        status = str(item.get("status") or "pending")
        counts[status] = counts.get(status, 0) + 1
    counts["total"] = len(payload.get("candidates") or [])
    return counts


def apply_approved(
    resolve_real_liked: Callable[[Any, Any], bool | None],
    send_like: Callable[[Any, Any], dict[str, Any]],
    path: Path | str | None = None,
    *,
    liked_set: set[str] | None = None,
    save_liked_set: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    reviewer: str = "codex",
) -> dict[str, Any]:
    """执行已批准点赞；每条 action 前复核真实状态，逐条保存结果。"""
    target = Path(path) if path else review_path()
    payload = load_review(target)
    approved = [item for item in payload.get("candidates") or [] if item.get("status") == "approved"]
    max_count = payload.get("max_count")
    if max_count is not None and len(approved) > int(max_count):
        raise ValueError(f"审核通过 {len(approved)} 条，超过 max_count={max_count}")

    liked = liked_set if liked_set is not None else set()
    liked_count = skipped_count = failed_count = 0
    for item in approved:
        oid, rpid = item.get("oid"), item.get("rpid")
        key = str(rpid)
        item["attempted_at"] = _now()
        item["executor"] = reviewer
        if key in liked:
            item.update({"status": "applied", "result": "already_liked", "executed_at": _now()})
            item.pop("error", None)
            skipped_count += 1
            _write(target, payload)
            continue
        try:
            real = resolve_real_liked(oid, rpid)
        except Exception as err:  # noqa: BLE001
            real = None
            item["error"] = f"状态复核异常: {err}"
        if real is True:
            liked.add(key)
            if save_liked_set:
                save_liked_set()
            item.update({"status": "applied", "result": "already_liked", "executed_at": _now()})
            item.pop("error", None)
            skipped_count += 1
            _write(target, payload)
            continue
        if real is None:
            item.update({"status": "failed", "result": "verify_unavailable"})
            item.setdefault("error", "复核不到真实状态，宁漏勿撤")
            failed_count += 1
            _write(target, payload)
            continue
        try:
            response = send_like(oid, rpid)
        except Exception as err:  # noqa: BLE001
            item.update({"status": "failed", "result": "exception", "error": str(err)[:240]})
            failed_count += 1
            _write(target, payload)
            sleep(8)
            continue
        if isinstance(response, dict) and response.get("code") == 0:
            liked.add(key)
            if save_liked_set:
                save_liked_set()
            item.update({"status": "applied", "result": "liked", "executed_at": _now()})
            item.pop("error", None)
            liked_count += 1
        else:
            code = response.get("code") if isinstance(response, dict) else "invalid_response"
            message = response.get("message") if isinstance(response, dict) else str(response)
            item.update({"status": "failed", "result": "api_error", "error": f"code={code} {message}"})
            failed_count += 1
        _write(target, payload)
        sleep(8)

    payload["last_applied_at"] = _now()
    _write(target, payload)
    result = summarize(payload)
    result.update(
        {
            "liked": liked_count,
            "skipped": skipped_count,
            "failed": failed_count,
            "executed": [dict(item) for item in approved],
        }
    )
    return result
