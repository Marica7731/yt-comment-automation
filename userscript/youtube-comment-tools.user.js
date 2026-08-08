// ==UserScript==
// @name         YouTube 评论纯文本复制 + AI整理（括号保护 + 曲目数量校正版）
// @namespace    https://www.culua.com/
// @version      2.9.0
// @description  在 YouTube 每条评论右上角添加“复制 / AI整理 / 设置”按钮，复制按钮改为复制评论 HTML 方便排查，带完整调试日志，兼容 Trusted Types，并保护正式名称括号；兼容开闭幕类章节时间轴；重复时间轴结果自动合并；兼容“时间戳 + ;”占位行、编号曲目后置起止时间；修复多条相同歌单但时间不同被误去重；仅对含时间戳评论显示 AI整理并高亮，含时间戳评论会按时间戳数量前置排序；本地代码清洗结果直接外显可复制，AI整理作为手动兜底
// @author       ChatGPT
// @match        https://www.youtube.com/*
// @match        https://youtu.be/*
// @grant        GM_setClipboard
// @grant        GM_addStyle
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_xmlhttpRequest
// @connect      *
// @run-at       document-end
// @updateURL    https://next.ytb-song-rank.culua.com/userscript/youtube-comment-tools.user.js
// @downloadURL  https://next.ytb-song-rank.culua.com/userscript/youtube-comment-tools.user.js
// ==/UserScript==

(function () {
  'use strict';

  const DEBUG = true;
  const LOG_TAG = '[YT-COMMENT-AI-DEBUG]';

  const COPY_BTN_CLASS = 'yt-comment-copy-btn';
  const AI_BTN_CLASS = 'yt-comment-ai-btn';
  const SETTINGS_BTN_CLASS = 'yt-comment-ai-settings-btn';
  const LOCAL_PANEL_CLASS = 'yt-comment-local-result-panel';
  const LOCAL_COPY_BTN_CLASS = 'yt-comment-local-copy-btn';
  const HOST_CLASS = 'yt-comment-copy-host';
  const TIMESTAMP_COMMENT_CLASS = 'yt-comment-has-timestamp';
  const COMMENT_DEBUG_ATTR = 'data-yt-comment-tools-injected';

  const DEFAULT_API_BASE = 'https://api.openai.com/v1';
  const DEFAULT_MODEL = 'gpt-4.1-mini';

  const PROMPT_TEMPLATE = `你现在要根据我提供的一段 YouTube 评论区时间轴，整理出歌曲命名列表。

这是一个严格筛选任务。你的目标不是“尽量多提取”，而是“只保留可以明确判断为歌曲的条目”，宁可少收，也不要把杂谈、MC、感想、互动、开场、结束、企划说明、串场、聊天内容误判成歌曲。

你的工作流程必须严格分成 5 步，并且只能在内部完成，不能把过程写出来：
1. 先逐行筛选，删除所有非歌曲条目。
2. 再只保留同时拥有“歌名”和“歌手”的有效歌曲条目。
3. 如果原文中存在明确的曲目序号（如【1】、【2】、【3】……），则必须检查这些序号对应的行里，哪些是有效歌曲条目。
4. 再统计最终有效歌曲总数，决定编号位数。
5. 最后把所有保留下来的歌曲，统一重写成严格固定格式后再一次性输出。

注意：你不能边判断边随意输出。你必须先在内部整理好最终列表，再统一按格式输出。

【核心原则】
1. 只提取“明确是歌曲”的条目，按原出现顺序输出。
2. 每首歌必须同时出现“歌名”和“歌手”才算有效。
3. 不要联网，不要用外部知识补全，不要猜测，不要脑补，只能根据我提供的文本判断。
4. 如果判断不稳，可直接跳过，但不能把“本来结构完整的歌曲条目”误删。
5. 最终只输出结果列表，或在特殊情况时输出指定提示语；除此之外不能有任何说明。
6. 原文中的 /、／、|、｜、￤、∣、丨 等，都可能只是“歌名 / 歌手”的分隔符。识别时可以参考语境判断，但最终输出时一律必须改写为 歌名 - 歌手，禁止保留原分隔符。

【严格筛选规则】
只有同时满足下面条件的条目，才允许保留为歌曲：
1. 条目中明确出现歌名。
2. 条目中明确出现歌手。
3. 条目整体看起来是“歌曲标注”而不是聊天、备注、说明或感想。

以下内容一律视为非歌曲，直接跳过：
1. talk、雑談、MC、聊天、感想、开场、结束、结束挨拶、告知、企划说明、串场、休息、返场。
2. 只有时间戳，没有歌名歌手的行。
3. 只有歌名，没有歌手的行。
4. 只有歌手，没有歌名的行。
5. “下一首”“这首”“刚刚那首”“这段”“这里开始”“副歌”“清唱”“伴奏”“弹唱”“练习”“试唱”等描述性内容。
6. “谢谢收听”“感谢观看”“请订阅”“字幕”“评论”“备注”等说明性内容。
7. 不完整、残缺、歧义很大、无法确认是歌曲列表格式的条目。
8. 看起来更像话题、段子、互动内容，而不是“歌名 - 歌手”信息的条目。

【曲目序号对应规则】
1. 如果原文中存在明确曲目序号，例如：
   - 【1】……
   - 【2】……
   - 【3】……
   或其他明显表示“第几首”的编号形式，
   那么这些序号可以用于检查曲目数量是否完整。
2. 如果某个带序号的条目本身已经明确具备“歌名 + 歌手”的完整结构，那么它必须被保留，不能随意漏掉。
3. 如果原文中存在 21 条带曲目序号且内容完整的歌曲条目，则最终结果也必须对应 21 首，不能只输出 20 首。
4. 不要因为歌名很短、像编号、像代号、像纯数字，就把带序号的完整歌曲条目误删。
5. 判断是否保留时，要优先看整条内容是否完整，而不是只看歌名外观。
6. 如果原文带有明确的曲目序号，并且这些序号对应的是有效歌曲条目，则最终结果应与这些有效序号条目一一对应。

【纯数字歌名保护规则】
1. 歌名可能是纯数字，这种情况不能因为歌名是数字就判定为无效。
2. 只要某一行整体仍然明显符合“歌名 / 歌手”或“歌名 - 歌手”的歌曲列表格式，就算歌名是纯数字，也必须保留。
3. 例如以下都应视为有效歌曲条目，而不是编号、楼层、时间或杂项：
   - 441/miwa
   - 366日/HY
   - 3月9日/レミオロメン
4. 不要因为歌名短、像编号、像数字代号，就把它当成歧义条目删除。
5. 判断一行是否有效时，要优先看整行是否具备“歌名 + 歌手”的完整结构，而不是只看歌名外观。

【括号内容处理规则】
1. 只有当括号内容明显属于罗马字、英文对照、读音、注音、翻译说明时，才删除这些括号内容。
2. 如果括号是名称主体的一部分，则必须保留，不能删除。
3. 判断时优先看括号前的写法：
   - 如果是“名称 + 空格 + (说明)”这种形式，通常括号属于注音或说明，可以删除。
   - 如果是“名称(括号内容)”这种紧贴写法，且整体本来就像正式名称的一部分，则必须保留。
4. 不要因为出现括号就把整条歌曲删掉。
5. 日文或正式名中的括号归属信息通常需要保留，例如：
   - ryo(supercell)
   - 久住小春（モーニング娘。）
6. 示例：
   - Plazma / 米津玄師 (Kenshi Yonezu)
     应输出：Plazma - 米津玄師
   - Os-宇宙人 (Os-uchujin) / エリオをかまってちゃん (Erio wo Kamatte-chan)
     应输出：Os-宇宙人 - エリオをかまってちゃん
   - 星が瞬くこんな夜に (Hoshi ga Matataku Konna Yoru ni) / ryo(supercell)
     应输出：星が瞬くこんな夜に - ryo(supercell)
   - バラライカ / 月島きらり starring 久住小春（モーニング娘。）
     应输出：バラライカ - 月島きらり starring 久住小春（モーニング娘。）

7. 如果歌手字段或歌名字段本身以 ） 或 ) 结尾，且前面存在正常正文内容，则该括号通常属于正式名称的一部分，必须保留，不能因为它出现在字段末尾就删除。
8. 歌名本身也可能包含 / 或 ／，只要它属于正式歌名的一部分，就必须保留，不能错误拆成两首歌或把它当成歌名与歌手的分隔符。
9. 正式歌名中的省略号、引号、感叹号等标点也必须保留，例如：
   - God knows...
   - Don't say "lazy"
   - ハロ／ハワユ
10. 如果只有极少数歌曲标题带有括号补充，例如：
   - さくら(独唱)
   这类括号内容通常更可能是标题本体的一部分，应优先保留；不要因为看起来像说明就随意删除。

【分隔符统一规则】
1. 原文中歌名与歌手之间，可能使用 /、／、|、｜、￤、∣、丨 等符号分隔，也可能出现全角半角混用。
2. 这些符号在识别时都只能视为“歌名和歌手的分隔符候选”，不得原样保留到最终输出。
3. 最终输出时，歌名与歌手之间只能使用半角连字符 -，并且左右各保留一个半角空格，格式必须是：
歌名 - 歌手
4. 禁止在最终结果中使用 /、／、|、｜、￤、∣、丨 作为歌名和歌手之间的分隔符。
5. 即使原文写的是：
嘘￤シド
フォニイ / ツミキ
ノーダウト｜Official髭男dism
最终也必须输出为：
嘘 - シド
フォニイ - ツミキ
ノーダウト - Official髭男dism

【缺少歌手时的处理规则】
1. 如果整份列表里的条目全都没有歌手信息，不要整理结果，直接输出：
请提供歌手信息后再处理。
2. 如果只有少数一两条没有歌手，而其他大多数条目都有完整的歌名和歌手，说明这些缺歌手的条目不是有效歌曲，直接跳过，不要输出，不要解释。

【格式优先级规则】
1. 最终输出时，格式要求与筛选要求同等重要，不能只保证内容正确而忽略格式。
2. 如果某一行无法同时满足“编号 + 句点 + 空格 + 歌名 + 空格-空格 + 歌手”的完整格式，则该行宁可删除，也不能以不完整格式输出。
3. 禁止输出没有编号的行。
4. 禁止输出没有句点 . 的编号。
5. 禁止输出没有 - 的歌曲行。
6. 禁止输出项目符号、破折号列表、自然语言列表、无编号列表。
7. 禁止把多首歌写在同一行。
8. 禁止省略编号中的 .
9. 禁止把 - 替换成其他符号，例如 —、–、−、~、～、/、|、￤。
10. 禁止使用 01)、01、、01：、01- 这种编号形式；只能使用 01. 或 001.。
11. 编号、句点、空格、歌名、空格、连字符、空格、歌手，这 8 个部分缺一不可。

【编号规则】
1. 你必须先在内部统计最终有效歌曲总数，再决定编号格式。
2. 如果最终有效歌曲总数是 1 到 99 首，所有行都必须使用两位编号：
01.
02.
03.
……
09.
10.
11.
3. 如果最终有效歌曲总数是 100 到 999 首，所有行都必须使用三位编号：
001.
002.
003.
……
010.
011.
100.
4. 编号必须从 01 或 001 开始，连续递增。
5. 禁止跳号。
6. 禁止重复编号。
7. 禁止从 00 开始。
8. 禁止混用两位编号和三位编号。
9. 一旦决定编号位数，整份输出必须统一。

【歌手敬语处理规则】
1. 如果原文里绝大多数歌曲行的歌手字段都统一带有敬语后缀，例如：さん、様、氏，则这通常只是列表书写习惯，不属于歌手正式名称的一部分。
2. 在这种“多数统一带敬语”的情况下，最终输出时应去掉这些敬语后缀，只保留歌手本名。
3. 如果只有一两条零星出现敬语，而其他大多数歌手字段都没有敬语，则不要把它当成统一格式；这类零星出现的内容更可能是歌手名的一部分或原文特殊写法，应保留。
4. 只有在“多数条目统一带敬语”的前提下，才允许批量去掉歌手后的敬语。

【输出格式要求】
1. 每行一首。
2. 格式必须严格为：
编号. 空格歌名 空格- 空格歌手
3. 这里的 编号、.、空格、- 都必须真实输出，不能省略。
4. . 必须是半角句点。
5. - 必须是半角连字符。
6. - 左右必须各有一个半角空格。
7. 除结果列表外，不能输出任何其他内容。
8. 不能输出标题、前言、说明、备注、总结、提示、空行、代码块标记。
9. 最终答案中的每一行都必须是完整结果行，不允许出现解释行。
10. 最终答案必须是纯列表，不能出现任何列表之外的文字。

【标准模板】
当最终有效歌曲总数为 1 到 99 首时，每一行都必须长成这样：
01. 歌名 - 歌手
02. 歌名 - 歌手
03. 歌名 - 歌手

当最终有效歌曲总数为 100 到 999 首时，每一行都必须长成这样：
001. 歌名 - 歌手
002. 歌名 - 歌手
003. 歌名 - 歌手

【禁止行为】
1. 禁止根据常识补歌手。
2. 禁止根据歌名联想歌手。
3. 禁止把“像是歌曲”的条目强行算进结果。
4. 禁止输出时间戳。
5. 禁止输出文件名。
6. 禁止输出括号补充、备注、来源、分析、解释、标题、前言、后记。
7. 禁止把非歌曲条目凑数进列表。
8. 禁止输出“以下是整理结果”“整理如下”“共 X 首”等说明文字。
9. 禁止输出代码块标记。
10. 禁止输出空白行。
11. 禁止输出任何不符合模板的行。

【输出前强制自检】
在真正输出之前，你必须逐项检查；只要有一项不满足，就继续修改，直到完全满足后才能输出：
1. 是否已经先完成筛选，再完成编号，而不是边想边输出？
2. 是否所有非歌曲条目都已删除？
3. 是否每一行都同时包含歌名和歌手？
4. 是否任何一行都没有时间戳？
5. 是否任何一行都没有说明性文字？
6. 是否任何一行都没有保留 /、／、|、｜、￤、∣、丨 作为歌名歌手分隔符？
7. 是否每一行都严格包含编号、半角句点 .、一个空格、歌名、空格、半角连字符 -、空格、歌手？
8. 是否没有任何一行漏掉编号？
9. 是否没有任何一行漏掉句点 .？
10. 是否没有任何一行漏掉 -？
11. 是否所有编号都从 01 或 001 开始连续递增？
12. 是否整份输出统一使用两位编号或统一使用三位编号？
13. 是否最终答案除了结果列表外没有任何别的字？
14. 如果原文中存在明确曲目序号，是否已经检查所有有效曲目序号条目都被一一对应保留？
15. 是否有任何一行因为“歌名是纯数字或数字较短”而被误删？如果该行仍然具备完整的歌名和歌手结构，则必须恢复输出。

【特殊情况】
1. 如果整份列表里的条目全都没有歌手信息，只能输出：
请提供歌手信息后再处理。

下面是要整理的时间轴：`;

  const AI_CLEAN_PROMPT_TEMPLATE = `你现在要把我提供的 YouTube 评论区时间轴清理成歌曲列表。

这是“清脏”任务，不是改写任务。你只能根据原文整理格式，不能根据常识补全、纠错、翻译、罗马字化、换歌手、换歌名，也不能把简称改成正式名。

【必须保留】
1. 歌名和歌手的原始文字、大小写、标点、假名、汉字、空格习惯必须尽量按原文保留。
2. 正式名称里的符号必须保留，例如 DISH//、Don't say "lazy"、God knows...、1/2、ハロ／ハワユ、ryo(supercell)、May'n。
3. 如果歌手本身包含 feat.、ft.、with、/、・、,、&、括号内正式成员信息，要保留。

【必须删除】
1. 所有时间戳、曲顺号、项目符号、标题行、OP、start、ED、MC、talk、告知、スパチャ読み、说明、链接、感谢语。
2. 歌名或歌手后面的罗马字、英文翻译、读音、释义、发行日期、挑战/初披露/途中まで等表演备注。
3. 这些脏注释常见于半角或全角括号/方括号中，例如：
   六等星[Rokutōsei] / ざらめ -> 六等星 - ざらめ
   花に亡霊[Ghost In A Flower] / ヨルシカ -> 花に亡霊 - ヨルシカ
   君はロックを聴かない (Kimi wa Rock wo Kikanai / You don't listen "Rock" music.) / あいみょん -> 君はロックを聴かない - あいみょん
   橋本潮 (Ushio Hashimono) -> 橋本潮
   Aimer (2019/05/05) -> Aimer
4. 如果括号内容是正式名称的一部分，不要删除，例如 ryo(supercell)、ナノウ(ほえほえP)、涼宮ハルヒ(平野綾)。

【筛选】
1. 只保留同时有歌名和歌手的歌曲行。
2. 没有歌手的行直接跳过；整份都没有歌手时，只输出：请提供歌手信息后再处理。
3. 不要把聊天、开场、结束、告知、链接、感想、章节说明当作歌曲。

【输出格式】
1. 只输出结果列表，不要标题、说明、代码块、空行。
2. 每行格式必须是：编号. 歌名 - 歌手
3. 1 到 99 首使用两位编号 01.；100 首以上使用三位编号 001.。
4. 分隔符只能使用半角 " - "，不要保留 /、//、／、｜ 作为歌名和歌手之间的分隔符。

【树形 Setlist 兼容】
如果原文是下面这种结构：
1
4:18~
7:37
├ 歌名 / 歌手
└ (罗马字或英文说明)
则只取“├/└ 后面含 歌名 / 歌手 的那一行”，使用开始时间 4:18，跳过结束时间、编号行和罗马字/英文说明行。

下面是要清理的时间轴：`;

  const AI_DIRECT_PROMPT_TEMPLATE = `你现在要直接根据我提供的 YouTube 评论区时间轴整理歌曲列表。

这是兜底整理任务。你必须直接阅读原文，不要参考任何脚本清洗结果。

【硬性要求】
1. 每一首必须同时有歌名和歌手。没有歌手的行必须跳过，不能猜、不能补、不能联网。
2. 不要把 OP、start、ED、MC、talk、告知、スパチャ読み、链接、感谢语、章节说明、聊天内容当成歌曲。
3. 只能删除脏信息，不能改写正式歌名或歌手名，不能翻译、罗马字化、纠错、替换成常识里的名字。
4. 必须删除歌名或歌手后的英文/罗马字/翻译/读音/发行日期/表演备注，例如：
   六等星[Rokutōsei] / ざらめ -> 六等星 - ざらめ
   若者のすべて[Wakamono no subete] / フジファブリック -> 若者のすべて - フジファブリック
   君はロックを聴かない (Kimi wa Rock wo Kikanai / You don't listen "Rock" music.) / あいみょん -> 君はロックを聴かない - あいみょん
   水星 / tofubeats feat.オノマトペ大臣 (tofubeats feat. Kariya Seira) -> 水星 - tofubeats feat.オノマトペ大臣
5. 如果括号是正式名称的一部分，必须保留，例如 ryo(supercell)、ナノウ(ほえほえP)、涼宮ハルヒ(平野綾)、DISH//、Don't say "lazy"、God knows...、1/2。

【输出格式】
1. 只输出最终歌曲列表，不要标题、说明、代码块、空行。
2. 每行格式必须严格为：编号. 歌名 - 歌手
3. 1 到 99 首使用两位编号；100 首以上使用三位编号。
4. 歌名和歌手之间只能使用半角 " - "。
5. 最终列表里不能出现没有歌手的行。

如果整份文本没有任何“歌名 + 歌手”的歌曲，只输出：
请提供歌手信息后再处理。

【树形 Setlist 兼容】
如果原文是下面这种结构：
1
4:18~
7:37
├ 歌名 / 歌手
└ (罗马字或英文说明)
则只取“├/└ 后面含 歌名 / 歌手 的那一行”，使用开始时间 4:18，跳过结束时间、编号行和罗马字/英文说明行。

下面是原文时间轴：`;

  function log(...args) {
    if (DEBUG) console.log(LOG_TAG, ...args);
  }

  function warn(...args) {
    if (DEBUG) console.warn(LOG_TAG, ...args);
  }

  function error(...args) {
    if (DEBUG) console.error(LOG_TAG, ...args);
  }

  function group(label, fn) {
    if (!DEBUG) {
      fn();
      return;
    }
    console.groupCollapsed(`${LOG_TAG} ${label}`);
    try {
      fn();
    } finally {
      console.groupEnd();
    }
  }

  function shortNode(node) {
    if (!node || !(node instanceof Element)) return String(node);
    const id = node.id ? `#${node.id}` : '';
    const cls = node.className && typeof node.className === 'string'
      ? '.' + node.className.trim().split(/\s+/).slice(0, 2).join('.')
      : '';
    return `${node.tagName.toLowerCase()}${id}${cls}`;
  }

  function normalizeText(text) {
    return (text || '')
      .replace(/\r\n/g, '\n')
      .replace(/\r/g, '\n')
      .replace(/\u00A0/g, ' ')
      .replace(/\u200B/g, '')
      .split('\n')
      .map(line => line.replace(/[ \t]+/g, ' ').trim())
      .filter(line => line.length > 0)
      .join('\n')
      .trim();
  }

  function normalizeTimelineMarkerChars(text) {
    return (text || '')
      .replace(/[０-９]/g, ch => String(ch.charCodeAt(0) - 0xFF10))
      .replace(/：/g, ':')
      .replace(/．/g, '.')
      .replace(/＃/g, '#');
  }

  function timestampToSeconds(timestamp) {
    const parts = normalizeTimelineMarkerChars(String(timestamp || '')).split(':').map(part => Number(part));
    if (parts.length < 2 || parts.length > 3 || parts.some(part => !Number.isFinite(part))) return null;

    const seconds = parts[parts.length - 1];
    const minutes = parts[parts.length - 2];
    const hours = parts.length === 3 ? parts[0] : 0;

    if (seconds < 0 || seconds >= 60 || minutes < 0 || minutes >= 60 || hours < 0) return null;
    return hours * 3600 + minutes * 60 + seconds;
  }


  function findTimestampStartPositionsInLine(line) {
    const source = normalizeTimelineMarkerChars(line || '');
    const positions = [];
    const regex = /(^|[^\d])((?:[\[【(（]\s*)?\d{1,2}:\d{2}(?::\d{2})?(?:\s*[\]】)）])?)(?!\d)/g;
    let match;

    while ((match = regex.exec(source))) {
      const rawTimestamp = (match[2] || '').replace(/^[\[【(（]\s*/u, '').replace(/\s*[\]】)）]$/u, '');
      if (timestampToSeconds(rawTimestamp) === null) continue;

      const index = match.index + (match[1] ? match[1].length : 0);
      if (index > 0 && /\d/.test(source[index - 1] || '')) continue;
      positions.push(index);
    }

    return Array.from(new Set(positions)).sort((a, b) => a - b);
  }

  function shouldKeepInlineSetlistRangeLineBeforeSplit(line) {
    const source = normalizeTimelineMarkerChars(line || '').trim();
    if (!source) return false;

    // 兼容同一行起止时间 + 歌曲信息：
    // 1曲目 38:12~43:24「ガーネット／奥華子」
    // 这类行不能被拆成 38:12~ 和 43:24「...」，否则会误取结束时间。
    return /^第?\s*\d{1,3}\s*(?:曲目|曲)\s*[：:\s\u3000]*\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜\-－—–−]\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?:[「『｢《〈【]|[\s\S]*[\/／|｜￤∣丨])[\s\S]+$/u.test(source);
  }

  function splitCollapsedTimelineLine(line) {
    const source = normalizeTimelineMarkerChars(line || '').trim();
    if (!source) return [];

    if (shouldKeepInlineSetlistRangeLineBeforeSplit(source)) return [source];

    const positions = findTimestampStartPositionsInLine(source);
    if (positions.length <= 1) return [source];

    const result = [];

    if (positions[0] > 0) {
      const prefix = source.slice(0, positions[0]).trim();
      if (prefix) result.push(prefix);
    }

    for (let i = 0; i < positions.length; i += 1) {
      const start = positions[i];
      const end = positions[i + 1] ?? source.length;
      const chunk = source.slice(start, end).trim();
      if (chunk) result.push(chunk);
    }

    return result;
  }

  function splitCollapsedTimelineLines(text) {
    const normalized = normalizeText(text);
    if (!normalized) return [];

    const lines = [];
    normalized.split('\n').forEach(line => {
      splitCollapsedTimelineLine(line).forEach(part => {
        const value = part.trim();
        if (value) lines.push(value);
      });
    });

    return lines;
  }

  function splitCollapsedTimelineText(text) {
    return splitCollapsedTimelineLines(text).join('\n');
  }

  function extractFirstTimestampInfo(text) {
    const normalized = normalizeTimelineMarkerChars(text || '');
    const match = normalized.match(/\d{1,2}:\d{2}(?::\d{2})?/);
    if (!match) return { label: '', seconds: null };

    const seconds = timestampToSeconds(match[0]);
    if (seconds === null) return { label: '', seconds: null };

    return {
      label: match[0],
      seconds
    };
  }

  function extractFirstTimestampSeconds(text) {
    return extractFirstTimestampInfo(text).seconds;
  }

  function extractTimelineTimestamps(text) {
    const normalized = normalizeText(text);
    if (!normalized) return [];

    const seen = new Set();
    const result = [];
    const regex = /(^|[^\d])(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)/g;
    let match;

    while ((match = regex.exec(normalized))) {
      const label = match[2];
      const seconds = timestampToSeconds(label);
      if (seconds === null || seen.has(label)) continue;
      seen.add(label);
      result.push({ label, seconds });
    }

    return result;
  }

  function hasTimelineTimestamp(text) {
    return extractTimelineTimestamps(text).length > 0;
  }

  function containsJapanese(text) {
    return /[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(text || '');
  }

  function containsLatin(text) {
    return /[A-Za-z]/.test(text || '');
  }

  function looksLikeMusicQualifier(text) {
    return /\b(feat\.?|ft\.?|ver\.?|version|mix|remix|edit|size|inst(?:rumental)?|off\s*vocal|live|solo|duet|acoustic|arrange|cover|chorus|short|full|tv|anime|movie|op|ed|from|single|album|demo|self[\s-]?cover|piano|guitar)\b/i.test(text || '');
  }

  function looksLikeLatinAnnotation(text) {
    if (!text) return false;
    const t = text.trim();

    if (!containsLatin(t)) return false;
    if (containsJapanese(t)) return false;
    if (!/^[A-Za-zÀ-ÖØ-öø-ÿ\u0100-\u024F0-9 .,:'’"“”&+_\-\/!?~～()[\]（）［］#＃♯♭★☆♪♫♡♥◎・･=×∞]+$/.test(t)) return false;

    return true;
  }

  function looksLikeRomanizationOrTranslation(text) {
    if (!text) return false;
    const t = text.trim();

    if (!looksLikeLatinAnnotation(t)) return false;
    if (looksLikeMusicQualifier(t)) return false;

    return true;
  }

  function stripTransliterationParensFromLine(line) {
    if (!line) return line;

    return line.replace(/([ \t\u3000]+)([\(（])([^()（）]{1,80})([\)）])/g, (match, leading, open, inner, close) => {
      const content = (inner || '').trim();

      if (looksLikeRomanizationOrTranslation(content)) {
        log('删除译文/罗马字括号', {
          original: line,
          removed: `${open}${content}${close}`
        });
        return '';
      }

      if (looksLikeMusicQualifier(content)) {
        log('保留音乐信息括号', {
          original: line,
          kept: `${open}${content}${close}`
        });
        return match;
      }

      log('保留括号', {
        original: line,
        kept: `${open}${content}${close}`
      });
      return match;
    });
  }

  function preprocessTimelineTextForAI(text) {
    const normalized = normalizeText(text);
    if (!normalized) return normalized;

    const lines = normalized.split('\n');
    const processedLines = lines.map(line => stripTrailingLatinAnnotationSuffix(stripTransliterationParensFromLine(line)));
    const result = processedLines.join('\n').trim();

    group('预处理 AI 输入文本', () => {
      log('原始长度', normalized.length);
      log('处理后长度', result.length);
      log('处理后预览', result.slice(0, 400));
    });

    return result;
  }

  function copyPlainText(text) {
    return new Promise((resolve, reject) => {
      if (!text) {
        reject(new Error('空内容'));
        return;
      }

      try {
        if (typeof GM_setClipboard === 'function') {
          GM_setClipboard(text, 'text');
          log('GM_setClipboard 复制成功', { length: text.length });
          resolve();
          return;
        }
      } catch (err) {
        error('GM_setClipboard 失败', err);
      }

      navigator.clipboard.writeText(text)
        .then(() => {
          log('navigator.clipboard 复制成功', { length: text.length });
          resolve();
        })
        .catch((err) => {
          error('navigator.clipboard 失败', err);
          reject(err);
        });
    });
  }

  function flashButton(button, text, success) {
    if (!button) return;

    const oldText = button.dataset.oldText || button.textContent || '';
    button.textContent = text;
    button.dataset.success = success ? '1' : '0';

    clearTimeout(button._resetTimer);
    button._resetTimer = setTimeout(() => {
      button.textContent = oldText;
      button.dataset.success = '';
    }, 1200);
  }

  function setLoadingButton(button, loading, loadingText = '处理中...') {
    if (!button) return;

    if (loading) {
      if (!button.dataset.oldText) {
        button.dataset.oldText = button.textContent;
      }
      button.textContent = loadingText;
      button.disabled = true;
    } else {
      button.textContent = button.dataset.oldText || 'AI整理';
      button.disabled = false;
    }
  }

  function getConfig() {
    const config = {
      apiBase: GM_getValue('yt_ai_api_base', DEFAULT_API_BASE),
      model: GM_getValue('yt_ai_model', DEFAULT_MODEL),
      apiKey: GM_getValue('yt_ai_api_key', '')
    };
    log('读取设置', {
      apiBase: config.apiBase,
      model: config.model,
      hasApiKey: Boolean(config.apiKey)
    });
    return config;
  }

  function saveConfig(config) {
    GM_setValue('yt_ai_api_base', config.apiBase || DEFAULT_API_BASE);
    GM_setValue('yt_ai_model', config.model || DEFAULT_MODEL);
    GM_setValue('yt_ai_api_key', config.apiKey || '');
    log('保存设置', {
      apiBase: config.apiBase || DEFAULT_API_BASE,
      model: config.model || DEFAULT_MODEL,
      hasApiKey: Boolean(config.apiKey)
    });
  }

  function buildUserInput(commentText, promptTemplate = AI_CLEAN_PROMPT_TEMPLATE) {
    const payload = `${promptTemplate || AI_CLEAN_PROMPT_TEMPLATE}\n${commentText}`;
    log('构造 AI 输入', {
      inputLength: payload.length,
      commentLength: commentText.length
    });
    return payload;
  }

  function parseOpenAIStyleResponse(json) {
    if (!json) return '';

    if (json.choices && json.choices[0]) {
      const choice = json.choices[0];

      if (choice.message && typeof choice.message.content === 'string') {
        return choice.message.content.trim();
      }

      if (Array.isArray(choice.message?.content)) {
        return choice.message.content
          .map(part => {
            if (typeof part === 'string') return part;
            if (part && typeof part.text === 'string') return part.text;
            return '';
          })
          .join('\n')
          .trim();
      }

      if (typeof choice.text === 'string') {
        return choice.text.trim();
      }
    }

    if (typeof json.output_text === 'string') {
      return json.output_text.trim();
    }

    if (Array.isArray(json.output)) {
      const texts = [];
      for (const item of json.output) {
        if (Array.isArray(item.content)) {
          for (const c of item.content) {
            if (c && typeof c.text === 'string') {
              texts.push(c.text);
            }
          }
        }
      }
      return texts.join('\n').trim();
    }

    return '';
  }

  function isSpecialNoArtistResponse(text) {
    const normalized = normalizeText(text).replace(/\s+/g, '');
    return normalized === '请提供歌手信息后再处理。'.replace(/\s+/g, '');
  }

  function stripLeadingSongIndexMarker(text) {
    const t = (text || '').trim();
    if (!t) return t;

    const plainNumberWithHyphen = t.replace(/^\d{1,3}\s*[\-—–−]\s*/u, '').trim();
    if (plainNumberWithHyphen !== t) return plainNumberWithHyphen;

    const withSeparator = t.replace(/^[#＃]\s*\d{1,3}\s*[.)．。、:：\-—–−]\s*/u, '').trim();
    if (withSeparator !== t) return withSeparator;

    return t.replace(/^[#＃]\s*\d{1,3}[\s\u3000]+/u, '').trim();
  }

  function stripLeadingSongContextMarker(text) {
    return (text || '')
      .replace(/^(?:encore|アンコール)[\s\u3000]+/iu, '')
      .trim();
  }

  function findTrailingBracketSuffix(text) {
    const raw = (text || '').trim();
    if (!raw) return null;

    const closeToOpen = {
      ')': '(',
      '）': '（',
      ']': '[',
      '］': '［'
    };
    const close = raw[raw.length - 1];
    const open = closeToOpen[close];
    if (!open) return null;

    let depth = 0;

    for (let i = raw.length - 1; i >= 0; i -= 1) {
      const ch = raw[i];

      if (ch === close) {
        depth += 1;
        continue;
      }

      if (ch !== open) continue;

      depth -= 1;
      if (depth !== 0) continue;

      if (!isWhitespaceChar(raw[i - 1])) return null;

      return {
        before: raw.slice(0, i).trim(),
        content: raw.slice(i + 1, raw.length - 1).trim(),
        removed: raw.slice(i).trim()
      };
    }

    return null;
  }

  function normalizeDuplicateAnnotationComparable(text) {
    return (text || '')
      .normalize('NFKC')
      .replace(/[“”‘’"'`]/g, '')
      .replace(/[\s\u3000]+/g, '')
      .replace(/[.．。｡、,，:：;；!！?？~～\-—–−_/／|｜￤∣丨]+/g, '')
      .trim()
      .toLowerCase();
  }

  function isDuplicateBracketAnnotation(before, content) {
    const left = normalizeDuplicateAnnotationComparable(before);
    const right = normalizeDuplicateAnnotationComparable(content);
    if (!left || !right) return false;
    return left === right;
  }

  function stripTrailingLatinAnnotationSuffix(text) {
    const raw = (text || '').trim();
    if (!raw) return raw;

    const trailing = findTrailingBracketSuffix(raw);
    if (trailing && trailing.before && isDuplicateBracketAnnotation(trailing.before, trailing.content)) {
      log('删除字段末尾重复括号注释', {
        original: raw,
        removed: trailing.removed
      });
      return trailing.before;
    }

    if (trailing && trailing.before && containsJapanese(trailing.before) && looksLikeLatinAnnotation(trailing.content)) {
      log('删除字段末尾英文/罗马字注释', {
        original: raw,
        removed: trailing.removed
      });
      return trailing.before;
    }

    const tightTrailing = raw.match(/([\(（\[［])([^()（）\[\]［］]{1,120})([\)）\]］])\s*$/u);
    if (tightTrailing) {
      const open = tightTrailing[1];
      const close = tightTrailing[3];
      const matchingClose = {
        '(': ')',
        '（': '）',
        '[': ']',
        '［': '］'
      };
      const before = raw.slice(0, tightTrailing.index).trim();
      const content = (tightTrailing[2] || '').trim();

      if (matchingClose[open] === close && before && isDuplicateBracketAnnotation(before, content)) {
        log('删除字段末尾紧贴重复括号注释', {
          original: raw,
          removed: tightTrailing[0].trim()
        });
        return before;
      }

      if (matchingClose[open] === close && before && containsJapanese(before) && looksLikeLatinAnnotation(content)) {
        log('删除字段末尾紧贴英文/罗马字注释', {
          original: raw,
          removed: tightTrailing[0].trim()
        });
        return before;
      }
    }

    return raw.replace(/([ \t\u3000]+)([\(（\[［])([^()（）\[\]［］]{1,120})([\)）\]］])\s*$/u, (match, leading, open, inner, close, offset, fullText) => {
      const matchingClose = {
        '(': ')',
        '（': '）',
        '[': ']',
        '［': '］'
      };
      const before = fullText.slice(0, offset).trim();
      const content = (inner || '').trim();

      if (matchingClose[open] !== close) {
        return match;
      }

      if (before && isDuplicateBracketAnnotation(before, content)) {
        log('删除字段末尾重复括号注释', {
          original: raw,
          removed: `${open}${content}${close}`
        });
        return '';
      }

      if (before && containsJapanese(before) && looksLikeLatinAnnotation(content)) {
        log('删除字段末尾英文/罗马字注释', {
          original: raw,
          removed: `${open}${content}${close}`
        });
        return '';
      }

      return match;
    }).trim();
  }

  function stripLooseEdgeTitleQuotes(text) {
    let t = (text || '').trim();

    for (let i = 0; i < 3; i += 1) {
      const next = t
        .replace(/^[「『｢《〈【]+/u, '')
        .replace(/[」』｣》〉】]+$/u, '')
        .trim();

      if (next === t) break;
      t = next;
    }

    return t;
  }

  // RULES.md R09：受保护正式标题符号（任何清洗步骤不可剥离）
  function hasProtectedTitle(text) {
    return /DISH\/\/|Don't say "lazy"|God knows\.\.\.|ハロ／ハワユ|ryo\(supercell\)|ナノウ\(ほえほえP\)|ツインテールは20歳まで♡/.test(text || '');
  }

  // RULES.md R07：删除歌名末尾"只唱一部分"表演备注括号（（少し）（ちょっと）（1番のみ）（練習）（うろ覚え）等）
  function stripPerformanceNoteParens(text) {
    return (text || '').replace(/\s*[（(](?:少し|ちょっと|うろ覚え|練習|[0-9０-９]+番のみ|short\.?|ワンコーラス|途中まで)[）)]\s*(?=/|$)/u, '');
  }

  // RULES.md R06：删除歌名末尾含空格或 | 的罗马字/译文括号（保护 ryo(supercell)）
  function stripParentheticalTransliteration(text) {
    return (text || '').replace(/\s*[(（][^)）]*(?:\s|\|)[^)）]*[)）]\s*(?=/|$)/u, '').trim();
  }

  function cleanSongOrArtistPart(text) {
    const raw = (text || '').trim();
    // R09：受保护正式标题直接返回
    if (hasProtectedTitle(raw)) return raw;

    let t = stripPerformanceNoteParens(raw);
    t = stripParentheticalTransliteration(t);
    t = stripTransliterationParensFromLine(t).trim();
    t = stripTimelineTreePrefix(t);
    t = stripTrailingLatinAnnotationSuffix(t);
    t = stripLeadingSongIndexMarker(t).trim();
    t = stripLeadingSongContextMarker(t).trim();
    t = stripLooseEdgeTitleQuotes(t);

    // 正式标题可能只占字段的一部分，例如 『作品名』歌手；不要把引号/书名号当边缘噪音删除。

    // 只清理真正像分隔符的边缘字符，不再清理 . 、 " 、 [] 等可能属于正式名称的字符
    t = t
      .replace(/^[\[［]+/g, '')
      .replace(/[\]］]+$/g, '')
      .replace(/^[\-—–−/／|｜￤∣丨:：;；]+/g, '')
      .replace(/[\-—–−/／|｜￤∣丨:：;；]+$/g, '')
      .trim();

    t = stripTrailingYearAnnotation(t);
    return stripTrailingVisualDecorations(stripLooseEdgeTitleQuotes(t));
  }

  function isBadField(text) {
    const t = (text || '').trim();

    if (!t) return true;
    if (/^(歌名|歌手|编号|未确定)$/i.test(t)) return true;
    if (/^\d{1,2}:\d{2}(?::\d{2})?$/.test(t)) return true;
    if (/^(talk|mc|雑談|聊天|感想|开场|结束|告知|返场|休息)$/i.test(t)) return true;

    return false;
  }

  function looksLikeMetaOnly(line) {
    const t = (line || '').trim();
    if (!t) return true;
    if (/^(```|~~~)/.test(t)) return true;
    if (/^(以下|下面|整理|结果|输出|歌曲列表|最终结果|说明|注：|注意|按顺序|已按顺序|共\s*\d+\s*首|共\d+首)/.test(t)) return true;
    if (/编号.*歌名.*歌手/.test(t)) return true;
    return false;
  }

  function stripLeadingTimestamp(text) {
    let t = normalizeTimelineMarkerChars(stripTimelineTreePrefix(text || '')).trim();
    const timestampPattern = /^(?:[\[【(（]\s*)?\d{1,2}:\d{2}(?::\d{2})?\s*(?:[\]】)）])?(?:[\s\u3000]*[;；,，、~～\-—–−]+\s*)?/u;

    for (let i = 0; i < 8; i += 1) {
      const next = stripTimelineTreePrefix(t.replace(timestampPattern, '').trim());
      if (next === t) break;
      t = next;
    }

    return t;
  }

  function stripLeadingSerialMarker(text) {
    let t = normalizeTimelineMarkerChars(text || '').trim();

    const patterns = [
      /^Re\s*[:：]\s*/iu,
      /^【\s*\d{1,3}\s*】\s*/u,
      /^[⟦〚]\s*\d{1,3}\s*[⟧〛]\s*/u,
      /^\[\s*\d{1,3}\s*\]\s*/u,
      /^\(\s*\d{1,3}\s*\)\s*/u,
      /^\d{1,3}\s*曲\s*[\/／]\s*/u,
      /^\d{1,3}\s+(?=\d{1,2}:\d{2}(?::\d{2})?\b)/u,
      /^\d{1,3}\s*[,，]\s+(?!\d)/u,
      /^\d{1,3}\s*[\-—–−]\s*/u,
      /^\d{1,3}\s*[.)．。、,，：:]\s+(?!\d)/u
    ];

    for (const p of patterns) {
      if (p.test(t)) {
        t = t.replace(p, '').trim();
        break;
      }
    }

    return t;
  }

  function stripLeadingTimelineIconMarks(text) {
    return stripTimelineTreePrefix((text || '')
      .replace(/^(?:[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000]*(?:\p{Extended_Pictographic}|[♪♫♬♩]))+\s*/u, '')
      .trim());
  }

  function stripLeadingTimelineDecorations(text) {
    let t = stripTimelineTreePrefix(text || '').trim();

    for (let i = 0; i < 6; i += 1) {
      const next = stripLeadingSerialMarker(stripLeadingTimelineIconMarks(stripLeadingTimestamp(stripTimelineTreePrefix(t))));
      if (next === t) break;
      t = next;
    }

    return t;
  }

  function findLastDelimiterIndex(text, delimiters) {
    let idx = -1;
    for (let i = 0; i < text.length; i += 1) {
      if (delimiters.includes(text[i])) idx = i;
    }
    return idx;
  }

  function isWhitespaceChar(char) {
    return /[\s\u3000]/u.test(char || '');
  }

  function findSpacedDelimitersOutsideBrackets(text, delimiters) {
    const source = text || '';
    const matches = [];
    let depth = 0;

    for (let i = 0; i < source.length; i += 1) {
      const ch = source[i];

      if ('([{（［【「『'.includes(ch)) {
        depth += 1;
        continue;
      }

      if (')]}）］】」』'.includes(ch)) {
        depth = Math.max(0, depth - 1);
        continue;
      }

      if (depth !== 0) continue;

      if (delimiters.includes(ch) && isWhitespaceChar(source[i - 1]) && isWhitespaceChar(source[i + 1])) {
        matches.push({ index: i, length: 1 });
      }
    }

    return matches;
  }

  function findSpacedDoubleSlashOutsideBrackets(text) {
    const source = text || '';
    let depth = 0;

    for (let i = 0; i < source.length - 1; i += 1) {
      const ch = source[i];

      if ('([{（［【「『'.includes(ch)) {
        depth += 1;
        continue;
      }

      if (')]}）］】」』'.includes(ch)) {
        depth = Math.max(0, depth - 1);
        continue;
      }

      if (depth !== 0) continue;

      if (source[i] === '/' && source[i + 1] === '/' && isWhitespaceChar(source[i - 1]) && isWhitespaceChar(source[i + 2])) {
        return i;
      }
    }

    return -1;
  }

  function stripTrailingArtistNotes(text) {
    return (text || '')
      .replace(/\s*[❄✨⭐★☆]*\s*(?:チャレンジ|challenge)\s*$/iu, '')
      .replace(/\s*[※＊❄✨⭐★☆]*\s*(?:[\[【(（]\s*)?(?:with\s+acoustic\s+gui?t[ae]?r|with\s+acoustic|acoustic\s+gui?t[ae]?r|acoustic|Original Song|Original song|ORIGINAL SONG|Original|オリジナル(?:曲|ソング)?|弾き語り(?:初披露)?|初披露|初公開|途中まで|ワンコーラス|挑戦枠?)(?:\s*[\]】)）])?\s*$/iu, '')
      .replace(/[ \t\u3000]+(?:Original Song|Original song|ORIGINAL SONG|Original|オリジナル(?:曲|ソング)?|弾き語り(?:初披露)?|初披露|初公開|途中まで|ワンコーラス|挑戦枠?)\s*$/iu, '')
      .replace(/\s*[※＊]\s*$/u, '')
      .trim();
  }

  function stripTrailingYearAnnotation(text) {
    return (text || '')
      .replace(/\s*[\[［【(（]\s*(?:18|19|20|21)\d{2}\s*(?:年)?\s*[\]］】)）]?\s*$/u, '')
      .trim();
  }

  function stripTrailingReleaseDate(text) {
    return stripTrailingYearAnnotation(
      (text || '')
        .replace(/\s*[\(（]\s*\d{4}\s*(?:[\/.\-年]\s*\d{1,2})\s*(?:[\/.\-月]\s*\d{1,2})?\s*日?\s*[\)）]\s*$/u, '')
        .replace(/\s*[\[［【]\s*\d{4}\s*(?:[\/.\-年]\s*\d{1,2})\s*(?:[\/.\-月]\s*\d{1,2})?\s*日?\s*[\]］】]\s*$/u, '')
    ).trim();
  }

  function stripTrailingReleaseMetadata(text) {
    return stripTrailingReleaseDate(text || '')
      // 末尾或歌手后面的发行日、作品关系说明统一视为元数据：
      // 和田光司 1999/04/23 デジモンアドベンチャー オープニング -> 和田光司
      .replace(/[\s\u3000]+(?:18|19|20|21)\d{2}\s*(?:[\/.\-年]\s*\d{1,2})\s*(?:[\/.\-月]\s*\d{1,2})?\s*日?.*$/u, '')
      .replace(/[\s\u3000]+\d+(?:st|nd|rd|th)?\s*オリジナル(?:ソング|曲)?\s*$/iu, '')
      .replace(/[\s\u3000]+オリジナル(?:ソング|曲)\s*$/u, '')
      .trim();
  }

  function stripTrailingArtistWorkTitle(text) {
    return stripTrailingReleaseDate(text)
      .replace(/\s*【[^】]{1,120}】\s*$/u, '')
      .trim();
  }

  function stripTrailingLatinAliasFromArtist(text) {
    const raw = (text || '').trim();
    if (!raw) return raw;

    const m = raw.match(/\s+[A-Za-z0-9 .,'’"!?&+_\-]+(?:\s*[\/／|｜￤∣丨]\s*[A-Za-z0-9 .,'’"!?&+_\-]+)+\s*$/u);
    if (!m) return raw;

    const before = raw.slice(0, m.index).trim();
    if (!before || !containsJapanese(before)) return raw;

    log('删除歌手字段后的罗马字/英文对照', {
      original: raw,
      kept: before,
      removed: m[0].trim()
    });

    return before;
  }

  function shouldPreserveTrailingDoubleSlash(text) {
    return /[A-Za-z0-9)\]）]\/\/\s*$/u.test((text || '').trim());
  }

  function restoreTrailingDoubleSlashIfNeeded(original, cleaned) {
    const value = (cleaned || '').trim();
    if (!value) return value;
    if (shouldPreserveTrailingDoubleSlash(original) && !/\/\/\s*$/u.test(value)) {
      return `${value}//`;
    }
    return value;
  }

  function cleanArtistPart(text) {
    const raw = stripTrailingLatinAliasFromArtist(stripTrailingArtistWorkTitle(stripTrailingReleaseMetadata(text)));
    const cleaned = stripTrailingVisualDecorations(stripTrailingReleaseMetadata(stripTrailingArtistNotes(cleanSongOrArtistPart(raw))));
    return restoreTrailingDoubleSlashIfNeeded(raw, cleaned);
  }

  function cleanMetadataPart(text) {
    return cleanSongOrArtistPart(text || '')
      .replace(/^[\[\]【】]+|[\[\]【】]+$/g, '')
      .trim();
  }

  function cleanArtistWithOptionalMetadata(text) {
    const raw = (text || '').trim();
    if (!raw) return '';

    const pipeMatches = findSpacedDelimitersOutsideBrackets(raw, '|｜￤∣丨');
    if (!pipeMatches.length) {
      return cleanArtistPart(raw);
    }

    const firstPipe = pipeMatches[0];
    const artist = cleanArtistPart(raw.slice(0, firstPipe.index));
    const metadata = cleanMetadataPart(raw.slice(firstPipe.index + firstPipe.length));

    if (!artist) return cleanArtistPart(raw);
    if (!metadata) return artist;

    return `${artist} [${metadata}]`;
  }

  function isDateSlashDelimiterAt(text, index) {
    const source = normalizeTimelineMarkerChars(text || '');
    if (index <= 0 || index >= source.length - 1) return false;
    if (source[index] !== '/') return false;

    const before = source.slice(0, index);
    const after = source.slice(index + 1);

    // 1999/04/23、7/20 这类日期里的 / 不是“歌名 / 歌手”分隔符。
    return /\d{1,4}\s*$/u.test(before) && /^\s*\d{1,2}(?:\D|$)/u.test(after);
  }

  function findLooseSongArtistDelimiterIndex(text) {
    const source = text || '';
    if (!source) return -1;

    let depth = 0;
    const asciiSlashCandidates = [];
    const fullwidthSlashCandidates = [];
    const pipeCandidates = [];

    for (let i = 0; i < source.length; i += 1) {
      const ch = source[i];

      if ('([{（［【「『'.includes(ch)) {
        depth += 1;
        continue;
      }

      if (')]}）］】」』'.includes(ch)) {
        depth = Math.max(0, depth - 1);
        continue;
      }

      if (depth !== 0) continue;

      if (ch === '/') {
        if (!isDateSlashDelimiterAt(source, i)) {
          asciiSlashCandidates.push(i);
        }
        continue;
      }

      if ('／'.includes(ch)) {
        fullwidthSlashCandidates.push(i);
        continue;
      }

      if ('|｜￤∣丨'.includes(ch)) {
        pipeCandidates.push(i);
      }
    }

    if (asciiSlashCandidates.length) return asciiSlashCandidates[0];
    if (pipeCandidates.length) return pipeCandidates[pipeCandidates.length - 1];
    if (fullwidthSlashCandidates.length) return fullwidthSlashCandidates[fullwidthSlashCandidates.length - 1];

    return -1;
  }

  function splitByDelimitersOutsideBrackets(text, delimiters) {
    const source = text || '';
    const parts = [];
    let depth = 0;
    let start = 0;

    for (let i = 0; i < source.length; i += 1) {
      const ch = source[i];

      if ('([{（［【「『《〈｢'.includes(ch)) {
        depth += 1;
        continue;
      }

      if (')]}）］】」』》〉｣'.includes(ch)) {
        depth = Math.max(0, depth - 1);
        continue;
      }

      if (depth !== 0) continue;

      if (delimiters.includes(ch)) {
        parts.push(source.slice(start, i).trim());
        start = i + 1;
      }
    }

    parts.push(source.slice(start).trim());
    return parts.filter(part => part.length > 0);
  }

  function looksLikeRelationMetadataPart(text) {
    const t = normalizeTimelineMarkerChars(text || '').trim();
    if (!t) return false;

    if (/^[「『《〈【]/u.test(t)) return true;
    if (/(?:OP|ED|オープニング|エンディング|Opening|Ending|テーマ|主題歌|挿入歌)/iu.test(t)) return true;
    if (/(?:ゲーム|アニメ|映画|ドラマ|ソフト|ブランド|レーベル|project|PROJECT|CIRCUS|SAGA\s*PLANETS|ゆずソフト|戯画)/iu.test(t)) return true;
    if (/(?:18|19|20|21)\d{2}/u.test(t)) return true;

    return false;
  }

  function extractMultiFieldFullwidthSlashSongArtist(text) {
    const raw = (text || '').trim();
    if (!raw || !raw.includes('／')) return null;

    const parts = splitByDelimitersOutsideBrackets(raw, '／');
    if (parts.length < 3) return null;

    const metadataParts = parts.slice(2);
    const hasMetadataShape =
      parts.length >= 4 ||
      metadataParts.some(part => looksLikeRelationMetadataPart(part));

    if (!hasMetadataShape) return null;

    const song = cleanSongOrArtistPart(parts[0]);
    const artist = cleanArtistWithOptionalMetadata(stripTrailingReleaseMetadata(parts[1]));

    if (isBadField(song) || isBadField(artist)) return null;

    return { song, artist };
  }


  function extractSongArtistCore(text) {
    const raw = stripTrailingArtistNotes(stripTrailingReleaseDate((text || '').trim()));
    if (!raw) return null;

    const multiFieldFullwidthSlash = extractMultiFieldFullwidthSlashSongArtist(raw);
    if (multiFieldFullwidthSlash && !shouldSkipParsedSongItem(multiFieldFullwidthSlash)) {
      return multiFieldFullwidthSlash;
    }

    let m = null;

    // 先处理明确的双斜杠分隔。歌手名也可能以 // 结尾，例如 DISH//。
    const doubleSlashIdx = findSpacedDoubleSlashOutsideBrackets(raw);
    if (doubleSlashIdx > 0) {
      const song = cleanSongOrArtistPart(raw.slice(0, doubleSlashIdx));
      const artist = cleanArtistWithOptionalMetadata(raw.slice(doubleSlashIdx + 2));
      if (!isBadField(song) && !isBadField(artist)) {
        return { song, artist };
      }
    }

    const pipeMatches = findSpacedDelimitersOutsideBrackets(raw, '|｜￤∣丨');
    m = raw.match(/^(.+)\s+[-—–−]\s+(.+)$/);
    if (m && pipeMatches.length > 0) {
      const song = cleanSongOrArtistPart(m[1]);
      const artist = cleanArtistWithOptionalMetadata(m[2]);
      if (!isBadField(song) && !isBadField(artist)) {
        return { song, artist };
      }
    }

    const spacedSlashMatches = findSpacedDelimitersOutsideBrackets(raw, '/／|｜￤∣丨');
    if (spacedSlashMatches.length > 0) {
      const firstDelimiter = spacedSlashMatches[0];
      const idx = firstDelimiter.index;
      const song = cleanSongOrArtistPart(raw.slice(0, idx));
      const artist = cleanArtistWithOptionalMetadata(raw.slice(idx + firstDelimiter.length));
      if (!isBadField(song) && !isBadField(artist)) {
        return { song, artist };
      }
    }

    // 优先匹配“前后都有空格”的分隔符，并使用贪婪左侧，尽量吃到最后一个真正分隔符
    m = raw.match(/^(.+)\s+[\/／|｜￤∣丨]\s+(.+)$/);
    if (m) {
      const song = cleanSongOrArtistPart(m[1]);
      const artist = cleanArtistWithOptionalMetadata(m[2]);
      if (!isBadField(song) && !isBadField(artist)) {
        return { song, artist };
      }
    }

    // 连字符分隔必须要求两边有空格，避免误切开 Os-宇宙人 这类正式名称
    m = raw.match(/^(.+)\s+[-—–−]\s+(.+)$/);
    if (m) {
      const song = cleanSongOrArtistPart(m[1]);
      const artist = cleanArtistWithOptionalMetadata(m[2]);
      if (!isBadField(song) && !isBadField(artist)) {
        return { song, artist };
      }
    }

    // 兼容无空格写法：441/miwa、366日/HY、Butter-Fly/和田光司 1999/04/23 ...
    // 发行日中的 / 不能当作歌名/歌手分隔符。
    const idx = findLooseSongArtistDelimiterIndex(raw);
    if (idx > 0 && idx < raw.length - 1) {
      const song = cleanSongOrArtistPart(raw.slice(0, idx));
      const artist = cleanArtistWithOptionalMetadata(raw.slice(idx + 1));
      if (!isBadField(song) && !isBadField(artist)) {
        return { song, artist };
      }
    }

    return null;
  }

  function extractSongArtistFromNumberedBodyFallback(text) {
    const raw = stripTrailingArtistNotes(stripTrailingReleaseDate((text || '').trim()));
    if (!raw) return null;

    const m = raw.match(/^(.+)[ \t\u3000]+([A-Za-z0-9][A-Za-z0-9 .,'’"!?&+_\-]*)$/u);
    if (!m) return null;

    const song = cleanSongOrArtistPart(m[1]);
    const artist = cleanArtistWithOptionalMetadata(m[2]);

    if (!song || !artist) return null;
    if (!containsJapanese(song)) return null;
    if (isBadField(song) || isBadField(artist)) return null;

    return { song, artist };
  }

  function cleanupAiLine(line) {
    let t = normalizeTimelineMarkerChars(line || '').trim();

    t = t.replace(/^(```|~~~)\s*/g, '').trim();
    t = t.replace(/^[>\-•*·●○◆◇■□▸▹▶▷]+/g, '').trim();
    t = t.replace(/^第?\s*\d{1,3}\s*[.)。、:：\-—–−]\s*/u, '').trim();
    t = t.replace(/^#\s*\d{1,3}\s+/u, '').trim();
    t = t.replace(/^第?\s*\d{1,3}\s+/u, '').trim();
    t = stripLeadingTimelineDecorations(t);

    return t;
  }

  function extractSongArtistFromAiLine(line) {
    const cleaned = cleanupAiLine(line);
    if (!cleaned) return null;
    if (looksLikeMetaOnly(cleaned)) return null;
    return extractSongArtistCore(cleaned);
  }

  function hasValidTimestampSeconds(value) {
    return typeof value === 'number' && Number.isFinite(value);
  }

  function hasHourPartTimestampLabel(label) {
    const normalized = normalizeTimelineMarkerChars(label || '').trim();
    if (!normalized || timestampToSeconds(normalized) === null) return false;
    return normalized.split(':').length === 3;
  }

  function shouldUseHourTimestampFormat(items) {
    if (!Array.isArray(items) || !items.length) return false;

    return items.some(item => {
      if (!item) return false;
      if (hasValidTimestampSeconds(item.timestampSeconds) && item.timestampSeconds >= 3600) return true;
      return hasHourPartTimestampLabel(item.timestampLabel);
    });
  }

  function formatTimestampSecondsForOutput(seconds, forceHours = false) {
    if (!hasValidTimestampSeconds(seconds)) return '';

    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const restSeconds = total % 60;
    const mm = String(minutes).padStart(2, '0');
    const ss = String(restSeconds).padStart(2, '0');

    return forceHours || hours > 0
      ? `${hours}:${mm}:${ss}`
      : `${minutes}:${ss}`;
  }

  function formatTimestampForOutput(item, options = {}) {
    const forceHours = Boolean(options.forceHours);

    if (hasValidTimestampSeconds(item?.timestampSeconds)) {
      return formatTimestampSecondsForOutput(item.timestampSeconds, forceHours);
    }

    const label = normalizeTimelineMarkerChars(item?.timestampLabel || '').trim();
    const labelSeconds = timestampToSeconds(label);
    if (labelSeconds !== null) {
      return formatTimestampSecondsForOutput(labelSeconds, forceHours || hasHourPartTimestampLabel(label));
    }

    return '';
  }

  function formatSongItems(items, options = {}) {
    if (!items || !items.length) return '';
    const includeTimestamps = Boolean(options.includeTimestamps);
    const width = items.length >= 100 ? 3 : 2;
    const orderedItems = items
      .map((item, index) => ({ item, index }))
      .sort((a, b) => {
        const aSeconds = a.item?.timestampSeconds;
        const bSeconds = b.item?.timestampSeconds;
        const aHasTimestamp = hasValidTimestampSeconds(aSeconds);
        const bHasTimestamp = hasValidTimestampSeconds(bSeconds);

        if (aHasTimestamp && bHasTimestamp && aSeconds !== bSeconds) {
          return aSeconds - bSeconds;
        }

        return a.index - b.index;
      })
      .map(entry => entry.item);

    const forceHourTimestamps = includeTimestamps && shouldUseHourTimestampFormat(orderedItems);

    return orderedItems
      .map((item, index) => {
        const line = `${String(index + 1).padStart(width, '0')}. ${item.song} - ${item.artist}`;
        if (!includeTimestamps) return line;

        const timestamp = formatTimestampForOutput(item, { forceHours: forceHourTimestamps });
        return timestamp ? `${timestamp} ${line}` : line;
      })
      .join('\n');
  }

  function parseAiSongList(text) {
    const normalized = normalizeText(text);
    if (!normalized) return [];

    if (isSpecialNoArtistResponse(normalized)) {
      return [{ __special_no_artist__: true }];
    }

    const lines = normalized.split('\n').map(line => line.trim()).filter(Boolean);
    const items = [];

    for (const line of lines) {
      if (/^请提供歌手信息后再处理。?$/.test(line)) {
        return [{ __special_no_artist__: true }];
      }
      if (looksLikeMetaOnly(line)) continue;

      const parsed = extractSongArtistFromAiLine(line);
      if (!parsed) continue;
      items.push(parsed);
    }

    return items;
  }

  function parseStructuredSourceLine(line) {
    let t = normalizeTimelineMarkerChars(stripWeirdLeadingChars(line || ''));
    if (!t) return null;

    const timestampInfo = extractFirstTimestampInfo(t);

    // 先去掉时间戳，再判断是否是 #01 / 1. / 【1】 这种带序号曲目
    t = stripLeadingTimestamp(t);
    t = stripLeadingTimelineIconMarks(t);
    t = t.replace(/^Re\s*[:：]\s*/iu, '').trim();
    if (!t) return null;

    const serialMatch =
      t.match(/^#\s*(\d{1,3})\s+(.+)$/u) ||
      t.match(/^【\s*(\d{1,3})\s*】\s*(.+)$/u) ||
      t.match(/^[⟦〚]\s*(\d{1,3})\s*[⟧〛]\s*(.+)$/u) ||
      t.match(/^\[\s*(\d{1,3})\s*\]\s*(.+)$/u) ||
      t.match(/^\(\s*(\d{1,3})\s*\)\s*(.+)$/u) ||
      t.match(/^(\d{1,3})\s*曲\s*[\/／]\s*(.+)$/u) ||
      t.match(/^(\d{1,3})\s+(\d{1,2}:\d{2}(?::\d{2})?[\s\u3000]+.+)$/u) ||
      t.match(/^(\d{1,3})\s*[,，]\s*(.+)$/u) ||
      t.match(/^(\d{1,3})\s*[\-—–−]\s*(.+)$/u) ||
      t.match(/^(\d{1,3})\s*[.)．。、,，：:]\s*(.+)$/u);

    if (!serialMatch) return null;

    const num = Number(serialMatch[1]);
    let body = (serialMatch[2] || '').trim();
    body = stripLeadingTimelineDecorations(body);
    if (!body) return null;

    const parsed = extractSongArtistCore(body) || extractSongArtistFromNumberedBodyFallback(body);
    if (!parsed) return null;
    if (shouldSkipParsedSongItem(parsed)) return null;

    return {
      num,
      timestampSeconds: timestampInfo.seconds,
      timestampLabel: timestampInfo.label,
      song: parsed.song,
      artist: parsed.artist
    };
  }

  function extractStructuredSongsFromSourceTimeline(text) {
    const normalized = normalizeText(text);
    if (!normalized) return [];

    const lines = normalized.split('\n');
    const items = [];
    const seenNums = new Set();

    for (const line of lines) {
      const item = parseStructuredSourceLine(line);
      if (!item) continue;
      if (seenNums.has(item.num)) continue;
      seenNums.add(item.num);
      items.push(item);
    }

    return items;
  }

  function isContiguousStructuredSetlist(items) {
    if (!items || !items.length) return false;

    const nums = items.map(item => item.num).filter(n => Number.isFinite(n)).sort((a, b) => a - b);
    if (!nums.length) return false;
    if (nums[0] !== 1) return false;

    for (let i = 0; i < nums.length; i += 1) {
      if (nums[i] !== i + 1) return false;
    }

    return true;
  }

  function isMostlyAscendingStructuredSetlist(items) {
    if (!Array.isArray(items) || items.length < 2) return false;

    const nums = items
      .map(item => item && item.num)
      .filter(n => Number.isFinite(n));

    if (nums.length < 2) return false;
    if (nums[0] !== 1) return false;

    let nonIncreasing = 0;
    let bigJump = 0;

    for (let i = 1; i < nums.length; i += 1) {
      const diff = nums[i] - nums[i - 1];
      if (diff <= 0) nonIncreasing += 1;
      if (diff > 2) bigJump += 1;
    }

    return nonIncreasing === 0 && bigJump === 0;
  }

  function hasTrailingArtistHonorific(text) {
    return /(?:さん|様|氏)\s*$/u.test((text || '').trim());
  }

  function stripTrailingArtistHonorific(text) {
    return (text || '').replace(/(?:さん|様|氏)\s*$/u, '').trim();
  }

  function normalizeArtistHonorifics(items) {
    if (!Array.isArray(items) || !items.length) return items || [];

    const valid = items.filter(item => item && typeof item.artist === 'string' && item.artist.trim());
    if (!valid.length) return items;

    const honorificCount = valid.filter(item => hasTrailingArtistHonorific(item.artist)).length;
    const ratio = honorificCount / valid.length;

    // 只有数量足够多且占比明显时，才认为是统一书写习惯
    if (honorificCount < 3 || ratio < 0.6) {
      return items;
    }

    return items.map(item => {
      if (!item || typeof item.artist !== 'string') return item;
      if (!hasTrailingArtistHonorific(item.artist)) return item;
      return { ...item, artist: stripTrailingArtistHonorific(item.artist) };
    });
  }

  function normalizeKanjiArtistSpacing(items) {
    if (!Array.isArray(items) || !items.length) return items || [];

    return items.map(item => {
      if (!item || typeof item.artist !== 'string') return item;

      const artist = item.artist
        // 只压缩汉字之间的空格：奥 華子 -> 奥華子
        // 不影响 Never young beach，也不影响 はる こたつぶとん倶楽部♧ 这类非纯汉字间隔
        .replace(/(?<=[\u3400-\u9FFF\uF900-\uFAFF])\s+(?=[\u3400-\u9FFF\uF900-\uFAFF])/gu, '')
        .trim();

      return { ...item, artist };
    });
  }

  function normalizeArtistDisplay(items) {
    return normalizeKanjiArtistSpacing(normalizeArtistHonorifics(items));
  }

  function normalizeLooseComparableText(text) {
    return (text || '')
      .normalize('NFKC')
      .replace(/[“”‘’"'`]/g, '')
      .replace(/[\s\u3000]+/g, '')
      .replace(/[，,、｡。]/g, '')
      .replace(/[!！?？~～]/g, '')
      .replace(/[.．…]+/g, '')
      .trim()
      .toLowerCase();
  }

  function dedupeSongItemsByTimestampAndIdentity(items) {
    if (!Array.isArray(items) || !items.length) return items || [];

    const seen = new Set();
    const result = [];

    for (const item of items) {
      if (!item) continue;

      const songKey = normalizeLooseComparableText(item.song);
      const artistKey = normalizeLooseComparableText(item.artist);

      if (!songKey || !artistKey || !hasValidTimestampSeconds(item.timestampSeconds)) {
        result.push(item);
        continue;
      }

      const key = `${Math.floor(item.timestampSeconds)}|${songKey}|${artistKey}`;
      if (seen.has(key)) continue;

      seen.add(key);
      result.push(item);
    }

    return result;
  }

  function hasReplacementCharacter(text) {
    return /\uFFFD/.test(text || '');
  }

  function isLowRiskLatinTailCorrection(sourceText, aiText) {
    const source = (sourceText || '').trim();
    const ai = (aiText || '').trim();
    if (!source || !ai || hasReplacementCharacter(source) || hasReplacementCharacter(ai)) return false;
    if (containsJapanese(source) || containsJapanese(ai)) return false;

    const sourceNorm = normalizeLooseComparableText(source);
    const aiNorm = normalizeLooseComparableText(ai);
    if (!sourceNorm || !aiNorm || sourceNorm === aiNorm) return false;

    if (sourceNorm.startsWith(aiNorm)) {
      const suffix = sourceNorm.slice(aiNorm.length);
      return /^[a-z]{1,3}$/.test(suffix);
    }

    if (aiNorm.startsWith(sourceNorm)) {
      const suffix = aiNorm.slice(sourceNorm.length);
      return /^[a-z]{1,3}$/.test(suffix);
    }

    return false;
  }

  function stripTrailingParenSuffix(text) {
    return (text || '').replace(/[\(（][^()（）]{1,30}[\)）]\s*$/u, '').trim();
  }

  function hasLikelyCjkParenSuffix(text) {
    const m = (text || '').match(/[\(（]([^()（）]{1,30})[\)）]\s*$/u);
    if (!m) return false;
    const inner = (m[1] || '').trim();
    if (!inner) return false;
    if (/[A-Za-z]/.test(inner)) return false;
    return /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]/u.test(inner);
  }

  function canRestoreSongParenSuffixFromSource(sourceItems) {
    if (!Array.isArray(sourceItems) || !sourceItems.length) return false;
    const count = sourceItems.filter(item => hasLikelyCjkParenSuffix(item && item.song)).length;
    if (!count) return false;
    return count <= Math.max(2, Math.floor(sourceItems.length * 0.25));
  }

  function isSourceJapaneseButAiLatinish(sourceText, aiText) {
    const source = (sourceText || '').trim();
    const ai = (aiText || '').trim();
    if (!source || !ai) return false;

    const sourceHasJapanese = containsJapanese(source);
    const aiHasJapanese = containsJapanese(ai);
    const aiLatinCount = (ai.match(/[A-Za-z]/g) || []).length;
    const aiCjkCount = (ai.match(/[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]/g) || []).length;

    return sourceHasJapanese && !aiHasJapanese && aiLatinCount >= 3 && aiLatinCount > aiCjkCount * 2;
  }

  function shouldPreferSourceSong(sourceSong, aiSong, allowParenSuffixRestore) {
    const source = (sourceSong || '').trim();
    const ai = (aiSong || '').trim();
    if (!source || !ai || source === ai) return false;

    const sourceNorm = normalizeLooseComparableText(source);
    const aiNorm = normalizeLooseComparableText(ai);

    if (isSourceJapaneseButAiLatinish(source, ai)) {
      return true;
    }

    if (sourceNorm === aiNorm && source.length > ai.length) {
      return true;
    }

    const sourceNoParenNorm = normalizeLooseComparableText(stripTrailingParenSuffix(source));
    if (allowParenSuffixRestore && sourceNoParenNorm && sourceNoParenNorm === aiNorm && hasLikelyCjkParenSuffix(source)) {
      return true;
    }

    if (source.startsWith(ai) && source.length > ai.length) {
      const suffix = source.slice(ai.length).trim();
      if (/^[、，,。｡.!！?？~～「『（\(]/u.test(suffix)) {
        return true;
      }
    }

    return false;
  }

  function shouldPreferSourceArtist(sourceArtist, aiArtist) {
    const source = (sourceArtist || '').trim();
    const ai = (aiArtist || '').trim();
    if (!source || !ai || source === ai) return false;

    const sourceNorm = normalizeLooseComparableText(source);
    const aiNorm = normalizeLooseComparableText(ai);

    if (isSourceJapaneseButAiLatinish(source, ai)) {
      return true;
    }

    if (sourceNorm === aiNorm && source.length > ai.length) {
      return true;
    }

    const sourceNoParenNorm = normalizeLooseComparableText(stripTrailingParenSuffix(source));
    if (sourceNoParenNorm && sourceNoParenNorm === aiNorm && /[\(（]/.test(source)) {
      return true;
    }

    if (source.startsWith(ai) && source.length > ai.length) {
      const suffix = source.slice(ai.length).trim();
      if (/^[・×xX&＆、,，「『（\(]/u.test(suffix)) {
        return true;
      }
    }

    return false;
  }

  function mergeFieldWithSourceFallback(sourceValue, aiValue, preferSourceByRule) {
    const source = (sourceValue || '').trim();
    const ai = (aiValue || '').trim();

    if (!source) return ai;
    if (!ai) return source;
    if (source === ai) return ai;

    if (hasTimelineTimestamp(source) && !hasTimelineTimestamp(ai)) {
      return ai;
    }

    if (hasReplacementCharacter(ai) && !hasReplacementCharacter(source)) {
      return source;
    }

    if (isLowRiskLatinTailCorrection(source, ai)) {
      return ai;
    }

    if (preferSourceByRule) {
      return source;
    }

    return source;
  }

  function mergeAiItemsWithSourceByOrder(aiItems, sourceItems) {
    if (!Array.isArray(aiItems) || !Array.isArray(sourceItems)) return aiItems || [];
    if (!aiItems.length || !sourceItems.length) return aiItems || [];
    if (aiItems.length !== sourceItems.length) return aiItems;

    const allowParenSuffixRestore = canRestoreSongParenSuffixFromSource(sourceItems);

    return aiItems.map((aiItem, index) => {
      const sourceItem = sourceItems[index];
      if (!aiItem || !sourceItem) return aiItem;

      const merged = { ...aiItem };

      if (hasValidTimestampSeconds(sourceItem.timestampSeconds)) {
        merged.timestampSeconds = sourceItem.timestampSeconds;
      }
      if (sourceItem.timestampLabel) {
        merged.timestampLabel = sourceItem.timestampLabel;
      }

      merged.song = mergeFieldWithSourceFallback(
        sourceItem.song,
        aiItem.song,
        shouldPreferSourceSong(sourceItem.song, aiItem.song, allowParenSuffixRestore)
      );

      merged.artist = mergeFieldWithSourceFallback(
        sourceItem.artist,
        aiItem.artist,
        shouldPreferSourceArtist(sourceItem.artist, aiItem.artist)
      );

      return merged;
    });
  }

  function stripWeirdLeadingChars(text) {
    return (text || '')
      .replace(/^[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000️]+/g, '')
      .trim();
  }

  function stripTimelineTreePrefix(text) {
    return (text || '')
      .replace(/^[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000]*(?:[├└┣┗┝┖│┃┆┇┊┋]+|[>＞]+|[-－—–−]+|[・･●○◆◇■□]+)\s*/u, '')
      .trim();
  }

  function stripTrailingVisualDecorations(text) {
    let t = (text || '').trim();

    for (let i = 0; i < 6; i += 1) {
      const next = t
        .replace(/[\s\u00A0\u3000\uFE0F\u200D]*(?:\p{Extended_Pictographic}|[♪♫♬♩♡♥★☆⭐✨❄☂])\s*$/u, '')
        .replace(/[\s\u00A0\u3000\uFE0F\u200D]+$/u, '')
        .trim();

      if (next === t) break;
      t = next;
    }

    return t;
  }

  function normalizeSetlistNumberChars(text) {
    return normalizeTimelineMarkerChars(text || '')
      .replace(/[①②③④⑤⑥⑦⑧⑨]/g, ch => String('①②③④⑤⑥⑦⑧⑨'.indexOf(ch) + 1))
      .trim();
  }

  function isStandaloneSetlistNumberLine(text) {
    const t = normalizeSetlistNumberChars(stripWeirdLeadingChars(text || ''));
    return /^[#＃]?\s*\d{1,3}\s*[.)．。、,，：:]?\s*$/u.test(t);
  }

  function getTimestampInfosInLine(text) {
    const normalized = normalizeTimelineMarkerChars(text || '');
    const result = [];
    const seen = new Set();
    const regex = /(^|[^\d])(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)/g;
    let match;

    while ((match = regex.exec(normalized))) {
      const label = match[2];
      const seconds = timestampToSeconds(label);
      if (seconds === null || seen.has(label)) continue;
      seen.add(label);
      result.push({ label, seconds });
    }

    return result;
  }

  function isTimestampRangeLikeLine(text) {
    const t = normalizeTimelineMarkerChars(stripWeirdLeadingChars(text || '')).trim();
    if (!t) return false;

    // 兼容：4:18~ / 4:18~7:37 / １ 4:18~7:37
    return /^(?:[#＃]?\s*\d{1,3}\s*[.)．。、,，：:]?\s*)?\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜-－—–−]\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*$/u.test(t);
  }

  function extractStartTimestampFromRangeLikeLine(text) {
    const infos = getTimestampInfosInLine(text || '');
    return infos[0] || { label: '', seconds: null };
  }

  function isRangeStartOnlyLine(text) {
    const t = normalizeTimelineMarkerChars(stripWeirdLeadingChars(text || '')).trim();
    if (!t) return false;

    return /^\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜-－—–−]\s*$/u.test(t);
  }

  function stripOuterSongTitleQuotes(text) {
    let t = (text || '').trim();

    for (let i = 0; i < 3; i += 1) {
      const next = t
        .replace(/^[『「｢《〈【\["'“”‘’]+/u, '')
        .replace(/[』」｣》〉】\]"'“”‘’]+$/u, '')
        .trim();

      if (next === t) break;
      t = next;
    }

    return t;
  }

  function stripInlineTrailingTimestampRange(text) {
    return (text || '')
      .replace(/\s+\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜-－—–−]\s*\d{1,2}:\d{2}(?::\d{2})?\s*$/u, '')
      .replace(/\s+\d{1,2}:\d{2}(?::\d{2})?\s*[~～〜-－—–−]\s*$/u, '')
      .trim();
  }

  function stripSetlistTitlePrefix(text) {
    let t = normalizeSetlistNumberChars(stripLeadingTimelineIconMarks(stripTimelineTreePrefix(stripWeirdLeadingChars(text || ''))));

    t = t
      .replace(/^第?\s*\d{1,3}\s*曲目\s*[：:]\s*/u, '')
      .replace(/^第?\s*\d{1,3}\s*曲\s*[：:]\s*/u, '')
      .trim();

    return t;
  }

  function extractSongArtistFromSetlistTitleLine(text) {
    let t = normalizeSetlistNumberChars(stripLeadingTimelineIconMarks(stripTimelineTreePrefix(stripWeirdLeadingChars(text || ''))));
    if (!/^第?\s*\d{1,3}\s*(?:曲目|曲)\s*[：:]/u.test(t)) return null;

    t = stripSetlistTitlePrefix(t);
    t = stripInlineTrailingTimestampRange(t);
    t = stripTrailingVisualDecorations(t);
    t = stripOuterSongTitleQuotes(t);
    t = stripTrailingVisualDecorations(t);
    t = stripOuterSongTitleQuotes(t);

    if (!t || isObviouslyNonSongText(t)) return null;

    const parsed = extractSongArtistCore(t) || extractSongArtistFromNumberedBodyFallback(t);
    if (!parsed) return null;
    if (!parsed.song || !parsed.artist) return null;
    if (shouldSkipParsedSongItem(parsed)) return null;

    return parsed;
  }


  function extractSongItemFromInlineSetlistRangeLine(text) {
    let t = normalizeSetlistNumberChars(stripLeadingTimelineIconMarks(stripTimelineTreePrefix(stripWeirdLeadingChars(text || ''))));
    if (!t) return null;

    // 兼容“曲目号 + 起止时间 + 歌曲信息”同一行：
    // 1曲目 38:12~43:24「ガーネット／奥華子」
    // 3曲目 01:10:43~01:14:32「カタオモイ／Aimer」
    // 只取第一个时间戳作为歌曲开始时间。
    const match = t.match(/^第?\s*\d{1,3}\s*(?:曲目|曲)\s*[：:\s\u3000]*(\d{1,2}:\d{2}(?::\d{2})?)\s*[~～〜\-－—–−]\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*(.+)$/u);
    if (!match) return null;

    const timestampLabel = match[1];
    const timestampSeconds = timestampToSeconds(timestampLabel);
    if (timestampSeconds === null) return null;

    let body = (match[2] || '').trim();
    body = stripInlineTrailingTimestampRange(body);
    body = stripTrailingVisualDecorations(body);
    body = stripOuterSongTitleQuotes(body);
    body = stripTrailingVisualDecorations(body);
    body = stripOuterSongTitleQuotes(body);

    if (!body || isObviouslyNonSongText(body)) return null;

    const parsed = extractSongArtistCore(body) || extractSongArtistFromNumberedBodyFallback(body);
    if (!parsed) return null;
    if (!parsed.song || !parsed.artist) return null;
    if (shouldSkipParsedSongItem(parsed)) return null;

    return {
      song: parsed.song,
      artist: parsed.artist,
      timestampLabel,
      timestampSeconds
    };
  }

  function findStartTimestampAfterSetlistTitle(rawLines, startIndex, maxLookahead = 6) {
    const end = Math.min(rawLines.length, startIndex + maxLookahead);

    for (let j = startIndex; j < end; j += 1) {
      const candidate = stripWeirdLeadingChars(rawLines[j] || '');
      if (!candidate) continue;

      if (isLikelyTranslationOnlyLine(candidate)) {
        continue;
      }

      if (isTimestampRangeLikeLine(candidate) || isTimestampStartPlaceholderLine(candidate) || isTimestampOnlyLine(candidate)) {
        const info = extractStartTimestampFromRangeLikeLine(candidate);
        if (!info.label) continue;

        let index = j;
        const next = stripWeirdLeadingChars(rawLines[j + 1] || '');
        if (
          next &&
          isTimestampOnlyLine(next) &&
          !isTimestampStartPlaceholderLine(next) &&
          (isRangeStartOnlyLine(candidate) || !/[~～〜-－—–−]/u.test(candidate))
        ) {
          index = j + 1;
        }

        return {
          timestampLabel: info.label,
          timestampSeconds: info.seconds,
          index
        };
      }

      if (isStandaloneSetlistNumberLine(candidate) || extractSongArtistFromSetlistTitleLine(candidate)) {
        return null;
      }

      if (isObviouslyNonSongText(candidate)) {
        continue;
      }

      return null;
    }

    return null;
  }

  function isLikelyTranslationOnlyLine(text) {
    let t = stripTimelineTreePrefix(stripWeirdLeadingChars(text || '')).trim();
    if (!t) return true;

    if (/^[\(（\[［][^()（）\[\]［］]{1,140}[\)）\]］]$/u.test(t)) {
      const inner = t.slice(1, -1).trim();
      return looksLikeLatinAnnotation(inner);
    }

    return false;
  }

  function findSongLineAfterSetlistTimeBlock(rawLines, startIndex, maxLookahead = 8) {
    let startInfo = null;
    let sawTimeBlock = false;
    const end = Math.min(rawLines.length, startIndex + maxLookahead);

    for (let j = startIndex; j < end; j += 1) {
      const candidate = stripWeirdLeadingChars(rawLines[j] || '');
      if (!candidate) continue;

      if (isStandaloneSetlistNumberLine(candidate)) {
        if (sawTimeBlock) break;
        continue;
      }

      if (isTimestampRangeLikeLine(candidate) || isTimestampStartPlaceholderLine(candidate)) {
        const info = extractStartTimestampFromRangeLikeLine(candidate);
        if (info.label && !startInfo) startInfo = info;
        sawTimeBlock = true;
        continue;
      }

      if (isTimestampOnlyLine(candidate)) {
        const info = extractFirstTimestampInfo(candidate);
        if (info.label && !startInfo) startInfo = info;
        sawTimeBlock = true;
        continue;
      }

      if (isLikelyTranslationOnlyLine(candidate)) {
        continue;
      }

      if (!sawTimeBlock || !startInfo || !startInfo.label) {
        break;
      }

      const songCandidate = stripTimelineTreePrefix(candidate);
      if (songCandidate && !isObviouslyNonSongText(songCandidate) && isSongArtistOnlyLine(songCandidate)) {
        return {
          timestampLabel: startInfo.label,
          timestampSeconds: startInfo.seconds,
          line: songCandidate,
          index: j
        };
      }

      break;
    }

    return null;
  }

  function isTimestampStartPlaceholderLine(text) {
    const t = normalizeTimelineMarkerChars(stripTimelineTreePrefix(stripWeirdLeadingChars(text || ''))).trim();

    // 兼容这种“歌曲开始时间占位”行：
    // 0:10:24 ;
    // 0:10:24;
    // 0:10:24；
    // 这类时间戳应作为下一条歌曲信息的开始时间。
    return /^(?:[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000]*(?:\p{Extended_Pictographic}|[♪♫♬♩▶▷►▸▹>|・･●○◆◇■□]))*\s*\d{1,2}:\d{2}(?::\d{2})?\s*[;；]+\s*$/u.test(t);
  }

  function isTimestampOnlyLine(text) {
    const t = normalizeTimelineMarkerChars(stripTimelineTreePrefix(stripWeirdLeadingChars(text || '')));
    return /^(?:[\s\uFE0F\u200E\u200F\u2060\u00A0\u3000]*(?:\p{Extended_Pictographic}|[♪♫♬♩▶▷►▸▹>|・･●○◆◇■□]))*\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)*\s*$/u.test(t) || isTimestampStartPlaceholderLine(t);
  }

  function extractPrimaryTimestamp(text) {
    const t = stripWeirdLeadingChars(text);
    const m = t.match(/(\d{1,2}:\d{2}(?::\d{2})?)/);
    return m ? m[1] : '';
  }

  function isObviouslyNonSongText(text) {
    const t = stripWeirdLeadingChars(text);
    if (!t) return true;
    if (/^(開始|结束|終了|end|start)$/i.test(t)) return true;
    if (/^(talk|mc|雑談|聊天|感想|告知|返场|休息)$/i.test(t)) return true;
    if (/(?:宣伝|告知|お知らせ)\s*$/u.test(t)) return true;
    if (/^(こんばんは＆チューニング|うんめー|痺れて痛い|三月の憂鬱|メロンパンのうた)$/u.test(t)) return true;
    if (/^編集中です/u.test(t)) return true;
    if (/^".+"$/.test(t)) return true;
    return false;
  }


  function normalizeSectionMarkerText(text) {
    return (text || '')
      .normalize('NFKC')
      .replace(/[\s　_\-—–−/／|｜￤∣丨:：;；,，.。!！?？~～・･]+/g, '')
      .trim()
      .toLowerCase();
  }

  function isNonSongSectionMarker(text) {
    const key = normalizeSectionMarkerText(text);
    if (!key) return false;

    // 只用于处理“幕開け / Opening”“閉幕 / Closing”这类两侧都有翻译的章节行。
    // 像“スパチャ読み”这种没有歌手字段的单行，本来就会被原有歌名/歌手解析逻辑跳过，不在这里额外处理。
    return /^(opening|open|op|start|starting|intro|introduction|幕開け|開幕|開始|オープニング|closing|close|end|ending|ed|outro|閉幕|終幕|終了|エンディング)$/.test(key);
  }

  function isNonSongChapterLikePair(song, artist) {
    const s = (song || '').trim();
    const a = (artist || '').trim();
    if (!s || !a) return false;

    // 章节型时间轴常见写法：幕開け / Opening、閉幕 / Closing。
    // 只有两侧都像开闭幕/开始结束说明时才跳过，避免误删 START / 歌手 这类真实歌曲。
    if (isNonSongSectionMarker(s) && isNonSongSectionMarker(a)) {
      return true;
    }

    return false;
  }

  function shouldSkipParsedSongItem(parsed) {
    if (!parsed) return true;
    return isNonSongChapterLikePair(parsed.song, parsed.artist);
  }

  function isSongArtistOnlyLine(text) {
    let t = normalizeTimelineMarkerChars(stripWeirdLeadingChars(text || ''));
    if (!t) return false;
    if (extractFirstTimestampInfo(t).label) return false;
    if (isTimestampOnlyLine(t)) return false;

    t = stripLeadingTimelineDecorations(t);
    if (!t) return false;
    if (isObviouslyNonSongText(t)) return false;

    return Boolean(extractSongArtistCore(t));
  }

  function normalizeHeadingComparableText(text) {
    return normalizeSectionMarkerText(stripLeadingTimelineIconMarks(text || ''))
      .replace(/[【】\[\]［］()（）<>＜＞《》〈〉「」『』#＃]/g, '')
      .replace(/[&＆＋+]/g, '')
      .replace(/\p{Extended_Pictographic}/gu, '')
      .trim();
  }

  function isSetlistHeadingLine(text) {
    const raw = normalizeTimelineMarkerChars(stripWeirdLeadingChars(text || '')).trim();
    if (!raw) return false;
    if (extractFirstTimestampInfo(raw).label) return false;
    if (extractSongArtistCore(stripTimelineTreePrefix(raw))) return false;

    const key = normalizeHeadingComparableText(raw);
    return /^(?:セトリ|セットリスト|setlist|setlisttimestamp|setlistandtimestamp|songlist|songlisttimestamp|歌った曲|歌唱曲|曲リスト|歌リスト)$/iu.test(key);
  }

  function isNonSetlistSectionHeadingLine(text) {
    const raw = normalizeTimelineMarkerChars(stripWeirdLeadingChars(text || '')).trim();
    if (!raw) return false;
    if (extractFirstTimestampInfo(raw).label) return false;

    const key = normalizeHeadingComparableText(raw);
    return /^(?:タイムライン|timeline|雑談パート|雑談|talk|mc|感想|告知|チャプター|chapters?)$/iu.test(key);
  }

  function filterRawLinesToPreferredSetlistSection(rawLines) {
    if (!Array.isArray(rawLines) || !rawLines.length) return rawLines || [];

    let startIndex = -1;
    for (let i = 0; i < rawLines.length; i += 1) {
      if (isSetlistHeadingLine(rawLines[i])) {
        startIndex = i + 1;
      }
    }

    if (startIndex < 0) return rawLines;

    const result = [];
    for (let i = startIndex; i < rawLines.length; i += 1) {
      const line = rawLines[i];
      if (result.length > 0 && isNonSetlistSectionHeadingLine(line)) {
        break;
      }
      result.push(line);
    }

    return result.length ? result : rawLines;
  }

  function extractPlainSongsFromSourceTimeline(text) {
    const normalized = normalizeText(text);
    if (!normalized) return [];

    const rawLines = filterRawLinesToPreferredSetlistSection(
      splitCollapsedTimelineLines(normalized)
        .map(line => stripWeirdLeadingChars(line))
        .filter(Boolean)
    );

    const mergedLines = [];

    for (let i = 0; i < rawLines.length; i += 1) {
      const line = rawLines[i];
      if (!line) continue;

      // 兼容“曲目号 + 起止时间 + 歌曲信息”同一行写法：
      // 1曲目 38:12~43:24「ガーネット／奥華子」
      // 这里必须取 38:12，而不是 43:24。
      const inlineRangeItem = extractSongItemFromInlineSetlistRangeLine(line);
      if (inlineRangeItem) {
        mergedLines.push(`${inlineRangeItem.timestampLabel} ${inlineRangeItem.song} / ${inlineRangeItem.artist}`);
        continue;
      }

      // 兼容“曲目标题行 + 下一行起止时间”写法：
      // 🎤1曲目：『晩餐歌/tuki.』
      // 7:06～10:55
      // 这里必须取 7:06，而不是 10:55。
      const titleLineParsed = extractSongArtistFromSetlistTitleLine(line);
      if (titleLineParsed) {
        const timeAfterTitle = findStartTimestampAfterSetlistTitle(rawLines, i + 1);
        if (timeAfterTitle && timeAfterTitle.timestampLabel) {
          mergedLines.push(`${timeAfterTitle.timestampLabel} ${titleLineParsed.song} / ${titleLineParsed.artist}`);
          i = timeAfterTitle.index;
          continue;
        }
      }

      // 兼容“编号 + 起止时间 + 树形曲名行”写法：
      // 1
      // 4:18~
      // 7:37
      // ├ インドア派ならトラックメイカー / Yunomi
      // └ (Indoorha nara Trackmaker)
      // 或 YouTube DOM 中被拆成：1 / 4:18~ / 7:37 / ├ 曲名 / 歌手
      if (isStandaloneSetlistNumberLine(line) || isTimestampRangeLikeLine(line)) {
        const block = findSongLineAfterSetlistTimeBlock(rawLines, isStandaloneSetlistNumberLine(line) ? i + 1 : i);
        if (block && block.timestampLabel && block.line) {
          mergedLines.push(`${block.timestampLabel} ${block.line}`);
          i = block.index;
          continue;
        }
      }

      // 兼容“歌曲开始时间占位 + 后续歌曲信息”写法：
      // 0:10:24 ;
      // 0:14:52 ANIMA / ReoNa
      // 输出带时间轴结果时应使用 0:10:24，而不是 0:14:52。
      if (isTimestampStartPlaceholderLine(line)) {
        const ts = extractPrimaryTimestamp(line);
        const next = stripTimelineTreePrefix(stripWeirdLeadingChars(rawLines[i + 1] || ''));

        if (ts && next && !isTimestampOnlyLine(next) && !isObviouslyNonSongText(next)) {
          mergedLines.push(`${ts} ${next}`);
          i += 1;
          continue;
        }

        continue;
      }

      // 处理两行写法：
      // 🎸 衛星 / 赤い公園
      // ▶ 02:22
      if (
        isSongArtistOnlyLine(line) &&
        isTimestampOnlyLine(rawLines[i + 1] || '') &&
        !isTimestampStartPlaceholderLine(rawLines[i + 1] || '')
      ) {
        const ts = extractPrimaryTimestamp(rawLines[i + 1] || '');
        if (ts) {
          mergedLines.push(`${ts} ${line}`);
          i += 1;
          continue;
        }
      }

      // 处理两行写法：
      // 8:47
      // 蜩/tetoさん
      if (isTimestampOnlyLine(line)) {
        const ts = extractPrimaryTimestamp(line);
        const next = stripTimelineTreePrefix(stripWeirdLeadingChars(rawLines[i + 1] || ''));
        const nextHasOwnTimestamp = Boolean(extractFirstTimestampInfo(next).label);

        if (next && !nextHasOwnTimestamp && !isTimestampOnlyLine(next) && !isObviouslyNonSongText(next)) {
          mergedLines.push(`${ts} ${next}`);
          i += 1;
          continue;
        }

        continue;
      }

      // 本来就是单行时间轴
      mergedLines.push(line);
    }

    const items = [];

    for (const line of mergedLines) {
      let t = stripWeirdLeadingChars(line);
      if (!t) continue;

      if (!/^\d{1,2}:\d{2}(?::\d{2})?\s*/.test(t)) continue;

      const timestampInfo = extractFirstTimestampInfo(t);

      t = stripLeadingTimelineDecorations(t);
      if (!t) continue;
      if (isObviouslyNonSongText(t)) continue;

      const parsed = extractSongArtistCore(t);
      if (!parsed) continue;
      if (!parsed.song || !parsed.artist) continue;
      if (shouldSkipParsedSongItem(parsed)) continue;

      items.push({
        ...parsed,
        timestampSeconds: timestampInfo.seconds,
        timestampLabel: timestampInfo.label
      });
    }

    return normalizeArtistDisplay(items);
  }

  function getBestLocalSourceItems(sourceText) {
    const sourceStructured = extractStructuredSongsFromSourceTimeline(sourceText);
    const sourceStructuredItems = normalizeArtistDisplay(sourceStructured.map(item => ({
      song: item.song,
      artist: item.artist,
      timestampSeconds: item.timestampSeconds,
      timestampLabel: item.timestampLabel
    })));
    const sourceIsContiguous = isContiguousStructuredSetlist(sourceStructured);
    const sourcePlain = extractPlainSongsFromSourceTimeline(sourceText);

    if (sourceIsContiguous && sourceStructuredItems.length >= sourcePlain.length) {
      return dedupeSongItemsByTimestampAndIdentity(sourceStructuredItems);
    }

    const bestItems = sourcePlain.length >= sourceStructuredItems.length
      ? sourcePlain
      : sourceStructuredItems;
    return dedupeSongItemsByTimestampAndIdentity(bestItems);
  }

  function buildLocalSongListOutput(sourceText, options = {}) {
    const items = getBestLocalSourceItems(sourceText);
    return items.length ? formatSongItems(items, options) : '';
  }

  function buildLocalSongListDisplayOutput(sourceText) {
    return buildLocalSongListOutput(sourceText, { includeTimestamps: true });
  }

  function buildSecondPassSongListOutput(aiText, options = {}) {
    const normalized = normalizeText(aiText);
    if (!normalized) return '';

    const localResult = buildLocalSongListOutput(normalized, options);
    if (normalizeText(localResult)) return localResult;

    const aiItems = normalizeArtistDisplay(
      parseAiSongList(normalized).filter(item => !item.__special_no_artist__)
    );

    return aiItems.length ? formatSongItems(aiItems, options) : normalized;
  }

  function normalizeAiSongListOutput(aiText, sourceText) {
    const normalizedAiText = normalizeText(aiText);
    if (!normalizedAiText) return normalizedAiText;

    const sourceStructured = extractStructuredSongsFromSourceTimeline(sourceText);
    const sourceIsContiguous = isContiguousStructuredSetlist(sourceStructured);
    const sourcePlain = extractPlainSongsFromSourceTimeline(sourceText);

    const sourceStructuredItems = normalizeArtistDisplay(sourceStructured.map(item => ({
      song: item.song,
      artist: item.artist,
      timestampSeconds: item.timestampSeconds,
      timestampLabel: item.timestampLabel
    })));
    const sourceStructuredMostlyAscending = isMostlyAscendingStructuredSetlist(sourceStructured);

    const bestSourceItems =
      sourceIsContiguous && sourceStructuredItems.length >= sourcePlain.length
        ? sourceStructuredItems
        : sourcePlain.length >= sourceStructuredItems.length
          ? sourcePlain
          : sourceStructuredItems;

    group('本地纠正判定', () => {
      log('原文结构化曲目数量', sourceStructured.length);
      log('原文是否连续编号曲目表', sourceIsContiguous);
      log('原文是否基本递增编号曲目表', sourceStructuredMostlyAscending);
      log('原文普通时间轴可提取数量', sourcePlain.length);
      log('原文最佳兜底数量', bestSourceItems.length);
    });

    if (isSpecialNoArtistResponse(normalizedAiText)) {
      if (bestSourceItems.length) {
        log('AI 误判为“缺少歌手”，改用原文本地提取结果');
        return formatSongItems(bestSourceItems);
      }
      return '请提供歌手信息后再处理。';
    }

    const aiItemsRaw = parseAiSongList(normalizedAiText);
    if (aiItemsRaw.length === 1 && aiItemsRaw[0].__special_no_artist__) {
      if (bestSourceItems.length) {
        log('AI 返回“缺少歌手”特殊提示，改用原文本地提取结果');
        return formatSongItems(bestSourceItems);
      }
      return '请提供歌手信息后再处理。';
    }

    const aiItems = normalizeArtistDisplay(aiItemsRaw.filter(item => !item.__special_no_artist__));

    group('本地纠正判定补充', () => {
      log('AI 解析数量', aiItems.length);
    });

    if (sourceIsContiguous && bestSourceItems.length > 0) {
      const sourceFormatted = formatSongItems(bestSourceItems);

      if (!aiItems.length) {
        log('AI 未提取到有效歌曲，直接采用原文结构化曲目表');
        return sourceFormatted;
      }

      if (aiItems.length !== bestSourceItems.length) {
        log('AI 结果数量与原文结构化曲目数量不一致，采用原文结构化曲目表');
        return sourceFormatted;
      }

      const aiMergedItems = mergeAiItemsWithSourceByOrder(aiItems, bestSourceItems);
      const aiFormatted = formatSongItems(aiMergedItems);

      return aiFormatted;
    }

    if (aiItems.length && bestSourceItems.length && aiItems.length === bestSourceItems.length) {
      const mergedItems = mergeAiItemsWithSourceByOrder(aiItems, bestSourceItems);
      log('AI 结果数量与原文本地提取数量一致，按顺序强兜底合并原文与低风险纠错');
      return formatSongItems(mergedItems);
    }

    if (aiItems.length && bestSourceItems.length > aiItems.length) {
      log('原文本地提取结果比 AI 更完整，采用原文本地提取结果', {
        aiCount: aiItems.length,
        sourceCount: bestSourceItems.length
      });
      return formatSongItems(bestSourceItems);
    }

    if (aiItems.length) {
      return formatSongItems(aiItems);
    }

    if (bestSourceItems.length) {
      log('AI 未成功提取，采用原文本地提取结果');
      return formatSongItems(bestSourceItems);
    }

    log('本地纠正未提取到有效歌曲行，保留原始结果', {
      preview: normalizedAiText.slice(0, 300)
    });

    return normalizedAiText;
  }

  function requestAIText(config, commentText, promptTemplate, label) {
    return new Promise((resolve, reject) => {
      if (!config.apiKey) {
        reject(new Error('请先填写 API Key'));
        return;
      }

      const apiBase = (config.apiBase || DEFAULT_API_BASE).replace(/\/+$/, '');
      const url = `${apiBase}/chat/completions`;

      const payload = {
        model: config.model || DEFAULT_MODEL,
        messages: [
          {
            role: 'user',
            content: buildUserInput(commentText, promptTemplate)
          }
        ],
        temperature: 0
      };

      log('准备请求 AI', {
        url,
        model: payload.model,
        label,
        bodyLength: JSON.stringify(payload).length
      });

      GM_xmlhttpRequest({
        method: 'POST',
        url,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${config.apiKey}`
        },
        data: JSON.stringify(payload),
        timeout: 120000,
        onload: (res) => {
          group(`${label || 'AI'} 响应`, () => {
            log('HTTP 状态', res.status);
            log('响应前 500 字', (res.responseText || '').slice(0, 500));
          });

          try {
            if (res.status < 200 || res.status >= 300) {
              throw new Error(`接口请求失败：HTTP ${res.status}\n${res.responseText || ''}`.trim());
            }

            const json = JSON.parse(res.responseText);
            const text = parseOpenAIStyleResponse(json);

            if (!text) {
              throw new Error('接口返回成功，但没有解析到文本结果');
            }

            const normalized = normalizeText(text);
            log('AI 文本解析成功', {
              label,
              textLength: normalized.length,
              preview: normalized.slice(0, 300)
            });

            resolve(normalized);
          } catch (err) {
            error('AI 解析失败', err);
            reject(err);
          }
        },
        onerror: (errObj) => {
          error('AI 请求网络错误', errObj);
          reject(new Error(`网络错误：${JSON.stringify(errObj)}`));
        },
        ontimeout: () => {
          error('AI 请求超时');
          reject(new Error('请求超时'));
        }
      });
    });
  }

  function callAI(config, commentText) {
    return Promise.all([
      requestAIText(config, commentText, AI_CLEAN_PROMPT_TEMPLATE, 'AI 清脏'),
      requestAIText(config, commentText, AI_DIRECT_PROMPT_TEMPLATE, 'AI 直接整理原文')
    ]).then(([aiCleanText, aiDirectText]) => {
      const aiCleanResult = normalizeText(aiCleanText);
      const secondPassResult = buildSecondPassSongListOutput(aiCleanResult, { includeTimestamps: true });
      const directResult = normalizeText(aiDirectText);

      log('AI 多结果整理完成', {
        aiCleanLines: countResultLines(aiCleanResult),
        secondPassLines: countResultLines(secondPassResult),
        directLines: countResultLines(directResult)
      });

      return {
        aiCleanResult,
        secondPassResult,
        directResult
      };
    });
  }

  function makeTextButton(className, text, title) {
    const btn = document.createElement('button');
    btn.className = className;
    btn.type = 'button';
    btn.textContent = text;
    btn.title = title || '';
    return btn;
  }

  function makeTabButton(name, text, active = false) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'yt-comment-ai-tab' + (active ? ' is-active' : '');
    btn.dataset.tab = name;
    btn.textContent = text;
    return btn;
  }

  function makePanel(name, active = false) {
    const div = document.createElement('div');
    div.className = 'yt-comment-ai-tab-panel' + (active ? ' is-active' : '');
    div.dataset.panel = name;
    return div;
  }

  function makeLabel(text) {
    const label = document.createElement('label');
    label.className = 'yt-comment-ai-label';
    label.textContent = text;
    return label;
  }

  function ensureModal() {
    let modal = document.getElementById('yt-comment-ai-modal');
    if (modal) return modal;

    log('创建弹窗（Trusted Types 安全版）');

    modal = document.createElement('div');
    modal.id = 'yt-comment-ai-modal';

    const mask = document.createElement('div');
    mask.className = 'yt-comment-ai-mask';

    const panel = document.createElement('div');
    panel.className = 'yt-comment-ai-panel';

    const header = document.createElement('div');
    header.className = 'yt-comment-ai-header';

    const title = document.createElement('div');
    title.className = 'yt-comment-ai-title';
    title.textContent = '评论 AI 整理';

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'yt-comment-ai-close';
    closeBtn.textContent = '×';

    header.appendChild(title);
    header.appendChild(closeBtn);

    const body = document.createElement('div');
    body.className = 'yt-comment-ai-body';

    const tabs = document.createElement('div');
    tabs.className = 'yt-comment-ai-tabs';

    const tabResult = makeTabButton('result', '结果', true);
    const tabSettings = makeTabButton('settings', '设置', false);
    const tabSource = makeTabButton('source', '原文', false);

    tabs.appendChild(tabResult);
    tabs.appendChild(tabSettings);
    tabs.appendChild(tabSource);

    const panelResult = makePanel('result', true);
    const panelSettings = makePanel('settings', false);
    const panelSource = makePanel('source', false);

    const localResultLabel = makeLabel('代码清洗结果');
    const localResultTextarea = document.createElement('textarea');
    localResultTextarea.className = 'yt-comment-ai-textarea';
    localResultTextarea.id = 'yt-comment-ai-local-result';
    localResultTextarea.placeholder = '这里会显示脚本本地规则先清洗出的结果';

    const localTimedResultLabel = makeLabel('带时间轴结果');
    const localTimedResultTextarea = document.createElement('textarea');
    localTimedResultTextarea.className = 'yt-comment-ai-textarea';
    localTimedResultTextarea.id = 'yt-comment-ai-local-timed-result';
    localTimedResultTextarea.placeholder = '这里会显示带原始时间戳的本地规则清洗结果';

    const aiCleanResultLabel = makeLabel('AI 清脏结果');
    const aiCleanResultTextarea = document.createElement('textarea');
    aiCleanResultTextarea.className = 'yt-comment-ai-textarea';
    aiCleanResultTextarea.id = 'yt-comment-ai-ai-clean-result';
    aiCleanResultTextarea.placeholder = '点击“用当前原文请求 AI”后，这里会显示 AI 只清脏后的结果';

    const aiSecondPassResultLabel = makeLabel('AI 清脏后二次代码清洗');
    const resultTextarea = document.createElement('textarea');
    resultTextarea.className = 'yt-comment-ai-textarea';
    resultTextarea.id = 'yt-comment-ai-result';
    resultTextarea.placeholder = '点击“用当前原文请求 AI”后，这里会显示 AI 清脏结果再经过本地规则清洗后的结果';

    const aiDirectResultLabel = makeLabel('AI 直接整理原文');
    const directResultTextarea = document.createElement('textarea');
    directResultTextarea.className = 'yt-comment-ai-textarea';
    directResultTextarea.id = 'yt-comment-ai-direct-result';
    directResultTextarea.placeholder = '点击“用当前原文请求 AI”后，这里会显示 AI 直接从原文整理出的结果';

    const resultActions = document.createElement('div');
    resultActions.className = 'yt-comment-ai-actions';

    const copyLocalResultBtn = document.createElement('button');
    copyLocalResultBtn.type = 'button';
    copyLocalResultBtn.id = 'yt-comment-ai-copy-local-result';
    copyLocalResultBtn.textContent = '复制代码结果';

    const copyLocalTimedResultBtn = document.createElement('button');
    copyLocalTimedResultBtn.type = 'button';
    copyLocalTimedResultBtn.id = 'yt-comment-ai-copy-local-timed-result';
    copyLocalTimedResultBtn.textContent = '复制带时间轴';

    const copyResultBtn = document.createElement('button');
    copyResultBtn.type = 'button';
    copyResultBtn.id = 'yt-comment-ai-copy-result';
    copyResultBtn.textContent = '复制二次清洗';

    const copyAiCleanResultBtn = document.createElement('button');
    copyAiCleanResultBtn.type = 'button';
    copyAiCleanResultBtn.id = 'yt-comment-ai-copy-ai-clean-result';
    copyAiCleanResultBtn.textContent = '复制 AI 清脏';

    const copyDirectResultBtn = document.createElement('button');
    copyDirectResultBtn.type = 'button';
    copyDirectResultBtn.id = 'yt-comment-ai-copy-direct-result';
    copyDirectResultBtn.textContent = '复制 AI 直出';

    const rerunBtn = document.createElement('button');
    rerunBtn.type = 'button';
    rerunBtn.id = 'yt-comment-ai-run-again';
    rerunBtn.textContent = '用当前原文请求 AI';

    resultActions.appendChild(copyLocalResultBtn);
    resultActions.appendChild(copyLocalTimedResultBtn);
    resultActions.appendChild(copyAiCleanResultBtn);
    resultActions.appendChild(copyResultBtn);
    resultActions.appendChild(copyDirectResultBtn);
    resultActions.appendChild(rerunBtn);
    panelResult.appendChild(localResultLabel);
    panelResult.appendChild(localResultTextarea);
    panelResult.appendChild(localTimedResultLabel);
    panelResult.appendChild(localTimedResultTextarea);
    panelResult.appendChild(aiCleanResultLabel);
    panelResult.appendChild(aiCleanResultTextarea);
    panelResult.appendChild(aiSecondPassResultLabel);
    panelResult.appendChild(resultTextarea);
    panelResult.appendChild(aiDirectResultLabel);
    panelResult.appendChild(directResultTextarea);
    panelResult.appendChild(resultActions);

    const apiBaseLabel = makeLabel('API Base URL');
    const apiBaseInput = document.createElement('input');
    apiBaseInput.type = 'text';
    apiBaseInput.id = 'yt-comment-ai-api-base';
    apiBaseInput.placeholder = 'https://api.openai.com/v1';

    const modelLabel = makeLabel('模型名称');
    const modelInput = document.createElement('input');
    modelInput.type = 'text';
    modelInput.id = 'yt-comment-ai-model';
    modelInput.placeholder = 'gpt-4.1-mini';

    const apiKeyLabel = makeLabel('API Key');
    const apiKeyInput = document.createElement('input');
    apiKeyInput.type = 'password';
    apiKeyInput.id = 'yt-comment-ai-api-key';
    apiKeyInput.placeholder = 'sk-...';

    const settingsActions = document.createElement('div');
    settingsActions.className = 'yt-comment-ai-actions';

    const saveBtn = document.createElement('button');
    saveBtn.type = 'button';
    saveBtn.id = 'yt-comment-ai-save-settings';
    saveBtn.textContent = '保存设置';

    settingsActions.appendChild(saveBtn);

    panelSettings.appendChild(apiBaseLabel);
    panelSettings.appendChild(apiBaseInput);
    panelSettings.appendChild(modelLabel);
    panelSettings.appendChild(modelInput);
    panelSettings.appendChild(apiKeyLabel);
    panelSettings.appendChild(apiKeyInput);
    panelSettings.appendChild(settingsActions);

    const sourceTextarea = document.createElement('textarea');
    sourceTextarea.className = 'yt-comment-ai-textarea';
    sourceTextarea.id = 'yt-comment-ai-source';
    sourceTextarea.placeholder = '这里会显示发送给 AI 的预处理后文本，可直接修改后再请求 AI';

    const sourceActions = document.createElement('div');
    sourceActions.className = 'yt-comment-ai-actions';

    const copySourceBtn = document.createElement('button');
    copySourceBtn.type = 'button';
    copySourceBtn.id = 'yt-comment-ai-copy-source';
    copySourceBtn.textContent = '复制发送内容';

    const runFromSourceBtn = document.createElement('button');
    runFromSourceBtn.type = 'button';
    runFromSourceBtn.id = 'yt-comment-ai-run-from-source';
    runFromSourceBtn.textContent = '用当前原文请求 AI';

    sourceActions.appendChild(copySourceBtn);
    sourceActions.appendChild(runFromSourceBtn);
    panelSource.appendChild(sourceTextarea);
    panelSource.appendChild(sourceActions);

    const status = document.createElement('div');
    status.className = 'yt-comment-ai-status';
    status.id = 'yt-comment-ai-status';

    body.appendChild(tabs);
    body.appendChild(panelResult);
    body.appendChild(panelSettings);
    body.appendChild(panelSource);
    body.appendChild(status);

    panel.appendChild(header);
    panel.appendChild(body);

    modal.appendChild(mask);
    modal.appendChild(panel);

    document.body.appendChild(modal);

    mask.addEventListener('click', closeModal);
    closeBtn.addEventListener('click', closeModal);

    modal.querySelectorAll('.yt-comment-ai-tab').forEach(tab => {
      tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });

    saveBtn.addEventListener('click', () => {
      const config = {
        apiBase: apiBaseInput.value.trim() || DEFAULT_API_BASE,
        model: modelInput.value.trim() || DEFAULT_MODEL,
        apiKey: apiKeyInput.value.trim()
      };
      saveConfig(config);
      setStatus('设置已保存');
    });

    copyLocalResultBtn.addEventListener('click', async () => {
      let text = localResultTextarea.value || '';
      let copiedFallback = false;

      if (!normalizeText(text) && normalizeText(localTimedResultTextarea.value || '')) {
        text = localTimedResultTextarea.value || '';
        copiedFallback = true;
      } else if (!normalizeText(text) && normalizeText(resultTextarea.value || '')) {
        text = resultTextarea.value || '';
        copiedFallback = true;
      } else if (!normalizeText(text) && normalizeText(aiCleanResultTextarea.value || '')) {
        text = aiCleanResultTextarea.value || '';
        copiedFallback = true;
      } else if (!normalizeText(text) && normalizeText(directResultTextarea.value || '')) {
        text = directResultTextarea.value || '';
        copiedFallback = true;
      }

      try {
        await copyPlainText(text);
        setStatus(copiedFallback ? '代码结果为空，已复制可用 AI 结果' : '已复制代码结果');
      } catch (err) {
        setStatus(`复制失败：${err.message || err}`, true);
      }
    });

    copyLocalTimedResultBtn.addEventListener('click', async () => {
      let text = localTimedResultTextarea.value || '';
      let copiedFallback = false;

      if (!normalizeText(text) && normalizeText(localResultTextarea.value || '')) {
        text = localResultTextarea.value || '';
        copiedFallback = true;
      } else if (!normalizeText(text) && normalizeText(resultTextarea.value || '')) {
        text = resultTextarea.value || '';
        copiedFallback = true;
      } else if (!normalizeText(text) && normalizeText(aiCleanResultTextarea.value || '')) {
        text = aiCleanResultTextarea.value || '';
        copiedFallback = true;
      } else if (!normalizeText(text) && normalizeText(directResultTextarea.value || '')) {
        text = directResultTextarea.value || '';
        copiedFallback = true;
      }

      try {
        await copyPlainText(text);
        setStatus(copiedFallback ? '带时间轴结果为空，已复制可用结果' : '已复制带时间轴结果');
      } catch (err) {
        setStatus(`复制失败：${err.message || err}`, true);
      }
    });

    copyAiCleanResultBtn.addEventListener('click', async () => {
      const text = aiCleanResultTextarea.value || '';
      try {
        await copyPlainText(text);
        setStatus('已复制 AI 清脏结果');
      } catch (err) {
        setStatus(`复制失败：${err.message || err}`, true);
      }
    });

    copyResultBtn.addEventListener('click', async () => {
      const text = resultTextarea.value || '';
      try {
        await copyPlainText(text);
        setStatus('已复制二次清洗结果');
      } catch (err) {
        setStatus(`复制失败：${err.message || err}`, true);
      }
    });

    copyDirectResultBtn.addEventListener('click', async () => {
      const text = directResultTextarea.value || '';
      try {
        await copyPlainText(text);
        setStatus('已复制 AI 直出结果');
      } catch (err) {
        setStatus(`复制失败：${err.message || err}`, true);
      }
    });

    copySourceBtn.addEventListener('click', async () => {
      const text = sourceTextarea.value || '';
      try {
        await copyPlainText(text);
        setStatus('已复制');
      } catch (err) {
        setStatus(`复制失败：${err.message || err}`, true);
      }
    });

    async function rerunFromCurrentSource() {
      const currentSourceText = (sourceTextarea.value || '').trim();
      const preparedText = normalizeText(currentSourceText);

      if (!preparedText) {
        setStatus('没有可请求 AI 的原文');
        return;
      }

      try {
        modal.dataset.commentText = preparedText;
        sourceTextarea.value = preparedText;
        const localResult = buildLocalSongListOutput(preparedText);
        const localTimedResult = buildLocalSongListDisplayOutput(preparedText);
        const localCount = countResultLines(localResult);
        const localTimedCount = countResultLines(localTimedResult);
        localResultTextarea.value = localResult;
        localTimedResultTextarea.value = localTimedResult;
        aiCleanResultTextarea.value = '';
        resultTextarea.value = '';
        directResultTextarea.value = '';
        switchTab('result');
        setStatus(
          localCount > 0 || localTimedCount > 0
            ? `代码清洗完成：纯歌单 ${localCount} 首，带时间轴 ${localTimedCount} 首，正在请求 AI 清脏和 AI 直出...`
            : '代码清洗无结果，正在请求 AI 清脏和 AI 直出...'
        );
        await waitForNextPaint();
        const config = readModalConfig();
        saveConfig(config);
        const result = await callAI(config, preparedText);
        if (!normalizeText(localResultTextarea.value || '')) {
          localResultTextarea.value = buildLocalSongListOutput(preparedText) || result.secondPassResult || result.directResult || result.aiCleanResult;
        }
        if (!normalizeText(localTimedResultTextarea.value || '')) {
          localTimedResultTextarea.value = buildLocalSongListDisplayOutput(preparedText) || localResultTextarea.value || result.secondPassResult || result.directResult || result.aiCleanResult;
        }
        aiCleanResultTextarea.value = result.aiCleanResult || '';
        resultTextarea.value = result.secondPassResult || '';
        directResultTextarea.value = result.directResult || '';
        setStatus(`整理完成：纯歌单 ${countResultLines(localResultTextarea.value)} 首，带时间轴 ${countResultLines(localTimedResultTextarea.value)} 首，AI 清脏 ${countResultLines(aiCleanResultTextarea.value)} 首，二次清洗 ${countResultLines(resultTextarea.value)} 首，AI 直出 ${countResultLines(directResultTextarea.value)} 首`);
      } catch (err) {
        setStatus(err.message || String(err), true);
      }
    }

    rerunBtn.addEventListener('click', rerunFromCurrentSource);
    runFromSourceBtn.addEventListener('click', rerunFromCurrentSource);

    return modal;
  }

  function readModalConfig() {
    const modal = ensureModal();
    return {
      apiBase: modal.querySelector('#yt-comment-ai-api-base').value.trim() || DEFAULT_API_BASE,
      model: modal.querySelector('#yt-comment-ai-model').value.trim() || DEFAULT_MODEL,
      apiKey: modal.querySelector('#yt-comment-ai-api-key').value.trim()
    };
  }

  function fillModalConfig() {
    const modal = ensureModal();
    const config = getConfig();
    const apiBaseInput = modal.querySelector('#yt-comment-ai-api-base');
    const modelInput = modal.querySelector('#yt-comment-ai-model');
    const apiKeyInput = modal.querySelector('#yt-comment-ai-api-key');

    if (apiBaseInput) apiBaseInput.value = config.apiBase || DEFAULT_API_BASE;
    if (modelInput) modelInput.value = config.model || DEFAULT_MODEL;
    if (apiKeyInput) apiKeyInput.value = config.apiKey || '';
  }

  function switchTab(tabName) {
    const modal = ensureModal();
    log('切换弹窗标签', tabName);

    modal.querySelectorAll('.yt-comment-ai-tab').forEach(el => {
      el.classList.toggle('is-active', el.dataset.tab === tabName);
    });

    modal.querySelectorAll('.yt-comment-ai-tab-panel').forEach(el => {
      el.classList.toggle('is-active', el.dataset.panel === tabName);
    });
  }

  function setStatus(message, isError = false) {
    const modal = ensureModal();
    const status = modal.querySelector('#yt-comment-ai-status');
    if (!status) return;
    status.textContent = message || '';
    status.dataset.error = isError ? '1' : '0';
    log('状态更新', { message, isError });
  }

  function waitForNextPaint() {
    return new Promise(resolve => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
  }

  function openModal({ sourceText = '', localResultText = '', localTimedResultText = '', aiCleanResultText = '', resultText = '', directResultText = '', statusText = '' } = {}) {
    const modal = ensureModal();
    fillModalConfig();

    const source = modal.querySelector('#yt-comment-ai-source');
    const localResult = modal.querySelector('#yt-comment-ai-local-result');
    const localTimedResult = modal.querySelector('#yt-comment-ai-local-timed-result');
    const aiCleanResult = modal.querySelector('#yt-comment-ai-ai-clean-result');
    const result = modal.querySelector('#yt-comment-ai-result');
    const directResult = modal.querySelector('#yt-comment-ai-direct-result');

    if (source) source.value = sourceText;
    if (localResult) localResult.value = localResultText;
    if (localTimedResult) localTimedResult.value = localTimedResultText;
    if (aiCleanResult) aiCleanResult.value = aiCleanResultText;
    if (result) result.value = resultText;
    if (directResult) directResult.value = directResultText;
    modal.dataset.commentText = sourceText || '';

    modal.style.display = 'flex';
    setStatus(statusText || '');
    switchTab((localResultText || localTimedResultText || aiCleanResultText || resultText || directResultText) ? 'result' : 'source');

    log('打开弹窗', {
      sourceLength: sourceText.length,
      localResultLength: localResultText.length,
      localTimedResultLength: localTimedResultText.length,
      aiCleanResultLength: aiCleanResultText.length,
      resultLength: resultText.length,
      directResultLength: directResultText.length
    });
  }

  function closeModal() {
    const modal = ensureModal();
    modal.style.display = 'none';
    log('关闭弹窗');
  }

  function extractDomTextWithLineBreaks(content) {
    if (!content) return '';

    const chunks = [];
    const blockTags = new Set([
      'DIV', 'P', 'LI', 'UL', 'OL', 'SECTION', 'ARTICLE', 'HEADER', 'FOOTER',
      'YT-FORMATTED-STRING', 'YT-ATTRIBUTED-STRING', 'YTD-EXPANDABLE-TAB-RENDERER'
    ]);
    const skipSelector = [
      `.${HOST_CLASS}`,
      `.${LOCAL_PANEL_CLASS}`,
      'button',
      'tp-yt-paper-button',
      'ytd-button-renderer',
      'ytd-comment-engagement-bar',
      'yt-formatted-string#more',
      'yt-formatted-string#less',
      '#more',
      '#less'
    ].join(',');

    function appendText(text) {
      if (!text) return;
      chunks.push(text);
    }

    function appendNewline() {
      const last = chunks[chunks.length - 1] || '';
      if (!chunks.length || /\n\s*$/.test(last)) return;
      chunks.push('\n');
    }

    function walk(node) {
      if (!node) return;

      if (node.nodeType === Node.TEXT_NODE) {
        appendText(node.nodeValue || '');
        return;
      }

      if (node.nodeType !== Node.ELEMENT_NODE) return;

      const el = node;
      if (el.matches && el.matches(skipSelector)) return;

      const tag = el.tagName;
      if (tag === 'BR') {
        appendNewline();
        return;
      }

      if (tag === 'IMG' && el.getAttribute('alt')) {
        appendText(el.getAttribute('alt') || '');
        return;
      }

      const shouldBreak = blockTags.has(tag);
      if (shouldBreak && chunks.length) appendNewline();

      for (const child of Array.from(el.childNodes)) {
        walk(child);
      }

      if (shouldBreak) appendNewline();
    }

    walk(content);
    return chunks.join('');
  }

  function makeCommentTextCandidate(raw, source) {
    const splitText = splitCollapsedTimelineText(raw || '');
    const normalized = normalizeText(splitText || raw || '');
    const timestampCount = extractTimelineTimestamps(normalized).length;
    const lineCount = normalized ? normalized.split('\n').length : 0;

    return {
      raw: normalized,
      source,
      timestampCount,
      lineCount,
      length: normalized.length,
      score: timestampCount * 100000 + lineCount * 100 + normalized.length
    };
  }

  function readCommentContentText(content) {
    const visibleRaw = content?.innerText || '';
    let fullRaw = content?.textContent || '';
    let domRaw = '';

    try {
      const clone = content.cloneNode(true);

      clone.querySelectorAll([
        `.${HOST_CLASS}`,
        `.${LOCAL_PANEL_CLASS}`,
        'tp-yt-paper-button',
        'ytd-button-renderer',
        'ytd-comment-engagement-bar',
        'yt-formatted-string#more',
        'yt-formatted-string#less',
        '#more',
        '#less'
      ].join(',')).forEach(node => node.remove());

      clone.querySelectorAll('br').forEach(br => {
        br.replaceWith(document.createTextNode('\n'));
      });

      clone.querySelectorAll('img[alt]').forEach(img => {
        img.replaceWith(document.createTextNode(img.getAttribute('alt') || ''));
      });

      fullRaw = clone.textContent || fullRaw;
      domRaw = extractDomTextWithLineBreaks(clone);
    } catch (err) {
      warn('读取完整评论 DOM 文本失败，回退 textContent/innerText', err);
    }

    const candidates = [
      makeCommentTextCandidate(domRaw, 'dom-walk'),
      makeCommentTextCandidate(fullRaw, 'textContent'),
      makeCommentTextCandidate(visibleRaw, 'innerText')
    ].filter(item => item.raw);

    candidates.sort((a, b) => b.score - a.score);
    const best = candidates[0] || makeCommentTextCandidate(visibleRaw || fullRaw || domRaw, 'fallback');
    const visibleNormalized = makeCommentTextCandidate(visibleRaw, 'innerText');
    const fullNormalized = makeCommentTextCandidate(fullRaw, 'textContent');

    log('评论文本候选', candidates.map(item => ({
      source: item.source,
      timestampCount: item.timestampCount,
      lineCount: item.lineCount,
      length: item.length,
      score: item.score,
      preview: item.raw.slice(0, 120)
    })));

    return {
      raw: best.raw,
      source: best.source,
      visibleLength: visibleNormalized.length,
      fullLength: fullNormalized.length,
      visibleTimestampCount: visibleNormalized.timestampCount,
      fullTimestampCount: fullNormalized.timestampCount
    };
  }

  function getCommentText(commentRoot) {
    const selectors = [
      '#content-text',
      'yt-attributed-string#content-text',
      '#expander #content-text',
      '#expander'
    ];

    let content = null;
    let matchedSelector = '';

    for (const selector of selectors) {
      content = commentRoot.querySelector(selector);
      if (content) {
        matchedSelector = selector;
        break;
      }
    }

    if (!content) {
      warn('未找到评论文本节点', {
        commentRoot: shortNode(commentRoot),
        tried: selectors
      });
      return '';
    }

    const textInfo = readCommentContentText(content);
    const raw = textInfo.raw || '';
    const normalized = normalizeText(raw);

    log('提取评论文本', {
      commentRoot: shortNode(commentRoot),
      selector: matchedSelector,
      source: textInfo.source,
      rawLength: raw.length,
      normalizedLength: normalized.length,
      visibleLength: textInfo.visibleLength,
      fullLength: textInfo.fullLength,
      visibleTimestampCount: textInfo.visibleTimestampCount,
      fullTimestampCount: textInfo.fullTimestampCount,
      preview: normalized.slice(0, 160)
    });

    return normalized;
  }

  function getCommentDebugHtml(commentRoot) {
    if (!commentRoot) return '';

    try {
      return commentRoot.outerHTML || '';
    } catch (err) {
      warn('读取评论 HTML 失败，回退复制纯文本', err);
      return getCommentText(commentRoot);
    }
  }

  function createCopyButton(commentRoot) {
    const btn = makeTextButton(COPY_BTN_CLASS, '复制HTML', '复制该评论 HTML / DOM 结构，方便排查识别问题');
    btn.dataset.oldText = '复制HTML';

    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();

      log('点击复制 HTML 按钮', shortNode(commentRoot));

      try {
        const text = getCommentDebugHtml(commentRoot);
        await copyPlainText(text);
        flashButton(btn, '已复制', true);
      } catch (err) {
        error('复制 HTML 失败', err);
        flashButton(btn, '失败', false);
      }
    });

    return btn;
  }

  function countResultLines(text) {
    return normalizeText(text).split('\n').filter(Boolean).length;
  }

  function getCurrentWatchVideoId() {
    try {
      const url = new URL(location.href);
      const watchVideoId = url.searchParams.get('v');
      if (watchVideoId) return watchVideoId;

      const shortsMatch = location.pathname.match(/^\/shorts\/([^/?#]+)/);
      if (shortsMatch && shortsMatch[1]) return shortsMatch[1];
    } catch (err) {
      warn('读取当前视频 ID 失败', err);
    }

    return '';
  }

  function buildTimestampJumpHref(seconds) {
    const safeSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const videoId = getCurrentWatchVideoId();

    if (videoId) {
      return `/watch?v=${encodeURIComponent(videoId)}&t=${safeSeconds}s`;
    }

    try {
      const url = new URL(location.href);
      url.searchParams.set('t', `${safeSeconds}s`);
      url.hash = '';
      return `${url.pathname}${url.search}${url.hash}`;
    } catch (err) {
      return `?t=${safeSeconds}s`;
    }
  }

  function updateBrowserUrlForTimestamp(href) {
    try {
      const url = new URL(href, location.origin);
      history.pushState(history.state, '', `${url.pathname}${url.search}${url.hash}`);
      return true;
    } catch (err) {
      warn('更新时间戳 URL 失败', err);
      return false;
    }
  }

  function seekVideoElementToSeconds(seconds) {
    const safeSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
    const video = document.querySelector('video');
    if (!video) return false;

    try {
      video.currentTime = safeSeconds;
      video.dispatchEvent(new Event('seeking', { bubbles: true }));
      video.dispatchEvent(new Event('timeupdate', { bubbles: true }));
      return true;
    } catch (err) {
      warn('设置 video.currentTime 失败', err);
      return false;
    }
  }

  function jumpToYouTubeTimestamp(seconds, href) {
    const safeSeconds = Math.max(0, Math.floor(Number(seconds) || 0));

    try {
      const currentVideoId = getCurrentWatchVideoId();
      const targetUrl = new URL(href, location.origin);
      const targetVideoId = targetUrl.searchParams.get('v') || currentVideoId;

      if (currentVideoId && targetVideoId && currentVideoId !== targetVideoId) {
        location.href = `${targetUrl.pathname}${targetUrl.search}${targetUrl.hash}`;
        return true;
      }

      updateBrowserUrlForTimestamp(href);

      // YouTube 的 SPA 有时会吞掉第一次自定义链接点击；这里立即 seek，再短延迟补两次，确保第一次点击就到位。
      let jumped = seekVideoElementToSeconds(safeSeconds);
      [80, 260, 600].forEach(delay => {
        setTimeout(() => {
          seekVideoElementToSeconds(safeSeconds);
        }, delay);
      });

      return jumped;
    } catch (err) {
      warn('直接跳转视频时间失败，回退为链接跳转', err);
    }

    return false;
  }

  function parseTimestampedOutputLine(line) {
    const raw = normalizeTimelineMarkerChars(line || '').trim();
    if (!raw) return null;

    const match = raw.match(/^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+)$/u);
    if (!match) return null;

    const seconds = timestampToSeconds(match[1]);
    if (seconds === null) return null;

    return {
      timestamp: match[1],
      seconds,
      body: match[2].trim()
    };
  }

  function renderClickableTimedResult(container, text) {
    if (!container) return;

    container.textContent = '';

    const normalized = normalizeText(text || '');
    if (!normalized) {
      container.dataset.empty = '1';
      return;
    }

    container.dataset.empty = '0';

    normalized.split('\n').forEach(line => {
      const row = document.createElement('div');
      row.className = 'yt-comment-local-timed-row';

      const parsed = parseTimestampedOutputLine(line);
      if (!parsed) {
        row.textContent = line;
        container.appendChild(row);
        return;
      }

      const href = buildTimestampJumpHref(parsed.seconds);
      const link = document.createElement('a');
      link.className = 'yt-simple-endpoint yt-comment-local-time-link';
      link.href = href;
      link.target = '';
      link.tabIndex = 0;
      link.setAttribute('force-new-state', 'true');
      link.dataset.seconds = String(parsed.seconds);
      link.textContent = parsed.timestamp;
      link.title = `跳转到 ${parsed.timestamp}`;

      link.addEventListener('click', (e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button === 1) {
          return;
        }

        e.preventDefault();
        e.stopPropagation();

        const jumped = jumpToYouTubeTimestamp(parsed.seconds, href);
        if (!jumped) {
          location.href = href;
        }
      });

      const body = document.createElement('span');
      body.className = 'yt-comment-local-timed-body';
      body.textContent = ` ${parsed.body}`;

      row.appendChild(link);
      row.appendChild(body);
      container.appendChild(row);
    });
  }

  function createInlineLocalResultPanel(commentRoot, localResult, localTimedResult) {
    const panel = document.createElement('div');
    panel.className = LOCAL_PANEL_CLASS;

    const header = document.createElement('div');
    header.className = 'yt-comment-local-result-header';

    const titleWrap = document.createElement('div');
    titleWrap.className = 'yt-comment-local-result-title-wrap';

    const title = document.createElement('span');
    title.className = 'yt-comment-local-result-title';
    title.textContent = '代码清洗结果';

    const meta = document.createElement('span');
    meta.className = 'yt-comment-local-result-meta';
    meta.dataset.role = 'local-result-meta';

    titleWrap.appendChild(title);
    titleWrap.appendChild(meta);

    const actions = document.createElement('div');
    actions.className = 'yt-comment-local-result-actions';

    const copyBtn = makeTextButton(LOCAL_COPY_BTN_CLASS, '复制纯歌单', '复制不带时间轴的本地代码清洗结果');
    copyBtn.dataset.oldText = '复制纯歌单';
    copyBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const textarea = panel.querySelector('[data-role="local-result"]');
      const text = textarea ? textarea.value : localResult;

      try {
        await copyPlainText(text);
        flashButton(copyBtn, '已复制', true);
      } catch (err) {
        error('复制代码清洗结果失败', err);
        flashButton(copyBtn, '失败', false);
      }
    });

    const copyTimedBtn = makeTextButton(LOCAL_COPY_BTN_CLASS, '复制带时间', '复制带时间轴的本地代码清洗结果');
    copyTimedBtn.dataset.oldText = '复制带时间';
    copyTimedBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const textarea = panel.querySelector('[data-role="local-timed-result"]');
      const text = textarea ? textarea.value : localTimedResult;

      try {
        await copyPlainText(text);
        flashButton(copyTimedBtn, '已复制', true);
      } catch (err) {
        error('复制带时间轴代码清洗结果失败', err);
        flashButton(copyTimedBtn, '失败', false);
      }
    });

    const toggleBtn = makeTextButton(LOCAL_COPY_BTN_CLASS, '收起', '展开或收起代码清洗结果');
    toggleBtn.dataset.oldText = '收起';
    toggleBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();

      const collapsed = panel.dataset.collapsed === '1';
      panel.dataset.collapsed = collapsed ? '0' : '1';
      toggleBtn.textContent = collapsed ? '收起' : '展开';
      toggleBtn.dataset.oldText = toggleBtn.textContent;
    });

    actions.appendChild(copyBtn);
    actions.appendChild(copyTimedBtn);
    actions.appendChild(toggleBtn);
    header.appendChild(titleWrap);
    header.appendChild(actions);

    const localSubtitle = document.createElement('div');
    localSubtitle.className = 'yt-comment-local-result-subtitle';
    localSubtitle.textContent = '纯歌单';

    const textarea = document.createElement('textarea');
    textarea.className = 'yt-comment-local-result-textarea';
    textarea.dataset.role = 'local-result';
    textarea.readOnly = true;
    textarea.spellcheck = false;

    const timedSubtitle = document.createElement('div');
    timedSubtitle.className = 'yt-comment-local-result-subtitle';
    timedSubtitle.textContent = '带时间轴';

    const timedLinks = document.createElement('div');
    timedLinks.className = 'yt-comment-local-timed-links';
    timedLinks.dataset.role = 'local-timed-result-links';

    const timedTextarea = document.createElement('textarea');
    timedTextarea.className = 'yt-comment-local-result-textarea yt-comment-local-copy-source';
    timedTextarea.dataset.role = 'local-timed-result';
    timedTextarea.readOnly = true;
    timedTextarea.spellcheck = false;
    timedTextarea.setAttribute('aria-hidden', 'true');
    timedTextarea.tabIndex = -1;

    panel.appendChild(header);
    panel.appendChild(localSubtitle);
    panel.appendChild(textarea);
    panel.appendChild(timedSubtitle);
    panel.appendChild(timedLinks);
    panel.appendChild(timedTextarea);

    updateInlineLocalResultPanel(panel, localResult, localTimedResult);

    log('创建代码清洗外显面板', {
      commentRoot: shortNode(commentRoot),
      lines: countResultLines(localResult),
      timedLines: countResultLines(localTimedResult)
    });

    return panel;
  }

  function updateInlineTextarea(textarea, text, count) {
    if (!textarea) return;

    if (textarea.value !== text) {
      textarea.value = text;
    }

    textarea.rows = Math.min(Math.max(count + 1, 4), 120);
    textarea.style.height = 'auto';
    requestAnimationFrame(() => {
      textarea.style.height = `${textarea.scrollHeight + 2}px`;
    });
  }

  function updateInlineLocalResultPanel(panel, localResult, localTimedResult) {
    if (!panel) return;

    const text = localResult || '';
    const timedText = localTimedResult || '';
    const count = countResultLines(text);
    const timedCount = countResultLines(timedText);
    const textarea = panel.querySelector('[data-role="local-result"]');
    const timedTextarea = panel.querySelector('[data-role="local-timed-result"]');
    const timedLinks = panel.querySelector('[data-role="local-timed-result-links"]');
    const meta = panel.querySelector('[data-role="local-result-meta"]');

    updateInlineTextarea(textarea, text, count);
    if (timedTextarea && timedTextarea.value !== timedText) {
      timedTextarea.value = timedText;
    }
    renderClickableTimedResult(timedLinks, timedText);

    if (meta) {
      meta.textContent = count > 0 || timedCount > 0
        ? `纯歌单 ${count} 首 / 带时间 ${timedCount} 首`
        : '';
    }
  }

  function ensureInlineLocalResultPanel(commentRoot, main, localResult, localTimedResult) {
    const existing = commentRoot.querySelector(`.${LOCAL_PANEL_CLASS}`);
    const text = normalizeText(localResult || '');
    const timedText = normalizeText(localTimedResult || '');

    if (!text && !timedText) {
      if (existing) {
        existing.remove();
        log('移除空代码清洗外显面板', shortNode(commentRoot));
      }
      return;
    }

    if (existing) {
      updateInlineLocalResultPanel(existing, text, timedText);
      return;
    }

    const panel = createInlineLocalResultPanel(commentRoot, text, timedText);
    const actionButtons = main.querySelector('#action-buttons, ytd-comment-engagement-bar');

    if (actionButtons && actionButtons.parentNode === main) {
      main.insertBefore(panel, actionButtons);
    } else {
      main.appendChild(panel);
    }
  }


  function normalizeSongListSignature(text) {
    const normalized = normalizeText(text || '');
    if (!normalized) return '';

    return normalized
      .split('\n')
      .map(line => line.replace(/^\d{1,3}\.\s*/u, '').trim())
      .filter(Boolean)
      .join('\n')
      .normalize('NFKC')
      .replace(/[\s　]+/g, '')
      .toLowerCase();
  }

  function getInlinePanelSignature(panel) {
    if (!panel) return '';
    const local = panel.querySelector('[data-role="local-result"]')?.value || '';
    const timed = panel.querySelector('[data-role="local-timed-result"]')?.value || '';

    // 优先用“带时间轴”做去重签名。
    // 不同评论可能歌单完全相同，但校正后的时间戳不同；旧逻辑只看纯歌单，会把后面的结果面板误删。
    return normalizeSongListSignature(timed) || normalizeSongListSignature(local);
  }

  function dedupeInlineLocalResultPanels() {
    const panels = Array.from(document.querySelectorAll(`.${LOCAL_PANEL_CLASS}`));
    const seen = new Map();
    let removed = 0;

    for (const panel of panels) {
      const signature = getInlinePanelSignature(panel);
      if (!signature) continue;

      if (!seen.has(signature)) {
        seen.set(signature, panel);
        panel.dataset.mergedDuplicate = '0';
        continue;
      }

      panel.remove();
      removed += 1;
    }

    if (removed > 0) {
      log('已合并重复代码清洗结果面板（按带时间轴签名去重）', { removed });
    }

    return removed;
  }

  function syncAIButtonForTimestampState(commentRoot, hasTimestamp) {
    const host = commentRoot.querySelector(`.${HOST_CLASS}`);
    if (!host) return;

    const aiButton = host.querySelector(`.${AI_BTN_CLASS}`);
    const settingsButton = host.querySelector(`.${SETTINGS_BTN_CLASS}`);

    if (hasTimestamp && !aiButton) {
      host.insertBefore(createAIButton(commentRoot), settingsButton || null);
      log('已补充 AI整理 兜底按钮', shortNode(commentRoot));
    } else if (!hasTimestamp && aiButton) {
      aiButton.remove();
      log('已移除无时间戳评论的 AI整理 按钮', shortNode(commentRoot));
    }
  }

  function createAIButton(commentRoot) {
    const btn = makeTextButton(AI_BTN_CLASS, 'AI整理', '打开可编辑原文，确认后再调用 AI 兜底整理');
    btn.dataset.oldText = 'AI整理';

    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();

      log('点击 AI整理 兜底入口', shortNode(commentRoot));

      const rawCommentText = getCommentText(commentRoot);
      if (!rawCommentText) {
        warn('AI整理中止：空评论文本');
        flashButton(btn, '空内容', false);
        return;
      }

      const preparedText = preprocessTimelineTextForAI(rawCommentText);
      const localResult = buildLocalSongListOutput(preparedText);
      const localTimedResult = buildLocalSongListDisplayOutput(preparedText);

      openModal({
        sourceText: preparedText,
        localResultText: localResult,
        localTimedResultText: localTimedResult,
        resultText: '',
        statusText: '可先修改原文，再点击“用当前原文请求 AI”。'
      });

      const modal = ensureModal();
      modal.dataset.commentText = preparedText;
    });

    return btn;
  }

  function createSettingsButton() {
    const btn = makeTextButton(SETTINGS_BTN_CLASS, '设置', '配置 API Base URL / 模型 / API Key');

    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      log('点击设置按钮');
      openModal({
        sourceText: '',
        resultText: '',
        statusText: ''
      });
      switchTab('settings');
    });

    return btn;
  }

  let timestampCommentOriginalIndex = 1;
  let isSortingTimestampComments = false;

  function resolveCommentRoot(node) {
    if (!node || !(node instanceof Element)) return null;

    if (node.matches('ytd-comment-view-model, ytd-comment-renderer')) {
      return node;
    }

    if (node.matches('ytd-comment-thread-renderer')) {
      return node.querySelector('ytd-comment-view-model, ytd-comment-renderer');
    }

    return node.closest('ytd-comment-view-model, ytd-comment-renderer');
  }

  function resolveCommentThread(commentRoot) {
    if (!commentRoot || !(commentRoot instanceof Element)) return null;
    if (commentRoot.matches('ytd-comment-thread-renderer')) return commentRoot;
    return commentRoot.closest('ytd-comment-thread-renderer') || null;
  }

  function setTimestampCommentMetadata(commentRoot, main, timestamps) {
    const list = Array.isArray(timestamps) ? timestamps : [];
    const hasTimestamp = list.length > 0;

    commentRoot.classList.toggle(TIMESTAMP_COMMENT_CLASS, hasTimestamp);

    // 旧版本曾同时给 #main 加高亮类，会形成两条黄线；这里主动清理掉。
    if (main && main !== commentRoot && main instanceof Element) {
      main.classList.remove(TIMESTAMP_COMMENT_CLASS);
    }

    const thread = resolveCommentThread(commentRoot);
    if (!thread) return;

    if (!thread.dataset.ytCommentOriginalIndex) {
      thread.dataset.ytCommentOriginalIndex = String(timestampCommentOriginalIndex);
      timestampCommentOriginalIndex += 1;
    }

    thread.dataset.ytCommentTimestampCount = String(list.length);
    thread.dataset.ytCommentHasTimestamp = hasTimestamp ? '1' : '0';
  }

  function getTimestampSortContainers() {
    return Array.from(document.querySelectorAll('ytd-item-section-renderer > #contents'))
      .filter(container => Array.from(container.children).some(child => child.matches('ytd-comment-thread-renderer')));
  }

  function getThreadTimestampCount(thread) {
    const value = Number(thread?.dataset?.ytCommentTimestampCount || 0);
    return Number.isFinite(value) && value > 0 ? value : 0;
  }

  function getThreadOriginalIndex(thread, fallback) {
    if (!thread.dataset.ytCommentOriginalIndex) {
      thread.dataset.ytCommentOriginalIndex = String(timestampCommentOriginalIndex);
      timestampCommentOriginalIndex += 1;
    }

    const value = Number(thread.dataset.ytCommentOriginalIndex);
    return Number.isFinite(value) ? value : fallback;
  }

  function sortTimestampCommentThreads() {
    if (isSortingTimestampComments) return 0;

    const containers = getTimestampSortContainers();
    let movedContainers = 0;

    isSortingTimestampComments = true;

    try {
      for (const container of containers) {
        const threads = Array.from(container.children)
          .filter(child => child.matches('ytd-comment-thread-renderer'));

        if (threads.length < 2) continue;
        if (!threads.some(thread => getThreadTimestampCount(thread) > 0)) continue;

        const sortedThreads = threads
          .map((thread, index) => ({
            thread,
            index,
            timestampCount: getThreadTimestampCount(thread),
            originalIndex: getThreadOriginalIndex(thread, index)
          }))
          .sort((a, b) => {
            if (a.timestampCount !== b.timestampCount) {
              return b.timestampCount - a.timestampCount;
            }
            return a.originalIndex - b.originalIndex;
          })
          .map(item => item.thread);

        const changed = sortedThreads.some((thread, index) => thread !== threads[index]);
        if (!changed) continue;

        const anchor = Array.from(container.children)
          .find(child => !child.matches('ytd-comment-thread-renderer')) || null;

        sortedThreads.forEach(thread => {
          container.insertBefore(thread, anchor);
        });

        movedContainers += 1;
      }
    } finally {
      isSortingTimestampComments = false;
    }

    if (movedContainers > 0) {
      log('已前置时间戳评论', { movedContainers });
    }

    return movedContainers;
  }

  function ensureButton(commentRoot) {
    if (!commentRoot) {
      warn('ensureButton 收到空 commentRoot');
      return;
    }

    const main =
      commentRoot.querySelector('#main') ||
      commentRoot.querySelector('#body') ||
      commentRoot;

    if (!main) {
      warn('找不到 main/body/commentRoot 容器', shortNode(commentRoot));
      return;
    }

    const text = getCommentText(commentRoot);
    if (!text) {
      warn('评论文本为空，跳过注入', shortNode(commentRoot));
      return;
    }

    const timestamps = extractTimelineTimestamps(text);
    const hasTimestamp = timestamps.length > 0;
    setTimestampCommentMetadata(commentRoot, main, timestamps);

    const preparedForLocal = hasTimestamp ? preprocessTimelineTextForAI(text) : '';
    const localResult = hasTimestamp ? buildLocalSongListOutput(preparedForLocal || text) : '';
    const localTimedResult = hasTimestamp ? buildLocalSongListDisplayOutput(preparedForLocal || text) : '';
    ensureInlineLocalResultPanel(commentRoot, main, localResult, localTimedResult);
    syncAIButtonForTimestampState(commentRoot, hasTimestamp);

    if (commentRoot.getAttribute(COMMENT_DEBUG_ATTR) === '1') {
      log('跳过已注入评论', shortNode(commentRoot));
      return;
    }

    const existing = commentRoot.querySelector(`.${HOST_CLASS}`);
    if (existing) {
      log('已存在 host，标记完成', shortNode(commentRoot));
      commentRoot.setAttribute(COMMENT_DEBUG_ATTR, '1');
      return;
    }

    if (getComputedStyle(main).position === 'static') {
      main.style.position = 'relative';
      log('将 main 设置为 relative', shortNode(main));
    }

    const host = document.createElement('div');
    host.className = `${HOST_CLASS} fallback-overlay`;
    host.appendChild(createCopyButton(commentRoot));
    if (hasTimestamp) {
      host.appendChild(createAIButton(commentRoot));
    }
    host.appendChild(createSettingsButton());

    main.appendChild(host);
    commentRoot.setAttribute(COMMENT_DEBUG_ATTR, '1');

    log('注入成功', {
      commentRoot: shortNode(commentRoot),
      main: shortNode(main),
      hostRect: {
        width: host.getBoundingClientRect().width,
        height: host.getBoundingClientRect().height
      }
    });
  }

  function scanComments(root = document, reason = 'manual') {
    const candidates = root.querySelectorAll(`
      ytd-comment-thread-renderer,
      ytd-comment-view-model,
      ytd-comment-renderer
    `);

    group(`开始扫描评论 | reason=${reason}`, () => {
      log('候选节点数', candidates.length);

      let resolvedCount = 0;
      let injectedCount = 0;

      candidates.forEach((node, index) => {
        const commentRoot = resolveCommentRoot(node);

        if (!commentRoot) return;

        resolvedCount += 1;

        const beforeInjected = commentRoot.getAttribute(COMMENT_DEBUG_ATTR) === '1';
        if (DEBUG && index < 10) {
          log(`候选[${index}]`, {
            raw: shortNode(node),
            root: shortNode(commentRoot),
            alreadyInjected: beforeInjected
          });
        }

        ensureButton(commentRoot);

        const afterInjected = commentRoot.getAttribute(COMMENT_DEBUG_ATTR) === '1';
        if (!beforeInjected && afterInjected) {
          injectedCount += 1;
        }
      });

      const reorderedContainers = sortTimestampCommentThreads();
      const mergedDuplicatePanels = dedupeInlineLocalResultPanels();

      log('扫描完成', {
        reason,
        candidates: candidates.length,
        resolvedCount,
        injectedCount,
        reorderedContainers,
        mergedDuplicatePanels
      });
    });
  }

  let scanTimer = null;

  function scheduleScan(reason = 'scheduled', delay = 120) {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(() => {
      scanComments(document, reason);
    }, delay);
  }

  function bootObserver() {
    const observer = new MutationObserver((mutations) => {
      let addedNodes = 0;
      let hit = false;

      for (const m of mutations) {
        if (m.addedNodes && m.addedNodes.length > 0) {
          addedNodes += m.addedNodes.length;
          hit = true;
        }
      }

      if (hit) {
        log('MutationObserver 命中', {
          mutationCount: mutations.length,
          addedNodes
        });
        scheduleScan('mutation');
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });

    log('MutationObserver 已启动');
  }

  function installDebugHelpers() {
    window.__YT_COMMENT_AI_DEBUG__ = {
      scan: (reason = 'window.manual') => scanComments(document, reason),
      getCommentNodes: () => Array.from(document.querySelectorAll('ytd-comment-view-model, ytd-comment-renderer')),
      getHosts: () => Array.from(document.querySelectorAll(`.${HOST_CLASS}`)),
      normalizeSongListOutput: (aiText, sourceText = aiText) => normalizeAiSongListOutput(aiText, sourceText),
      buildLocalSongListOutput: (sourceText) => buildLocalSongListOutput(sourceText),
      buildLocalSongListDisplayOutput: (sourceText) => buildLocalSongListDisplayOutput(sourceText),
      splitCollapsedTimelineText: (sourceText) => splitCollapsedTimelineText(sourceText),
      extractTimelineTimestamps: (text) => extractTimelineTimestamps(text),
      sortTimestampComments: () => sortTimestampCommentThreads(),
      extractStructuredSongs: (text) => extractStructuredSongsFromSourceTimeline(text),
      dedupeInlinePanels: () => dedupeInlineLocalResultPanels(),
      isNonSongSectionMarker: (text) => isNonSongSectionMarker(text),
      isTimestampStartPlaceholderLine: (text) => isTimestampStartPlaceholderLine(text),
      dumpFirstComment: () => {
        const first = document.querySelector('ytd-comment-view-model, ytd-comment-renderer');
        if (!first) return null;
        const rawText = getCommentText(first);
        const preparedText = preprocessTimelineTextForAI(rawText);
        const structured = extractStructuredSongsFromSourceTimeline(preparedText);
        return {
          node: first,
          rawText,
          preparedText,
          timestamps: extractTimelineTimestamps(preparedText),
          localResult: buildLocalSongListOutput(preparedText),
          localTimedResult: buildLocalSongListDisplayOutput(preparedText),
          structuredSongs: structured,
          html: first.outerHTML.slice(0, 3000)
        };
      }
    };
    log('已挂载调试对象到 window.__YT_COMMENT_AI_DEBUG__');
  }

  function boot() {
    log('boot 开始', location.href);

    try {
      ensureModal();
      fillModalConfig();
    } catch (err) {
      error('弹窗初始化失败，但继续执行评论按钮扫描', err);
    }

    installDebugHelpers();
    scanComments(document, 'boot');
    bootObserver();

    let lastUrl = location.href;
    setInterval(() => {
      if (location.href !== lastUrl) {
        log('检测到 URL 变化', {
          from: lastUrl,
          to: location.href
        });
        lastUrl = location.href;
        setTimeout(() => scanComments(document, 'url-change-500ms'), 500);
        setTimeout(() => scanComments(document, 'url-change-1500ms'), 1500);
        setTimeout(() => scanComments(document, 'url-change-3000ms'), 3000);
      }
    }, 800);

    document.addEventListener('yt-navigate-finish', () => {
      log('收到 yt-navigate-finish');
      setTimeout(() => scanComments(document, 'yt-navigate-finish'), 800);
    }, true);

    window.addEventListener('load', () => {
      log('window load');
      setTimeout(() => scanComments(document, 'window-load-1000ms'), 1000);
      setTimeout(() => scanComments(document, 'window-load-2500ms'), 2500);
    });

    setTimeout(() => scanComments(document, 'boot-2000ms'), 2000);
    setTimeout(() => scanComments(document, 'boot-5000ms'), 5000);
  }

  GM_addStyle(`
    .${HOST_CLASS} {
      display: flex !important;
      align-items: center !important;
      gap: 6px !important;
      flex-wrap: wrap !important;
      pointer-events: auto !important;
    }

    .${HOST_CLASS}.fallback-overlay {
      position: absolute !important;
      top: 0 !important;
      right: 0 !important;
      z-index: 9999 !important;
      background: rgba(0, 0, 0, 0.55) !important;
      padding: 4px 6px !important;
      border-radius: 12px !important;
      backdrop-filter: blur(2px) !important;
      box-sizing: border-box !important;
    }

    .${COPY_BTN_CLASS},
    .${AI_BTN_CLASS},
    .${LOCAL_COPY_BTN_CLASS},
    .${SETTINGS_BTN_CLASS} {
      appearance: none !important;
      border: 1px solid rgba(255,255,255,.16) !important;
      background: rgba(255,255,255,.10) !important;
      color: var(--yt-spec-text-primary, #fff) !important;
      border-radius: 16px !important;
      padding: 4px 10px !important;
      font-size: 12px !important;
      line-height: 1.4 !important;
      cursor: pointer !important;
      transition: all .15s ease !important;
      white-space: nowrap !important;
      min-height: auto !important;
    }

    .${COPY_BTN_CLASS}:hover,
    .${AI_BTN_CLASS}:hover,
    .${LOCAL_COPY_BTN_CLASS}:hover,
    .${SETTINGS_BTN_CLASS}:hover {
      background: rgba(255,255,255,.18) !important;
    }

    .${COPY_BTN_CLASS}[data-success="1"],
    .${AI_BTN_CLASS}[data-success="1"],
    .${LOCAL_COPY_BTN_CLASS}[data-success="1"] {
      background: rgba(46, 125, 50, .95) !important;
      border-color: rgba(46, 125, 50, .95) !important;
      color: #fff !important;
    }

    .${COPY_BTN_CLASS}[data-success="0"],
    .${AI_BTN_CLASS}[data-success="0"],
    .${LOCAL_COPY_BTN_CLASS}[data-success="0"] {
      background: rgba(198, 40, 40, .95) !important;
      border-color: rgba(198, 40, 40, .95) !important;
      color: #fff !important;
    }

    .${AI_BTN_CLASS}:disabled {
      opacity: .65 !important;
      cursor: wait !important;
    }

    .${TIMESTAMP_COMMENT_CLASS} {
      border-radius: 8px !important;
      background: rgba(255, 214, 102, .10) !important;
      box-shadow: inset 3px 0 0 rgba(255, 214, 102, .88) !important;
    }

    .${LOCAL_PANEL_CLASS} {
      margin-top: 10px !important;
      padding: 12px 14px !important;
      border: 1px solid #d8b84f !important;
      border-left: 4px solid #d19a00 !important;
      border-radius: 8px !important;
      background: #fff8df !important;
      box-sizing: border-box !important;
      max-width: 100% !important;
      box-shadow: 0 1px 0 rgba(0,0,0,.05) !important;
    }

    .yt-comment-local-result-header {
      display: flex !important;
      align-items: center !important;
      justify-content: space-between !important;
      gap: 8px !important;
      margin-bottom: 10px !important;
    }

    .yt-comment-local-result-title-wrap {
      display: flex !important;
      align-items: baseline !important;
      gap: 8px !important;
      min-width: 0 !important;
    }

    .yt-comment-local-result-title {
      color: #2d2410 !important;
      font-size: 14px !important;
      font-weight: 700 !important;
      line-height: 1.35 !important;
    }

    .yt-comment-local-result-meta {
      color: #6f5a20 !important;
      font-size: 13px !important;
      font-weight: 600 !important;
      line-height: 1.35 !important;
      white-space: nowrap !important;
    }

    .yt-comment-local-result-actions {
      display: flex !important;
      align-items: center !important;
      gap: 6px !important;
      flex: 0 0 auto !important;
    }

    .yt-comment-local-result-actions .${LOCAL_COPY_BTN_CLASS} {
      border: 1px solid #5a4819 !important;
      background: #6f5514 !important;
      color: #fff !important;
      border-radius: 14px !important;
      padding: 5px 12px !important;
      font-size: 12px !important;
      font-weight: 700 !important;
      line-height: 1.35 !important;
    }

    .yt-comment-local-result-actions .${LOCAL_COPY_BTN_CLASS}:hover {
      background: #4e3d12 !important;
      border-color: #4e3d12 !important;
    }

    .${LOCAL_PANEL_CLASS}[data-collapsed="1"] .yt-comment-local-result-subtitle,
    .${LOCAL_PANEL_CLASS}[data-collapsed="1"] .yt-comment-local-result-textarea,
    .${LOCAL_PANEL_CLASS}[data-collapsed="1"] .yt-comment-local-timed-links {
      display: none !important;
    }

    .${LOCAL_PANEL_CLASS}[data-collapsed="1"] .yt-comment-local-result-header {
      margin-bottom: 0 !important;
    }

    .yt-comment-local-result-subtitle {
      color: #4f411a !important;
      font-size: 13px !important;
      font-weight: 700 !important;
      line-height: 1.35 !important;
      margin: 8px 0 6px !important;
    }

    .yt-comment-local-result-textarea {
      width: 100% !important;
      min-height: 0 !important;
      max-height: none !important;
      box-sizing: border-box !important;
      resize: none !important;
      overflow: hidden !important;
      border: 1px solid #d4c38e !important;
      border-radius: 8px !important;
      background: #fffef8 !important;
      color: #24211a !important;
      padding: 10px 12px !important;
      font-size: 13px !important;
      line-height: 1.55 !important;
      outline: none !important;
      white-space: pre !important;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
    }

    .yt-comment-local-result-textarea + .yt-comment-local-result-subtitle {
      margin-top: 12px !important;
    }

    .yt-comment-local-copy-source {
      display: none !important;
    }

    .yt-comment-local-timed-links {
      width: 100% !important;
      box-sizing: border-box !important;
      border: 1px solid #d4c38e !important;
      border-radius: 8px !important;
      background: #fffef8 !important;
      color: #24211a !important;
      padding: 10px 12px !important;
      font-size: 13px !important;
      line-height: 1.55 !important;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
      white-space: pre-wrap !important;
      user-select: none !important;
    }

    .yt-comment-local-timed-row {
      min-height: 1.55em !important;
      white-space: pre-wrap !important;
      display: grid !important;
      grid-template-columns: max-content 1fr !important;
      column-gap: 6px !important;
      align-items: baseline !important;
    }

    .yt-comment-local-timed-body {
      min-width: 0 !important;
      white-space: pre-wrap !important;
      user-select: text !important;
    }

    .yt-comment-local-time-link {
      color: #065fd4 !important;
      text-decoration: none !important;
      cursor: pointer !important;
      font-weight: 700 !important;
      user-select: none !important;
    }

    .yt-comment-local-time-link:hover {
      color: #044a9f !important;
      text-decoration: underline !important;
    }

    #yt-comment-ai-modal {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 999999;
      align-items: center;
      justify-content: center;
    }

    .yt-comment-ai-mask {
      position: absolute;
      inset: 0;
      background: rgba(0,0,0,.55);
    }

    .yt-comment-ai-panel {
      position: relative;
      width: min(900px, calc(100vw - 32px));
      max-height: calc(100vh - 32px);
      overflow: hidden;
      background: #0f0f0f;
      color: #fff;
      border: 1px solid rgba(255,255,255,.12);
      border-radius: 16px;
      box-shadow: 0 12px 40px rgba(0,0,0,.45);
      display: flex;
      flex-direction: column;
    }

    .yt-comment-ai-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      border-bottom: 1px solid rgba(255,255,255,.08);
    }

    .yt-comment-ai-title {
      font-size: 16px;
      font-weight: 700;
    }

    .yt-comment-ai-close {
      appearance: none;
      border: none;
      background: transparent;
      color: #fff;
      font-size: 24px;
      cursor: pointer;
      line-height: 1;
    }

    .yt-comment-ai-body {
      padding: 16px;
      overflow: auto;
    }

    .yt-comment-ai-tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
    }

    .yt-comment-ai-tab {
      appearance: none;
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(255,255,255,.06);
      color: #fff;
      border-radius: 12px;
      padding: 6px 12px;
      cursor: pointer;
    }

    .yt-comment-ai-tab.is-active {
      background: rgba(255,255,255,.16);
    }

    .yt-comment-ai-tab-panel {
      display: none;
    }

    .yt-comment-ai-tab-panel.is-active {
      display: block;
    }

    .yt-comment-ai-label {
      display: block;
      margin: 12px 0 6px;
      font-size: 13px;
      opacity: .9;
    }

    .yt-comment-ai-panel input,
    .yt-comment-ai-textarea {
      width: 100%;
      box-sizing: border-box;
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(255,255,255,.04);
      color: #fff;
      border-radius: 12px;
      padding: 10px 12px;
      font-size: 13px;
      outline: none;
    }

    .yt-comment-ai-textarea {
      min-height: 320px;
      resize: vertical;
      line-height: 1.55;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: pre-wrap;
    }

    .yt-comment-ai-tab-panel[data-panel="result"] .yt-comment-ai-textarea {
      min-height: 220px;
    }

    .yt-comment-ai-actions {
      display: flex;
      gap: 8px;
      margin-top: 12px;
      flex-wrap: wrap;
    }

    .yt-comment-ai-actions button {
      appearance: none;
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(255,255,255,.08);
      color: #fff;
      border-radius: 12px;
      padding: 8px 12px;
      cursor: pointer;
    }

    .yt-comment-ai-status {
      margin-top: 12px;
      font-size: 13px;
      color: rgba(255,255,255,.85);
      white-space: pre-wrap;
      word-break: break-word;
    }

    .yt-comment-ai-status[data-error="1"] {
      color: #ff8a80;
    }
  `);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
