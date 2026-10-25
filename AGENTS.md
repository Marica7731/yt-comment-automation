# yt-comment-automation 项目级 Agent 规则

本文件只记录长期有效的项目约束、规范、权威入口、执行边界和验收要求。
不要在这里写运行日志、单轮状态、事故流水、临时排障记录、提交历史或数据快照。

## 权威入口

按任务需要读取以下文件，不把内容复制进本文件：

- `README.md`：项目概览、命令入口和安全边界。
- `docs/AUTOMATION_BACKGROUND.md`：独立定时任务的持久背景、网络边界和每轮流程。
- `docs/OPS_CURRENT.md`：当前采用的调度和运维分工。
- `docs/HANDOVER.md`：架构、数据结构、机制和事故经验。
- `RULES.md`：歌单清洗和发布规则的唯一权威源。

## 凭据与远端入口

- GitHub 仓库：`Marica7731/yt-comment-automation`。
- WDC 仓库：`/opt/yt-comment-automation`。
- WDC GitHub token：`/root/.secrets/github-token`，仅供 WDC 脚本和 GitHub API 使用；
  不得把值写入仓库、日志、通知或 Agent 配置。
- GitHub 访问优先使用上述 token；SSH 存在时可用于 Git，但不要把“需要新 token”
  作为默认前提。

## 信息归档边界

- 长期约束、规范和入口：本文件。
- 当前调度与运维分工：`docs/OPS_CURRENT.md`。
- 架构和历史经验：`docs/HANDOVER.md`。
- 运行日志与单轮结果：`logs/`、`data/`，不要写进本文件。
- 临时诊断、探针和一次性排查：`dev/` 或临时输出，不写进本文件。

## 执行约束

- 所有 YouTube/B 站网络请求、评论发布和点赞 action 必须经 WDC：
  `ssh -o BatchMode=yes vps-wdc`。
- 点赞由 WDC `like_auto.py` 独立调度；Codex 不逐条审核点赞。
- 评论内容的最终发布决定由 Codex 基于原始数据和 `RULES.md` 作出，纯脚本不得代替审核。
- 评论发布必须经过 `review_cli approve --messages-file` 和 `review_cli apply`；
  只有 `verification.ok=true` 且真实回读通过才算成功。
- `rejected` 是需用户明确授权的忽略终态。Codex 和自动心跳无权自行拒绝或忽略候选；
  检索不到、歌手缺失、来源不确定或暂时无法拟订时必须保持 `pending`，继续检索或等待用户决定。
  `review_cli reject` 必须提供用户同意的原话；未经用户同意的旧拒绝项用 `reopen-rejected` 恢复。
- `user_owned` 同样是用户授权终态；`review_cli mark-user-owned` 必须记录用户明确同意的原话。
- 删除评论只能走项目既有删除门禁；任何归属不确定的情况都不得删除。
- 所有命令必须设置有界 timeout，禁止无界等待。
- 禁止手工 `curl`、直连外部接口、修改 crontab 或用未授权凭据绕过门禁。

## 本文件维护

新增内容前先判断它是否属于“长期约束、规范或入口”。
如果只是某轮运行状态、日志摘要、修复记录或统计数字，应写入对应数据文件或项目文档，而不是本文件。
