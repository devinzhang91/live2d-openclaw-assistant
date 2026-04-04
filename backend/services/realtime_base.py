"""
端到端实时语音抽象基类

定义统一的接口，供不同实现（Volc、本地模型等）继承
"""
from abc import ABC, abstractmethod
from typing import Callable, Optional


class RealtimeCallback:
    """事件回调接口"""

    def on_session_started(self, data: dict):
        """会话启动，data 包含 {dialog_id}"""
        pass

    def on_asr_response(self, text: str, is_interim: bool = False):
        """ASR 识别结果"""
        pass

    def on_asr_ended(self):
        """用户说话结束"""
        pass

    def on_tts_response(self, audio_bytes: bytes):
        """TTS 音频数据"""
        pass

    def on_tts_sentence_start(self, data: dict):
        """TTS 句子开始"""
        pass

    def on_tts_sentence_end(self, data: dict):
        """TTS 句子结束"""
        pass

    def on_tts_ended(self, data: dict):
        """TTS 结束"""
        pass

    def on_chat_response(self, data: dict):
        """模型回复文本"""
        pass

    def on_chat_ended(self, data: dict):
        """模型回复结束"""
        pass

    def on_session_finished(self):
        """会话结束"""
        pass

    def on_session_failed(self, error_message: str):
        """会话失败"""
        pass

    def on_error(self, exc: Exception):
        """错误"""
        pass

    def on_close(self):
        """连接关闭"""
        pass


class RealtimeSession(ABC):
    """端到端实时语音会话抽象"""

    session_id: str
    is_active: bool

    def set_callback(self, callback: RealtimeCallback):
        self._callback = callback

    @abstractmethod
    async def start_session(self):
        """启动会话，建立 WebSocket 连接并初始化"""
        pass

    @abstractmethod
    async def send_audio(self, audio_chunk: bytes):
        """发送音频数据（20ms PCM）"""
        pass

    @abstractmethod
    async def end_asr(self):
        """发送 END_ASR 信号，通知服务器音频输入结束（push_to_talk 模式）"""
        pass

    @abstractmethod
    async def send_text(self, text: str):
        """发送文本（text 模式）"""
        pass

    @abstractmethod
    async def finish_session(self):
        """结束会话"""
        pass

    @abstractmethod
    async def close(self):
        """关闭连接"""
        pass

    def _notify_session_started(self, data: dict):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_session_started(data)

    def _notify_asr_response(self, text: str, is_interim: bool = False):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_asr_response(text, is_interim)

    def _notify_asr_ended(self):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_asr_ended()

    def _notify_tts_response(self, audio_bytes: bytes):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_tts_response(audio_bytes)

    def _notify_tts_sentence_start(self, data: dict):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_tts_sentence_start(data)

    def _notify_tts_sentence_end(self, data: dict):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_tts_sentence_end(data)

    def _notify_tts_ended(self, data: dict):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_tts_ended(data)

    def _notify_chat_response(self, data: dict):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_chat_response(data)

    def _notify_chat_ended(self, data: dict):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_chat_ended(data)

    def _notify_session_finished(self):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_session_finished()

    def _notify_session_failed(self, error_message: str):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_session_failed(error_message)

    def _notify_error(self, exc: Exception):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_error(exc)

    def _notify_close(self):
        if hasattr(self, '_callback') and self._callback:
            self._callback.on_close()


class RealtimeService(ABC):
    """端到端实时语音服务抽象"""

    @abstractmethod
    async def create_session(
        self,
        session_id: str,
        config: dict = None,
        callback: RealtimeCallback = None,
    ) -> RealtimeSession:
        """创建端到端实时语音会话"""
        pass
