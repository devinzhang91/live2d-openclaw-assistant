"""
OpenAI 兼容的 LLM 服务
支持 OpenAI、阿里云通义千问等兼容 OpenAI API 的服务
"""
import asyncio
from typing import AsyncGenerator

from openai import AsyncOpenAI

from backend.services.llm_base import BaseLLMService


class OpenAILLMService(BaseLLMService):
    """OpenAI 兼容的 LLM 服务"""

    def _init_client(self):
        """初始化 LLM 客户端"""
        try:
            self.client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
            )
            print(f"OpenAI LLM 客户端初始化成功: {self.base_url}")
        except Exception as e:
            print(f"OpenAI LLM 客户端初始化失败: {str(e)}")
            raise

    async def _chat_completion(self, **kwargs) -> dict:
        """非流式聊天补全"""
        response = await self.client.chat.completions.create(**kwargs)
        return response.model_dump()

    async def _stream_chat_completion(self, **kwargs) -> AsyncGenerator[str, None]:
        """流式聊天补全，token 一个一个输出"""
        try:
            # stream=True 时，create() 返回一个协程，需要 await 来获取异步生成器
            stream = await self.client.chat.completions.create(**kwargs)

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    # 逐个字符输出以最大化减少延时
                    content = chunk.choices[0].delta.content
                    for char in content:
                        yield char
                        await asyncio.sleep(0)  # 让出控制权
        except Exception as e:
            print(f"OpenAI LLM 流式输出错误: {str(e)}")
            raise
