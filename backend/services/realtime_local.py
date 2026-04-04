"""
本地端到端模型占位实现

待后续接入本地模型（如 SenseVoice、FunAudioLLM 等）
"""
from backend.services.realtime_base import RealtimeService


class LocalRealtimeService(RealtimeService):
    """本地端到端模型占位实现"""

    async def create_session(
        self,
        session_id: str,
        config: dict = None,
        callback = None,
    ):
        raise NotImplementedError("本地端到端模型待实现")
