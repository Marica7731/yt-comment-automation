# yt-comment-automation

给 B 站合集视频的评论区自动发布「YouTube 时间戳歌轴」评论的工具。

B 站投稿简介第一行通常是 `https://youtu.be/<id>`（对应油管原视频）。本项目自动：

1. **检测合集更新**：读取 B 站 UGC 合集（ugc_season）全部视频，对比上次快照找出新增
2. **抓取油管评论区**：无 cookie，纯 urllib 拉取评论 + 简介 + 章节
3. **本地规则清洗**：从评论时间轴提取「时间戳 + 歌名 - 歌手」列表
   （规则移植自油猴脚本《YouTube 评论纯文本复制 + AI整理》，含括号保护、编号剥离、宣伝过滤、分隔符统一）
4. **AI 兜底**：本地结果不足时用 DeepSeek（deepseek-v4-flash）直接从原文整理，自动命中 prompt 缓存降成本
5. **发布 + 飞书通知**：用 B 站投稿 cookie 发布评论，成功后飞书通知
   （B 站链接 / 油管链接 / 评论时间 / 歌曲数量）

## 目录结构

```
yt_comment_automation/
  collections.py   B站合集抓取 + 新增检测
  yt_fetch.py      油管评论/简介抓取（无 cookie，原始 JSON 落盘缓存）
  clean.py         本地规则清洗：时间戳/歌名/歌手提取
  ai.py            DeepSeek 兜底整理（responses API + prompt 缓存）
  bili_comment.py  B站评论：cookie 加载、已有评论检测、发布
  notify.py        飞书文本消息
  pipeline.py      管道编排（增量/全量/指定）
  cli.py           命令行入口
  config.py        配置（环境变量 + private.env）
tests/
  test_clean.py    清洗规则单元测试
```

## 使用

```bash
# 0. 配置（复制 private.env.example → private.env 填入真实值；敏感项也可用环境变量）
cp private.env.example private.env

# 1. 只读扫描：列出合集视频与新增
python -m yt_comment_automation.cli scan

# 2. 干跑：处理 N 个视频但不发布不通知（预览将发布的评论）
python -m yt_comment_automation.cli dry-run --limit 3

# 3. 指定视频干跑
python -m yt_comment_automation.cli dry-run --bvid BV1ixuN6AExD

# 4. 正式运行：增量（只处理新增 + 未发布存量），发布 + 飞书通知
python -m yt_comment_automation.cli run --mode incremental

# 5. 正式运行：全量（处理快照内所有未发布视频）
python -m yt_comment_automation.cli run --mode full
```

## 配置项（private.env / 环境变量）

| 变量 | 说明 |
|---|---|
| `BILI_COOKIE_FILE` | B站投稿 cookie（biliup 格式 JSON，含 SESSDATA/bili_jct/DedeUserID） |
| `COLLECTION_ANCHORS` | 合集锚点 BV 号，逗号分隔（合集内任意视频 BV 号） |
| `COLLECTION_NAMES` | 合集显示名（可选） |
| `OWNER_MID` | 发布账号 mid（用于跳过已发布检测） |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（可选，本地结果不足时兜底） |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `MY_FEISHU_OPEN_ID` | 飞书自建应用 |
| `DRY_RUN` | 默认 1 只干跑（CLI run 命令读取） |

## 跳过与幂等

- 已发布过「时间戳歌轴评论」的视频自动跳过（按 owner mid + 评论内容含 ≥3 条时间戳编号判定）
- 处理记录存 `data/processed.json`，合集快照存 `data/collections_snapshot.json`，可安全重跑
- 油管原始 JSON 缓存于 `data/yt_raw/<id>.info.json`，二次运行免抓取

## 机密与安全

- `private.env`、`runtime/`、`data/` 已在 `.gitignore` 中排除，**不会上传任何 cookie / API Key / IP**
- 无第三方运行时依赖（标准库 urllib/re/json），测试用 pytest
