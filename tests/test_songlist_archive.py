"""songlist_archive 归档导入的回归测试。

fixture 复刻 song_serch_lyrics 合并文件的真实结构：
文件级「文件名：」行 + 按 [yt_id] 分节 + 主歌单/开始时间版/起止时间版 text 代码块。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yt_comment_automation import pipeline, songlist_archive

MERGED_MD = """文件名：歌单_[2026-10-28至2026-10-29]_VTuber_第59组合并.md

文件名：歌单_[2026-10-29][cqH8ZbBnokw]_VTuber.md

# [2026-10-29][cqH8ZbBnokw] VTuber

## 主歌单

```text
01. 名もなき詩 - Mr.Children
02. 時の流れに身をまかせ - テレサ・テン
```

## 开始时间版索引

```text
0:09:17 01. 名もなき詩 / Mr.Children
0:21:37 02. 時の流れに身をまかせ / テレサ・テン
```

## 起止时间版索引

```text
0:09:17 ~ 0:15:02 01. 名もなき詩 / Mr.Children
0:21:37 ~ 0:25:42 02. 時の流れに身をまかせ / テレサ・テン
0:29:40 03. からくりピエロ / 40mP feat.初音ミク
```

文件名：歌单_[2026-10-29][9tmYFNPNtE0]_VTuber.md

# [2026-10-29][9tmYFNPNtE0] VTuber

## 开始时间版索引

```text
0:47:21 01. Do you think about me? / aiko
```
"""


@pytest.fixture()
def archive_root(tmp_path: Path) -> Path:
    root = tmp_path / "song_serch_lyrics"
    target = root / "songlists" / "2026-10-28至2026-10-29"
    target.mkdir(parents=True)
    (target / "歌单_[2026-10-28至2026-10-29]_VTuber_第59组合并.md").write_text(
        MERGED_MD, encoding="utf-8"
    )
    return root


def setup_function(_: object) -> None:
    songlist_archive.reset_refresh_state_for_tests()


def test_find_section_matches_yt_id(archive_root: Path) -> None:
    found = songlist_archive.find_section(archive_root, "cqH8ZbBnokw")
    assert found is not None
    label, section = found
    assert "2026-10-28至2026-10-29" in label
    assert any("[cqH8ZbBnokw]" in line for line in section[:10])


def test_find_section_no_match(archive_root: Path) -> None:
    assert songlist_archive.find_section(archive_root, "b1m7GjiVkOY") is None
    assert songlist_archive.find_section(archive_root, "") is None


def test_extract_prefers_range_index(archive_root: Path) -> None:
    _, section = songlist_archive.find_section(archive_root, "cqH8ZbBnokw")
    kind, lines = songlist_archive.extract_index(section)
    assert kind == "range"
    # 起止块优先且整块使用；块内允许混有只有开始时间的行
    assert len(lines) == 3
    assert lines[0].startswith("0:09:17 ~ 0:15:02")
    assert lines[2].startswith("0:29:40 03.")


def test_extract_falls_back_to_start_index(archive_root: Path) -> None:
    _, section = songlist_archive.find_section(archive_root, "9tmYFNPNtE0")
    kind, lines = songlist_archive.extract_index(section)
    assert kind == "start"
    assert lines == ["0:47:21 01. Do you think about me? / aiko"]


def test_build_messages_range_and_mixed() -> None:
    messages = songlist_archive.build_messages(
        [
            "0:09:17 ~ 0:15:02 01. 名もなき詩 / Mr.Children",
            "0:21:37 ~ 0:25:42 02. 時の流れに身をまかせ / テレサ・テン",
            "0:29:40 03. からくりピエロ / 40mP feat.初音ミク",
            "这不是时间戳行",
        ]
    )
    assert messages == [
        "0:09:17-0:15:02 01. 名もなき詩 - Mr.Children",
        "0:21:37-0:25:42 02. 時の流れに身をまかせ - テレサ・テン",
        "0:29:40 03. からくりピエロ - 40mP feat.初音ミク",
    ]


def test_build_messages_protects_double_slash() -> None:
    messages = songlist_archive.build_messages(["0:01:00 01. DISH// / 陌生艺术家"])
    assert messages == ["0:01:00 01. DISH// - 陌生艺术家"]


def test_import_draft_end_to_end(archive_root: Path) -> None:
    draft = songlist_archive.import_draft(archive_root, "cqH8ZbBnokw")
    assert draft is not None
    assert draft.source == "song_serch_lyrics"
    assert draft.song_count == 3
    # 单条多行消息（与既有 draft_messages 一致），超长切分由发布层负责
    assert draft.messages == [
        "0:09:17-0:15:02 01. 名もなき詩 - Mr.Children\n"
        "0:21:37-0:25:42 02. 時の流れに身をまかせ - テレサ・テン\n"
        "0:29:40 03. からくりピエロ - 40mP feat.初音ミク"
    ]
    assert "起止时间版索引" not in draft.index_text
    assert draft.index_text.splitlines()[0].startswith("0:09:17 ~ 0:15:02")
    addendum = draft.review_addendum(prefix_empty=True)
    assert addendum.startswith("[song_serch_lyrics 归档 songlists/")
    assert addendum.endswith(draft.index_text)


def test_import_draft_missing(archive_root: Path) -> None:
    assert songlist_archive.import_draft(archive_root, "zzzzzzzzzzz") is None


def test_refresh_skips_non_git_dir(archive_root: Path) -> None:
    assert songlist_archive.refresh(archive_root) is False


def test_refresh_skips_dirty_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "archive_clone"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, env=env, capture_output=True, text=True)
    git("init", "-q")
    (repo / "a.md").write_text("x", encoding="utf-8")
    git("add", "a.md")
    git("commit", "-qm", "init")
    (repo / "a.md").write_text("dirty", encoding="utf-8")
    assert songlist_archive.refresh(repo) is False
    assert (repo / "a.md").read_text(encoding="utf-8") == "dirty"


def test_pipeline_hook_disabled_without_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SONG_SERCH_LYRICS_ROOT", raising=False)
    assert pipeline._archive_draft_or_none("cqH8ZbBnokw") is None


def test_pipeline_hook_imports_from_archive(
    archive_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SONG_SERCH_LYRICS_ROOT", str(archive_root))
    draft = pipeline._archive_draft_or_none("cqH8ZbBnokw")
    assert draft is not None
    assert draft.song_count == 3
    assert draft.messages[0].startswith("0:09:17-0:15:02")
