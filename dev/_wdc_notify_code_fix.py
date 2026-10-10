"""Send the code-fix Feishu report for this round's clean.py/pipeline.py fixes."""

import sys

sys.path.insert(0, "/opt/yt-comment-automation")

from yt_comment_automation import notify  # noqa: E402

BRIEF = notify.build_code_fix_brief(
    summary="简介出演者时段表不再压过真歌单评论；「歌名/歌手」成对引号行可正确拆分；"
            "串场词与去重判定修正",
    root_cause="pipeline 无条件把 YouTube 简介传给 build_comment_songlist_ranked。"
               "接力/collab 视频的简介是出演者时段表，每行带 / @handle，被解析成歌名/歌手后"
               "条数盖过评论里的真歌单（BV152pu6GEzJ：7 行出演表压过 6 行真歌单）。"
               "另外评论区惯用的「时间戳 歌名/歌手」成对引号写法里，分隔符落在外层引号内部，"
               "被括号掩蔽逻辑跳过，歌名与歌手拆不开，整串变成歌名、歌手为空（BV1Dvpg6BE8Y）。",
    files=[
        "yt_comment_automation/pipeline.py",
        "yt_comment_automation/clean.py",
        "tests/test_clean.py",
    ],
    changes=[
        "pipeline：存在结构化歌单评论时 desc_rank_source 置空，简介一律不参与排序竞争",
        "clean：新增 _unwrap_matched_cjk_edge_brackets，先剥成对 CJK 引号最外层"
        "（含 `1曲目「…」` 编号前缀）再做歌名/歌手拆分",
        "clean：@handle 社交账号不计入排序键的「带歌手数」",
        "clean：无歌手条目不再整体豁免去重，同时间戳+同歌名即判重"
        "（BV1Dvpg6BE8Y 首尾重复的 告白日和 此前残留两份）",
        "clean：トーク②/トーク③ 等圈号后缀补判；未闭合开引号不再当环节行判据"
        "（真歌「あっちゅー魔！」此前被丢掉）",
        "clean：次でラスト/ラスト1曲 串场提示词不是歌名",
    ],
    tests=[
        "tests/test_clean.py 新增 5 组真实样例回归（引号拆分、编号引号拆分、"
        "未闭合引号真歌、串场词、relay 时段表不压真歌单）",
        "python -m pytest tests/ -q → 191 passed（原 183）",
        "py_compile + pyflakes 干净",
        "WDC 已部署 HEAD=58e1876 并验证新函数生效",
    ],
    commit="58e1876",
)

if __name__ == "__main__":
    ok, note = notify.send_feishu_message(BRIEF)
    print(("SENT " if ok else "FAILED ") + str(note))
    sys.exit(0 if ok else 1)
