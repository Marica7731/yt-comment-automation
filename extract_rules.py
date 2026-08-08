"""DS 规则提炼：把本地规则与 DS 结果的差异样本交给 DeepSeek，提炼出结构化规则。

流程：
1. 读取 data/rule_diff_samples.json（本地结果 vs DS 结果差异 + 原文行）
2. 用 DeepSeek（reasoning high）分析差异模式，输出结构化 JSON 规则
3. 规则格式：
   {
     "version": 1,
     "rules": [
       {
         "category": "performance_note_cleanup",
         "description": "...",
         "trigger_patterns": ["（ちょっと）", "（少し）", ...],
         "action": "delete_from_song_title",
         "regex": "(?:ちょっと|少し|1番のみ|練習|うろ覚え)",
         "examples": [{"input": "...", "output": "..."}],
         "protection": ["Don't say \\"lazy\\""]
       }
     ]
   }
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yt_comment_automation import ai, config  # noqa: E402

RULE_PROMPT = """你是一个 YouTube 歌枠评论时间戳歌轴清洗规则的提炼专家。

下面是一批"本地规则结果 vs DeepSeek 结果"的差异样本。本地规则是确定性代码，
DeepSeek 是模型判断。你的任务：从这些差异中提炼出**可落地的确定性规则**，
让本地代码以后能自动处理这些情况。

【任务要求】
1. 逐类归纳差异背后的模式（例如：歌名末尾的（ちょっと）（少し）（1番のみ）（練習）（うろ覚え）
   是"只唱一部分"的表演备注应删除；〔1〕 这种序号前缀应剥离；罗马字括号注释应删除等）。
2. 每一类规则必须给出：
   - category：简短英文分类名
   - description：中文说明
   - action：delete_suffix / delete_prefix / normalize / keep（对输入做何种处理）
   - regex：可直接用于 JS/Python 的正则（注意 JS 与 Python 兼容，避免 \p 等差异语法）
   - examples：2-5 个 输入->输出 例子（来自样本）
   - protection：明确列出的"绝对不能误删"的合法情况（例如 Don't say "lazy" 的引号是歌名一部分、
     8.32 纯数字歌名、ryo(supercell) 括号是正式名、DISH// 双斜杠、ツインテールは20歳まで♡ 的 ♡ 是标题一部分）
3. 区分以下三种差异：
   a. 本地错、DS 对（本地该修没修）→ 提炼成新规则
   b. DS 错、本地对（DS 误伤）→ 提炼成保护规则（protection），明确本地不可动
   c. 两边都勉强（如全角数字 １・２・３ vs 1・2・3）→ 归为 normalize 规则
4. 只输出一个 JSON 对象，不要任何其他文字、代码块标记、说明。

差异样本：
{samples}"""


def load_samples(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_samples(samples: list[dict]) -> str:
    """压缩差异样本为紧凑文本，控制 token。"""
    lines = []
    for s in samples:
        lines.append(f"## {s['bvid']} (local={s['local']} ds={s['ds']})")
        if s.get("ds_removed"):
            lines.append(f"DS删: {json.dumps(s['ds_removed'], ensure_ascii=False)}")
        if s.get("ds_added"):
            lines.append(f"DS增: {json.dumps(s['ds_added'], ensure_ascii=False)}")
        src = s.get("source_lines") or []
        if src:
            lines.append(f"原文: {json.dumps(src[:6], ensure_ascii=False)}")
    return "\n".join(lines)


def extract_json(text: str) -> dict:
    """从 DS 输出中提取 JSON（容忍前后杂质）。"""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("DS 未输出 JSON")
    return json.loads(m.group(0))


def main():
    samples_path = Path("data/rule_diff_samples.json")
    samples = load_samples(samples_path)
    if not samples:
        print("无差异样本")
        return

    import tomllib
    import urllib.request

    cfg = tomllib.loads(open(config.get("CODEX_CONFIG", r"C:\Users\终焉\.codex\config.toml"), encoding="utf-8").read())
    key = (cfg.get("model_providers") or {}).get("deepseek", {}).get("experimental_bearer_token") or ""
    if not key:
        key = config.deepseek_api_key()
    if not key:
        print("无 DEEPSEEK_API_KEY")
        return

    batch_size = int(config.get("RULE_BATCH_SIZE", "9"))
    batches = [samples[i : i + batch_size] for i in range(0, len(samples), batch_size)]
    all_rules: dict = {"version": 1, "rules": [], "notes": []}
    for bi, batch in enumerate(batches, 1):
        summary = summarize_samples(batch)
        print(f"[批次 {bi}/{len(batches)}] 差异样本 {len(batch)} 个，输入约 {len(summary)} 字符")

        prompt = RULE_PROMPT.format(samples=summary)
        payload = {
            "model": "deepseek-v4-flash",
            "input": [
                {"role": "developer", "content": "你是 YouTube 歌枠评论清洗规则的提炼专家，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "max_output_tokens": 32000,
            "temperature": 0,
            "reasoning": {"effort": "high"},
        }
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=420) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("status") != "completed":
            print(f"[批次 {bi}] DS 状态异常: {data.get('status')} {data.get('error')}")
            all_rules["notes"].append({"batch": bi, "error": f"status={data.get('status')}"})
            continue
        parts = []
        for item in data.get("output", []) or []:
            if item.get("type") == "message":
                for c in item.get("content", []) or []:
                    if c.get("type") == "output_text" and c.get("text"):
                        parts.append(c["text"])
        text = "\n".join(parts).strip()
        print(f"[批次 {bi}] DS 输出 {len(text)} 字符")

        try:
            rules = extract_json(text)
        except Exception as e:  # noqa: BLE001
            print(f"[批次 {bi}] JSON 解析失败: {e}")
            all_rules["notes"].append({"batch": bi, "error": str(e), "raw": text[:500]})
            continue
        all_rules["rules"].extend(rules.get("rules", []))
        if rules.get("notes"):
            all_rules["notes"].extend(rules["notes"])

        out_path = Path("data/rules_from_ds.json")
        out_path.write_text(json.dumps(all_rules, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[批次 {bi}] 累计规则 {len(all_rules['rules'])} 条")

    out_path = Path("data/rules_from_ds.json")
    out_path.write_text(json.dumps(all_rules, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n最终规则已保存 -> {out_path} ({len(all_rules['rules'])} 条)")
    print(json.dumps(all_rules, ensure_ascii=False, indent=2)[:3000])


if __name__ == "__main__":
    main()
