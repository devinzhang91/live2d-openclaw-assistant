#!/usr/bin/env python3
"""
简单的 TTS 服务示例（使用 edge-tts 或 pyttsx3）
"""
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import io

app = FastAPI(title="Simple TTS Service")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 尝试导入不同的 TTS 库
tts_engine = None
tts_library = None

try:
    import edge_tts
    tts_library = "edge-tts"
    print("使用 edge-tts 作为 TTS 引擎")
except ImportError:
    try:
        import pyttsx3
        tts_library = "pyttsx3"
        print("使用 pyttsx3 作为 TTS 引擎")
    except ImportError:
        print("未安装 TTS 库，请运行:")
        print("  pip install edge-tts")
        print("  或")
        print("  pip install pyttsx3")


@app.post("/tts/stream")
async def stream_tts(
    text: str = Query(..., description="要合成的文本"),
    voice: str = Query("zh-CN-XiaoxiaoNeural", description="语音"),
    sample_rate: int = Query(22050, description="采样率"),
):
    """
    流式文本转语音
    """
    try:
        if tts_library == "edge-tts":
            return await _edge_tts_stream(text, voice, sample_rate)
        elif tts_library == "pyttsx3":
            return await _pyttsx3_stream(text, voice, sample_rate)
        else:
            return {"error": "未配置 TTS 库"}

    except Exception as e:
        return {"error": str(e)}


@app.post("/tts/file")
async def file_tts(
    text: str = Query(..., description="要合成的文本"),
    voice: str = Query("zh-CN-XiaoxiaoNeural", description="语音"),
):
    """
    文件文本转语音
    """
    try:
        if tts_library == "edge-tts":
            return await _edge_tts_file(text, voice)
        elif tts_library == "pyttsx3":
            return await _pyttsx3_file(text, voice)
        else:
            return {"error": "未配置 TTS 库"}

    except Exception as e:
        return {"error": str(e)}


async def _edge_tts_stream(text: str, voice: str, sample_rate: int):
    """使用 edge-tts 流式合成"""
    communicate = edge_tts.Communicate(text, voice)

    async def generate():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(generate(), media_type="audio/mpeg")


async def _edge_tts_file(text: str, voice: str):
    """使用 edge-tts 文件合成"""
    communicate = edge_tts.Communicate(text, voice)

    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]

    return StreamingResponse(
        io.BytesIO(audio_data),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "attachment; filename=output.mp3"},
    )


async def _pyttsx3_stream(text: str, voice: str, sample_rate: int):
    """使用 pyttsx3 流式合成（简化版）"""
    engine = pyttsx3.init()
    engine.say(text)

    # pyttsx3 不支持流式，所以使用文件方式
    output_file = "temp_tts_output.wav"
    engine.save_to_file(text, output_file)
    engine.runAndWait()

    # 读取文件并流式返回
    with open(output_file, "rb") as f:
        audio_data = f.read()

    import os
    os.remove(output_file)

    async def generate():
        yield audio_data

    return StreamingResponse(generate(), media_type="audio/wav")


async def _pyttsx3_file(text: str, voice: str):
    """使用 pyttsx3 文件合成"""
    engine = pyttsx3.init()
    engine.say(text)

    output_file = "temp_tts_output.wav"
    engine.save_to_file(text, output_file)
    engine.runAndWait()

    # 读取文件
    with open(output_file, "rb") as f:
        audio_data = f.read()

    import os
    os.remove(output_file)

    return StreamingResponse(
        io.BytesIO(audio_data),
        media_type="audio/wav",
        headers={"Content-Disposition": "attachment; filename=output.wav"},
    )


if __name__ == "__main__":
    import uvicorn

    print("🚀 启动简单 TTS 服务...")
    print("📍 TTS API: http://localhost:5002")

    uvicorn.run(app, host="0.0.0.0", port=5002)
