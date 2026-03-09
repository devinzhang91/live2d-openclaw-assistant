"""
ASR 服务兼容层

保留原有的 asr_service 接口，内部使用新的架构
"""
from backend.config.settings import settings

# 根据配置选择 ASR 服务提供商
if settings.asr_provider == "volc":
    from backend.services.asr_volc import VolcASRService
    asr_service = VolcASRService()
else:
    # 默认使用 faster-whisper
    from backend.services.asr_whisper import FasterWhisperASRService
    asr_service = FasterWhisperASRService(
        model_size=settings.whisper_model_size
    )
