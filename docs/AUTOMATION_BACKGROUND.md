# yt-comment-automation 定时任务背景

最后更新：2026-10-19

## 项目身份

- 项目名：`yt-comment-automation`
- 本地项目路径：`/Users/be/Documents/ChatGPT/yt-comment-automation`
- 远程生产：WDC `/opt/yt-comment-automation`
- GitHub：`Marica7731/yt-comment-automation`
- 目标：从 B 站自家合集视频对应的 YouTube 原始评论/简介中识别增量歌单，由 Codex 审核并发布；粉丝回复点赞由 WDC 独立自动化。
- 凭据：B 站 cookie、飞书凭据和 YouTube key 只存 WDC `private.env` 或其指向的运行时文件；GitHub token 只存 WDC `/root/.secrets/github-token`。任何密钥值都不得写入仓库、日志、通知或 Agent 配置。

## 调度身份

- WDC `dev/wdc_incremental_cycle.sh` 每 20 分钟触发一次 GitHub Action，等待同轮 payload，同步到 WDC，再运行 cache-only 清洗。
- Codex 增量检查心跳约每 10 分钟运行一次；它只消费 WDC 已完成的结果，不为常规检查重复 dispatch。
- 每日北京时间 22:00 和 04:00 运行评论/点赞运维审计。
- 日期和时间约束只放在调度配置里，不写进执行 prompt 的正文。
- 每次自动化运行先读取 `README.md`、本文件、`docs/OPS_CURRENT.md`、`docs/HANDOVER.md` 和 `RULES.md`。

## 网络与执行边界

1. 评论内容证据由 WDC 触发的 GitHub Action 同轮抓取；WDC 通过 `dev/wdc_run_youtube_action.py` dispatch 并同步结果。
2. WDC 消费 Action 结果时必须使用 `YOUTUBE_FETCH_MODE=cache_only`，不得在清洗阶段再次抓 YouTube。
3. 所有 B 站访问、评论发布、删除和点赞 action 必须经 `ssh -o BatchMode=yes vps-wdc` 在 WDC 执行。
4. Action 原始审核材料只信任 `data/incremental_audit/latest.json` 与 `previous.json`；内容审核必须亲自读取实际 JSON。
5. `data/yt_raw/*.info.json`、`history/`、`fetch_times.json` 与 `yt_comment_ids.json` 在管线入口和出口清空。
6. 每条命令必须有 bounded timeout，禁止无界等待。
7. 禁止手工 `curl` B 站、直连 B 站接口、修改 crontab 绕过项目脚本、外部 AI key 或未授权凭据。

## 增量审核规则

新视频必须同时满足“视频增量 + 时间戳歌单增量”才进入审核。已存在视频在以下任一情况重新审核：

1. 新增带时间戳的评论；
2. 原评论区接近整体替换；
3. 原带时间戳评论被编辑；
4. 原无时间戳评论变为有时间戳；
5. 简介中对应时间戳内容新增或被编辑。

只有原始评论或简介存在结构化歌曲列表时才可拟订发布文案。感谢语、观后感、反应短语、台词、日期/活动时间、零散梗和聊天时间点不是歌单。结构化 SETLIST 足以确认列出的歌名为歌曲；无歌手不是发布门槛，直接按无歌手格式发布。拿不准某行时可自行检索，能确认就发，检索不到也不得让其余已确认歌曲停在 pending。不得使用 `approve --use-draft`，最终 messages 必须由 Codex 阅读原始数据后重新拟订。

## 评论发布与删除

- 发布必须经过 `review_cli approve --messages-file`，再执行 `review_cli apply`。
- 只有 `verification.ok=true` 且 B 站实时回读通过才算成功。
- `applied_unverified` 必须同轮对比原始输入、最终文案和真实回读；已有 rpid 但顶层回读不到时按驳回/未发布处理。
- 可见重复或敏感旧评论的删除只能走 `review_cli cleanup-retry-without-artist` -> `review.py` -> `bili_comment.delete_comment`。
- 删除前后必须复核 `bvid`、正整数 `rpid`、`bili_jct`、`DedeUserID == OWNER_MID`、`aid`、账号归属和目标内容；任一不确定即不删。
- 用户明确要求只删除时使用 `--delete-only`，删除后禁止自动重发。

## 点赞自动化

- WDC 每 20 分钟运行 `like_auto.py --max-count 10 --rounds 8`。
- 每轮先重扫新鲜列表，再批准当前批次并执行；瞬时失败会重新扫描后重试。
- 180 秒 freshness、action 前真实“未赞”复核、防重集合与 8 秒频控不可绕过。
- Codex 不审核单条点赞，只检查调度、积压、失败率、ledger 和不可恢复异常。

## 运维审计

每日 22:00 和 04:00：

1. 读取最新运行日志、Action 状态、`latest.json` 与 `previous.json`。
2. 运行 `dev/incremental_audit.py` 检查原始 JSON、哈希状态和 review candidate 是否一致。
3. 检查评论队列、清洗输入/输出、发布 verification、rpids 和 B 站真实回读。
4. 运行 `dev/like_success_audit.py`，检查 `like_auto` 日志、队列、成功率与 `liked_rpids.json`。
5. 对可复现缺陷做最小修复、补回归测试、提交、推送、部署并通知。
6. 复核 raw/history/ledger 残留、crontab、Git 工作树和队列是否归零。

## 通知边界

- 实际发布评论、点赞、删除、不可恢复失败、原始数据门禁异常或代码修复必须经 WDC `notify.send_feishu_message` 报告。
- 评论通知使用项目紧凑格式；点赞、429、崩溃和修复可附技术审计字段。
- 同一异常在没有新动作或状态变化时只通知一次。
- 没有待办、没有实际 action 且没有未解释异常时保持安静。

## 文档入口

- `README.md`：项目简介、使用方式、配置和安全边界。
- `docs/OPS_CURRENT.md`：当前调度和运维分工。
- `docs/HANDOVER.md`：架构、部署、数据、机制和事故经验。
- `RULES.md`：清洗和发布规则的唯一权威源。
- `AGENTS.md`：长期约束、权威入口和凭据位置。
