# OpenClaw Webhook API 使用指南

> 官方文档：https://docs.openclaw.ai/zh-CN/automation/webhook  
> 本文档结合官方文档与 live2d-ai-assistant 项目的实际接入经验整理。

---

## 1. 启用 Webhook

在 `~/.openclaw/openclaw.json` 中配置：

```json
{
  "hooks": {
    "enabled": true,
    "token": "your-shared-secret",
    "path": "/hooks",
    "allowRequestSessionKey": true
  }
}
```

- `hooks.token` 为必填项（当 `enabled=true` 时）。
- `hooks.path` 默认为 `/hooks`。
- **`allowRequestSessionKey: true`**：允许客户端指定 `sessionKey`，实现多轮对话上下文持久化（官方文档未明确提及，但已验证有效）。修改后需要**重启 openclaw-gateway 进程**使其生效。

---

## 2. 认证

每个请求必须携带 hook 令牌，三种方式（推荐顺序）：

| 方式 | 示例 |
|------|------|
| `Authorization` 请求头（推荐） | `Authorization: Bearer <token>` |
| `x-openclaw-token` 请求头 | `x-openclaw-token: <token>` |
| URL 参数（已弃用） | `?token=<token>` |

---

## 3. 端点

### 3.1 `POST /hooks/wake` — 触发心跳事件

向主会话注入一个系统事件，用于提醒 Agent 检查并响应外部变化。

```json
{
  "text": "收到新邮件",
  "mode": "now"
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | ✅ | 事件描述 |
| `mode` | `now` \| `next-heartbeat` | ❌ | 是否立即触发心跳（默认 `now`） |

**响应：** `200 OK`

---

### 3.2 `POST /hooks/agent` — 直接运行 Agent 处理任务

最常用的端点。向 Agent 发送消息，Agent 异步处理后返回结果。

```json
{
  "message": "Run this",
  "name": "Email",
  "sessionKey": "hook:email:msg-123",
  "wakeMode": "now",
  "deliver": false,
  "channel": "last",
  "to": "+15551234567",
  "model": "openai/gpt-4o",
  "thinking": "low",
  "timeoutSeconds": 120
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | ✅ | Agent 要处理的提示/消息 |
| `name` | string | ❌ | Hook 的可读名称（作为会话摘要前缀） |
| `sessionKey` | string | ❌ | 会话标识符。**默认为随机的 `hook:<uuid>`**（每次新建 session，无上下文）。**设置固定值可实现多轮对话**，要求服务端启用 `allowRequestSessionKey: true` |
| `wakeMode` | `now` \| `next-heartbeat` | ❌ | 触发时机（默认 `now`） |
| `deliver` | boolean | ❌ | 是否将结果发送到消息渠道（默认 `true`）。设为 `false` 仅做处理不推送 |
| `channel` | string | ❌ | 消息渠道（`last`、`whatsapp`、`telegram`、`discord`、`slack` 等，默认 `last`） |
| `to` | string | ❌ | 接收者标识（电话号码 / 聊天 ID / 频道 ID） |
| `model` | string | ❌ | 覆盖本次运行的模型（如 `anthropic/claude-3-5-sonnet`） |
| `thinking` | string | ❌ | 思考级别（`low` / `medium` / `high`） |
| `timeoutSeconds` | number | ❌ | Agent 运行的最大秒数 |

**响应：** `202 Accepted`

```json
{ "ok": true, "runId": "22c3a84e-cf8d-4c93-b837-233b6a45b7ea" }
```

> ⚠️ `/hooks/agent` 是**异步**接口，202 只表示任务已启动，**不包含 Agent 的回复内容**。获取结果需通过 WebSocket 事件监听（见第 5 节）。

**效果：**
- 运行一个独立的 Agent 回合。
- **始终在主会话中发布摘要**（无论 `deliver` 如何）。
- 若 `wakeMode=now`，立即触发心跳。

---

### 3.3 `POST /hooks/<name>` — 自定义映射 Hook

通过 `hooks.mappings` 将自定义端点映射到 `wake` 或 `agent` 操作，支持模板和 JS/TS 转换模块。

内置预设：
- `hooks.presets: ["gmail"]` — 启用 Gmail 映射

---

## 4. 响应状态码

| 状态码 | 说明 |
|--------|------|
| `200` | `/hooks/wake` 成功 |
| `202` | `/hooks/agent` 接受（异步，任务启动） |
| `401` | 认证失败（token 无效或缺失） |
| `400` | 请求体无效（含参数错误，如 `allowRequestSessionKey` 未启用时发送 `sessionKey`） |
| `413` | 请求体过大 |

---

## 5. 异步结果获取：WebSocket 事件监听

由于 `/hooks/agent` 返回 202 而非结果，必须通过 WebSocket 获取 Agent 的回复。

### 5.1 连接与认证

```python
import asyncio, json, uuid, websockets

WS_URL = "ws://localhost:18789"
TOKEN  = "your-token"

ws = await websockets.connect(
    WS_URL,
    additional_headers={"Origin": "http://localhost:18789"},
)
await asyncio.wait_for(ws.recv(), timeout=5)  # 等待欢迎消息

cid = str(uuid.uuid4())[:8]
await ws.send(json.dumps({
    "type": "req", "id": cid, "method": "connect",
    "params": {
        "minProtocol": 3, "maxProtocol": 3,
        "client": {
            "id": "cli", "version": "1.0", "platform": "python",
            "mode": "webchat", "instanceId": "my-app",
        },
        "role": "operator", "scopes": ["operator.admin"],
        "caps": [], "auth": {"token": TOKEN},
        "userAgent": "my-app/1.0", "locale": "zh-CN",
    }
}))
```

### 5.2 监听 Agent 回复事件

```python
session_key = "live2d-ai"
expected_sk = f"agent:main:{session_key}"

while True:
    raw = await asyncio.wait_for(ws.recv(), timeout=120)
    msg = json.loads(raw)
    
    if msg.get("type") != "event":
        continue
    if msg.get("event") != "chat":
        continue
    
    payload = msg.get("payload", {})
    if payload.get("sessionKey") != expected_sk:
        continue
    if payload.get("state") != "final":
        continue
    
    # 提取回复文本
    content = payload.get("content", [])
    text = "".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    )
    break
```

### 5.3 完整流程（先连 WS，再发 Hook）

```python
async def call_agent(message: str, session_key: str) -> str:
    # 1. 建立 WebSocket 连接并认证
    ws = await websockets.connect(WS_URL, additional_headers={"Origin": WS_URL})
    await ws.recv()
    await ws_auth(ws, TOKEN)
    
    # 2. POST /hooks/agent（带 sessionKey）
    async with httpx.AsyncClient() as c:
        await c.post(
            f"{BASE_URL}/hooks/agent",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={
                "message": message,
                "name": "Live2D",
                "sessionKey": session_key,
                "deliver": False,
                "wakeMode": "now",
            },
        )
    
    # 3. 监听 WS 事件，等待 final 状态
    expected_sk = f"agent:main:{session_key}"
    text = await wait_for_final_event(ws, expected_sk)
    
    await ws.close()
    return text
```

> **重要**：必须**先建立 WS 连接，再发 POST 请求**。否则可能错过在连接建立之前到达的事件。

---

## 6. Session 上下文持久化

| 模式 | `sessionKey` | 行为 |
|------|-------------|------|
| 默认（无上下文） | `hook:<随机uuid>`（每次不同） | 每次都是全新会话，无历史记忆 |
| 持久上下文 | 固定值（如 `live2d-ai`） | 同一 session，Agent 可访问历史对话 |

实际存储的 session key 格式为 `agent:main:<your-sessionKey>`，例如 `agent:main:live2d-ai`。

**配置要求：**

1. `~/.openclaw/openclaw.json` 中设置 `hooks.allowRequestSessionKey: true`
2. 修改配置后**重启 openclaw-gateway 进程**
3. 每次请求携带相同的 `sessionKey`

---

## 7. 安全建议

- 将 webhook 端口保持在 loopback（`127.0.0.1`）、内网或受信任的反向代理之后，不要暴露到公网。
- 使用专用的 hook token，勿与 Gateway 网关认证 token 复用。
- 避免在 webhook 日志中记录含敏感信息的请求体。
- 请求体默认以安全边界包装处理。如需禁用，在 mapping 配置中设置 `allowUnsafeExternalContent: true`（⚠️ 仅用于受信任的内部来源）。

---

## 8. 本项目配置（live2d-ai-assistant）

### app_config.json

```json
"openclaw": {
  "enabled": true,
  "base_url": "http://127.0.0.1:18789",
  "token": "your-token",
  "agent_name": "Live2D",
  "session_key": "live2d-ai",
  "timeout_seconds": 120
}
```

### ~/.openclaw/openclaw.json（关键片段）

```json
"hooks": {
  "enabled": true,
  "token": "your-token",
  "path": "/hooks",
  "allowRequestSessionKey": true
}
```

### 后端实现

- `backend/services/openclaw_service.py` — WebSocket 事件监听 + HTTP hook 触发
- 超时设置：WS recv 120s，整体 120s
- session 标识过滤：仅接受 `sessionKey == "agent:main:live2d-ai"` 且 `state == "final"` 的事件

---

## 9. 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| POST 返回 `400` | `allowRequestSessionKey` 未启用或 gateway 未重启 | 检查配置，重启 gateway |
| 每次都是新 session，无上下文 | `sessionKey` 未固定或 `allowRequestSessionKey` 未生效 | 确认配置并重启 gateway |
| 等不到 WS 事件 | WS 在 POST 之后才连接，错过了事件 | 必须先建 WS 连接，再 POST |
| `401 Unauthorized` | token 不匹配 | 确认 `app_config.json` 与 `openclaw.json` 中的 token 相同 |
| Gateway 响应慢 | 模型处理时间长 | 调大 `timeoutSeconds` 参数 |
