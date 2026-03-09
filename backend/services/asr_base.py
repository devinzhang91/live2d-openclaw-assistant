"""
ASR 服务抽象基类
定义统一的 ASR 接口，支持多种 ASR 后端
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Callable, Optional
import numpy as np


class ASRStreamCallback:
    """流式 ASR 回调接口

    用于在识别过程中实时返回结果
    """

    def __init__(self):
        self.on_partial_result: Optional[Callable[[str], None]] = None
        """收到部分识别结果时调用，参数: text"""

        self.on_definite_sentence: Optional[Callable[[str], None]] = None
        """VAD 确认一句话结束时调用（definite=True），参数: text"""

        self.on_final_result: Optional[Callable[[str], None]] = None
        """收到最终识别结果时调用（is_last_package），参数: text"""

        self.on_error: Optional[Callable[[Exception], None]] = None
        """发生错误时调用，参数: exception"""

        self.on_close: Optional[Callable[[], None]] = None
        """连接关闭时调用"""


class ASRSession(ABC):
    """ASR 流式会话

    管理一次流式识别的生命周期
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.is_active = False
        self._callback: Optional[ASRStreamCallback] = None

    def set_callback(self, callback: ASRStreamCallback):
        """设置回调接口"""
        self._callback = callback

    def _notify_partial(self, text: str):
        """通知部分结果"""
        if self._callback and self._callback.on_partial_result:
            self._callback.on_partial_result(text)

    def _notify_definite(self, text: str):
        """通知 VAD 确认句子（definite=True）"""
        if self._callback and self._callback.on_definite_sentence:
            self._callback.on_definite_sentence(text)

    def _notify_final(self, text: str):
        """通知最终结果"""
        if self._callback and self._callback.on_final_result:
            self._callback.on_final_result(text)

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
    async def send_audio(self, audio: np.ndarray, sample_rate: int):
        """发送音频数据"""
        pass

    @abstractmethod
    async def end(self):
        """结束会话，等待最终结果"""
        pass

    @abstractmethod
    async def close(self):
        """关闭连接"""
        pass


class ASRService(ABC):
    """ASR 服务抽象基类"""

    def __init__(self):
        self.sample_rate = 16000
        self.channels = 1

    @abstractmethod
    async def transcribe_file(self, audio_data: bytes, language: str = "zh") -> str:
        """
        语音文件识别（同步或异步）

        Args:
            audio_data: 音频文件数据
            language: 语言代码

        Returns:
            识别到的文本
        """
        pass

    @abstractmethod
    async def create_session(
        self,
        session_id: str,
        language: str = "zh",
        callback: Optional[ASRStreamCallback] = None
    ) -> ASRSession:
        """
        创建流流式识别会话

        Args:
            session_id: 会话唯一标识
            language: 语言代码
            callback: 回调接口

        Returns:
            ASR 会话对象
        """
        pass

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        language: str = "zh",
    ) -> AsyncGenerator[str, None]:
        """
        流式语音识别（默认实现，可被子类重写）

        Args:
            audio_stream: 音频数据流
            language: 语言代码

        Yields:
            识别到的文本
        """
        # 默认实现：收集所有音频，然后一次性识别
        all_data = b""
        async for chunk in audio_stream:
            all_data += chunk

        text = await self.transcribe_file(all_data, language)

        for char in text:
            yield char
