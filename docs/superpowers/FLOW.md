# 程序运行流程

## 目录

1. [启动流程](#1-启动流程)
2. [文本对话流程](#2-文本对话流程)
3. [语音对话流程（语音回环模式）](#3-语音对话流程语音回环模式)
4. [实时语音流程（WebSocket）](#4-实时语音流程websocket)
5. [OpenClaw 集成流程](#5-openclaw-集成流程)

---

## 1. 启动流程

### 1.1 启动序列

```mermaid
sequenceDiagram
    participant User
    participant Start as start.py
    participant Main as main.py
    participant Settings as Settings
    participant REST as rest.py
    participant WS as websocket.py

    User->>Start: python start.py

    Start->>Main: uvicorn.run("backend.main:app")

    Main->>Main: load_dotenv() 加载 .env

    Main->>Main: FastAPI(title="Live2D AI Assistant")

    Main->>Main: mount /static -> frontend/static/

    Main->>Main: Jinja2Templates -> frontend/templates/

    Main->>Main: include_router(rest_router, /api)
    Main->>Main: include_router(ws_router, /api)

    Note over Main: 应用就绪，监听 0.0.0.0:8000

    User->>Main: 打开浏览器 http://localhost:8000
    Main-->>User: 返回 index.html
```

### 1.2 服务初始化顺序

```mermaid
flowchart LR
    A["1. 环境变量加载<br/>load_dotenv()"] --> B["2. Settings 单例<br/>settings.py"]
    B --> C["3. 各 Service 单例初始化"]
    C --> D["4. ConfigManager 加载<br/>app_config.json"]
    D --> E["5. FastAPI 路由注册"]
    E --> F["6. uvicorn 启动"]
```

---

## 2. 文本对话流程

### 2.1 序列图

```mermaid
sequenceDiagram
    participant User
    participant Frontend as 前端 app.js
    participant WS as websocket.py
    participant Config as ConfigManager
    participant LLM as LLMService
    participant TTS as TTSService

    User->>Frontend: 输入文本并发送

    Frontend->>WS: WebSocket text 消息
    WS->>WS: handle_text_message()
    WS->>Config: get_system_prompt()
    Config-->>WS: prompt 文本

    WS->>WS: 添加用户消息到 history
    WS->>WS: pipeline_llm_tts(history)

    par 并发执行
        WS->>LLM: chat_completion(messages, stream=True)
        LLM-->>WS: llm_chunk (逐 token)
        WS-->>Frontend: llm_chunk
    and
        loop TTS 流式合成
            WS->>TTS: send_task(text_chunk)
            TTS-->>WS: tts_audio (PCM)
            WS-->>Frontend: tts_audio
        end
    end

    LLM-->>WS: llm_complete
    TTS-->>WS: tts_complete

    WS->>WS: 添加 assistant 消息到 history
    WS-->>Frontend: llm_complete
    WS-->>Frontend: tts_complete

    Frontend-->>User: 展示回复文本 + 播放音频
```

### 2.2 LLM → TTS 流水线细节

```mermaid
flowchart TB
    A["LLM stream<br/>逐 token 输出"] --> B{检查 flush 条件}
    B -->|遇标点 或 len≥12 | C["send_task(text)<br/>发送给 TTS"]
    B -->|不满足条件 | D["累积到缓冲区"]
    D --> A
    C --> E["TTS session<br/>流式返回 PCM"]
    E --> F["分批转发前端<br/>16384 bytes/批"]
```

---

## 3. 语音对话流程（语音回环模式）

### 3.1 完整语音回环概览

```mermaid
flowchart LR
    A["🎤 麦克风"] --> B["VAD 检测"]
    B --> C["ASR 识别"]
    C --> D["LLM 生成"]
    D --> E["TTS 合成"]
    E --> F["🔊 扬声器"]

    style A fill:#e1f5fe
    style F fill:#e8f5e8
```

### 3.2 音频采集到播放完整序列

```mermaid
sequenceDiagram
    participant User
    participant Frontend as 前端 app.js
    participant WS as websocket.py
    participant VAD as VADService
    participant ASR as ASRService
    participant LLM as LLMService
    participant TTS as TTSService

    User->>Frontend: 按住麦克风按钮
    Frontend->>WS: {"type": "audio_start"}
    Frontend->>WS: {"type": "audio", "content": <PCM base64>}
    Frontend->>WS: {"type": "audio", "content": <PCM base64>}
    User->>Frontend: 松开麦克风按钮
    Frontend->>WS: {"type": "audio_end"}

    WS->>WS: 创建 ASR 会话
    loop 音频流
        WS->>ASR: send_audio_chunk_raw(pcm_bytes)
        ASR-->>WS: asr_partial (中间结果)
        WS-->>Frontend: asr_partial
    end

    WS->>ASR: send_audio_chunk_raw(is_last=True)
    ASR-->>WS: asr_final (最终结果)
    WS-->>Frontend: asr_complete

    WS->>WS: pipeline_llm_tts(history)

    par LLM + TTS 并发
        WS->>LLM: chat_completion(stream=True)
        LLM-->>WS: llm_chunk
        WS-->>Frontend: llm_chunk
    and
        loop TTS 流式
            WS->>TTS: send_task(text_chunk)
            TTS-->>WS: tts_audio
            WS-->>Frontend: tts_audio
        end
    end

    WS-->>Frontend: llm_complete
    WS-->>Frontend: tts_complete

    Frontend-->>User: 展示文本 + 播放音频
```

### 3.3 VAD 缓冲处理流程

```mermaid
flowchart TB
    A["audio_start"] --> B["创建 ASR session"]
    B --> C["接收 audio chunks"]
    C --> D["实时送入 ASR"]
    D --> E{"收到 audio_end?"}
    E -->|否| C
    E -->|是| F["发送 is_last=True"]
    F --> G["等待 ASR 最终结果<br/>超时 10s"]
    G --> H{"收到 asr_final?"}
    H -->|是| I["处理识别结果"]
    H -->|否| J["使用最后的 partial 结果"]
    J --> I
```

---

## 4. 实时语音流程（WebSocket）

### 4.1 端到端实时语音概览

```mermaid
flowchart LR
    A["🎤 麦克风"] --> B["WebSocket<br/>/ws/realtime_volc"]
    B --> C["火山端到端模型"]
    C --> D["TTS 流式返回"]
    D --> E["🔊 扬声器"]
    C --> F["ASR 中间结果"]
    F --> G["LLM 回复流"]
    G --> H["显示文本"]
```

### 4.2 WebSocket 实时语音会话序列

```mermaid
sequenceDiagram
    participant User
    participant Frontend as 前端 app.js
    participant WS as websocket.py
    participant Realtime as VolcRealtimeSession
    participant Volcano as 火山引擎

    User->>Frontend: 按住麦克风按钮
    Frontend->>WS: {"type": "audio_start"}

    WS->>Realtime: create_session()
    WS->>Volcano: WebSocket 连接
    Volcano-->>WS: ConnectionStarted

    Realtime->>Volcano: StartSession
    Volcano-->>Realtime: SessionStarted
    Realtime-->>WS: realtime_session_started

    User->>Frontend: 说话（持续发送）
    Frontend->>WS: {"type": "audio", "content": <PCM>}

    loop 实时语音交互
        WS->>Volcano: TaskRequest (gzip 压缩音频)
        Volcano-->>Realtime: ASRResponse (实时识别)
        Realtime-->>WS: on_asr_response()
        WS-->>Frontend: asr_partial

        Volcano-->>Realtime: TTSResponse (音频帧)
        Realtime-->>WS: on_tts_response()
        WS-->>Frontend: tts_audio
    end

    User->>Frontend: 松开按钮
    Frontend->>WS: {"type": "audio_end"}

    WS->>Volcano: END_ASR 事件
    Volcano-->>Realtime: ASREnded
    Volcano-->>Realtime: ChatEnded
    Volcano-->>Realtime: TTSEnded
    Volcano-->>Realtime: SessionFinished

    Realtime-->>WS: on_session_finished()
    WS-->>Frontend: realtime_session_finished

    WS->>Volcano: FinishSession
    WS->>Volcano: FinishConnection
```

### 4.3 实时语音服务端事件处理

```mermaid
flowchart TB
    A["接收 WebSocket 消息"] --> B{解析 message_type}

    B -->|0x09 Full Server Response| C["解析 JSON payload"]
    C --> D{"event_id"}

    D -->|150 SessionStarted| E["on_session_started()"]
    D -->|450 ASR_INFO| F["on_asr_response()"]
    D -->|451 ASRResponse| G["on_asr_response()"]
    D -->|459 ASREnded| H["on_asr_ended()"]
    D -->|350 TTSSentenceStart| I["on_tts_sentence_start()"]
    D -->|351 TTSSentenceEnd| J["on_tts_sentence_end()"]
    D -->|352 TTSResponse| K["on_tts_response()"]
    D -->|359 TTSEnded| L["on_tts_ended()"]
    D -->|550 ChatResponse| M["on_chat_response()"]
    D -->|559 ChatEnded| N["on_chat_ended()"]
    D -->|153 SessionFailed| O["on_session_failed()"]

    B -->|0x0B Audio Only Response| P["解析 TTSResponse 帧"]
    P --> K
```

---

## 5. OpenClaw 集成流程

### 5.1 意图路由决策

```mermaid
flowchart LR
    A["用户输入"] --> B["IntentRouter"]
    B --> C{决策}
    C -->|route=OPENCLAW| D["OpenClaw 工具调用"]
    C -->|route=LLM| E["普通 LLM 对话"]
```

### 5.2 OpenClaw 处理序列

```mermaid
sequenceDiagram
    participant User
    participant Frontend as 前端 app.js
    participant WS as websocket.py
    participant Intent as IntentRouter
    participant OC as OpenClawService
    participant LLM as LLMService
    participant TTS as TTSService

    User->>Frontend: 发送消息
    Frontend->>WS: text 消息
    WS->>Intent: decide(user_text, history)
    Intent-->>WS: Decision(route=OPENCLAW)

    WS-->>Frontend: openclaw_thinking

    WS->>OC: call_agent(user_text)
    OC->>OC: POST /hooks/agent
    OC-->>WS: openclaw_response

    WS-->>Frontend: openclaw_message (显示结果)

    WS->>WS: build_openclaw_notify_messages()
    WS->>WS: pipeline_llm_tts(history,<br/>override_messages)

    par TTS 播报
        WS->>LLM: chat_completion(转述 prompt)
        LLM-->>WS: llm_chunk
        WS->>TTS: send_task()
        TTS-->>WS: tts_audio
        WS-->>Frontend: tts_audio
    end

    WS-->>Frontend: llm_complete
    WS-->>Frontend: tts_complete

    Note over WS: 对话历史只记录用户输入，<br/>不记录 OpenClaw 原始回复
```

---

## 附录：消息类型参考

### WebSocket 客户端消息

| type | 说明 |
|------|------|
| `text` | 文本消息 |
| `audio_start` | 开始发送音频流 |
| `audio` | 音频数据块（base64 PCM） |
| `audio_end` | 音频流结束 |

### WebSocket 服务端消息

| type | 说明 |
|------|------|
| `status` | 状态通知 |
| `asr_partial` | ASR 中间结果 |
| `asr_complete` | ASR 最终结果 |
| `llm_chunk` | LLM 流式输出 |
| `llm_complete` | LLM 输出完成 |
| `llm_thinking` | LLM 思考中 |
| `tts_audio` | TTS 音频数据 |
| `tts_complete` | TTS 播放完成 |
| `tts_sentence_start` | TTS 句子开始 |
| `tts_sentence_end` | TTS 句子结束 |
| `openclaw_thinking` | OpenClaw 处理中 |
| `openclaw_message` | OpenClaw 返回结果 |
| `realtime_session_started` | 实时语音会话启动 |
| `realtime_session_finished` | 实时语音会话结束 |
| `error` | 错误信息 |
