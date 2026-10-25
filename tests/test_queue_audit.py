import json
from pathlib import Path

from dev._queue_audit import song_count_mismatches


def write_item(queue_dir: Path, bvid: str, status: str, song_count: int) -> None:
    (queue_dir / f"{bvid}.json").write_text(
        json.dumps(
            {
                "bvid": bvid,
                "status": status,
                "song_count": song_count,
                "approved_messages": [
                    "0:03:05 01. 準透明少年 - ヨルシカ\n"
                    "0:11:00 02. フラレガイガール - さユり"
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_song_count_mismatches_checks_applied_records_only(tmp_path):
    write_item(tmp_path, "BV1BROKEN", "applied", 1)
    write_item(tmp_path, "BV1OK", "applied", 2)
    write_item(tmp_path, "BV1PENDING", "pending", 9)

    assert song_count_mismatches(tmp_path) == [("BV1BROKEN", 1, 2)]
