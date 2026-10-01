# yt-comment-automation 交接文档

> 最后更新：2026-10-01。本文档面向接手本项目的维护者（人或代理），覆盖架构、部署、数据、机制、坑与验证纪律。接手前必读。

## 1. 项目是什么

自动监控 B 站 4 个合集（直播/直播2/直播3/凛々咲，497 个自家视频）里的 VTuber 歌枠投稿，抓取对应 YouTube 直播的评论区/简介中的时间戳歌单，清洗成规范格式后作为 B 站评论发布到视频下方，并附带源/发布双时间轴的飞书通知。附带两个附属任务：粉丝回复自动点赞、每日清洗复盘。

- 仓库：`https://github.com/Marica7731/yt-comment-automation`（public，master，无密钥；private.env 被 gitignore）
- 生产：WDC VPS `/opt/yt-comment-automation`（cron 驱动，长期无人值守）
- 下游消费：`G:\codex-work\plugin` 的油猴插件 + `RULES.md` 共享清洗规则（`yt_comment_automation/rules.py` 由 auto_evolve 自动演进）

## 2. 部署与调度全景（WDC）

| 任务 | cron | 命令 | 日志 |
|---|---|---|---|
| 歌单管线 | `*/20 * * * *` | `cron_job.sh`（flock + DRY_RUN=0 + timeout 3600 + run --mode incremental） | `logs/run_*.log`（保留 30 个 ≈10 小时） |
| 粉丝点赞 | `13 * * * *` | `flock -n /tmp/like-fans.lock python3 like_fans.py` | `logs/like_fans.log` |
| 每日清洗复盘 | `0 0 * * *`(UTC)=北京 8:00 | `flock -n /tmp/daily-review.lock python3 daily_clean_review.py` | `logs/daily_review.log` |

- 运行时数据：`/opt/yt-comment-automation/data/`；飞书凭据：`run.sh` 从 `/opt/feishupy-vps-jp/runtime/bridge.env` 加载（FEISHU_APP_ID/SECRET/MY_FEISHU_OPEN_ID）；B 站 cookie：`private.env` 的 `BILI_COOKIE_FILE` 指向 `/opt/feishupy-vps-wdc-canary/runtime/biliup_cookies.json`；审核开关：`CODEX_REVIEW=1`、`LIKE_REVIEW=1`。
- `private.env` 其他项：`COLLECTION_NAMES=直播,直播2,直播3,凛々咲`、`IGNORE_BVIDS`（6 个无歌单视频，逗号分隔）、`OWNER_MID=3546597260528367`。
- **所有 B 站 API 请求必须带 cookie**（裸请求 412，换 UA 没用）。
- 本地对应仓库：`G:\codex-work\yt-comment-automation`。发布流程：本地改 → commit/push → WDC `git pull` → 实跑验证。

## 3. 数据文件清单（data/）

| 文件 | 用途 | 关键性 |
|---|---|---|
| `processed.json` | 已发布 bvid 集合（posted 立即落盘，防崩溃重复发） | 高 |
| `collections_snapshot.json` | 合集视频快照（list 结构，每轮覆盖） | 中 |
| `run_*.json` | 每轮运行明细，含 message 字段（发布内容落盘，复盘用） | 中 |
| `yt_raw/<ytid>.info.json` | YouTube 抓取缓存（**无歌单的结果不落缓存**） | 中 |
| `yt_raw/history/<ytid>/*.info.json` | 覆盖前轮转，留 3 份（解析前与主缓存合并） | 中 |
| `yt_raw/fetch_times.json` | 每视频上次真实抓取时刻账本（重抓间隔依据） | 高 |
| `yt_raw/yt_comment_ids.json` | 评论 id 账本（自适应翻页对账，每视频 500 条） | 中 |
| `data/liked_rpids.json`（仓库根 data/） | 已点赞 rpid 集合（防 toggle 重复） | 高 |
| `codex_review/*.json` | 歌单待审核/已批准/已发布账本，cron 不覆盖终态 | 高 |
| `like_review.json` | 点赞候选与 Codex 批准/执行结果，cron 合并不覆盖终态 | 高 |
| `deleted_dupes.json` | 历史清理记录 | 低 |

## 4. Codex 审核与执行链路

- `CODEX_REVIEW=1`（默认）：管线抓取并生成草稿或原始时间戳来源，写入 `data/codex_review/<bvid>.json`；状态为 `pending` 时 cron 不发布，Codex 审核后才进入 `approved`。
- `LIKE_REVIEW=1`（默认）：`like_fans.py` 每小时只合并候选到 `data/like_review.json`，不执行点赞 action；Codex 用 `like_review_cli approve` 批准，随后 `python like_fans.py --apply ...` 才执行。
- 审核文件是审计账本：`queue/merge` 不覆盖 `approved/applied/rejected`；执行前重新读取服务器真实点赞状态，状态不可确认宁可跳过。
- `OPENCODE_API_KEY`、`DEEPSEEK_API_KEY` 仅保留在旧代码/工具中，生产发布链默认不读取；不要把 key 写入 GitHub。
- 审核入口：`review_cli list/show/approve/apply`；点赞入口：`like_review_cli list/show/approve/reject`，执行动作固定为 `like_fans.py --apply`。

## 5. 关键机制与坑（按事故沉淀，改动前必读）

### 抓取（yt_fetch.py）
- **抓取频率按"同一视频两次抓取的间隔"控制**：新视频（B站投稿 ≤2 天）每轮抓，老视频 ≥12 小时（`_refetch_gate`，上次抓取时刻查 `fetch_times.json` 账本——无歌单不落主缓存所以 mtime 不可用）。不到间隔跳过该视频本轮，**绝不用缓存内容顶替**。
- **全局请求节流 2 秒**：`req_pace.py` 跨进程共享时钟（fcntl 文件锁），YouTube 抓取与 B 站请求、点赞脚本共用。风控看出口 IP 总速率。
- **429 重试最多 5 次**（Retry-After 优先，退避 2/4/8/16/30s），任一次成功放行；飞书 429 通知一轮只发一条。
- **自适应翻页**：评论按 `commentId`（缺失回退文本 sha1）对账，第 1 页有新评论才翻下一页，某页全旧即停——但**仅限已发布视频的升级复查**（early_stop=True）；未发布视频必须抓满 5 页（歌单被闲聊顶到后面页时，提前停=永远抓不回）。上限 5 页=100 条触达。
- 缓存有效性只能由处理结果决定：发布=留缓存，0 首未发布=不落缓存+删旧缓存。静态判定缓存有效性会被骗（闲聊表像歌单）。
- 简介提取必须认 `attributedDescription`（新版 YouTube 页面正文在这，simpleText 常为空）。
- 评论排序优先「新しい順」（sortFilterSubMenuRenderer 的 continuation token），热门排序会漏置顶歌单。

### 清洗（clean.py / rules.py）
- **区间行**（`0:12:01 - 0:16:36 コネクト / ClariS`）必须整行保留取开始时间，且**起止都输出**（ParsedSong.timestamp_end_seconds，输出 `0:12:01-0:16:36 01. …`）；三种形态：同行/歌名在下行/结束时间在下行。
- **「emoji+序号」前缀**（`🎸01. 0:05:03 …`、`🎸EN.` 返场）要组合剥离，序号剥完必须剩时间戳开头才生效（保护 8.8/4.3.2.1 数字歌名）。
- **树形表格歌单**（序号+TAB+可空时间戳列，可能拆两条评论）AI 路径可解析（空时间戳沿用上方最近时间戳）；本地兜底不支持无时间戳行——已知 gap。
- 裸歌名判定：单字汉字（奏/虹/桜）是真歌名不能因长度拒；1-3 字纯平假名（まで）是残片要拒（3 字假名真歌名如 すずめ 会被拒——历来靠 AI 路径，已知边角）。
- MC/环节行结尾（紹介/説明/コーナー/待ち/コール）、社交账号行（X：handle/status/数字）、宣伝/告知 直接拒。
- 候选来源排序键 = **(带歌手数, 秒级时间戳数, 条数)**——接力时段表/预告文条数多但无歌手无秒级，天然沉底；绝不能按条数排。
- 无结构化歌单评论时，简介必须含 ≥2 个秒级时间戳（H:MM:SS）才允许本地兜底（钟点时段表/预告文的结构性闸门）。
- 歌名 >40 字符判脏（预告文/标题残片）。
- 提取入口 `html.unescape`（YouTube 源带 &#39; 等）。
- 双重编号剥离（`14.あなたの夜…`）、全角 ／ 优先于半角 / 作分隔、歌名内半角 /（ハロ/ハワユ，两侧假名）不切。

### 发布与 B 站（bili_comment.py / pipeline.py）
- **B 站 reply 读接口返回的 message 是 HTML 转义的**（'→&#39;）——校验自己评论先 unescape 再比对，读回有 &#39; 不是发错。
- reply/action 点赞是 **toggle**：只有确认服务器当前未赞才发。判态用顶层评论列表的 `action` 字段（**reaction 恒 null 是陷阱**）；mid 一律 str() 归一比较（接口给字符串）。
- 超长评论主评论+楼中楼续写；多 P 视频每 P 一条主评论（时间戳按 pages[].duration 重算，区间标签会退化为开始时间——已知降级）。
- 升级模式：已发 <3 首时复查，新歌单严格多于已发且 ≥3 首才删旧发新；新投稿每轮 force 重抓，老投稿 2 小时 TTL。
- 忽略列表 `IGNORE_BVIDS` 现有 6 个：BV1MW3R6vEoE,BV17KGK62EyU,BV1VERyBnEG6,BV1WAYb6zEoE,BV1one569EZt,BV18ZaZ6hE2F。

### 点赞（like_fans.py，部署在仓库根，WDC cron）
- msgfeed「回复我的」游标翻页：响应 `cursor{id,time}`，下一页参数 `id` + `reply_time`（实测所得，勿猜其他参数名）；**页内有新赞才继续翻**，整页已赞/重复即停，上限 10 页。
- msgfeed 点赞不限视频（回复我的=别人回复我们）；**评论区补扫限自家视频**（OWN_BVIDS=processed posted ∪ collections_snapshot）——补扫扫整个评论区，外人视频绝不能扫。
- 点赞 8 秒频控只在真实点赞后消耗；点赞成功即写 liked_rpids.json。
- 飞书通知只有标题一个 👍，明细纯文本不折叠，仅有点赞动作才发；跳过明细只进 stdout 日志。

### 通知（notify.py）
- 成功通知：源时间戳全量（未过滤）+ 发布内容 + 非满额时附 AI 清理说明。**注意 explain_cleanup 是事后解说没有执行权，排查问题只看代码和日志，别信说明文字的归因。**
- 崩溃通知：cli 包 try/except（正式运行）+ cron_job.sh 检查退出码兜底。

### 复盘（daily_clean_review.py）
- 对比缓存源时间戳行 vs run json message：被洗掉的源行原文列飞书。匹配必须归一（多版本 SETLIST 的分隔符/序号/时间戳差异），歌名段命中即算保留。列出的缺失行含大量本就该洗掉的行（START/宣伝/框架行），人工扫一眼判断真误杀。

## 6. 验证纪律（血泪沉淀，违反必出事故）

1. **部署脚本后必须实跑验证**；重大改动用**原样 cron 命令连跑两轮**看稳态（只跑一轮手工测试不算数——重抓间隔账本 bug 就是第二轮才暴露的）。
2. 代码改动先 `python -m py_compile` + `pyflakes` + `pytest tests/`（91 项）；重构后必跑 pyflakes（多P改造曾遗留 NameError 崩 28 小时）。
3. Python 写文件用 Write 工具，禁止 heredoc 嵌码（Git Bash 引号会毁 f-string）；复杂逻辑写脚本文件跑，不塞 `python -c`。
4. **禁止编造 API 的 host/路径/参数**：参数不确定就自己抓包看真实请求（浏览器 HAR/服务端实测），抓不到就明说没依据。HTTP 200 ≠ 参数正确（编造参数被静默忽略返回首页同款数据），必须比对返回内容。
5. 诊断先看日志/cache 再下结论；用户贴的飞书通知可能滞后于已做的修复；汇报时间必须换算北京时间。
6. WDC 连接：本机 paramiko 直连为主（凭据 `D:/Download/HostDZire WDC.md` 两行格式：IP+密码；runner 脚本 `dev/_wdc_run_fix_likes.py` 自带 3 次重试）；直连异常时的备用通道：Git Bash `ssh -F "C:/Users/终焉/.ssh/config" jp`（密钥登录）+ jp 上 sshpass 跳板（用完删 /tmp/wdcpw）。注意 Git Bash 的 ssh 写不进中文用户名的 known_hosts，加 `-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=accept-new`。

## 7. dev/ 工具速查

- `dev/_wdc_run_fix_likes.py <本地脚本>`：通用 WDC 执行器（上传 /tmp/_wdc_task.py 执行回显）。
- `dev/_mock_test_like_fans.py`、`dev/_mock_paginated_likes.py`：like_fans 决策逻辑 mock 测试（stub urlopen，11+7 项断言）。
- `dev/_opencode_model_bench.py`、`dev/_bench_retry*.py`：全模型基准（加模型名即可重跑）。
- `dev/_like_audit.py`：一次性评论区对账（**仅限人工对账，禁止挂 cron**——范围大于 msgfeed）。
- 其余 `_wdc_*.py` 为历次事故的排查探针，可读可删。

## 8. 已知限制与未做事项

- 本地兜底不支持树形表格歌单的无时间戳行；原始来源仍会进入 Codex 审核，由审核者决定是否补发。
- Codex 审核是发布前人工/代理决策点，未批准的候选不会产生网络 action；审核文件损坏时必须先修复账本。
- 多 P 视频的区间标签退化为开始时间（split_items_by_pages 重建条目）。
- msgfeed 聚合只显示同会话最新一条，旧回复靠评论区补扫兜底（补扫限自家视频，外人视频下的折叠回复覆盖不到）。
- 翻页上限 5 页（100 条触达），超过的深部歌单抓不到（与旧行为一致）。
- 3 字纯假名真歌名（すずめ）本地路径拒收，交由 Codex 依据原始来源审核。
- 歌单 run 日志只留 10 小时，长期审计靠 data/run_*.json（约保留 1 个月）。

## 9. 文档索引

- `README.md`：项目简介
- `RULES.md`：R01-R17 清洗规则权威文档（本地/插件共用）
- `docs/feishu-notify-tutorial.md`：飞书通知通用教程
- `CODEX_GOAL.md`：目标跟踪约定（完成后重命名归档）
- `tests/`：91 项单元测试
