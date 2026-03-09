# 安装和使用指南

## 完整回环架构（流式+buffer）

本项目集成了完整的语音交互回环，采用流式+buffer 形式：

```
用户麦克风 → 流式音频块 → VAD 缓冲 → 检测到完整语音 → ASR 识别 → LLM 生成 → TTS 合成 → 扬声器
   (前端)      (实时)       (buffer)         (自动)        (后端)      (后端)      (后端)     (前端)
```

**关键特性：**
- ✅ **VAD 使用 Silero 模型**（高精度语音检测）
- ✅ **流式+buffer 处理**（实时音频流 + 智能缓冲）
- ✅ **自动触发 ASR**（VAD 检测到完整语音后自动触发）
- ✅ **所有服务集成启动**（无需单独启动 ASR/TTS 服务）

## 快速开始

### 1. 配置环境

```bash
cd live2d-ai-assistant
cp```.env.example .env
```

编辑 `.env` 文件，只需配置 LLM API Key：

```bash
# LLM Configuration（必需）
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-openai-api-key-here  # 替换为你的 API Key
LLM_MODEL=gpt-4o-mini
```

### 2. 安装依赖

```bash
# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
venv\Scripts\activate  # Windows

# 安装所有依赖
pip install -r requirements.txt
```

**依赖说明：**

- `fastapi`: Web 框架
- `torch`, `torchaudio`: PyTorch（VAD 模型）
- `faster-whisper`: 语音识别（首次运行自动下载模型）
- `edge-tts`: 语音合成（使用 Microsoft Edge TTS）
- `openai`: LLM 接口
- `numpy`, `soundfile`: 音频处理

**首次运行时：**
- `torch` 会自动下载 Silero VAD 模型（约 100MB）
- `faster-whisper` 会自动下载 Whisper 模型（约 150MB）

### 3. 启动服务

```bash
python`` start.py
```

或者：

```bash
cd backend
python main.py
```

**启动后会自动加载：**
- ✅ Silero VAD 模型
- ✅ Whisper ASR 模型
- ✅ Edge-TTS 引擎
- ✅ LLM 客户端

### 4. 访问应用

打开浏览器访问：http://localhost:8000

## 使用方式

### 方式一：文本对话

1. 在输入框中输入文本
2. 点击"发送"按钮或按 Enter 键
3. AI 会流式返回回复

### 方式二：语音对话（流式+buffer）

1. 按住麦克风按钮 🎤 开始录音
2. 说话（可以持续说话，系统会实时处理）
3. 松开按钮结束录音
4. 系统自动执行：
   - **VAD 实时检测**：检测语音活动，智能缓冲
   - **ASR 自动触发**：VAD 检测到完整语音后自动识别
   - **LLM 生成**：AI 思考并生成回复
   - **TTS 合成**：将回复转为语音
   - **自动播放**：在浏览器中播放回复语音

## 流式+Buffer 原理

### VAD Buffer 机制

1. **实时接收音频块**：前端每 100ms 发送一次音频块
2. **VAD 实时检测**：每个音频块都经过 VAD 检测
3. **智能缓冲**：
   - 检测到语音开始：开始缓冲音频数据
   - 检测到持续语音：继续缓冲
   - 检测到静音超过阈值（0.8 秒）：认为语音结束
4. **自动触发 ASR**：当检测到完整语音后，自动将缓冲的音频发送给 ASR

### 优势

- ✅ **实时性**：边录音边处理，无需等待录音结束
- ✅ **准确性**：Silero VAD 模型提供高精度语音检测
- ✅ **灵活性**：可以持续说话，系统智能判断语音边界
- ✅ **低延迟**：检测到语音结束后立即触发 ASR

## 配置说明

### VAD 配置

使用 Silero VAD 模型：

```bash
VAD_THRESHOLD=0.5         # 检测阈值（0.0-1.0）
VAD_SAMPLE_RATE=16000    # 采样率
```

**调整阈值：**
- 增大值（如 0.7）：更严格，可能漏掉较轻的语音
- 减小值（如 0.3）：更宽松，可能误判噪音为语音

**调整静音持续时间（在 `vad_service.py` 中）：**
```python
self.max_silence_duration = int(self.sample_rate * 0.8)  # 0.8 秒
```

### LLM 配置

#### 使用 OpenAI（推荐）

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-openai-api-key
LLM_MODEL=gpt-4o-mini
```

#### 使用其他兼容 OpenAI API 的服务

```bash
# 例如使用 DeepSeek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=your-deepseek-api-key
LLM_MODEL=deepseek-chat
```

### ASR 配置

默认使用 `faster-whisper` 的 `base` 模型。

如需使用更高质量的模型，修改 `backend/services/asr_service.py`：
```python
model_size = "small"  # tiny, base, small, medium, large
```

### TTS 配置

使用 `edge-tts`，支持多种语音：

```bash
TTS_VOICE=zh-CN-XiaoxiaoNeural  # 默认：中国女声
```

其他可选语音：
- `zh-CN-YunxiNeural`: 中国男声
- `zh-CN-XiaoyiNeural`: 童声
- `en-US-JennyNeural`: 美国女声

## 项目结构

```
live2d-ai-assistant/
├── frontend/              # 前端（HTML/CSS/JS）
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/
│   │       ├── app.js                  # 主应用
│   │       ├── audio-recorder.js       # 音频录制（流式）
│   │       ├── chat.js                # WebSocket 通信
│   │       └── live2d-wrapper.js      # Live2D 封装
│   └── templates/index.html
├── backend/               # 后端（Python FastAPI）
│   ├── main.py
│   ├── api/
│   │   ├── rest.py        # REST API
│   │   └── websocket.py   # WebSocket（流式+buffer）
│   ├── services/          # 集成服务
│   │   ├── llm_service.py      # LLM（OpenAI 接口）
│   │   ├── asr_service.py      # ASR（faster-whisper）
│   │   ├── tts_service.py      # TTS（edge-tts）
│   │   └── vad_service.py      # VAD（Silero 模型）
│   └── config/settings.py      # 配置管理
├── requirements.txt       # Python 依赖
├── .env.example          # 环境变量示例
├── start.py              # 启动脚本
└── README.md
```

## API 文档

启动服务后访问：http://localhost:8000/docs

## 故障排除

### 1. Silero VAD 模型下载失败

检查网络连接，首次运行需要下载模型（约 100MB）。

模型会自动下载到 `~/.cache/torch/hub/checkpoints/`。

### 2. Whisper 模型下载失败

检查网络连接，首次运行需要下载模型（约 150MB）。

模型会自动下载到 `~/.cache/huggingface/hub/`。

### 3. LLM 连接失败

- 检查 API Key 是否正确
- 检查网络连接
- 确认 LLM 服务可用

### 4. 音频录制失败

确保浏览器有麦克风权限，并且使用 HTTPS 或 localhost。

### 5. VAD 检测不准确

调整 `VAD_THRESHOLD` 值或静音持续时间阈值。

## 性能优化

### 使用 GPU 加速

1. 安装 CUDA 版本的 PyTorch：
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

2. 修改 `backend/services/vad_service.py`：
```python
# 在 _load_model 方法中添加
torch.set_default_tensor_type(torch.cuda.FloatTensor)
```

3. 修改 `backend/services/asr_service.py`：
```python
self.model = WhisperModel(model_size, device="cuda", compute_type="float16")
```

### VAD 优化

- 调整缓冲区大小（`buffer_size_samples`）
- 调整静音持续时间阈值（`max_silence_duration`）
- 使用更小的 VAD 模型（Silero 只有一个版本）

### ASR 优化

- 使用 `tiny` 模型（最快）
- 使用 GPU 加速
- 减少 `beam_size`（在 `asr_service.py` 中）

## 后续优化

- [ ] 实现完整的 Live2D 表情控制
- [ ] 添加对话历史管理
- [ ] 支持多语言切换
- [ ] 添加用户认证
- [ ] 优化音频质量
- [ ] 实现断点续传
- [ ] 添加录音波形显示
- [ ] 支持多用户并发

## 许可证

MIT License
