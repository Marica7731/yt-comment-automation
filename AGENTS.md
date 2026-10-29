# AGENTS.md

这份文件告诉维护者怎样清洗评论、准备歌单并安全发布。改动前先读一遍。

## 先看这些文件

- `README.md`：项目是什么、怎样运行。
- `docs/AUTOMATION_BACKGROUND.md`：自动任务和网络边界。
- `docs/OPS_CURRENT.md`：现在使用的运行步骤。
- `docs/HANDOVER.md`：系统结构和重要经验。
- `RULES.md`：歌单清洗和发布的最终规则。

## Codex++ 和模型怎样分工

- Codex++ 是做事的 harness：它读取原始 JSON 和 `RULES.md`，安排清洗、检索和起草，再调用项目现有工具处理审核和发布。
- DeepSeek、MiMo 或本地模型是 Codex++ 可以使用的模型后端。换后端不等于换发布流程，也不自动改变发布权限。
- 不要把这个项目说成“模型只写候选”。按现有规则，Codex++ 会负责从原文到发布的整条流程。
- 模型可以帮助理解、检索、清洗和起草；纯脚本不能代替项目要求的内容判断。
- 只要内容符合 `RULES.md`、通过现有审核命令和真实回读，就继续原有发布流程。不要再加一个与任务无关的人工审批步骤。

## 网络、账号和文件

- 所有 YouTube/B 站网络请求、评论发布和点赞 action 都经 WDC：`ssh -o BatchMode=yes vps-wdc`。
- 点赞由 WDC 的 `like_auto.py` 自己定时处理，Codex 不用逐条决定点赞。
- GitHub 仓库是 `Marica7731/yt-comment-automation`；WDC 工作目录是 `/opt/yt-comment-automation`。
- GitHub token 只从 WDC 的 `/root/.secrets/github-token` 读取并交给现有脚本。不要复制、打印或提交 token。
- 不要用手写的 `curl`、直接请求外部接口、改 crontab 或借用未授权的凭据来绕过项目工具。
- 不要删除或改名配置、workflow、`RULES.md`、原始数据或项目目录。只改完成当前任务需要的文件。
- 命令要有超时，不要无限等待。

## 评论状态和发布

- 发布评论必须先运行 `review_cli approve --messages-file`，再运行 `review_cli apply`。
- 只有命令报告 `verification.ok=true)，并且从真实页面读回内容一致，才算发布成功。
- 找不到歌曲、歌手不明、来源不清或暂时写不出时，保持 `pending`，继续检索或等用户决定。不能把它偷偷标成已解决。
- `rejected` 表示用户同意忽略。只有拿到用户这次明确同意的原话，才能运行 `review_cli reject`。
- 旧的拒绝项若没有用户同意的原话，用 `reopen-rejected` 恢复。
- `user_owned` 表示用户同意把内容归用户所有。运行 `review_cli mark-user-owned` 时要记录用户明确同意的原话。
- 删除评论只能用项目已有的删除流程。归属不清楚时不要删除。
- 不要为“更安全”额外拦住已通过以上规则和检查的正常发布，也不要跳过已有审核或真实回读。
