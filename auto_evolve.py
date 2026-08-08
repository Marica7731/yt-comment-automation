"""DS 自动规则进化引擎：分析新差异 → DS 生成规则变更 → 应用到插件/本地 → 验证 → 推送。

闭环：
1. 输入：本地规则 vs DS 结果的差异样本（data/rule_diff_samples.json 或新样本）
2. DeepSeek (reasoning high) 输出结构化规则变更：
   [
     {
       "function": "stripPerformanceNoteParens",   # 插件目标函数名
       "kind": "update_regex" | "insert_function", # 更新现有正则 / 插入新函数
       "old_regex": "...",                          # update_regex 时匹配旧正则
       "new_regex": "...",                          # 新正则（JS 转义格式，Python 端自动去转义）
       "js_function": "function stripXxx(t){...}",  # insert_function 时提供完整函数
       "py_regex": "...",                           # 可选：Python 端正则（缺省由 new_regex 转换）
       "tests": [{"input": "...", "expect_song": "...", "expect_artist": "..."}]
     }
   ]
3. 应用器：
   - user.js：按 function 名定位函数体，替换正则或插入新函数（锚点 = cleanSongOrArtistPart 之前）
   - rules.py：同步更新/新增对应正则常量与函数
4. 验证：node --check user.js 语法 + pytest 跑新增测试；任一失败则回滚不推送
5. 通过后生成 commit + push（WDC cron 会自动 pull）
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
USERJS = REPO / "userscript" / "youtube-comment-tools.user.js"
PLUGIN_JS = Path(r"G:\codex-work\plugin") / "YouTube 评论纯文本复制 + AI整理（括号保护 + 曲目数量校正版）.user.js"
RULES_PY = REPO / "yt_comment_automation" / "rules.py"

EVOLVE_PROMPT = """你是 YouTube 歌枠评论清洗规则的自动迭代工程师。你负责把「新发现的差异模式」转化为
插件(user.js) 和本地 Python 规则(rules.py) 的**确定性代码变更**。

背景：插件和本地规则已经能处理大部分格式，但 DeepSeek 模型在评论整理时发现了一些
本地规则还没覆盖的新模式（见下方差异样本）。你要为这些新模式生成精确的代码变更。

【插件目标函数当前源码】（你的 old_regex 必须能在这个源码里精确匹配到）：
{functions_source}

【硬性约束】
1. 只允许修改以下函数的规则逻辑，绝不允许改插件的 UI、抓取、事件绑定等非规则逻辑：
   - stripPerformanceNoteParens（删除表演备注括号：少し/ちょっと/1番のみ/練習/うろ覚え）
   - stripParentheticalTransliteration（删除译文/罗马字括号）
   - stripTrailingLatinAnnotationSuffix（删除尾随拉丁注释）
   - stripTrailingArtistNotes（删除歌手尾注）
   - stripLeadingSongIndexMarker / stripLeadingSerialMarker（剥离序号）
   - cleanSongOrArtistPart（歌名/歌手字段清洗入口）
2. 每个变更必须给出：
   - function：目标函数名
   - kind：update_regex（更新现有函数的正则）或 insert_function（在 cleanSongOrArtistPart 前插入新函数）
   - new_regex：JS 格式正则（字面量内 / 必须转义为 \\/，lookahead 用 (?=...)）
   - 若 update_regex：old_regex 必须是目标函数源码里现有正则的**精确子串**（含分隔符 / 和 flags）
   - 若 insert_function：js_function 提供完整函数源码（含 function 关键字）
   - py_regex：Python 格式正则（与 JS 对应，Python 不需要转义 /）
   - tests：至少 2 个 {{input, expect_song, expect_artist}} 测试（input 是完整评论行，含时间戳）
3. 保护原则：绝不能误删 8.32 纯数字歌名、DISH//、Don't say "lazy"、ryo(supercell)、
   ツインテールは20歳まで♡ 等合法标题；新增正则必须在 protection 里说明为何安全。
4. 只输出 JSON 数组，不要任何其他文字/代码块标记/说明。

差异样本：
{samples}"""


def extract_functions_source() -> str:
    """提取插件里允许修改的规则函数源码，供 DS 生成精确 old_regex。"""
    funcs = extract_functions_map()
    return "\n\n".join(funcs.values()) if funcs else "(未找到函数源码)"


def extract_functions_map() -> dict[str, str]:
    """提取插件允许修改的规则函数源码映射 {函数名: 源码}。"""
    src = USERJS.read_text(encoding="utf-8")
    targets = [
        "stripPerformanceNoteParens",
        "stripParentheticalTransliteration",
        "stripTrailingLatinAnnotationSuffix",
        "stripTrailingArtistNotes",
        "stripLeadingSongIndexMarker",
        "stripLeadingSerialMarker",
        "cleanSongOrArtistPart",
    ]
    result: dict[str, str] = {}
    for name in targets:
        idx = src.find(f"  function {name}(")
        if idx < 0:
            continue
        brace_idx = src.find("{", idx)
        if brace_idx < 0:
            continue
        depth = 0
        end = brace_idx
        for i in range(brace_idx, len(src)):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        result[name] = src[idx:end]
    return result


def _sample_relates_to_function(sample: dict, func_name: str) -> bool:
    """判断差异样本是否与该函数语义相关（通过 removed/added 关键词粗判）。"""
    removed = " ".join(sample.get("ds_removed") or [])
    added = " ".join(sample.get("ds_added") or [])
    haystack = f"{removed} {added}"
    func_keywords = {
        "stripPerformanceNoteParens": ["（", ")", ")", "少し", "ちょっと", "1番のみ", "練習", "うろ覚え", "short"],
        "stripParentheticalTransliteration": ["(", ")", "|", " ", "Hibi", "Gyakkou", "Zetchou"],
        "stripTrailingLatinAnnotationSuffix": ["(", ")", "[", "]", "Aliens", "Hibiki"],
        "stripTrailingArtistNotes": ["＠", "@", "＠ClariS"],
        "stripLeadingSongIndexMarker": ["01", "02", "〔", "〔10〕", "JANE", "RE:I AM"],
        "stripLeadingSerialMarker": ["RE:", "Re:", "〔"],
    }
    kws = func_keywords.get(func_name, [])
    return any(kw in haystack for kw in kws)


SINGLE_FUNC_PROMPT = """你是 YouTube 歌枠评论清洗规则的自动迭代工程师。现在只编辑**一个函数**。

【目标函数】{function_name} 的当前源码：
```
{function_source}
```

【差异样本】（本地规则 vs DS 结果，表明该函数需要改进的地方）：
{samples}

【任务】
1. 分析差异样本，判断目标函数是否需要更新正则/逻辑。
2. 如果需要：输出 JSON 数组，包含**一条**变更对象：
   - function："{function_name}"
   - kind："update_regex"
   - old_regex：目标函数源码里现有正则的**精确子串**（含 / 分隔符和 flags，如 /foo/g）
   - new_regex：新正则（JS 格式，字面量内 / 必须转义为 \\/，lookahead 用 (?=...)）
   - py_regex：Python 格式正则（与 new_regex 对应，Python 不需要转义 /）
   - tests：2-3 个 {{input, expect_song, expect_artist}}（input 是完整评论行含时间戳）
   - protection：说明为何不会误伤 8.32/DISH//Don't say "lazy"/ryo(supercell) 等合法标题
3. 如果差异样本与目标函数无关或无需修改：输出空数组 []。
4. 只输出 JSON 数组，不要任何其他文字。"""


def load_diff_samples() -> list[dict]:
    path = REPO / "data" / "rule_diff_samples.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def call_ds_evolve(samples: list[dict]) -> list[dict]:
    """调用 DS 生成规则变更（单函数聚焦 + 重试）。

    关键设计：每次只让 DS 编辑**一个目标函数**（提供该函数完整源码 + 相关差异），
    避免多函数源码 + 多差异同时塞入导致 reasoning 消耗爆炸（max_output_tokens incomplete）。
    effort 用 low 保证稳定输出（high 的 reasoning 会把 token 吃满）。
    """
    import tomllib
    import urllib.request

    cfg = tomllib.loads(open(r"C:\Users\终焉\.codex\config.toml", encoding="utf-8").read())
    key = (cfg.get("model_providers") or {}).get("deepseek", {}).get("experimental_bearer_token") or ""

    # 允许编辑的规则函数（按顺序聚焦）
    editable = [
        "stripPerformanceNoteParens",
        "stripParentheticalTransliteration",
        "stripTrailingLatinAnnotationSuffix",
        "stripTrailingArtistNotes",
        "stripLeadingSongIndexMarker",
        "stripLeadingSerialMarker",
    ]
    all_changes: list[dict] = []
    funcs = extract_functions_map()
    for func_name in editable:
        func_src = funcs.get(func_name, "")
        if not func_src:
            print(f"[{func_name}] 未找到函数源码，跳过")
            continue
        # 聚焦该函数相关差异：removed/added 关键词能命中该函数语义的样本
        related = [s for s in samples if _sample_relates_to_function(s, func_name)]
        if not related:
            print(f"[{func_name}] 无相关差异样本，跳过")
            continue
        summary = "\n".join(
            f"## {s.get('bvid')} (local={s.get('local')} ds={s.get('ds')})\n"
            f"DS删: {json.dumps(s.get('ds_removed') or [], ensure_ascii=False)}\n"
            f"DS增: {json.dumps(s.get('ds_added') or [], ensure_ascii=False)}\n"
            f"原文: {json.dumps((s.get('source_lines') or [])[:4], ensure_ascii=False)}"
            for s in related[:5]
        )
        payload = {
            "model": "deepseek-v4-flash",
            "input": [
                {"role": "developer", "content": "你是 YouTube 歌枠评论清洗规则迭代工程师，输出严格 JSON。"},
                {"role": "user", "content": SINGLE_FUNC_PROMPT.format(
                    function_name=func_name, function_source=func_src, samples=summary
                )},
            ],
            "max_output_tokens": 32000,
            "temperature": 0,
            "reasoning": {"effort": "low"},
        }
        func_changes: list[dict] = []
        for attempt in range(3):
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/responses",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=420) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                print(f"[{func_name}] 尝试 {attempt + 1}/3 网络错误: {e}")
                continue
            if data.get("status") != "completed":
                print(f"[{func_name}] 尝试 {attempt + 1}/3 状态异常: {data.get('status')} {data.get('error')}")
                continue
            parts = []
            for item in data.get("output", []) or []:
                if item.get("type") == "message":
                    for c in item.get("content", []) or []:
                        if c.get("type") == "output_text" and c.get("text"):
                            parts.append(c["text"])
            text = "\n".join(parts).strip()
            m = re.search(r"\[[\s\S]*\]", text)
            if not m:
                print(f"[{func_name}] 尝试 {attempt + 1}/3 未输出 JSON 数组: {text[:150]}")
                continue
            try:
                func_changes = json.loads(m.group(0))
                print(f"[{func_name}] 尝试 {attempt + 1} 生成 {len(func_changes)} 条变更")
                break
            except json.JSONDecodeError as e:
                print(f"[{func_name}] 尝试 {attempt + 1}/3 JSON 解析失败: {e}")
                continue
        all_changes.extend(func_changes)
        # 每函数成功即落盘
        (REPO / "data" / "evolve_changes.json").write_text(
            json.dumps(all_changes, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[{func_name}] 累计 {len(all_changes)} 条变更（已落盘）")
    return all_changes


def _replace_in_function(src: str, func_name: str, old_regex: str, new_regex: str) -> str | None:
    """在指定函数体内替换 old_regex → new_regex。返回新源码；找不到返回 None。"""
    funcs = extract_functions_map()
    func_src = funcs.get(func_name)
    if not func_src or old_regex not in func_src:
        return None
    new_func_src = func_src.replace(old_regex, new_regex, 1)
    return src.replace(func_src, new_func_src, 1)


def apply_to_userjs(changes: list[dict]) -> list[str]:
    """应用变更到 user.js，返回操作日志。"""
    src = USERJS.read_text(encoding="utf-8")
    log = []
    for change in changes:
        func = change.get("function", "")
        kind = change.get("kind", "update_regex")
        if kind == "update_regex":
            old_regex = change.get("old_regex", "")
            new_regex = change.get("new_regex", "")
            if not old_regex or not new_regex:
                log.append(f"SKIP {func}: 缺 old/new regex")
                continue
            # 优先限定在目标函数体内替换（避免同正则多处出现）
            replaced = _replace_in_function(src, func, old_regex, new_regex)
            if replaced is not None:
                src = replaced
                log.append(f"OK {func}: regex 已更新（函数体内）")
                continue
            # 兜底：全局唯一匹配
            if old_regex not in src:
                log.append(f"SKIP {func}: old_regex 未找到")
                continue
            if src.count(old_regex) != 1:
                log.append(f"SKIP {func}: old_regex 出现 {src.count(old_regex)} 次且函数体内未命中")
                continue
            src = src.replace(old_regex, new_regex, 1)
            log.append(f"OK {func}: regex 已更新")
        elif kind == "insert_function":
            js_func = change.get("js_function", "")
            anchor = "  function cleanSongOrArtistPart(text) {"
            if anchor not in src:
                log.append(f"SKIP {func}: 锚点未找到")
                continue
            if f"function {func}(" in src:
                log.append(f"SKIP {func}: 函数已存在")
                continue
            src = src.replace(anchor, js_func.strip() + "\n\n" + anchor, 1)
            log.append(f"OK {func}: 函数已插入")
        else:
            log.append(f"SKIP {func}: 未知 kind={kind}")
    USERJS.write_text(src, encoding="utf-8")
    return log


def _normalize_py_regex(py_regex: str) -> str:
    """规范化 DS 输出的 Python 正则。

    处理两种 DS 输出瑕疵：
    1. r'...' / r"..." 前缀引号
    2. JSON 解码把 \b 变成退格符 \x08（恢复为 \\b）
    """
    value = (py_regex or "").strip()
    if len(value) >= 3 and value[0] in "rRbB" and value[1] in "'\"":
        quote = value[1]
        if value.endswith(quote) and len(value) >= 3:
            value = value[2:-1]
    # 恢复被 JSON 破坏的 \b 词边界
    value = value.replace("\x08", "\\b")
    return value


def apply_to_rules_py(changes: list[dict]) -> list[str]:
    """同步应用到 rules.py：就地更新现有正则常量（跨行定义也支持）。"""
    src = RULES_PY.read_text(encoding="utf-8")
    log = []
    for change in changes:
        func = change.get("function", "")
        py_regex = _normalize_py_regex(change.get("py_regex", ""))
        if not py_regex:
            continue
        # 函数 → Python 常量名映射（就地更新现有常量，而非追加新常量）
        const_map = {
            "stripPerformanceNoteParens": "PERFORMANCE_NOTE_PAREN_SUFFIX_RE",
            "stripParentheticalTransliteration": "TRANSLITERATION_PAREN_SUFFIX_RE",
            # 以下函数在 rules.py 无对应常量（属 clean.py 逻辑），Python 端跳过
            "stripTrailingLatinAnnotationSuffix": "",
            "stripTrailingArtistNotes": "",
            "stripLeadingSongIndexMarker": "",
            "stripLeadingSerialMarker": "",
        }
        const_name = const_map.get(func, "")
        if not const_name:
            log.append(f"SKIP {func}: 无 Python 常量映射")
            continue
        # 定位常量定义起点；paren_start 直接指向 re.compile( 末尾的 (
        start_marker = f"{const_name} = re.compile("
        idx = src.find(start_marker)
        if idx < 0:
            log.append(f"SKIP {func}: {const_name} 未找到")
            continue
        paren_start = idx + len(start_marker) - 1
        depth = 0
        in_str = False
        str_char = ""
        end = paren_start
        i = paren_start
        while i < len(src):
            ch = src[i]
            if in_str:
                if ch == "\\":
                    i += 2
                    continue
                if ch == str_char:
                    in_str = False
            else:
                if ch in "'\"":
                    in_str = True
                    str_char = ch
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            i += 1
        # 替换整段定义
        new_def = f"{const_name} = re.compile({py_regex!r})"
        src = src[:idx] + new_def + src[end:]
        log.append(f"OK {func}: {const_name} 已就地更新")
    RULES_PY.write_text(src, encoding="utf-8")
    return log


def append_tests(changes: list[dict]) -> None:
    """把 DS 提供的测试追加到 tests/test_rules.py。"""
    test_file = REPO / "tests" / "test_rules.py"
    existing = test_file.read_text(encoding="utf-8")
    # 确保导入 apply_song_cleanup
    if "from yt_comment_automation.rules import apply_song_cleanup" not in existing:
        existing = existing.replace(
            "from yt_comment_automation import rules",
            "from yt_comment_automation import rules\nfrom yt_comment_automation.rules import apply_song_cleanup",
            1,
        )
    added = 0
    for i, change in enumerate(changes):
        tests = change.get("tests") or []
        for j, t in enumerate(tests):
            inp = t.get("input", "")
            if not inp:
                continue
            func_name = f"ds_evolved_{i}_{j}"
            body = (
                f"\n\ndef test_{func_name}():\n"
                f"    parsed = apply_song_cleanup({inp!r})\n"
            )
            if t.get("expect_song"):
                body += f"    assert {t['expect_song']!r} in parsed\n"
            if t.get("expect_artist"):
                body += f"    assert {t['expect_artist']!r} in parsed\n"
            existing += body
            added += 1
    if added:
        test_file.write_text(existing, encoding="utf-8")


def validate() -> list[str]:
    """node --check user.js + pytest。返回错误列表。"""
    errors = []
    for js_path in (USERJS, PLUGIN_JS):
        r = subprocess.run(["node", "--check", str(js_path)], capture_output=True, text=True)
        if r.returncode != 0:
            errors.append(f"user.js 语法错误: {r.stderr[:400]}")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        errors.append(f"pytest 失败: {r.stdout[-800:]}")
    return errors


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="DS 自动规则进化")
    parser.add_argument("--samples", default="", help="差异样本 JSON 路径（默认 data/rule_diff_samples.json）")
    parser.add_argument("--changes", default="", help="直接加载已保存的变更 JSON（跳过 DS 调用）")
    parser.add_argument("--apply", action="store_true", help="应用变更到 user.js/rules.py（默认只生成预览不落盘）")
    args = parser.parse_args()

    if args.changes:
        changes = json.loads(Path(args.changes).read_text(encoding="utf-8"))
        print(f"加载已保存变更 {len(changes)} 条: {args.changes}")
    else:
        samples = load_diff_samples() if not args.samples else json.loads(Path(args.samples).read_text(encoding="utf-8"))
        if not samples:
            print("无差异样本")
            return 0
        print(f"差异样本 {len(samples)} 个，调用 DS 生成规则变更...")
        changes = call_ds_evolve(samples)
        print(f"DS 返回 {len(changes)} 条变更")

    if not args.apply:
        print(json.dumps(changes, ensure_ascii=False, indent=2)[:4000])
        print("\n(预览模式，未落盘。加 --apply 应用并验证)")
        return 0

    userjs_log = apply_to_userjs(changes)
    py_log = apply_to_rules_py(changes)
    append_tests(changes)
    for l in userjs_log + py_log:
        print(f"  {l}")

    errors = validate()
    if errors:
        # 回滚：git 恢复
        subprocess.run(["git", "checkout", "--", "userscript/youtube-comment-tools.user.js", "yt_comment_automation/rules.py", "tests/test_rules.py"], cwd=REPO)
        print("\n❌ 验证失败，已回滚：")
        for e in errors:
            print(f"  {e}")
        return 1

    print("\n✅ 验证通过（user.js 语法 OK + pytest 全绿）")
    print("下一步：人工 review diff 后 commit + push（WDC cron 自动拉取）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
