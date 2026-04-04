# 端到端实时语音模式设计

## 1. 概述

为 Live2D AI 助手新增**端到端实时语音模式**，替代现有的 ASR → LLM → TTS 管道。用户可选择在配置文件中选择使用哪种语音交互模式。

- **模式 A（现有）:** pipeline 模式 — VAD → ASR → LLM → TTS
- **模式 B（新增）:** realtime_volc — 火山端到端实时语音 API
- **模式 C（占位）:** realtime_local — 本地端到端模型（预留接口）

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        前端                                  │
│  ┌──────────────┐  ┌───────────────────┐  ┌─────────────┐ │
│  │  pipeline.js │  │   realtime-volc.js │  │ live2d-... │ │
│  │  (现有管道)   │  │   (新增:火山实时)    │  │  (Live2D)   │ │
│  └──────┬───────┘  └─────────┬──────────┘  └──────┬──────┘ │
│         │                     │                     │        │
│         └──────────────┬──────┴─────────────────────┘        │
│                        ▼                                      │
│                   app.js (模式路由)                            │
└────────────────────────┼────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                        后端                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │               realtime_service.py                     │  │
│  │         (工厂函数: 根据 VOICE_MODE 选择实现)            │  │
│  └──────────────────────┬───────────────────────────────┘  │
│                         │                                    │
│  ┌──────────────────────┴───────────────────────────────┐  │
│  │              realtime_base.py                       │  │
│  │              (抽象基类: 定义统一接口)                  │  │
│  └──────────────────────┬───────────────────────────────┘  │
│                         │                                    │
│     ┌────────────────────┴────────────────────┐             │
│     │                 │                       │             │
│  ┌──▼───────┐   ┌─────▼────────┐   ┌──────▼───────┐      │
│  │ realtime │   │ realtime_volc │   │ realtime_local│      │
│  │  _volc   │   │   (火山实现)   │   │   (本地占位)  │      │
│  └──────────┘   └───────────────┘   └───────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 后端模块设计

### 3.1 抽象基类 `backend/services/realtime_base.py`

定义统一的端到端实时语音接口。

**RealtimeCallback — 事件回调接口：**

```python
class RealtimeCallback:
    on_session_started: Callable[[dict], None]   # 会话启动，参数: {dialog_id}
    on_asr_response: Callable[[str], None]      # ASR 识别结果，参数: text
    on_tts_response: Callable[[bytes], None]    # TTS 音频数据，参数: audio_bytes
    on_tts_sentence_start: Callable[[dict], None]  # TTS 句子开始
    on_tts_sentence_end: Callable[[dict], None]    # TTS 句子结束
    on_session_finished: Callable[[], None]      # 会话结束
    on_session_failed: Callable[[str], None]     # 会话失败，参数: error_message
    on_error: Callable[[Exception], None]         # 错误
    on_close: Callable[[], None]                 # 连接关闭
```

**RealtimeSession — 会话抽象：**

```python
class RealtimeSession(ABC):
    session_id: str
    is_active: bool

    def set_callback(self, callback: RealtimeCallback): ...

    @abstractmethod
    async def start_session(self): ...

    @abstractmethod
    async def send_audio(self, audio_chunk: bytes): ...
        """发送音频数据（20ms PCM）"""

    @abstractmethod
    async def send_text(self, text: str): ...
        """发送文本（text 模式）"""

    @abstractmethod
    async def finish_session(self): ...

    @abstractmethod
    async def close(self): ...
```

**RealtimeService — 服务抽象：**

```python
class RealtimeService(ABC):
    @abstractmethod
    async def create_session(
        self,
        session_id: str,
        config: dict,
        callback: RealtimeCallback
    ) -> RealtimeSession: ...
```

### 3.2 火山实现 `backend/services/realtime_volc.py`

**协议实现：**

| 组件 | 说明 |
|------|------|
| 协议版本 | v1 |
| 消息类型 | Full-client request (0x01), Full-server response (0x09), Audio-only response (0x0B), Error (0x0F) |
| 序列化 | JSON (文本事件), Raw (音频数据) |
| 压缩 | gzip（暂不支持） |

**二进制帧格式：**

```
Byte 0: [Protocol Version (4bit) | Header Size (4bit)]
Byte 1: [Message Type (4bit) | Flags (4bit)]
Byte 2: [Serialization (4bit) | Compression (4bit)]
Byte 3: Reserved (0x00)
[Optional fields per Flags]
[Payload Size (4 bytes, big-endian)]
[Payload]
```

**事件定义：**

| 客户端事件 | ID | 说明 |
|-----------|-----|------|
| StartConnection | 1 | 建立 WebSocket 连接 |
| FinishConnection | 2 | 断开连接 |
| StartSession | 100 | 启动会话 |
| FinishSession | 102 | 结束会话 |
| TaskRequest | 200 | 发送音频数据 |
| EndASR | 400 | 音频输入结束（push_to_talk 模式） |
| ChatTextQuery | 501 | 文本输入 |

| 服务端事件 | ID | 说明 |
|-----------|-----|------|
| ConnectionStarted | 50 | 连接成功 |
| ConnectionFailed | 51 | 连接失败 |
| SessionStarted | 150 | 会话启动，返回 dialog_id |
| SessionFinished | 152 | 会话结束 |
| SessionFailed | 153 | 会话失败 |
| TTSResponse | 352 | 返回音频数据 |
| TTSSentenceStart | 350 | TTS 句子开始 |
| TTSSentenceEnd | 351 | TTS 句子结束 |
| ASRInfo | 450 | 检测到用户说话 |
| ASRResponse | 451 | ASR 识别结果 |
| ASREnded | 459 | 用户说话结束 |
| ChatResponse | 550 | 模型回复文本 |
| ChatEnded | 559 | 模型回复结束 |

**VolcRealtimeSession 核心逻辑：**

```
start_session():
  1. 建立 WebSocket 连接
  2. 发送 StartConnection
  3. 等待 ConnectionStarted
  4. 发送 StartSession (含 model、tts、asr、dialog 配置)
  5. 等待 SessionStarted
  6. 启动 _recv_loop 后台任务

send_audio(audio_chunk):
  1. 构造二进制帧 (Message Type=0x02 Audio-only request)
  2. 直接发送音频数据（无 JSON）

_recv_loop():
  1. 循环读取 WebSocket 帧
  2. 根据 Message Type 和 Event 分发到对应回调
  3. TTSResponse: 音频数据传给 on_tts_response
  4. ASRResponse: 识别文本传给 on_asr_response
  5. ASREnded: 通知用户说话结束
  6. SessionFinished: 置结束标志

finish_session():
  1. 发送 FinishSession 事件
  2. 等待 SessionFinished 事件

close():
  1. 取消 _recv_loop
  2. 发送 FinishConnection
  3. 关闭 WebSocket
```

**音频参数：**

| 方向 | 格式 | 采样率 | 位深 | 声道 |
|------|------|--------|------|------|
| 输入 | PCM / Opus | 16000 | int16 | mono |
| 输出 | OGG Opus (默认) / PCM | 24000 | 16bit | mono |

**配置参数 (StartSession)：**

```python
{
    "tts": {
        "audio_config": {
            "format": "pcm_s16le",   # 或 "pcm"
            "sample_rate": 24000,
            "channel": 1
        },
        "speaker": "zh_female_vv_jupiter_bigtt"  # 音色
    },
    "asr": {
        "extra": {
            "input_mod": "push_to_talk"  # 或 "keep_alive"
        }
    },
    "dialog": {
        "extra": {
            "model": "1.2.1.1",  # 或 "2.2.0.0"
            "enable_volc_websearch": False,
            "enable_music": False
        }
    }
}
```

### 3.3 本地占位 `backend/services/realtime_local.py`

```python
class LocalRealtimeService(RealtimeService):
    """本地端到端模型占位实现"""

    async def create_session(
        self,
        session_id: str,
        config: dict,
        callback: RealtimeCallback
    ) -> RealtimeSession:
        raise NotImplementedError("本地模型待实现")
```

### 3.4 工厂函数 `backend/services/realtime_service.py`

```python
def create_realtime_service(provider: str = None) -> RealtimeService:
    """
    根据配置创建端到端实时语音服务

    Args:
        provider: realtime_volc / realtime_local

    Returns:
        RealtimeService 实例
    """
    provider = provider or os.getenv("REALTIME_PROVIDER", "realtime_volc")

    if provider == "realtime_local":
        from backend.services.realtime_local import LocalRealtimeService
        return LocalRealtimeService()
    else:  # 默认 realtime_volc
        from backend.services.realtime_volc import VolcRealtimeService
        return VolcRealtimeService()
```

---

## 4. 前端模块设计

### 4.1 `frontend/static/js/realtime-volc.js`

**核心类: RealtimeVolcController**

```javascript
class RealtimeVolcController {
    constructor(options)
    async connect()
    async startSession(config)
    async sendAudio(audioChunk)   // 20ms PCM
    async sendText(text)
    async finishSession()
    async close()

    // 回调
    onSessionStarted(dialogId)
    onASRResponse(text, is Interim)
    onTTSResponse(audioBuffer)
    onTTSEnd()
    onError(error)
}
```

**音频处理：**

- 录音：使用 `AudioContext` + `MediaRecorder` 或 `AudioWorklet` 采集 16kHz PCM
- 发送节奏：每 20ms 发送一包（640 bytes），休眠 20ms
- 播放：使用 `AudioContext` 解码并播放 OGG/PCM 音频流

**WebSocket 事件流：**

```
连接 → startSession() → sendAudio() × N → (服务端 VAD 检测结束) →
→ onASRResponse() → onTTSResponse() → ... → finishSession()
```

### 4.2 模式路由 (app.js)

```javascript
// 根据配置选择模式
const voiceMode = CONFIG.VOICE_MODE;  // 'pipeline' | 'realtime_volc'

if (voiceMode === 'realtime_volc') {
    realtimeController = new RealtimeVolcController({...});
} else {
    // 现有 pipeline 逻辑
}
```

---

## 5. 配置项

### 5.1 .env 新增

```bash
# ===========================================
# 语音模式选择
# ===========================================
# pipeline:   现有管道 (VAD → ASR → LLM → TTS)
# realtime_volc: 火山端到端实时语音
# realtime_local: 本地端到端模型（占位）
VOICE_MODE=realtime_volc

# ===========================================
# 火山端到端实时语音配置
# ===========================================
VOLC_REALTIME_APP_ID=your-app-id
VOLC_REALTIME_ACCESS_KEY=your-access-key
VOLC_REALTIME_RESOURCE_ID=volc.speech.dialog
VOLC_REALTIME_APP_KEY=PlgvMymc7f3tQnJ6
VOLC_REALTIME_WS_URL=wss://openspeech.bytedance.com/api/v3/realtime/dialogue

# 模型版本: 1.2.1.1 (O2.0) / 2.2.0.0 (SC2.0)
VOLC_REALTIME_MODEL=1.2.1.1

# 音色 (O2.0)
VOLC_REALTIME_VOICE=zh_female_vv_jupiter_bigtt

# 功能开关
VOLC_REALTIME_ENABLE_WEBSEARCH=false
VOLC_REALTIME_ENABLE_MUSIC=false
```

### 5.2 音色列表

**O2.0 版本精品音色：**

| 音色 ID | 描述 |
|---------|------|
| zh_female_vv_jupiter_bigtt | vv音色，活泼灵动的女声 |
| zh_female_xiaohe_jupiter_bigtt | xiaohe音色，甜美活泼的女声，有台湾口音 |
| zh_male_yunzhou_jupiter_bigtt | yunzhou音色，清爽沉稳的男声 |
| zh_male_xiaotian_jupiter_bigtt | xiaotian音色，清爽磁性的男声 |

**SC2.0 版本克隆音色：**

| 音色 ID | 描述 |
|---------|------|
| saturn_zh_female_* | 女性克隆音色 |
| saturn_zh_male_* | 男性克隆音色 |

---

## 6. 错误处理

| 错误码 | 错误信息 | 处理方式 |
|--------|----------|----------|
| 45000003 | Abnormal silence audio | 重试连接 |
| 50000000 | AudioQueryError | 通知前端，结束会话 |
| 52000042 | DialogAudioIdleTimeoutError | 使用 `keep_alive` 模式 |
| 50700000 | CallWithTimeout | 重试或通知前端 |
| 55000001 | ServerError | 通知前端，结束会话 |

**客户端保护机制：**

- WebSocket 连接失败：重试 3 次，间隔 1s
- 5 分钟无交互：自动结束会话

---

## 7. 文件结构

```
backend/services/
├── realtime_base.py      # 抽象基类和回调接口
├── realtime_volc.py      # 火山端到端实时语音实现
├── realtime_local.py     # 本地模型占位
└── realtime_service.py   # 工厂函数

frontend/static/js/
└── realtime-volc.js      # 前端实时语音控制器

.env.example              # 新增配置项
```

---

## 8. 测试计划

| 测试类型 | 内容 |
|----------|------|
| 单元测试 | 二进制帧构造/解析、事件转换 |
| 集成测试 | 完整对话流程（启动→录音→响应→结束） |
| 人工测试 | 长时间对话、超时恢复、模式切换 |

---

## 9. 实现清单

- [ ] `backend/services/realtime_base.py` — 抽象基类
- [ ] `backend/services/realtime_volc.py` — 火山实现
- [ ] `backend/services/realtime_local.py` — 本地占位
- [ ] `backend/services/realtime_service.py` — 工厂函数
- [ ] `frontend/static/js/realtime-volc.js` — 前端模块
- [ ] `.env.example` — 新增配置
- [ ] 单元测试
