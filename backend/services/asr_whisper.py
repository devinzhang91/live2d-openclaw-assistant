"""
Faster-Whisper ASR 服务实现（本地模型）
"""
import os
import asyncio
import numpy as np
import io
import soundfile as sf
from faster_whisper import WhisperModel
from typing import Optional

# 配置 HuggingFace 镜像源（适用于国内网络环境）
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

from backend.services.asr_base import ASRService, ASRSession, ASRStreamCallback


class WhisperASRSession(ASRSession):
    """Faster-Whisper 流式会话（伪流式）"""

    def __init__(self, session_id: str, model: WhisperModel, language: str = "zh"):
        super().__init__(session_id)
        self.model = model
        self.language = language
        self._audio_buffer = []
        self._sample_rate = 16000

    async def start(self):
        """启动会话"""
        self.is_active = True

    async def send_audio(self, audio: np.ndarray, sample_rate: int):
        """收集音频数据"""
        if not self.is_active:
            raise RuntimeError("Session not active")

        self._audio_buffer.append(audio)
        self._sample_rate = sample_rate

        # 发送部分结果（模拟）
        # 由于 faster-whisper 不支持真正的流式，这里不发送部分结果
        # 子类可以重写这个方法实现真正的流式

    async def end(self):
        """结束会话，识别收集的音频"""
        if not self.is_active:
            return

        # 合并所有音频
        if self._audio_buffer:
            audio = np.concatenate(self._audio_buffer)
        else:
            audio = np.array([])

        # 使用 Whisper 识别
        text = ""
        if len(audio) > 0:
            segments, info = self.model.transcribe(
                audio,
                language=self.language,
                beam_size=5,
                vad_filter=True
            )
            text = " ".join([seg.text for seg in segments])

        # 通知最终结果
        self._notify_final(text.strip())

    async def close(self):
        """关闭连接"""
        self.is_active = False
        self._audio_buffer = []
        self._notify_close()


class FasterWhisperASRService(ASRService):
    """Faster-Whisper ASR 服务"""

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        super().__init__()
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self._load_model()

    def _load_model(self):
        """加载 Whisper 模型"""
        try:
            print(f"正在加载 Whisper 模型 ({self.model_size})，首次运行会自动下载...")
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type
            )
            print("Whisper 模型加载成功")
        except ImportError:
            print("未安装 faster-whisper，正在安装...")
            import subprocess
            subprocess.check_call(["pip", "install", "faster-whisper"])
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type
            )
            print("Whisper 模型加载成功")
        except Exception as e:
            print(f"Whisper 模型加载失败: {str(e)}")
            raise

    async def transcribe_file(self, audio_data: bytes, language: str = "zh") -> str:
        """
        语音文件识别

        Args:
            audio_data: 音频文件数据
            language: 语言代码

        Returns:
            识别到的文本
        """
        try:
            # 使用 soundfile 读取音频
            audio_bytes = io.BytesIO(audio_data)
            audio_array, sr = sf.read(audio_bytes, dtype='float32')

            # 如果是立体声，转换为单声道
            if len(audio_array.shape) > 1:
                audio_array = audio_array.mean(axis=1)

            # 使用 Whisper 进行识别
            segments, info = self.model.transcribe(
                audio_array,
                language=language,
                beam_size=5,
                vad_filter=True,
                word_timestamps=True
            )

            # 合并所有片段的文本
            text = " ".join([segment.text for segment in segments])
            return text.strip()

        except Exception as e:
            print(f"ASR 识别错误: {str(e)}")
            raise

    async def create_session(
        self,
        session_id: str,
        language: str = "zh",
        callback: Optional[ASRStreamCallback] = None
    ) -> WhisperASRSession:
        """
        创建流式识别会话

        Args:
            session_id: 会话唯一标识
            language: 语言代码
            callback: 回调接口

        Returns:
            ASR 会话对象
        """
        session = WhisperASRSession(session_id, self.model, language)
        if callback:
            session.set_callback(callback)
        return session
