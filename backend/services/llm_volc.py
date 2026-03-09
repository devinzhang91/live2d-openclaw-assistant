"""
火山引擎 LLM 服务
使用 aiohttp 实现（基于测试成功的代码）
"""
import asyncio
import json
from typing import AsyncGenerator, Optional

from backend.services.llm_base import BaseLLMService


class VolcLLMService(BaseLLMService):
    """火山引擎 LLM 服务"""

    def _init_client(self):
        """初始化火山引擎 LLM 客户端（aiohttp 模式）"""
        # aiohttp 不需要预先初始化客户端
        # 在每次请求时动态创建 session
        pass

    async def _chat_completion(self, **kwargs) -> dict:
        """非流式聊天补全"""
        import aiohttp

        # base_url 可能已经包含 /chat/completions，检查一下
        if self.base_url.endswith("/chat/completions"):
            url = self.base_url
        else:
            url = self.base_url + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 确保不使用流式
        kwargs["stream"] = False

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=kwargs, headers=headers) as response:
                result = await response.json()
                return result

    async def _stream_chat_completion(self, **kwargs) -> AsyncGenerator[str, None]:
        """
        流式聊天补全，token 一个一个输出

        使用 Server-Sent Events (SSE) 方式流式接收
        """
        import aiohttp

        # base_url 可能已经包含 /chat/completions，检查一下
        if self.base_url.endswith("/chat/completions"):
            url = self.base_url
        else:
            url = self.base_url + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # 启用流式输出
        kwargs["stream"] = True

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=kwargs, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"LLM Error: {error_text}")

                # 读取 SSE 流
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if not line:
                        continue
                    if line.startswith('data: '):
                        data_str = line[6:]
                        if data_str == '[DONE]':
                            break
                        try:
                            data = json.loads(data_str)
                            if data.get('choices') and data['choices'][0].get('delta', {}).get('content'):
                                content = data['choices'][0]['delta']['content']
                                # 逐个字符输出以最大化减少延时
                                for char in content:
                                    yield char
                                    await asyncio.sleep(0)  # 让出控制权
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
