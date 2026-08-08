# CODEX_GOAL — B站合集视频评论区时间戳歌轴自动发布

- 建立时间：2026-08-08
- 总控会话：sess_06c8479d-b9c1-4147-86af-2906da158c83（G:\codex-work\yt-comment-automation）
- 状态：进行中

## 目标
为两个 B 站合集（直播1=70 视频、直播2=22 视频）内缺少时间戳歌轴评论的视频，
自动从视频简介首行的 YouTube 链接拉取评论区原始 JSON，清洗出「时间戳 + 歌名 - 歌手」列表，
用合集 owner 账号（mid 3546597260528367）发布评论，成功后发飞书通知。

## 范围
- 合集1：anchor BV13ege65Es5（ugc_season 8744333「直播」，9 节，70 视频）
- 合集2：anchor BV1ZYNT6hEEe（ugc_season 8744348「直播2」，5 节，22 视频）
- 已发布过时间戳歌轴评论的视频跳过（如 BV16aNn6zEqv / BV1xbub6EEj4）
- 处理链：合集检测 → YouTube 评论抓取（无 cookie）→ 本地规则清洗 → DeepSeek 兜底 → 发布 → 飞书

## 禁止事项
- 不把 IP、apikey、cookie、token 上传 GitHub
- 不重复发布已存在的时间戳评论
- 不修改 song_serch_lyrics / feishupy_deve 源码（只读复用）
- 不在 WDC VPS 之外并发写同一 data 目录

## 验收条件
1. GitHub 仓库 yt-comment-automation 已创建，代码可运行（不含任何机密）
2. WDC VPS 上 cron 定时运行增量检测，新视频自动发评论
3. 每个成功评论发飞书通知：B站链接 / 油管链接 / 评论时间 / 歌曲数量
4. 92 个存量视频全部检查过：已发布的跳过，缺的补齐
5. 干跑样本（SAMPLE_PREVIEW.md）经用户确认格式无误后放量

## 当前状态
- [x] 两个仓库规则对比分析完成（daily-song-list 覆盖最全/日文定制；song_serch_lyrics 抓取最稳/有误伤；plugin 油猴规则可移植）
- [x] 合集视频数量验证：70 + 22 = 92，part 字段内嵌 [日期][YouTubeID]
- [x] 评论抓取实测：8 个视频全部成功，29/22/20/18/12/10/8/6 首不等
- [x] 本地规则清洗 Python 移植版完成（19 个单元测试通过）
- [x] DeepSeek responses API 实测可用，prompt 缓存自动命中
- [x] 发布接口验证：cookie 有效（owner 账号），reply/add 鉴权通过
- [x] 干跑 5 个样本生成（SAMPLE_PREVIEW.md）
- [ ] 用户确认干跑样本格式
- [ ] GitHub 仓库创建 + push
- [ ] WDC VPS 部署 + cron
- [ ] 存量全量发布（用户确认后）

## 下一步
1. 用户确认 SAMPLE_PREVIEW.md 的 5 个样本格式
2. 创建 GitHub 仓库并 push 代码（确认无机密后）
3. WDC VPS clone + private.env + cron 定时
4. 正式运行 full 模式处理存量
