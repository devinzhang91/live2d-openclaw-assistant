# 程序架构说明

## 目录

1. [系统概览](#1-系统概览)
2. [项目结构](#2-项目结构)
3. [技术架构图](#3-技术架构图)
4. [后端服务模块](#4-后端服务模块)
5. [模块依赖关系](#5-模块依赖关系)
6. [前端模块](#6-前端模块)

---

## 1. 系统概览

### 1.1 项目定位

Live2D AI 助手是一个集成了 Live2D 看板娘的智能对话系统，支持**文本对话**和**语音对话**两种交互模式。

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | HTML5, CSS3, JavaScript, Live2D Widget |
| 后端 | Python FastAPI |
| ASR | faster-whisper（本地）、Volc ASR（云端） |
| LLM | OpenAI 兼容接口（OpenAI、DeepSeek、阿里等） |
| TTS | edge-tts（本地）、Volc TTS（云端） |
| VAD | Silero VAD（能量检测） |

### 1.3 两种语音模式

本项目支持两种不同的语音交互模式：

| 模式 | 说明 | 特点 |
|------|------|------|
| **pipeline（语音回环）** | VAD → ASR → LLM → TTS 分阶段处理 | 支持断句、通用 ASR 模型 |
| **realtime（实时语音）** | WebSocket 流式端到端对话 | 低延迟、自带 ASR/TTS |

配置通过环境变量 `VOICE_MODE` 选择：

```python
VOICE_MODE=pipeline     # 默认，分阶段语音回环
VOICE_MODE=realtime_volc  # 火山端到端实时语音
VOICE_MODE=realtime_local # 本地模型（预留）
```

---

## 2. 项目结构

```mermaid
classDiagram
direction TB

class main {
    +app: FastAPI
}

class rest_router {
    +POST /llm/chat
    +POST /asr/transcribe
    +POST /tts/synthesize
    +POST /vad/detect
    +GET /settings
    +POST /settings
}

class ws_router {
    +WS /ws/chat
    +WS /ws/realtime_volc
}

class Settings {
    +host, port, debug
    +llm_*, asr_*, tts_*, vad_*
    +voice_mode
}

class ConfigManager {
    +get_settings_dict()
    +update_settings()
    +get_current_voice_type()
    +get_system_prompt()
}

class LLMService
class ASRService
class TTSService
class VADService
class IntentRouter
class OpenClawService

class RealtimeService {
    <<abstract>>
    +create_session()
}

class VolcRealtimeService {
    +create_session()
}

class LocalRealtimeService {
    +create_session()
}

main --> rest_router
main --> ws_router
main --> Settings
rest_router --> ConfigManager
rest_router --> LLMService
rest_router --> ASRService
rest_router --> TTSService
rest_router --> VADService
ws_router --> IntentRouter
ws_router --> OpenClawService
IntentRouter --> OpenClawService
ConfigManager --> Settings
RealtimeService <|-- VolcRealtimeService
RealtimeService <|-- LocalRealtimeService
ws_router --> RealtimeService
```

---

## 3. 技术架构图

### 3.1 系统分层架构

```mermaid
graph TB
    subgraph 前端层["前端 (frontend/)"]
        A1["index.html"]
        A2["app.js<br>音频录制/播放"]
        A3["live2d-controller.js<br>Live2D 控制"]
    end

    subgraph API层["API 层 (backend/api/)"]
        B1["rest.py<br>REST API"]
        B2["websocket.py<br>WebSocket API"]
    end

    subgraph 服务层["服务层 (backend/services/)"]
        C1["LLM Service<br>llm_service.py"]
        C2["ASR Service<br>asr_service.py"]
        C3["TTS Service<br>tts_service.py"]
        C4["VAD Service<br>vad_service.py"]
        C5["Intent Router<br>intent_router.py"]
        C6["OpenClaw Service<br>openclaw_service.py"]
    end

    subgraph 实时语音["实时语音 (backend/services/)"]
        D1["RealtimeService<br>realtime_service.py"]
        D2["VolcRealtimeService<br>realtime_volc.py"]
        D3["LocalRealtimeService<br>realtime_local.py"]
    end

    subgraph 配置层["配置层 (backend/config/)"]
        E1["Settings<br>settings.py<br>环境变量"]
        E2["ConfigManager<br>config_manager.py<br>运行时配置"]
    end

    A2 --> B2
    B1 --> C1 & C2 & C3 & C4
    B2 --> C1 & C2 & C3 & C4 & C5 & C6
    B2 --> D1
    C5 --> C6
    E2 --> E1
```

### 3.2 服务模块职责一览

| 模块 | 文件 | 职责 |
|------|------|------|
| **LLM Service** | `llm_service.py` | LLM 调用封装，支持 OpenAI 兼容接口 |
| **ASR Service** | `asr_service.py` | 语音识别服务抽象，根据配置选择 faster-whisper 或 Volc ASR |
| **TTS Service** | `tts_service.py` | 语音合成服务抽象，根据配置选择 edge-tts 或 Volc TTS |
| **VAD Service** | `vad_service.py` | 语音活动检测，使用 Silero VAD 模型 |
| **Intent Router** | `intent_router.py` | 意图识别，决定走 OpenClaw 还是普通 LLM |
| **OpenClaw Service** | `openclaw_service.py` | OpenClaw webhook 调用 |
| **ConfigManager** | `config_manager.py` | 运行时配置管理（性格、语速、TTS 参数等） |

---

## 4. 后端服务模块

### 4.1 目录结构

```
backend/
├── main.py                 # FastAPI 应用入口
├── api/
│   ├── rest.py            # REST API 路由
│   └── websocket.py       # WebSocket 路由
├── config/
│   ├── settings.py        # 环境变量配置
│   └── config_manager.py  # 运行时配置管理
└── services/
    ├── llm_service.py     # LLM 服务抽象
    ├── llm_openai.py      # OpenAI LLM 实现
    ├── llm_volc.py        # 火山 LLM 实现
    ├── asr_service.py      # ASR 服务抽象
    ├── asr_base.py        # ASR 基类
    ├── asr_whisper.py     # faster-whisper 实现
    ├── asr_volc.py        # 火山 ASR 实现
    ├── tts_service.py      # TTS 服务抽象
    ├── tts_base.py        # TTS 基类
    ├── tts_volc.py        # 火山 TTS 实现
    ├── vad_service.py     # VAD 服务
    ├── intent_router.py   # 意图路由
    ├── openclaw_service.py # OpenClaw 调用
    ├── realtime_service.py  # 实时语音工厂
    ├── realtime_base.py    # 实时语音抽象基类
    ├── realtime_volc.py    # 火山实时语音实现
    └── realtime_local.py   # 本地实时语音实现
```

### 4.2 服务实现继承关系

```mermaid
classDiagram
direction TB

class LLMService {
        +chat_completion()
    }

class OpenAILLMService {
        +client: OpenAI
        +chat_completion()
    }

class VolcLLMService {
        +chat_completion()
    }

class ASRService {
        +transcribe_file()
        +create_session()
    }

class ASRBase {
        +model
        +transcribe_file()
        +create_session()
    }

class WhisperASRService {
        +model
        +transcribe_file()
    }

class VolcASRService {
        +transcribe_file()
    }

class TTSService {
        +synthesize_text()
    }

class VolcTTSService {
        +synthesize_text()
        +create_session()
        +get_audio_chunks()
    }

class RealtimeService {
        <<abstract>>
        +create_session()
    }

class VolcRealtimeService {
        +create_session()
    }

class LocalRealtimeService {
        +create_session()
    }

LLMService <|-- OpenAILLMService
LLMService <|-- VolcLLMService
ASRService <|-- ASRBase
ASRBase <|-- WhisperASRService
ASRBase <|-- VolcASRService
TTSService <|-- VolcTTSService
RealtimeService <|-- VolcRealtimeService
RealtimeService <|-- LocalRealtimeService
```

---

## 5. 模块依赖关系

### 5.1 REST API 请求处理链

```mermaid
sequenceDiagram
    participant Frontend
    participant REST_API as rest.py
    participant Config as ConfigManager
    participant LLM as LLMService
    participant ASR as ASRService
    participant TTS as TTSService
    participant VAD as VADService

    Frontend->>REST_API: POST /llm/chat
    REST_API->>Config: 获取 system_prompt
    Config-->>REST_API: prompt 文本
    REST_API->>LLM: chat_completion(messages)
    LLM-->>REST_API: response

    Frontend->>REST_API: POST /asr/transcribe
    REST_API->>ASR: transcribe_file(audio)
    ASR-->>REST_API: text

    Frontend->>REST_API: POST /tts/synthesize
    REST_API->>TTS: synthesize_text(text)
    TTS-->>REST_API: audio bytes

    Frontend->>REST_API: POST /vad/detect
    REST_API->>VAD: is_speech(audio)
    VAD-->>REST_API: is_speech: bool
```

### 5.2 WebSocket 语音回环处理链

```mermaid
sequenceDiagram
    participant Frontend
    participant WS as websocket.py
    participant VAD as VADService
    participant ASR as ASRService
    participant LLM as LLMService
    participant TTS as TTSService
    participant Config as ConfigManager

    Frontend->>WS: audio_start
    Frontend->>WS: audio (流式)

    WS->>ASR: send_audio_chunk()
    ASR-->>WS: asr_partial

    Frontend->>WS: audio_end
    WS->>ASR: send_audio_chunk(is_last=true)
    ASR-->>WS: asr_final

    WS->>Config: get_system_prompt()
    Config-->>WS: prompt

    WS->>LLM: chat_completion(stream=True)
    LLM-->>WS: llm_chunk

    WS->>TTS: send_task(text_chunk)
    TTS-->>WS: tts_audio

    WS-->>Frontend: tts_complete
```

---

## 6. 前端模块

### 6.1 前端目录结构

```
frontend/
├── templates/
│   └── index.html          # 主页面
└── static/
    ├── css/                # 样式文件
    └── js/
        ├── app.js          # 主应用逻辑
        ├── chat.js         # 聊天逻辑
        ├── audio-recorder.js # 音频录制
        ├── live2d-controller.js # Live2D 控制
        └── live2d-wrapper.js    # Live2D 封装
```

### 6.2 前端与后端交互

```mermaid
sequenceDiagram
    participant User
    participant Live2D as Live2D Widget
    participant Frontend as app.js
    participant Backend as websocket.py

    User->>Frontend: 按住麦克风按钮
    Frontend->>Backend: audio_start
    User->>Frontend: 说话
    Frontend->>Backend: audio (PCM base64)
    User->>Frontend: 松开麦克风按钮
    Frontend->>Backend: audio_end

    Backend-->>Frontend: asr_partial
    Backend-->>Frontend: asr_complete
    Backend-->>Frontend: llm_chunk
    Backend-->>Frontend: llm_complete

    loop TTS 流式返回
        Backend-->>Frontend: tts_audio
    end
    Backend-->>Frontend: tts_complete

    Frontend->>Live2D: 播放音频
    Frontend-->>User: 展示回复文本
```

### 6.3 前端核心功能

| 文件 | 职责 |
|------|------|
| `app.js` | WebSocket 连接管理、消息收发、音频流处理 |
| `chat.js` | 对话历史管理、UI 更新 |
| `audio-recorder.js` | 麦克风音频采集、VAD 前端检测 |
| `live2d-controller.js` | Live2D 动作、表情控制 |
| `live2d-wrapper.js` | Live2D SDK 封装 |

---

## 附录：关键配置项

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `VOICE_MODE` | 语音模式：pipeline / realtime_volc / realtime_local | `pipeline` |
| `LLM_API_KEY` | LLM API 密钥 | - |
| `LLM_MODEL` | LLM 模型 | `qwen-max` |
| `ASR_PROVIDER` | ASR 提供商：whisper / volc | `whisper` |
| `TTS_PROVIDER` | TTS 提供商：volc / edge | `volc` |
| `VOLC_TTS_VOICE_TYPE` | TTS 音色 ID | `zh_female_cancan_mars_bigtts` |
