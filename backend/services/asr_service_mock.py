"""
简化的 ASR 服务（模拟版本）
用于演示和测试，实际使用时需要替换为真实的 ASR API
"""
from typing import AsyncGenerator, Optional
import asyncio
from backend.config.settings import settings


class ASRService:
    def __init__(self):
        self.api_url = settings.asr_api_url
        self.api_key = settings.asr_api_key
        self.sample_rate = settings.asr_sample_rate
        self.channels = settings.asr_channels

    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        language: str = "zh",
    ) -> AsyncGenerator[str, None]:
        """
        流式语音识别（模拟版本）

        实际使用时，这里应该调用真实的 ASR API
        """
        # 收集所有音频数据
        all_data = b""
        async for chunk in audio_stream:
            all_data += chunk

        # 模拟识别结果（实际应该发送到 ASR API）
        # 这里只是为了演示
        mock_texts = [
            "你好，我想问一个问题",
            "今天天气怎么样",
            "请帮我写一段代码",
            "你好，我是来测试语音识别的",
            "你能听懂我说的话吗"
        ]

        import random
        result_text = random.choice(mock_texts)

        # 模拟流式输出
        for char in result_text:
            yield char
            await asyncio.sleep(0.05)  # 模拟流式延迟

    async def transcribe_file(self, audio_file: bytes, language: str = "zh") -> str:
        """
        语音文件识别（模拟版本）
        """
        # 模拟识别结果
        return "这是模拟的语音识别结果，请配置真实的 ASR API"


# 全局实例
asr_service = ASRService()
