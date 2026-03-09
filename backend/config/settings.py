"""
配置文件
使用环境变量进行配置
"""
import os
from functools import lru_cache


@lru_cache
def get_settings():
    """获取配置"""
    return Settings()


class Settings:
    """应用配置"""

    # ========== 基础配置 ==========
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    # ========== LLM 配置 ==========
    llm_base_url: str = os.getenv(
        "LLM_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "qwen-max")
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "2000"))
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.7"))

    # ========== ASR 配置 ==========
    asr_provider: str = os.getenv("ASR_PROVIDER", "whisper")  # whisper, volc
    whisper_model_size: str = os.getenv("WHISPER_MODEL_SIZE", "base")

    # 火山引擎 ASR 配置
    volc_asr_app_id: str = os.getenv("VOLC_ASR_APP_ID", "")
    volc_asr_access_key: str = os.getenv("VOLC_ASR_ACCESS_KEY", "")
    volc_asr_resource_id: str = os.getenv(
        "VOLC_ASR_RESOURCE_ID",
        "volc.bigasr.sauc.duration"
    )
    volc_asr_ws_url: str = os.getenv(
        "VOLC_ASR_WS_URL",
        "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    )

    # ========== TTS 配置 ==========
    tts_provider: str = os.getenv("TTS_PROVIDER", "volc")  # volc, edge

    # 火山引擎 TTS 配置
    volc_tts_app_id: str = os.getenv("VOLC_TTS_APP_ID", "")
    volc_tts_access_token: str = os.getenv("VOLC_TTS_ACCESS_TOKEN", "")
    volc_tts_resource_id: str = os.getenv("VOLC_TTS_RESOURCE_ID", "volc.service_type.10029")
    volc_tts_ws_url: str = os.getenv(
        "VOLC_TTS_WS_URL",
        "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    )
    volc_tts_voice_type: str = os.getenv(
        "VOLC_TTS_VOICE_TYPE",
        "zh_female_cancan_mars_bigtts"
    )

    # Edge TTS 配置
    edge_tts_voice: str = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")

    # ========== VAD 配置 ==========
    vad_model_path: str = os.getenv(
        "VAD_MODEL_PATH",
        "models/silero_vad_v4.onnx"
    )
    vad_threshold: float = float(os.getenv("VAD_THRESHOLD", "0.25"))
    vad_sample_rate: int = int(os.getenv("VAD_SAMPLE_RATE", "16000"))


# 全局配置实例
settings = get_settings()
