# 火山端到端实时语音全双工改造实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `realtime_volc` 模式从 push_to_talk 改为全双工持续对话模式，前端点击按钮后持续发送 200ms 音频包，由服务端 recv_timeout=120s 自动结束会话。

**Architecture:** 后端改动主要是把 `input_mod` 改为 `"audio"` 并加 `recv_timeout`，去掉 `END_ASR` 发送，改用 `session.send_audio()` 统一发音频。前端改动主要是按钮交互逻辑和持续 200ms 发包。

**Tech Stack:** Python FastAPI, WebSocket, JavaScript, 火山引擎实时语音 API

---

## 文件变更总览

| 文件 | 变更内容 |
|------|----------|
| `backend/services/realtime_volc.py` | 添加 `recv_timeout` 到 StartSession；添加 `_build_audio_message` 导出 |
| `backend/services/realtime_service.py` | 透传 `input_mod` 和 `recv_timeout` 参数 |
| `backend/api/websocket.py` | 使用 `session.send_audio()`；移除 `END_ASR`；处理 `audio_stop`；处理会话结束 |
| `frontend/static/js/app.js` | 全双工按钮交互；持续 200ms 发包；处理 `realtime_session_finished` |

---

## Task 1: 后端 — realtime_volc.py 添加 recv_timeout 参数

**Files:**
- Modify: `backend/services/realtime_volc.py`

- [ ] **Step 1: 在 `start_session` 的 StartSession 配置中添加 `recv_timeout: 120`**

在 `start_session` 方法的 `start_payload` 中找到 `dialog.extra` 字典，在 `enable_music` 后面添加 `"recv_timeout": 120`。

当前代码（约第411-415行）：
```python
"extra": {
    "model": self.model,
    "enable_volc_websearch": self.enable_websearch,
    "enable_music": self.enable_music,
}
```

改为：
```python
"extra": {
    "model": self.model,
    "enable_volc_websearch": self.enable_websearch,
    "enable_music": self.enable_music,
    "recv_timeout": 120,
}
```

- [ ] **Step 2: 在 `VolcRealtimeSession.__init__` 添加 `recv_timeout` 参数**

在 `__init__` 方法参数列表中添加 `recv_timeout: int = 120`，并存储为实例属性 `self.recv_timeout = recv_timeout`。

- [ ] **Step 3: 提交**

```bash
git add backend/services/realtime_volc.py
git commit -m "feat(realtime): add recv_timeout parameter to VolcRealtimeSession"
```

---

## Task 2: 后端 — realtime_service.py 透传新参数

**Files:**
- Modify: `backend/services/realtime_service.py`

- [ ] **Step 1: 在 `create_realtime_service` 中透传 `input_mod` 和 `recv_timeout`**

查看当前 `create_realtime_service` 函数（约第9-28行），当创建 `VolcRealtimeService` 时，需要传入 `input_mod` 和 `recv_timeout` 参数。

当前：
```python
from backend.services.realtime_volc import VolcRealtimeService
return VolcRealtimeService()
```

改为：
```python
from backend.services.realtime_volc import VolcRealtimeService
return VolcRealtimeService(
    input_mod=os.getenv("REALTIME_INPUT_MOD", "audio"),
    recv_timeout=int(os.getenv("REALTIME_RECV_TIMEOUT", "120")),
)
```

- [ ] **Step 2: 提交**

```bash
git add backend/services/realtime_service.py
git commit -m "feat(realtime): pass input_mod and recv_timeout to VolcRealtimeService"
```

---

## Task 3: 后端 — websocket.py 重构音频发送逻辑

**Files:**
- Modify: `backend/api/websocket.py`

- [ ] **Step 1: 移除硬编码的 demo 路径导入**

删除约第783-785行：
```python
import sys
sys.path.insert(0, "/Users/zhangyoujin/Downloads/python3.7")
import protocol as demo_protocol
```

- [ ] **Step 2: 将手动构造 task_request 帧改为调用 `session.send_audio()`**

找到约第787-800行的手动构造帧代码：

```python
task_request = bytearray(
    demo_protocol.generate_header(
        message_type=demo_protocol.CLIENT_AUDIO_ONLY_REQUEST,
        serial_method=demo_protocol.NO_SERIALIZATION,
    )
)
task_request.extend(int(200).to_bytes(4, 'big'))  # Event = TASK_REQUEST
task_request.extend((len(session_id)).to_bytes(4, 'big'))
task_request.extend(session_id.encode('utf-8'))
payload_bytes = gzip.compress(pcm_bytes)
task_request.extend((len(payload_bytes)).to_bytes(4, 'big'))
task_request.extend(payload_bytes)

await active_session._ws.send(bytes(task_request))
```

替换为：
```python
await active_session.send_audio(pcm_bytes)
```

同时删除顶部的 `import gzip`（如果不再需要）和 `from backend.services.realtime_volc.py` 中已有 `_build_audio_message` 函数。

- [ ] **Step 3: 修改 `audio_end` 处理 — 不再发送 END_ASR**

将 `audio_end` 分支（约第810-820行）改为只记录状态，不发送 END_ASR：

```python
elif message_type == "audio_end":
    # 全双工模式下 audio_end 不发送 END_ASR
    # 会话由服务端 recv_timeout 自动结束
    audio_ended_sent = True
    await manager.send_personal_message(
        {"type": "status", "message": "Session active, waiting for timeout..."},
        websocket,
    )
```

- [ ] **Step 4: 添加 `audio_stop` 消息处理 — 停止发送音频但保持会话**

在 `audio_end` 分支后面添加：

```python
elif message_type == "audio_stop":
    # 用户主动停止录音（但不断开会话，等 recv_timeout 自然结束）
    await manager.send_personal_message(
        {"type": "status", "message": "Audio stopped, waiting for session end..."},
        websocket,
    )
```

- [ ] **Step 5: 在 finally 块确保会话结束后关闭 WebSocket**

在 `finally` 块（约第847-856行）中，已经有 `finish_session` 和 `close` 调用。需要确认：当 `active_session` 不为 None 时，等待会话结束信号或直接关闭。

当前代码已经处理得很好，只需要确保 `manager.disconnect(websocket)` 在会话关闭后被调用。

- [ ] **Step 6: 提交**

```bash
git add backend/api/websocket.py
git commit -m "feat(realtime): refactor audio sending to use session.send_audio(), remove END_ASR for full-duplex mode"
```

---

## Task 4: 前端 — app.js 全双工按钮交互

**Files:**
- Modify: `frontend/static/js/app.js`

- [ ] **Step 1: 添加全双工模式标识和状态**

在 `App` 构造函数中（约第12-14行）添加：
```javascript
this.realtimeFullDuplex = false;  // 是否为全双工实时语音模式
this.realtimeRecording = false;  // 全双工模式下是否正在录音
this.realtimeTimer = null;        // 全双工模式 200ms 发包定时器
```

- [ ] **Step 2: 修改 `initChatManager` 检测全双工模式**

约第122-125行，添加检测：
```javascript
if (this._settingsData && this._settingsData.voice_mode === 'realtime_volc') {
    wsPath = '/api/ws/realtime_volc';
    this.realtimeFullDuplex = true;
}
```

- [ ] **Step 3: 修改 `switchInputMode` — 全双工模式下不启动 VAD**

约第186-197行，找到 `voice` 模式的处理，改为：
```javascript
} else {
    voiceModeBtn.classList.add('active');
    textModeBtn.classList.remove('active');
    voiceInputArea.style.display = 'flex';
    textInputArea.style.display = 'none';
    // 全双工模式下不需要前端 VAD，等待用户点击按钮
}
```

- [ ] **Step 4: 修改录音按钮交互 — 全双工模式**

约第324-348行，修改 `recordBtn` 的事件绑定：

```javascript
// 全双工模式：点击开始/停止
// 非全双工模式：按住说话
if (this.realtimeFullDuplex) {
    recordBtn.addEventListener('click', () => {
        if (this.realtimeRecording) {
            this.stopRealtimeRecording();
        } else {
            this.startRealtimeRecording();
        }
    });
} else {
    // 按住说话（原有逻辑）
    recordBtn.addEventListener('mousedown', () => { this.startRecording(); });
    recordBtn.addEventListener('mouseup', () => { this.stopRecording(); });
    recordBtn.addEventListener('mouseleave', () => {
        if (this.isRecording) this.stopRecording();
    });
    recordBtn.addEventListener('touchstart', (e) => { e.preventDefault(); this.startRecording(); });
    recordBtn.addEventListener('touchend', (e) => { e.preventDefault(); this.stopRecording(); });
}
```

- [ ] **Step 5: 添加 `startRealtimeRecording` 方法**

在 `startRecording` 方法后面（约第640行）添加：

```javascript
startRealtimeRecording() {
    if (this.realtimeRecording || !this.audioAvailable) return;

    try {
        if (this.live2dController) this.live2dController.unlockAudioContext();
        this._live2dReact('listening');

        // 发送 audio_start 建立会话
        if (this.chatManager) this.chatManager.startAudioStream();
        this.realtimeRecording = true;

        const recordBtn = document.getElementById('recordBtn');
        recordBtn.classList.add('recording');
        const voicePrompt = document.getElementById('voicePrompt');
        if (voicePrompt) {
            voicePrompt.textContent = '🎤 录音中...';
            voicePrompt.style.background = '#dcfce7';
            voicePrompt.style.color = '#16a34a';
        }

        // 开始 200ms 定时发送
        this.audioRecorder.start();
        this._startRealtimeAudioLoop();

        this.updateStatus('实时语音录音中...');
    } catch (error) {
        console.error('开始实时录音失败:', error);
        this.showError('无法开始录音');
    }
}

stopRealtimeRecording() {
    if (!this.realtimeRecording) return;

    this.realtimeRecording = false;

    // 停止 200ms 定时发送
    if (this.realtimeTimer) {
        clearInterval(this.realtimeTimer);
        this.realtimeTimer = null;
    }

    const recordBtn = document.getElementById('recordBtn');
    if (recordBtn) recordBtn.classList.remove('recording');
    const voicePrompt = document.getElementById('voicePrompt');
    if (voicePrompt) {
        voicePrompt.textContent = '等待会话结束...';
        voicePrompt.style.background = '#fef9c3';
        voicePrompt.style.color = '#a16207';
    }

    // 发送 audio_stop（不断会话）
    if (this.chatManager) {
        this.chatManager.sendAudioStop();
    }

    this.updateStatus('会话即将结束...');
}

_startRealtimeAudioLoop() {
    // 每 200ms 发送一包音频
    this.realtimeTimer = setInterval(async () => {
        if (!this.realtimeRecording || !this.chatManager) return;
        // 音频已在 audioRecorder.start() 中通过 onDataChunk 发送
        // 此处不需要额外处理
    }, 200);
}
```

- [ ] **Step 6: 修改 `handleChatMessage` 处理 `realtime_session_finished`**

约第831-837行，修改现有处理：

```javascript
case 'realtime_session_finished':
    console.log('[WebSocket] 实时语音会话已结束');
    this.realtimeRecording = false;
    if (this.realtimeTimer) {
        clearInterval(this.realtimeTimer);
        this.realtimeTimer = null;
    }
    if (this.audioRecorder) this.audioRecorder.stop();
    const recordBtn = document.getElementById('recordBtn');
    if (recordBtn) recordBtn.classList.remove('recording');
    const voicePrompt = document.getElementById('voicePrompt');
    if (voicePrompt) {
        voicePrompt.textContent = '按住录音按钮开始说话';
        voicePrompt.style.background = '#f1f5f9';
        voicePrompt.style.color = '#64748b';
    }
    this.updateStatus('就绪');
    break;
```

- [ ] **Step 7: 提交**

```bash
git add frontend/static/js/app.js
git commit -m "feat(frontend): implement full-duplex voice interaction for realtime_volc mode"
```

---

## Task 5: 前端 — chat.js 添加 sendAudioStop 方法

**Files:**
- Modify: `frontend/static/js/chat.js`

- [ ] **Step 1: 添加 `sendAudioStop` 方法**

找到 `ChatManager` 类，添加：

```javascript
sendAudioStop() {
    if (!this.isConnected()) return;
    this.ws.send(JSON.stringify({ type: 'audio_stop' }));
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/static/js/chat.js
git commit -m "feat(chat): add sendAudioStop method to ChatManager"
```

---

## Task 6: 配置 — settings.py 添加新环境变量

**Files:**
- Modify: `backend/config/settings.py`

- [ ] **Step 1: 添加 `REALTIME_INPUT_MOD` 和 `REALTIME_RECV_TIMEOUT` 环境变量**

在 `voice_mode` 配置后面添加：

```python
# ========== 火山端到端实时语音配置 ==========
realtime_input_mod: str = os.getenv("REALTIME_INPUT_MOD", "audio")  # audio 或 push_to_talk
realtime_recv_timeout: int = int(os.getenv("REALTIME_RECV_TIMEOUT", "120"))  # 静默超时（秒），最大 120
```

- [ ] **Step 2: 提交**

```bash
git add backend/config/settings.py
git commit -m "feat(config): add REALTIME_INPUT_MOD and REALTIME_RECV_TIMEOUT env vars"
```

---

## Task 7: 集成测试

**Files:**
- 无文件变更

- [ ] **Step 1: 启动服务**

```bash
cd /Users/zhangyoujin/Git/live2d-openclaw-assistant
source .venv/bin/activate
python start.py
```

- [ ] **Step 2: 测试全双工语音交互**

1. 打开浏览器访问 http://localhost:8000
2. 切换到语音模式
3. 点击录音按钮
4. 说话，观察是否实时收到 TTS 音频
5. 停止说话，等待约120秒观察会话是否自动结束
6. 再次点击按钮，确认可以重新开始会话

- [ ] **Step 3: 提交**

```bash
git add -A
git commit -m "test: manual integration test for full-duplex realtime voice"
```

---

## 自检清单

- [ ] `VolcRealtimeSession` 的 StartSession 配置中包含 `recv_timeout: 120` 和 `input_mod: "audio"`
- [ ] `websocket.py` 中 `audio_end` 不再发送 END_ASR
- [ ] `websocket.py` 使用 `session.send_audio()` 而非手动构造帧
- [ ] `websocket.py` 不再有硬编码 demo 路径
- [ ] `app.js` 全双工模式下按钮点击开始/停止，而非按住说话
- [ ] `app.js` 收到 `realtime_session_finished` 后重置 UI 状态
- [ ] `chat.js` 有 `sendAudioStop` 方法
- [ ] 所有参数可通过环境变量配置
