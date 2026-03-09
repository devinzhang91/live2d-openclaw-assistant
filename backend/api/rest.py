"""
API 路由 - REST API
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import base64

from backend.services.llm_service import llm_service
from backend.services.asr_service import asr_service
from backend.services.tts_service import tts_service
from backend.services.vad_service import vad_service
from backend.config.config_manager import config_manager


router = APIRouter()


# ========== 数据模型 ==========

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    stream: bool = False
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


class ChatResponse(BaseModel):
    role: str
    content: str


class VADRequest(BaseModel):
    sample_rate: Optional[int] = None
    threshold: Optional[float] = None


class VADResponse(BaseModel):
    is_speech: bool
    speech_prob: Optional[float] = None
    segments: Optional[List[tuple]] = None


# ========== LLM 端点 ==========

@router.post("/llm/chat", response_model=ChatResponse)
async def chat_completion(request: ChatRequest):
    """
    聊天补全（非流式）
    """
    try:
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        result = await llm_service.chat_completion(
            messages,
            stream=False,
            model=request.model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )

        content = result["choices"][0]["message"]["content"]
        return ChatResponse(role="assistant", content=content)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== ASR 端点 ==========

@router.post("/asr/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = "zh"
):
    """
    语音识别
    """
    try:
        audio_data = await file.read()
        text = await asr_service.transcribe_file(audio_data, language)
        return {"text": text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== TTS 端点 ==========

@router.post("/tts/synthesize")
async def synthesize_text(
    text: str,
    voice: Optional[str] = None
):
    """
    文本转语音
    """
    try:
        audio_data = await tts_service.synthesize_text(text, voice)
        # 将音频数据编码为 base64
        audio_base64 = base64.b64encode(audio_data).decode()
        return {"audio": audio_base64, "format": "mp3"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== VAD 端点 ==========

@router.post("/vad/detect")
async def vad_detect(
    file: UploadFile = File(...),
    sample_rate: Optional[int] = None
):
    """
    检测音频是否包含语音
    """
    try:
        import numpy as np
        import soundfile as sf
        import io

        # 读取音频数据
        audio_data = await file.read()
        audio_bytes = io.BytesIO(audio_data)

        # 使用 soundfile 读取
        audio_array, sr = sf.read(audio_bytes, dtype='float32')

        # 如果是立体声，转换为单声道
        if len(audio_array.shape) > 1:
            audio_array = audio_array.mean(axis=1)

        is_speech = vad_service.is_speech(audio_array, sample_rate)

        return {"is_speech": is_speech, "sample_rate": sr}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vad/segments")
async def vad_segments(
    file: UploadFile = File(...),
    sample_rate: Optional[int] = None,
    min_speech_duration_ms: int = 250,
    min_silence_duration_ms: int = 100,
):
    """
    获取语音片段时间戳
    """
    try:
        import numpy as np
        import soundfile as sf
        import io

        # 读取音频数据
        audio_data = await file.read()
        audio_bytes = io.BytesIO(audio_data)

        # 使用 soundfile 读取
        audio_array, sr = sf.read(audio_bytes, dtype='float32')

        # 如果是立体声，转换为单声道
        if len(audio_array.shape) > 1:
            audio_array = audio_array.mean(axis=1)

        segments = vad_service.get_speech_segments(
            audio_array,
            sample_rate,
            min_speech_duration_ms,
            min_silence_duration_ms,
        )

        return {"segments": segments, "sample_rate": sr}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 设置端点 ==========

class UpdateSettingsRequest(BaseModel):
    personality_id: Optional[str] = None
    speed_ratio: Optional[float] = None
    vad_speech_threshold: Optional[float] = None
    vad_interrupt_tts: Optional[bool] = None
    openclaw: Optional[dict] = None


@router.get("/settings")
async def get_settings():
    """获取当前设置（AI 性格、TTS 配置等）"""
    return config_manager.get_settings_dict()


@router.post("/settings")
async def update_settings(request: UpdateSettingsRequest):
    """更新设置"""
    try:
        config_manager.update_settings(
            personality_id=request.personality_id,
            speed_ratio=request.speed_ratio,
            vad_speech_threshold=request.vad_speech_threshold,
            vad_interrupt_tts=request.vad_interrupt_tts,
            openclaw=request.openclaw,
        )
        return {"success": True, "settings": config_manager.get_settings_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 健康检查 ==========

@router.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "services": {
            "llm": "ok" if llm_service.client else "not configured",
            "asr": "ok" if asr_service else "not configured",
            "tts": "ok" if tts_service else "not configured",
            "vad": "ok" if vad_service.model else "not configured",
        }
    }
