# 程序架构与运行流程文档设计

## 目标

为新加入的开发者编写两份概要级文档，帮助快速理解项目架构和运行机制。

## 文档一：程序架构说明

**文件路径：** `docs/superpowers/ARCHITECTURE.md`

### 内容结构

1. **系统概览**
   - 项目定位：Live2D 看板娘 AI 助手
   - 技术栈：Python FastAPI / faster-whisper / edge-tts / Volcano Engine
   - 两种语音模式：完整语音回环（VAD→ASR→LLM→TTS） vs 实时语音（WebSocket 流式）

2. **模块结构图（Mermaid 类图）**
   - 展示 backend/ 和 frontend/ 的目录结构
   - 每个服务模块的职责一句话说明

3. **后端服务模块说明**
   - ASR 服务：asr_whisper.py、asr_volc.py
   - TTS 服务：tts_volc.py、tts_base.py
   - LLM 服务：llm_openai.py、llm_volc.py、llm_base.py
   - VAD 服务：vad_service.py（能量检测）
   - 实时语音服务：realtime_volc.py、realtime_local.py、realtime_base.py
   - 配置管理：config_manager.py、settings.py

4. **模块依赖关系图（Mermaid 顺序图）**
   - API 层 → 服务层 → 配置层的调用关系

## 文档二：程序运行流程

**文件路径：** `docs/superpowers/FLOW.md`

### 内容结构

1. **启动流程（Mermaid 顺序图）**
   - start.py → main.py → FastAPI init → WebSocket 路由注册

2. **文本对话流程（Mermaid 顺序图）**
   - 前端请求 → /api/chat → LLM → TTS 合成 → 前端响应

3. **语音对话流程（完整回环，Mermaid 顺序图）**
   - 麦克风采集 → VAD 检测 → ASR 识别 → LLM 生成 → TTS 合成 → 扬声器播放

4. **实时语音流程（WebSocket，Mermaid 顺序图）**
   - 连接建立 → StartSession → 音频流 → ASR 中间结果 → LLM 流 → TTS 流 → 会话结束

## 设计约束

- 每份文档 5-8 张 Mermaid 图
- 图的大小适中，避免单图过于复杂
- 使用中文标题和标签
- 文档头部包含目录便于导航
