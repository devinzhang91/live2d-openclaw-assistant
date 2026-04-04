# 火山端到端实时语音实现总结

## 协议层面关键发现

### 1. WebSocket 帧格式

**头部 (4 bytes):**
```
Byte 0: [Protocol Version (4bit) | Header Size (4bit)]
Byte 1: [Message Type (4bit) | Message Type Specific Flags (4bit)]
Byte 2: [Serialization (4bit) | Compression (4bit)]
Byte 3: Reserved (0x00)
```

**客户端音频帧 (Audio-only request) — 关键发现:**
- `message_type = 0x02`
- `flags = 0x00 (NO_SEQUENCE)` — 不带 sequence 字段
- `serialization = 0x0 (NO_SERIALIZATION)`
- `compression = 0x1 (GZIP)` — 音频数据必须 gzip 压缩
- payload = gzip(音频数据)

**事件帧 (Full-client request):**
- `message_type = 0x01`
- `flags = 0x04 (HAS_EVENT)` 或组合 `0x04 | 0x01 | 0x02`
- `serialization = 0x1 (JSON)`, `compression = 0x1 (GZIP)`
- payload = gzip(json)

### 2. 客户端事件 ID

| 事件 | ID | 说明 |
|------|-----|------|
| StartConnection | 1 | 建立 WebSocket 连接 |
| FinishConnection | 2 | 断开连接 |
| StartSession | 100 | 启动会话 |
| FinishSession | 102 | 结束会话 |
| TaskRequest | 200 | 发送音频数据 |
| EndASR | 400 | 音频输入结束 (push_to_talk) |
| ChatTextQuery | 501 | 文本输入 |

### 3. 服务端事件 ID

| 事件 | ID | 说明 |
|------|-----|------|
| ConnectionStarted | 50 | 连接成功 |
| SessionStarted | 150 | 会话启动 |
| SessionFinished | 152 | 会话结束 |
| SessionFailed | 153 | 会话失败 |
| TTSSentenceStart | 350 | TTS 句子开始 |
| TTSSentenceEnd | 351 | TTS 句子结束 |
| TTSResponse | 352 | TTS 音频数据 |
| TTSEnded | 359 | TTS 结束 |
| ASRInfo | 450 | 检测到用户说话 |
| ASRResponse | 451 | ASR 识别结果 |
| ASREnded | 459 | 用户说话结束 |
| ChatResponse | 550 | 模型回复文本 |
| ChatEnded | 559 | 模型回复结束 |

### 4. StartSession 配置

必须包含完整字段，否则会报 `InvalidSpeaker` 错误：

```json
{
  "event": 100,
  "namespace": "S2SAudioDialogue",
  "tts": {
    "audio_config": {
      "format": "pcm",
      "sample_rate": 24000,
      "channel": 1
    },
    "speaker": "zh_male_yunzhou_jupiter_bigtts"  // 必须使用 _bigtts 后缀
  },
  "asr": {
    "extra": {
      "end_smooth_window_ms": 1500,
      "input_mod": "push_to_talk"  // 或 "keep_alive"
    }
  },
  "dialog": {
    "bot_name": "豆包",
    "system_role": "你使用活泼灵动的女声，性格开朗，热爱生活。",
    "speaking_style": "你的说话风格简洁明了，语速适中，语调自然。",
    "location": {"city": "北京"},
    "extra": {
      "model": "1.2.1.1",
      "enable_volc_websearch": false,
      "enable_music": false
    }
  }
}
```

### 5. 音频参数

| 方向 | 格式 | 采样率 | 位深 | 声道 |
|------|------|--------|------|------|
| 输入 | PCM / Opus | 16000 | int16 | mono |
| 输出 | PCM (pcm_s16le) | 24000 | 16bit | mono |

### 6. push_to_talk 模式关键流程

1. `StartConnection` → `ConnectionStarted`
2. `StartSession` → `SessionStarted`
3. 循环发送 `TaskRequest` (音频帧)
4. **发送 `EndASR` 信号** — 通知服务器音频输入结束
5. 接收 `ASRResponse` ( interim=false 表示最终结果)
6. 接收 `ChatResponse` 流
7. 接收 `TTSResponse` 流
8. 接收 `ChatEnded` → `TTSSentenceEnd` → `TTSEnded`
9. `FinishSession` → `SessionFinished`
10. `FinishConnection`

### 7. 验证过的音色 ID

- `zh_male_yunzhou_jupiter_bigtts` ✓ (男声，清爽沉稳)
- `zh_female_vv_jupiter_bigtt` ✗ (InvalidSpeaker)
- `zh_female_xiaohe_jupiter_bigtt` (女声，甜美活泼，台湾口音)
- `zh_male_xiaotian_jupiter_bigtt` (男声，清爽磁性)

### 8. 错误码

| 错误码 | 说明 | 处理方式 |
|--------|------|----------|
| 52000042 | DialogAudioIdleTimeoutError | 需要在发送完音频后及时发送 END_ASR |
| 40000000 | InvalidSpeaker | 音色 ID 不正确，需加 _bigtts 后缀 |
