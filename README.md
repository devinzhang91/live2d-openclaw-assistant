# Live2D AI 助手

一个集成的 Live2D 看板娘 AI 助手，支持完整的语音交互回环。

## 功能特性

- **Live2D 看板娘**: 交互式 3D 动态角色
- **完整语音回环**: 音频 → VAD → ASR → LLM → TTS → 音频
- **语音识别 (ASR)**: 使用 faster-whisper，自动下载模型
- **大语言模型 (LLM)**: 支持 OpenAI 兼容接口（OpenAI、DeepSeek 等）
- **语音合成 (TTS)**: 使用 edge-tts，无需配置
- **语音活动检测 (VAD)**: 基于能量检测，无需模型

## 技术栈

- **前端**: HTML5, CSS3, JavaScript, Live2D Widget
- **后端**: Python (FastAPI)
- **ASR**: faster-whisper（自动下载模型）
- **LLM**: OpenAI 兼容接口
- **TTS**: edge-tts（Microsoft Edge TTS）
- **VAD**: 能量检测（无依赖）

## 完整回环流程

```
用户麦克风 → VAD 检测 → ASR 识别 → LLM 生成 → TTS 合成 → 扬声器
   (前端)      (后端)      (后端)      (后端)      (后端)     (前端)
```

## 快速开始

### 1. 配置环境

```bash
cp .env.example .env
```

编辑 `.env`，配置 LLM API Key：

```bash
LLM_API_KEY=your-openai-api-key-here
```

如果使用火山引擎 TTS（V3 双向流式），建议至少配置以下参数：

```bash
TTS_PROVIDER=volc
VOLC_TTS_APP_ID=your-app-id
VOLC_TTS_ACCESS_TOKEN=your-access-token
VOLC_TTS_RESOURCE_ID=volc.service_type.10029
VOLC_TTS_WS_URL=wss://openspeech.bytedance.com/api/v3/tts/bidirection
VOLC_TTS_VOICE_TYPE=zh_female_cancan_mars_bigtts
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

**首次运行会自动下载 Whisper 模型（约 150MB）**

### 3. 启动服务

```bash
python start.py
```

### 4. 访问应用

打开浏览器访问：http://localhost:8000

## 使用方式

### 文本对话

在输入框中输入文本，点击发送或按 Enter 键。

### 语音对话（完整回环）

1. 按住麦克风按钮 🎤 开始录音
2. 说话
3. 松开按钮
4. 系统自动执行完整回环并播放语音回复

## 项目结构

```
live2d-ai-assistant/
├── frontend/               # 前端代码
│   ├── static/
│   │   ├── css/           # 样式文件
│   │   └── js/            # JavaScript 文件
│   └── templates/         # HTML 模板
├── backend/               # 后端代码
│   ├── main.py            # FastAPI 主程序
│   ├── api/               # API 路由
│   ├── services/          # 集成服务（LLM/ASR/TTS/VAD）
│   └── config/            # 配置文件
├── requirements.txt       # Python 依赖
├── .env.example          # 环境变量示例
├── start.py              # 启动脚本
└── INSTALL.md            # 详细安装指南
```

## 详细文档

查看 [INSTALL.md](INSTALL.md) 获取：
- 完整配置说明
- 故障排除
- 性能优化
- API 文档

## 开发计划

- [ ] Live2D 表情控制
- [ ] 对话历史管理
- [ ] 多模型切换
- [ ] 用户认证
- [ ] 移动端优化

## 许可证

MIT License
