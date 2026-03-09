"""
TTS 服务入口
根据配置选择不同的 TTS 服务实现
"""
import os
from backend.config.settings import settings
from backend.services.tts_base import TTSService

# 根据配置选择 TTS 服务提供商
if settings.tts_provider == "volc":
    from backend.services.tts_volc import VolcTTSService
    tts_service = VolcTTSService()
else:
    # 默认使用火山引擎 TTS
    from backend.services.tts_volc import VolcTTSService
    tts_service = VolcTTSService()

# 导出所有可用的 TTS 服务
__all__ = [
    'TTSService',
    'VolcTTSService',
    'tts_service',
]
