"""回归测试：processed.json 账本在并发 apply / cycle 下不丢条目。

复现 2026-11-09 事故：WDC 生产运行 13:43 轮 cycle 在 13:44:06 调用
save_processed，把 recheck_bvids（含全部 pending bvid）从账本里 ``existing -= recheck``
剔掉；而 Codex 在 13:43:56 经 review_cli apply 发布的 pending bvid 因此被从账本抹除，
失去重复发布防护。修复后 save_processed 只在“本轮确实重新发布”时才从账本剔除
（recheck & posted），pending bvid 由 Codex 发布时不会被 cycle 误删。
"""
from __future__ import annotations

import json
from pathlib import Path

from yt_comment_automation import pipeline, review


def _write_ledger(data_dir: Path, posted: list[str]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / "processed.json"
    p.write_text(
        json.dumps({"posted": posted}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def test_save_processed_preserves_concurrently_published_pending(tmp_path):
    data_dir = tmp_path / "data"
    p = _write_ledger(data_dir, ["BV_PendingPublished"])
    # 模拟 cycle 运行：该 bvid 仍在 recheck 中，但 cycle 本轮没有发布它（posted 为空）
    pipeline.save_processed(data_dir, posted=set(), recheck={"BV_PendingPublished"})
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert "BV_PendingPublished" in saved["posted"]


def test_save_processed_preserves_published_when_other_recheck_present(tmp_path):
    data_dir = tmp_path / "data"
    p = _write_ledger(data_dir, ["BV_Pub", "BV_Recheck"])
    # cycle 本轮只重新发布了 BV_Recheck，BV_Pub 是 Codex 早先发布的 pending 候选
    pipeline.save_processed(data_dir, posted={"BV_Recheck"}, recheck={"BV_Recheck", "BV_Pub"})
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert "BV_Pub" in saved["posted"]
    assert "BV_Recheck" in saved["posted"]


def test_save_processed_strips_and_readds_reposted_deleted(tmp_path):
    data_dir = tmp_path / "data"
    p = _write_ledger(data_dir, ["BV_Deleted"])
    # cycle 本届重新发布了被删除的 bvid：它在 recheck 也在 posted，剔除后会再被合并回来
    pipeline.save_processed(data_dir, posted={"BV_Deleted"}, recheck={"BV_Deleted"})
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert "BV_Deleted" in saved["posted"]


def test_mark_processed_is_lock_safe_and_idempotent(tmp_path):
    data_dir = tmp_path / "data"
    review._mark_processed(data_dir, "BV_A")
    review._mark_processed(data_dir, "BV_A")  # 重复调用不应产生重复或丢条目
    review._mark_processed(data_dir, "BV_B")
    saved = json.loads((data_dir / "processed.json").read_text(encoding="utf-8"))
    assert set(saved["posted"]) == {"BV_A", "BV_B"}


def test_mark_processed_coexists_with_cycle_save(tmp_path):
    data_dir = tmp_path / "data"
    # Codex apply 写入 BV_A
    review._mark_processed(data_dir, "BV_A")
    # cycle 保存（recheck 含 BV_A 但 cycle 未发布它）
    pipeline.save_processed(data_dir, posted={"BV_Cycle"}, recheck={"BV_A"})
    saved = json.loads((data_dir / "processed.json").read_text(encoding="utf-8"))
    assert "BV_A" in saved["posted"]
    assert "BV_Cycle" in saved["posted"]
