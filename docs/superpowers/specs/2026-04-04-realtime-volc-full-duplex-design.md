# 火山端到端实时语音全双工改造设计

## 1. 目标

将 `realtime_volc` 模式从 push_to_talk 改为全双工持续对话模式。

## 2. 交互模型

```
用户点击语音按钮
    ↓
前端 VAD 检测到语音活动
    ↓
建立 WebSocket 连接
    ↓
StartSession (input_mod: "audio", recv_timeout: 120)
    ↓
← 持续发送 200ms 音频包 →
← 持续接收 TTS 音频流 → 前端播放
    ↓
用户停止说话（静默）
    ↓
服务端 recv_timeout=120s 无响应
    ↓
服务端发送 SessionFinished
    ↓
前端收到，关闭 WebSocket，回到待机
```

## 3. 打断机制

- 打断由火山服务端自动处理（event 450 → 清空 TTS 队列）
- 前端无需实现打断逻辑，服务端自动处理用户继续说话时 AI 正在说话的情况

## 4. 关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `input_mod` | `"audio"` | 持续音频输入模式 |
| `recv_timeout` | `120` | 服务端静默超时（秒），最大允许值 |
| 音频包间隔 | 200ms | 前端每 200ms 发送一包音频 |
| 采样率 | 16000Hz | 输入音频采样率 |
| 输出格式 | pcm_s16le | 24kHz, 16bit, mono |

## 5. 前端变更 (frontend/static/js/)

### 5.1 新增模式

- 新增 `voiceMode = 'realtime_full_duplex'` 标识全双工模式
- `switchInputMode('voice')` 时：
  - 不启动 pipeline 模式的 VAD 监听
  - 改为"点击按钮开始"的交互

### 5.2 按钮交互

- **按钮按下**：开始录音，持续发送 200ms 音频包
- **按钮松开**：继续录音，但不停止（等待 recv_timeout 超时自然结束）
- **再次点击**：主动断开连接

### 5.3 WebSocket 消息

| type | 方向 | 说明 |
|------|------|------|
| `audio_start` | 前端→后端 | 开始持续录音并发送音频 |
| `audio` | 前端→后端 | 200ms 音频数据块（持续发送） |
| `audio_stop` | 前端→后端 | 主动停止录音（不断开连接，等 recv_timeout） |
| `tts_audio` | 后端→前端 | TTS 音频流 |
| `asr_partial` | 后端→前端 | ASR 实时识别结果 |
| `chat_response` | 后端→前端 | LLM 回复文本流 |
| `realtime_session_started` | 后端→前端 | 会话已启动 |
| `realtime_session_finished` | 后端→前端 | 会话结束（recv_timeout 触发） |

## 6. 后端变更 (backend/api/websocket.py)

### 6.1 StartSession 配置

```python
{
    "event": 100,
    "namespace": "S2SAudioDialogue",
    "tts": {
        "audio_config": {
            "format": "pcm",
            "sample_rate": 24000,
            "channel": 1
        },
        "speaker": "<voice_type>"
    },
    "asr": {
        "extra": {
            "end_smooth_window_ms": 1500,
            "input_mod": "audio"  # 持续输入模式
        }
    },
    "dialog": {
        "extra": {
            "recv_timeout": 120,
            "input_mod": "audio"
        }
    }
}
```

### 6.2 不再发送 END_ASR

- push_to_talk 模式下 `audio_end` 触发 END_ASR
- 全双工模式下 `audio_end` 不发送 END_ASR
- 会话由服务端 recv_timeout 计时器自动结束

### 6.3 会话结束处理

- 收到 `SessionFinished` (event 152) 或 `SessionFailed` (event 153) 时
- 关闭 WebSocket 连接
- 前端收到 `realtime_session_finished` 消息

## 7. 状态机（前端）

```
idle → [点击按钮] → listening → [VAD 检测到语音] → talking
talking → [recv_timeout 结束] → idle
talking → [再次点击按钮] → idle
```

## 8. 不涉及的变更

- 后端 VAD（`vad_service.py`）— 不需要
- pipeline 模式 — 不受影响，独立存在
- OpenClaw 集成 — 在 pipeline 模式下工作，不涉及 realtime_volc
