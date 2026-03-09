"""
LLM 服务抽象基类
"""
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional, Union


class BaseLLMService(ABC):
    """LLM 服务抽象基类"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.client = None
        self._init_client()

    @abstractmethod
    def _init_client(self):
        """初始化 LLM 客户端"""
        pass

    @abstractmethod
    async def _chat_completion(self, **kwargs) -> dict:
        """非流式聊天补全"""
        pass

    async def _stream_chat_completion(self, **kwargs) -> AsyncGenerator[str, None]:
        """流式聊天补全，token 一个一个输出

        子类可以重写此方法，默认实现使用流式接口
        """
        raise NotImplementedError("子类必须实现 _stream_chat_completion 方法")

    def chat_completion(
        self,
        messages: list[dict],
        stream: bool = True,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Union[AsyncGenerator[str, None], object]:
        """
        聊天补全

        Args:
            messages: 消息列表
            stream: 是否流式输出
            model: 模型名称
            max_tokens: 最大 token 数
            temperature: 温度参数

        Returns:
            流式输出时返回异步生成器，非流式时返回协程
        """
        kwargs = {
            "model": model or self.model,
            "messages": messages,
            "stream": stream,
        }

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = self.max_tokens

        if temperature is not None:
            kwargs["temperature"] = temperature
        else:
            kwargs["temperature"] = self.temperature

        if stream:
            # 流式模式：直接返回 _stream_chat_completion 的结果
            # _stream_chat_completion 是异步生成器，调用它返回 AsyncGenerator 对象
            return self._stream_chat_completion(**kwargs)
        else:
            # 非流式模式：返回协程
            return self._chat_completion(**kwargs)
