#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
火山引擎 API 集成测试: TTS -> ASR -> LLM

从 volc_key.md 读取配置
参考示例: /Users/zhangyoujin/Downloads/sauc_python/sauc_websocket_demo.py
"""
import asyncio
import sys
import os
import json
import gzip
import uuid
import struct
import re

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 从 volc_key.md 读取配置
def load_config():
    config_path = os.path.join(PROJECT_ROOT, "volc_key.md")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 解析 API key
    api_key_match = re.search(r"- ([a-f0-9-]{36})", content)
    api_key = api_key_match.group(1) if api_key_match else ""

    # 解析 APP ID
    app_id_match = re.search(r"APP ID\s*-\s*(\d+)", content, re.IGNORECASE)
    app_id = app_id_match.group(1) if app_id_match else ""

    # 解析 Access Token
    access_token_match = re.search(r"Access Token\s*-\s*([^\s]+)", content, re.IGNORECASE)
    access_token = access_token_match.group(1) if access_token_match else ""

    # 解析 Secret Key
    secret_key_match = re.search(r"Secret Key\s*-\s*([^\s]+)", content, re.IGNORECASE)
    secret_key = secret_key_match.group(1) if secret_key_match else ""

    print(f"从 {config_path} 加载配置:")
    print(f"  APP ID: {app_id[:10]}..." if len(app_id) > 10 else f"  APP ID: {app_id}")
    print(f"  API Key: {api_key[:10]}..." if len(api_key) > 10 else f"  API Key: {api_key}")
    print(f"  Access Token: {access_token[:10]}..." if len(access_token) > 10 else f"  Access Token: {access_token}")

    return {
        "api_key": api_key,
        "app_id": app_id,
        "access_token": access_token,
        "secret_key": secret_key
    }


# 加载配置
config = load_config()
VOLC_APP_ID = config["app_id"]
VOLC_API_KEY = config["api_key"]
VOLC_ACCESS_TOKEN = config["access_token"]

# 协议常量
PROTO_VERSION = 0x1
HEADER_SIZE = 0x1
SERIALIZATION_JSON = 0x1
COMPRESSION_GZIP = 0x1

# TTS 协议常量
TTS_MSG_TYPE_FULL_CLIENT_REQUEST = 0x01
TTS_MSG_TYPE_AUDIO_ONLY_RESPONSE = 0x0B

# ASR 协议常量
ASR_MSG_TYPE_FULL_REQUEST = 0x01
ASR_MSG_TYPE_AUDIO_ONLY_REQUEST = 0x02
ASR_MSG_TYPE_FULL_RESPONSE = 0x09
ASR_MSG_TYPE_ERROR_RESPONSE = 0x0F

ASR_FLAG_NO_SEQUENCE = 0x00
ASR_FLAG_POS_SEQUENCE = 0x01
ASR_FLAG_NEG_SEQUENCE = 0x02
ASR_FLAG_NEG_WITH_SEQUENCE = 0x03


def build_header(msg_type, flags=0, serialization=1, compression=1):
    byte0 = (PROTO_VERSION << 4) | HEADER_SIZE
    byte1 = (msg_type << 4) | flags
    byte2 = (serialization << 4) | compression
    byte3 = 0x00
    return bytes([byte0, byte1, byte2, byte3])


def pack_payload(payload_bytes, compress=True):
    if compress:
        payload_bytes = gzip.compress(payload_bytes)
    size_bytes = struct.pack(">I", len(payload_bytes))
    return size_bytes + payload_bytes


# ============ TTS ============

async def test_tts(text):
    print("\n=== TTS 测试 ===")
    print(f"输入: {text}")

    import websockets

    ws_url = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    headers = {"Authorization": f"Bearer; {VOLC_ACCESS_TOKEN}"}

    audio_chunks = []
    synthesis_complete = False

    try:
        async with websockets.connect(ws_url, additional_headers=headers, ping_interval=None) as ws:
            payload = {
                "app": {
                    "appid": VOLC_APP_ID,
                    "token": VOLC_ACCESS_TOKEN,
                    "cluster": "volcano_tts"
                },
                "user": {"uid": str(uuid.uuid4())},
                "audio": {
                    "voice_type": "zh_female_cancan_mars_bigtts",
                    "encoding": "mp3"
                },
                "request": {
                    "reqid": str(uuid.uuid4()),
                    "text": text,
                    "operation": "submit",
                    "disable_markdown_filter": True
                }
            }

            header = build_header(1, 0, 1, 1)
            packed = pack_payload(json.dumps(payload).encode("utf-8"), True)
            await ws.send(header + packed)

            while not synthesis_complete:
                data = await ws.recv()
                if len(data) < 8:
                    continue

                msg_type = (data[1] >> 4) & 0x0F
                flags = data[1] & 0x0F

                if msg_type == 0x0B:  # TTS_MSG_TYPE_AUDIO_ONLY_RESPONSE
                    offset = 4
                    if flags == 0x01:
                        offset += 4
                    elif flags in (0x02, 0x03):
                        if flags == 0x03:
                            offset += 4
                        synthesis_complete = True

                    payload_size = struct.unpack(">I", data[offset:offset+4])[0]
                    offset += 4
                    audio_data = data[offset:offset+payload_size]
                    if audio_data:
                        audio_chunks.append(audio_data)
    except Exception as e:
        print(f"TTS 错误: {e}")
        raise

    all_audio = b"".join(audio_chunks)
    print(f"输出: {len(all_audio)} 字节的音频数据")
    return all_audio


# ============ ASR ============

def build_asr_full_request(seq: int):
    header = build_header(1, ASR_FLAG_POS_SEQUENCE, 1, 1)

    payload = {
        "user": {"uid": "demo_uid"},
        "audio": {
            "format": "pcm",  # 使用 PCM 格式
            "rate": 16000,
            "bits": 16,
            "channel": 1
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": True,
            "enable_nonstream": False
        }
    }

    payload_bytes = json.dumps(payload).encode("utf-8")
    compressed_payload = gzip.compress(payload_bytes)
    payload_size = struct.pack(">I", len(compressed_payload))

    request = bytearray()
    request.extend(header)
    request.extend(struct.pack(">i", seq))  # 使用正序列号
    request.extend(payload_size)
    request.extend(compressed_payload)

    return bytes(request)


def build_asr_audio_request(seq: int, segment: bytes, is_last: bool = False):
    if is_last:
        flags = ASR_FLAG_NEG_WITH_SEQUENCE
        seq_to_send = -seq  # 最后一包发送负序列号
    else:
        flags = ASR_FLAG_POS_SEQUENCE
        seq_to_send = seq

    header = build_header(2, flags, 0, 1)  # audio only, raw serialization, gzip compression

    request = bytearray()
    request.extend(header)
    request.extend(struct.pack(">i", seq_to_send))

    compressed_segment = gzip.compress(segment)
    request.extend(struct.pack(">I", len(compressed_segment)))
    request.extend(compressed_segment)

    return bytes(request)


def parse_asr_response(msg: bytes):
    header_size = msg[0] & 0x0f
    message_type = msg[1] >> 4
    message_type_specific_flags = msg[1] & 0x0f
    serialization_method = msg[2] >> 4
    message_compression = msg[2] & 0x0f

    payload = msg[header_size*4:]

    response = {
        "code": 0,
        "event": 0,
        "is_last_package": False,
        "payload_sequence": 0,
        "payload_size": 0,
        "payload_msg": None
    }

    # 解析 message_type_specific_flags
    if message_type_specific_flags & 0x01:
        response["payload_sequence"] = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]
    if message_type_specific_flags & 0x02:
        response["is_last_package"] = True
    if message_type_specific_flags & 0x04:
        response["event"] = struct.unpack(">i", payload[:4])[0]
        payload = payload[4:]

    if not payload:
        return response

    # 解析 message_type
    if message_type == ASR_MSG_TYPE_FULL_RESPONSE:
        response["payload_size"] = struct.unpack(">I", payload[:4])[0]
        payload = payload[4:]
    elif message_type == ASR_MSG_TYPE_ERROR_RESPONSE:
        response["code"] = struct.unpack(">i", payload[:4])[0]
        response["payload_size"] = struct.unpack(">I", payload[4:8])[0]
        payload = payload[8:]

    # 解压缩
    if message_compression == COMPRESSION_GZIP:
        try:
            payload = gzip.decompress(payload)
        except Exception as e:
            print(f"解压缩失败: {e}")
            return response

    # 解析 payload
    if serialization_method == SERIALIZATION_JSON:
        try:
            response["payload_msg"] = json.loads(payload.decode("utf-8"))
        except Exception as e:
            print(f"JSON 解析失败: {e}")

    return response


async def test_asr(audio_data):
    print("\n=== ASR 测试 ===")
    print(f"输入: {len(audio_data)} 字节")

    import websockets
    import soundfile as sf
    import io
    import numpy as np

    # 解码音频数据
    audio_bytes = io.BytesIO(audio_data)
    audio_array, sr = sf.read(audio_bytes, dtype="float32")
    if len(audio_array.shape) > 1:
        audio_array = audio_array.mean(axis=1)

    # 重采样到 16000Hz
    if sr != 16000:
        ratio = 16000 / sr
        new_length = int(len(audio_array) * ratio)
        indices = np.linspace(0, len(audio_array) - 1, new_length)
        audio_array = np.interp(indices, np.arange(len(audio_array)), audio_array)

    # 转换为 PCM 格式
    audio = np.clip(audio_array, -1.0, 1.0)
    audio_pcm = (audio * 32767.0).astype(np.int16).tobytes()

    # WebSocket 连接
    ws_url = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
    headers = {
        "X-Api-App-Key": VOLC_APP_ID,
        "X-Api-Access-Key": VOLC_ACCESS_TOKEN,
        "X-Api-Resource-Id": "volc.bigasr.sauc.duration",
        "X-Api-Connect-Id": str(uuid.uuid4())
    }

    final_text = ""
    partial_text = ""
    seq = 1

    try:
        async with websockets.connect(ws_url, additional_headers=headers, ping_interval=None) as ws:
            print("WebSocket 连接成功")

            # 1. 发送 full client request
            request = build_asr_full_request(seq)
            seq += 1
            await ws.send(request)
            print("已发送配置请求")

            # 2. 发送音频数据 - 分段发送
            segment_duration = 200  # 200ms
            segment_size = 6400  # 200ms at 16kHz, 16-bit, mono
            total_segments = (len(audio_pcm) + segment_size - 1) // segment_size

            print(f"准备发送 {total_segments} 个音频段")

            for i in range(total_segments):
                start_idx = i * segment_size
                end_idx = min((i + 1) * segment_size, len(audio_pcm))
                segment = audio_pcm[start_idx:end_idx]

                is_last = (i == total_segments - 1)
                request = build_asr_audio_request(seq, segment, is_last)
                await ws.send(request)
                print(f"发送音频段 {i+1}/{total_segments}: seq={seq}, 最后={is_last}")

                if not is_last:
                    seq += 1

                # 分段之间暂停模拟实时流
                if not is_last:
                    await asyncio.sleep(segment_duration / 1000.0)

            # 3. 接收响应
            timeout = 15.0
            start = asyncio.get_event_loop().time()

            while asyncio.get_event_loop().time() - start < timeout:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    response = parse_asr_response(msg)

                    print(f"收到响应: {json.dumps(response, ensure_ascii=False)[:200]}")

                    # 处理错误
                    if response["code"] != 0:
                        print(f"ASR 错误: {response}")
                        break

                    # 处理识别结果
                    if response["payload_msg"]:
                        if "result" in response["payload_msg"]:
                            result_data = response["payload_msg"]["result"]
                            text = result_data.get("text", "")
                            utterances = result_data.get("utterances", [])

                            if utterances:
                                last = utterances[-1]
                                if last.get("definite", False) or (not utterances and text):
                                    final_text = text
                                    print(f"识别完成: {text}")
                                    if response["is_last_package"]:
                                        return final_text
                                elif text and text != partial_text:
                                    partial_text = text
                                    print(f"部分结果: {text}")

                    # 如果是最后一包，返回结果
                    if response["is_last_package"]:
                        break

                except asyncio.TimeoutError:
                    pass
    except Exception as e:
        print(f"ASR 错误: {e}")
        import traceback
        traceback.print_exc()
        raise

    print(f"输出: {final_text}")
    return final_text


# ============ LLM ============

async def test_llm(text):
    print("\n=== LLM 测试 ===")
    print(f"输入: {text}")

    import aiohttp

    url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    headers = {
        "Authorization": f"Bearer {VOLC_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "doubao-1.5-pro-32k-250115",
        "messages": [
            {"role": "system", "content": "你是一个友好的AI助手，请用简洁的语言回答。"},
            {"role": "user", "content": text}
        ],
        "max_tokens": 200,
        "temperature": 0.7
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                result = await response.json()

                if "choices" in result and result["choices"]:
                    content = result["choices"][0]["message"]["content"]
                    print(f"回复: {content}")
                    return content
                else:
                    raise Exception(f"LLM Error: {result}")
    except Exception as e:
        print(f"LLM 错误: {e}")
        raise


async def run_full_test():
    print("\n" + "=" * 60)
    print("火山引擎 API 集成测试 (TTS -> ASR -> LLM)")
    print("=" * 60)

    test_text = "你好，请问你是谁"

    # 1. TTS
    audio_data = await test_tts(test_text)

    output_path = os.path.join(os.path.dirname(__file__), "test_output.mp3")
    with open(output_path, "wb") as f:
        f.write(audio_data)
    print(f"音频已保存: {output_path}")

    # 2. ASR
    recognized_text = await test_asr(audio_data)

    # 3. LLM
    if recognized_text:
        llm_response = await test_llm(recognized_text)
    else:
        print("ASR 识别失败，使用原始文本进行 LLM 测试")
        llm_response = await test_llm(test_text)

    # Summary
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    print(f"原始文本: {test_text}")
    print(f"ASR识别: {recognized_text}")
    print(f"LLM回复: {llm_response}")
    print("\n测试完成!")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="火山引擎 API 集成测试")
    parser.add_argument("--mode", choices=["full", "tts", "asr", "llm"], default="full", help="测试模式")
    args = parser.parse_args()

    try:
        if args.mode == "full":
            await run_full_test()
        elif args.mode == "tts":
            test_text = "你好，请问你是谁"
            audio = await test_tts(test_text)
            output_path = os.path.join(os.path.dirname(__file__), "test_output.mp3")
            with open(output_path, "wb") as f:
                f.write(audio)
            print(f"音频已保存: {output_path}")
        elif args.mode == "asr":
            output_path = os.path.join(os.path.dirname(__file__), "test_output.mp3")
            if not os.path.exists(output_path):
                print("测试音频文件不存在，请先运行 TTS 测试")
                return
            with open(output_path, "rb") as f:
                audio = f.read()
            text = await test_asr(audio)
            print(f"识别结果: {text}")
        elif args.mode == "llm":
            test_text = "你好，请问你是谁"
            result = await test_llm(test_text)
            print(f"回复: {result}")
    except KeyboardInterrupt:
        print("\n测试被中断")
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
