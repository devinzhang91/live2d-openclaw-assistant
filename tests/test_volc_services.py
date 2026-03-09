#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 backend/services/asr_volc.py、tts_volc.py 和 llm_volc.py
测试 TTS -> ASR -> LLM 完整流程
"""
import asyncio
import sys
import os
import re

# 添加项目根目录到 Python 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def load_config():
    """从 volc_key.md 读取配置"""
    config_path = os.path.join(PROJECT_ROOT, "volc_key.md")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 解析 API key
    api_key_match = re.search(r"- ([a-f0-9-]{36})", content)
    api_key = api_key_match.group(1) if api_key_match else ""

    # 解析 APP ID
    app_id_match = re.search(r"APP ID\s*-?\s*(\d+)", content, re.IGNORECASE)
    app_id = app_id_match.group(1) if app_id_match else ""

    # 解析 Access Token
    access_token_match = re.search(r"Access Token\s*-?\s*([^\s]+)", content, re.IGNORECASE)
    access_token = access_token_match.group(1) if access_token_match else ""

    print(f"从 {config_path} 加载配置:")
    print(f"  APP ID: {app_id[:10]}..." if len(app_id) > 10 else f"  APP ID: {app_id}")
    print(f"  API Key: {api_key[:10]}..." if len(api_key) > 10 else f"  API Key: {api_key}")
    print(f"  Access Token: {access_token[:10]}..." if len(access_token) > 10 else f"  Access Token: {access_token}")

    return {
        "api_key": api_key,
        "app_id": app_id,
        "access_token": access_token,
    }


async def test_tts(tts_service, text: str) -> bytes:
    """测试 TTS"""
    print("\n=== TTS 测试 ===")
    print(f"输入: {text}")

    audio_data = await tts_service.synthesize_text(text)
    print(f"输出: {len(audio_data)} 字节的音频数据")

    return audio_data


async def test_asr(asr_service, audio_data: bytes) -> str:
    """测试 ASR"""
    print("\n=== ASR 测试 ===")
    print(f"输入: {len(audio_data)} 字节")

    recognized_text = await asr_service.transcribe_file(audio_data, language="zh")
    print(f"输出: {recognized_text}")

    return recognized_text


async def test_llm(llm_service, text: str) -> str:
    """测试 LLM"""
    print("\n=== LLM 测试 ===")
    print(f"输入: {text}")

    messages = [
        {"role": "system", "content": "你是一个友好的AI助手，请用简洁的语言回答。"},
        {"role": "user", "content": text}
    ]

    # 非流式调用
    result = await llm_service.chat_completion(messages, stream=False)
    content = result["choices"][0]["message"]["content"]
    print(f"回复: {content}")

    return content


async def run_full_test():
    """运行完整测试 TTS -> ASR -> LLM"""
    print("\n" + "=" * 60)
    print("火山引擎服务测试 (TTS -> ASR -> LLM)")
    print("=" * 60)

    # 加载配置
    config = load_config()

    # 导入服务
    from backend.services.tts_volc import VolcTTSService
    from backend.services.asr_volc import VolcASRService
    from backend.services.llm_volc import VolcLLMService

    # 初始化服务
    tts_service = VolcTTSService(
        app_id=config["app_id"],
        access_token=config["access_token"],
        ws_url="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
        voice_type="zh_female_cancan_mars_bigtts",
        encoding="mp3"
    )

    asr_service = VolcASRService(
        app_id=config["app_id"],
        access_key=config["access_token"],
        resource_id="volc.bigasr.sauc.duration",
        ws_url="wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    )

    llm_service = VolcLLMService(
        api_key=config["api_key"],
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        model="doubao-1.5-pro-32k-250115",
        max_tokens=200,
        temperature=0.7
    )

    test_text = "你好，请问你是谁"

    # 1. TTS
    audio_data = await test_tts(tts_service, test_text)

    # 保存音频文件
    output_path = os.path.join(PROJECT_ROOT, "tests", "test_output_services.mp3")
    with open(output_path, "wb") as f:
        f.write(audio_data)
    print(f"音频已保存: {output_path}")

    # 2. ASR
    recognized_text = await test_asr(asr_service, audio_data)

    # 3. LLM
    if recognized_text:
        llm_response = await test_llm(llm_service, recognized_text)
    else:
        print("ASR 识别失败，使用原始文本进行 LLM 测试")
        llm_response = await test_llm(llm_service, test_text)

    # 汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"原始文本: {test_text}")
    print(f"ASR识别: {recognized_text}")
    print(f"LLM回复: {llm_response}")
    print("\n测试完成!")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="火山引擎服务测试")
    parser.add_argument("--mode", choices=["full", "tts", "asr", "llm"], default="full", help="测试模式")
    args = parser.parse_args()

    config = load_config()

    # 导入服务
    from backend.services.tts_volc import VolcTTSService
    from backend.services.asr_volc import VolcASRService

    try:
        if args.mode == "full":
            await run_full_test()

        elif args.mode == "tts":
            print("\n=== TTS 测试 ===")
            test_text = "你好，请问你是谁"

            tts_service = VolcTTSService(
                app_id=config["app_id"],
                access_token=config["access_token"],
                ws_url="wss://openspeech.bytedance.com/api/v3/tts/bidirection",
                voice_type="zh_female_cancan_mars_bigtts",
                encoding="mp3"
            )

            audio = await tts_service.synthesize_text(test_text)
            print(f"生成音频: {len(audio)} 字节")

            output_path = os.path.join(PROJECT_ROOT, "tests", "test_output_services.mp3")
            with open(output_path, "wb") as f:
                f.write(audio)
            print(f"音频已保存: {output_path}")

        elif args.mode == "asr":
            print("\n=== ASR 测试 ===")

            # 使用 TTS 生成的音频
            output_path = os.path.join(PROJECT_ROOT, "tests", "test_output_services.mp3")
            if not os.path.exists(output_path):
                print("测试音频文件不存在，请先运行 TTS 测试")
                return

            with open(output_path, "rb") as f:
                audio = f.read()

            asr_service = VolcASRService(
                app_id=config["app_id"],
                access_key=config["access_token"],
                resource_id="volc.bigasr.sauc.duration",
                ws_url="wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
            )

            text = await asr_service.transcribe_file(audio, language="zh")
            print(f"识别结果: {text}")

        elif args.mode == "llm":
            print("\n=== LLM 测试 ===")
            test_text = "你好，请问你是谁"

            from backend.services.llm_volc import VolcLLMService

            llm_service = VolcLLMService(
                api_key=config["api_key"],
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                model="doubao-1.5-pro-32k-250115",
                max_tokens=200,
                temperature=0.7
            )

            messages = [
                {"role": "system", "content": "你是一个友好的AI助手，请用简洁的语言回答。"},
                {"role": "user", "content": test_text}
            ]

            result = await llm_service.chat_completion(messages, stream=False)
            content = result["choices"][0]["message"]["content"]
            print(f"回复: {content}")

    except KeyboardInterrupt:
        print("\n测试被中断")
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
