# yt-comment-automation 定时任务背景

最后更新：2026-10-06

## 项目身份

- 项目名：`yt-comment-automation`
- 本地项目路径：`/Users/be/Documents/ChatGPT/yt-comment-automation`
- 远程生产：WDC `/opt/yt-comment-automation`
- 目标：读取 B 站自家合集视频对应的 YouTube 时间戳歌单，清洗为规范歌轴评论，经 Codex 审核后发布；同时审核并执行粉丝回复点赞。
- 账号与凭据：B 站 cookie、飞书凭据和 YouTube key 只存 WDC `private.env` 或其指向的本地运行时文件，不写入 Git、GitHub Actions secret、旧 bridge 或外部模型服务。

## 调度身份

- Automation ID：`yt-comment-codex-queue`
- 运行方式：standalone cron，每 30 分钟运行一次。
- 每次运行都会从保存的 prompt 新建独立聊天，不依赖上一次聊天上下文；因此 prompt、README、HANDOVER 和本文件共同构成持久背景。
- 任务绑定本地项目 `yt-comment-automation`，工作目录固定为上述本地路径。
- 任务不得创建、恢复或续跑 `/goal`，不得修改 crontab，不得调用或配置 OpenCode、DeepSeek 或其他外部 AI key。

官方说明：standalone scheduled task 每次运行从保存的 prompt 开始并新建聊天；项目背景和跨轮约束必须写入 task prompt。参见 [Scheduled tasks](https://learn.chatgpt.com/docs/automations)。

## 网络与执行边界

1. 本机只允许运行 `dev/run_youtube_action.py` 来推送目标、触发 GitHub Action、等待 payload 并同步 WDC；脚本内部通过 SSH/Git 完成网络编排。
2. 所有 YouTube 和 B 站网络请求、评论发布、点赞 action 都必须经 `ssh -o BatchMode=yes vps-wdc` 在 WDC 执行。
3. WDC 的 `cron_job.sh` 使用 `YOUTUBE_FETCH_MODE=cache_only`；缓存缺失必须报告为 `error_cache_miss` 或 Action 失败，禁止伪装为 `skipped_no_songs`。
4. 每条命令必须有 bounded timeout；不执行无界等待。

## 每轮工作顺序

1. 读取最新 `logs/run_*.log`、`data/run_*.json`，检查 `error_cache_miss`、`skipped_throttled`、异常 `skipped_no_songs`、反复跳过的正常稿件和未解释的 `error`。
2. 在本机运行 `python3 dev/run_youtube_action.py --timeout 360 --poll-interval 5`，核对目标数、`fetched`、`failures` 和 WDC `sync`。
3. 在 WDC 运行 `bash cron_job.sh`，读取最新日志和 run 记录。
4. 在 WDC 运行 `flock -n /tmp/like-fans.lock python3 like_fans.py >> logs/like_fans.log 2>&1`，该步骤只合并候选。
5. 读取评论和点赞队列。评论状态为 `pending/approved/applying/applied/applied_unverified`；点赞状态为 `pending/approved/applied/rejected/failed`。
6. 对范围内 pending 歌单读取 `source_text`、`draft_messages`、标题和来源，依据 `RULES.md` 审核；不完整或不可信的候选保持 pending。
7. 对 approved 歌单执行 `review_cli apply --bvid <bvid>`，亲自读取返回 JSON、`status`、`verification`、`rpids`，并在 WDC 回读自有评论数。
8. 对 `applied_unverified` 先执行 `review_cli verify --bvid <bvid>`；只有没有历史 rpid 且接口明确返回不存在时才允许一次 `recover-missing`，已有 rpid 不得重复发布。
9. 对点赞 pending 逐条检查 `content/source/oid/rpid`，排除自己、广告、垃圾和不安全内容；批准后执行 `python3 like_fans.py --apply /opt/yt-comment-automation/data/like_review.json`。
10. 结束前再次核对队列、最近日志和 crontab；评论/点赞 cron 必须移除，只保留每日复盘 cron。

## 状态语义

- `skipped_throttled`：距上次真实抓取不足间隔，必须核对间隔账本。
- `error_cache_miss`：Action 缓存缺失，属于生产阻塞，必须刷新 Action 后重跑。
- `skipped_no_songs`：只有在缓存存在且原始来源确认无歌单时才可接受。
- `applied_unverified`：已尝试发布但验收未通过，必须在同一轮读取结果并处理，不得静默结束。
- `applied` 且 `verification.ok=true`：只有读到这个组合才算评论发布完成。
- `like_review` 的 pending/approved 不代表已经点赞；只有 `applied` 才是 action 已执行。

## 通知边界

- 实际发布评论、执行点赞、人工失败、发现旧 AI key/直发分支或完成代码修复时，必须通过 WDC 的 `notify.send_feishu_message` 发送具体报告。
- 评论成功/失败通知使用项目定义的紧凑格式；点赞、429、崩溃和代码修复可保留技术审计字段。
- 没有待办、没有异常且没有实际 action 时保持安静，不用泛化状态通知掩盖异常。

## 文档入口

- `README.md`：项目简介、使用方式、配置和安全边界。
- `docs/HANDOVER.md`：架构、部署、数据、机制、验证纪律和事故经验。
- `RULES.md`：清洗规则权威文档。
- 本文件：独立定时任务的持久背景；每次新对话先读本文件和 `docs/HANDOVER.md`。
