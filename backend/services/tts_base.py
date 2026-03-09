"""
TTS 服务抽象基类
定义统一的 TTS 接口，支持多种 TTS 后端
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Callable, Optional
import numpy as np


class TTSStreamCallback:
    """流式 TTS 回调接口

    用于在合成过程中实时返回音频数据
    """

    def __init__(self):
        self.on_audio_chunk: Optional[Callable[[bytes], None]] = None
        """收到音频数据块时调用，参数: audio_bytes"""

        self.on_complete: Optional[Callable[[], None]] = None
        """合成完成时调用"""

        self.on_error: Optional[Callable[[Exception], None]] = None
        """发生错误时调用，参数: exception"""

        self.on_close: Optional[Callable[[], None]] = None
        """连接关闭时调用"""


class TTSSession(ABC):
    """TTS 流式会话

    管理一次流式合成的生命周期
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.is_active = False
        self._callback: Optional[TTSStreamCallback] = None

    def set_callback(self, callback: TTSStreamCallback):
        """设置回调接口"""
        self._callback = callback

    def _notify_audio_chunk(self, audio_chunk: bytes):
        """通知音频数据块"""
        if self._callback and self._callback.on_audio_chunk:
            self._callback.on_audio_chunk(audio_chunk)

    def _notify_complete(self):
        """通知完成"""
        if self._callback and self._callback.on_complete:
            self._callback.on_complete()

    def _notify_error(self, error: Exception):
        """通知错误"""
        if self._callback and self._callback.on_error:
            self._callback.on_error(error)

    def _notify_close(self):
        """通知关闭"""
        if self._callback and self._callback.on_close:
            self._callback.on_close()

    @abstractmethod
    async def start(self):
        """启动会话"""
        pass

    @abstractmethod
    async def send_text(self, text: str):
        """发送要合成的文本"""
        pass

    @abstractmethod
    async def close(self):
        """关闭连接"""
        pass


class TTSService(ABC):
    """TTS 服务抽象基类"""

    def __init__(self):
        self.sample_rate = 24000
        self.channels = 1
        self.encoding = "mp3"  # mp3, wav, pcm, ogg_opus

    @abstractmethod
    async def synthesize_text(self, text: str, voice: str = None) -> bytes:
        """
        文本转语音（非流式）

        Args:
            text: 要合成的文本
            voice: 音色标识

        Returns:
            音频数据
        """
        pass

    @abstractmethod
    async def synthesize_stream(
        self,
        text_stream: AsyncGenerator[str, None],
        voice: str = None
    ) -> AsyncGenerator[bytes, None]:
        """
        流式文本转语音

        Args:
            text_stream: 文本数据流
            voice: 音色标识

        Yields:
            音频数据块
        """
        pass

    @abstractmethod
    async def create_session(
        self,
        session_id: str,
        voice: str = None,
        callback: Optional[TTSStreamCallback] = None
    ) -> TTSSession:
        """
        创建流式合成会话

        Args:
            session_id: 会话唯一标识
            voice: 音色色标识
            callback: 回调接口

        Returns:
            TTS 会话对象
        """
        pass
