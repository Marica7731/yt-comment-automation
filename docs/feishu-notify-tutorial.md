# 飞书机器人通知教程（通用）

给任意脚本/定时任务发飞书消息的完整教程。纯标准库（`urllib`），不依赖第三方库，Windows / Linux / WSL 都可用。

## 一、准备：创建飞书自建应用

1. 打开 [飞书开放平台](https://open.feishu.cn/app) → 「创建企业自建应用」。
2. 随便填应用名称（如 `通知机器人`），创建后进入应用详情。
3. 在「凭证与基础信息」页拿到：
   - `App ID`（形如 `cli_xxxxxxxxxxxxxxxx`）
   - `App Secret`（形如 `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）
4. 在「权限管理」里开通：
   - `im:message`（获取与发送单聊、群组消息）
   - `im:message:send_as_bot`（以应用身份发消息）
5. 在「应用能力」里确保启用「机器人」能力。
6. 在「版本管理与发布」里创建版本并**发布上线**（否则调用会报权限错误）。企业自建应用发布后默认所有成员可用。

## 二、获取接收人 open_id

飞书消息要发给具体的人，需要知道对方的 `open_id`（每个应用下每个用户唯一）。

方式 A（推荐，一次性）：用「获取用户信息」接口

```python
import json
import urllib.request

APP_ID = "cli_xxx"
APP_SECRET = "xxx"

# 1. 换 tenant_access_token
resp = json.load(urllib.request.urlopen(urllib.request.Request(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    data=json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
), timeout=10))
token = resp["tenant_access_token"]

# 2. 查用户 open_id（需要手机号或邮箱，且该用户已授权给应用）
# GET https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id
```

方式 B（最简单）：让接收人给机器人发一条消息，然后在飞书开放平台「事件与回调」或应用后台看 `open_id`。

方式 C（本项目已有）：`MY_FEISHU_OPEN_ID` 已配置在环境里，直接复用即可。

## 三、发送文本消息（核心代码）

```python
import json
import urllib.request

APP_ID = "cli_xxx"
APP_SECRET = "xxx"
RECEIVER_OPEN_ID = "ou_xxx"  # 接收人 open_id

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"

def send_feishu_message(text: str) -> tuple[bool, str]:
    """发送文本消息到指定 open_id。返回 (成功, 说明)。"""
    # 1. 换 token
    body = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        token = json.loads(resp.read().decode("utf-8"))["tenant_access_token"]

    # 2. 发消息
    payload = {
        "receive_id": RECEIVER_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    req = urllib.request.Request(MESSAGE_URL, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "Authorization": f"Bearer {token}"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))
    if resp_data.get("code") != 0:
        return False, f"code={resp_data.get('code')} msg={resp_data.get('msg')}"
    return True, f"message_id={resp_data.get('data', {}).get('message_id', '')}"
```

调用：

```python
ok, note = send_feishu_message("✅任务完成\n详情见日志")
print(ok, note)
```

消息内容 `\n` 换行即可，emoji 直接写。

## 四、命令行用法（本项目已封装）

`send_codex_brief.py` 从标准输入读取文本并发送到配置好的 open_id，适合在 bash/PowerShell 里管道调用：

```bash
# 直接管道
echo "✅部署完成" | python G:/codex-work/feishupy_deve/feishu_yt_plus/send_codex_brief.py

# 多行内容
printf "✅构建成功\n版本 v1.2.3\n时间 $(date)" | python .../send_codex_brief.py

# 干跑（只打印不发送）
echo "测试" | python .../send_codex_brief.py --dry-run
```

依赖：脚本从环境变量读取飞书凭据（`FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `MY_FEISHU_OPEN_ID`），需先 export 或在进程环境里配置好。它内部加载 `feishu_hub.py` 的发送函数，凭据也可以由该 hub 的既有配置提供。

## 五、常见问题

| 现象 | 原因 |
|---|---|
| `code=99991663` / 权限错误 | 应用没开通 `im:message` 权限，或版本没发布上线 |
| `code=99991668` | open_id 不属于当前应用（换了个应用就失效，要重新查） |
| token 获取失败 `code=10003` | App ID / Secret 填错 |
| 消息发出去但收不到 | 接收人没在应用可见范围内（企业自建应用默认全员可见，自建小程序需加人） |
| 中文乱码 | 请求头必须带 `Content-Type: application/json; charset=utf-8`，内容用 `ensure_ascii=False` |

## 六、安全提醒

- `App Secret` 属于敏感信息，不要提交进 git、不要写进 Markdown/交接文档。
- 放环境变量或本地 gitignore 的 `private.env` 文件。
- 发送内容默认会被飞书服务端留存，别发 token / cookie / 密码。
