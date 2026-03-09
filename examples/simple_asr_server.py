#!/usr/bin/env python3
"""
简单的 ASR 服务示例（使用 Whisper）
"""
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import io
import sys
import os

app = FastAPI(title="Simple ASR Service")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局模型
whisper_model = None


def load_model():
    """加载 Whisper 模型"""
    global whisper_model
    try:
        import whisper
        print("正在加载 Whisper 模型...")
        whisper_model = whisper.load_model("base")
        print("Whisper 模型加载成功")
    except ImportError:
        print("未安装 whisper，请运行: pip install openai-whisper")
        sys.exit(1)


@app.on_event("startup")
async def startup_event():
    """启动事件"""
    load_model()


@app.post("/asr/stream")
async def stream_asr(file: UploadFile = File(...)):
    """
    流式语音识别（简化版）
    """
    try:
        # 读取音频文件
        audio_data = await file.read()

        # 使用 Whisper 识别
        import numpy as np

        # 这里简化处理，实际应该根据音频格式处理
        # 暂时返回模拟结果
        text = "这是模拟的语音识别结果，请配置真实的 ASR 服务"

        # 流式返回
        async def generate():
            for char in text:
                yield char
                await asyncio.sleep(0.05)

        return StreamingResponse(generate(), media_type="text/plain")

    except Exception as e:
        return {"error": str(e)}


@app.post("/asr/file")
async def file_asr(file: UploadFile = File(...)):
    """
    文件语音识别
    """
    try:
        # 读取音频文件
        audio_data = await file.read()

        # 保存到临时文件
        temp_file = "temp_audio.wav"
        with open(temp_file, "wb") as f:
            f.write(audio_data)

        # 使用 Whisper 识别
        result = whisper_model.transcribe(temp_file)
        text = result["text"]

        # 删除临时文件
        os.remove(temp_file)

        return {"text": text}

    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn

    print("🚀 启动简单 ASR 服务...")
    print("📍 ASR API: http://localhost:5001")

    uvicorn.run(app, host="0.0.0.0", port=5001)
