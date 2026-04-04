"""
端到端实时语音服务工厂函数

根据配置创建对应的实时语音服务实现
"""
import os


def create_realtime_service(provider: str = None) -> "RealtimeService":
    """
    根据配置创建端到端实时语音服务

    Args:
        provider: 服务提供商
            - realtime_volc: 火山端到端实时语音
            - realtime_local: 本地端到端模型（占位）

    Returns:
        RealtimeService 实例
    """
    provider = provider or os.getenv("REALTIME_PROVIDER", "realtime_volc")

    if provider == "realtime_local":
        from backend.services.realtime_local import LocalRealtimeService
        return LocalRealtimeService()
    else:  # 默认 realtime_volc
        from backend.services.realtime_volc import VolcRealtimeService
        return VolcRealtimeService(
            input_mod=os.getenv("REALTIME_INPUT_MOD", "audio"),
            recv_timeout=int(os.getenv("REALTIME_RECV_TIMEOUT", "120")),
        )
