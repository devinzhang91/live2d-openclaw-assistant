"""
LLM 服务模块入口
提供 LLM 服务工厂函数和全局实例
"""
import os
from typing import Optional

from backend.services.llm_base import BaseLLMService
from backend.services.llm_openai import OpenAILLMService
from backend.services.llm_volc import VolcLLMService


# LLM 提供者工厂
def create_llm_service(
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
) -> BaseLLMService:
    """
    创建 LLM 服务实例

    Args:
        provider: 提供者 (openai, volc)，默认从环境变量读取
        base_url: API 地址
        api_key: API 密钥
        model: 模型名称
        max_tokens: 最大 token 数
        temperature: 温度参数

    Returns:
        LLM 服务实例
    """
    provider = provider or os.getenv("LLM_PROVIDER", "openai")

    if provider == "volc":
        base_url = base_url or os.getenv(
            "VOLC_LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
        )
        api_key = api_key or os.getenv("VOLC_LLM_API_KEY", "")
        model = model or os.getenv("VOLC_LLM_MODEL", "doubao-seed-1-6-251015")
        max_tokens = max_tokens or int(
            os.getenv("VOLC_LLM_MAX_TOKENS", "2000")
        )
        temperature = temperature or float(
            os.getenv("VOLC_LLM_TEMPERATURE", "0.7")
        )
        return VolcLLMService(base_url, api_key, model, max_tokens, temperature)
    else:  # 默认使用 OpenAI 兼容接口
        from backend.config.settings import settings
        base_url = base_url or settings.llm_base_url
        api_key = api_key or settings.llm_api_key
        model = model or settings.llm_model
        max_tokens = max_tokens or settings.llm_max_tokens
        temperature = temperature or settings.llm_temperature
        return OpenAILLMService(base_url, api_key, model, max_tokens, temperature)


# 全局实例（默认根据环境变量选择）
llm_service: BaseLLMService = create_llm_service()


# 导出所有
__all__ = [
    "BaseLLMService",
    "OpenAILLMService",
    "VolcLLMService",
    "create_llm_service",
    "llm_service",
]
