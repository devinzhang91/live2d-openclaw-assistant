# -*- coding: utf-8 -*-
"""
API Router - WebSocket Real-time Communication
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List
import asyncio
import base64
import io
import re
import uuid
import soundfile as sf
import numpy as np

from backend.services.llm_service import llm_service
from backend.services.asr_service import asr_service
from backend.services.tts_service import tts_service
from backend.services.vad_service import vad_service
from backend.services.openclaw_service import openclaw_service
from backend.services.intent_router import intent_router, OPENCLAW_ROUTE
from backend.config.settings import settings
from backend.config.config_manager import config_manager


router = APIRouter()


class ConnectionManager:
    """WebSocket connection manager"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        try:
            await websocket.send_json(message)
        except Exception:
            pass  # 连接已关闭时静默忽略

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            await connection.send_json(message)


manager = ConnectionManager()


def extract_sentences(text: str):
    """
    从文本缓冲区中提取已完整的句子。
    返回 (sentences_list, remaining_buffer)。

    切分规则：
      1. 强终止符 。！？!?… 或换行 —— 立即切分
      2. 弱终止符 ，、；,;  —— 当前缓冲区已达 COMMA_MIN_LEN 时切分
         避免把极短片段切走（如"你好，"）
    """
    COMMA_MIN_LEN = 20
    STRONG = re.compile(r'[。！？…!?]+\s*|\n+')
    WEAK   = re.compile(r'[，、；,;]\s*')

    sentences = []
    last = 0
    i = 0
    while i < len(text):
        m = STRONG.match(text, i)
        if m:
            sentence = text[last:m.end()].strip()
            if sentence:
                sentences.append(sentence)
            last = m.end()
            i = last
            continue

        m = WEAK.match(text, i)
        if m and (i - last) >= COMMA_MIN_LEN:
            sentence = text[last:m.end()].strip()
            if sentence:
                sentences.append(sentence)
            last = m.end()
            i = last
            continue

        i += 1

    remaining = text[last:]
    return sentences, remaining


async def pipeline_llm_tts(history: list, websocket: WebSocket, override_messages: list = None):
    """
    最低延时 LLM→TTS 流水线。

    核心设计：
      - 创建一个 TTS session 供整轮对话使用
      - LLM token 流按小缓冲区（遇标点 或 len>=FLUSH_LEN）调用 send_task()，
        无需先凑齐完整句子
      - _recv_loop 在后台持续接收音频帧并入队
      - audio_forwarder 与 llm_producer 并发运行，实时把音频帧推给前端
      - LLM 结束后调用 finish_session()，_recv_loop 设置完成事件，audio_forwarder 退出

    首字延时：仅取决于 LLM 首 token + TTS 首帧，通常 < 1 s。
    """
    full_response_chunks = []
    FLUSH_LEN = 12   # 非标点时累积字符数（提高以减少 TaskRequest 次数，给 TTS 更大文本上下文）
    FLUSH_PUNCT = re.compile(r'[。！？…!?\n]')  # 仅强标点触发 flush；逗号不触发，避免过度切分

    # 创建并启动 TTS session（含握手）
    voice_type = config_manager.get_current_voice_type()
    speed_ratio = config_manager.get_speed_ratio()

    from backend.services.tts_volc import VolcTTSService
    volc_tts = tts_service if isinstance(tts_service, VolcTTSService) else None

    if volc_tts is not None:
        # 使用 token-level streaming 路径
        tts_session = await volc_tts.create_session(
            session_id=str(uuid.uuid4()),
            voice=voice_type,
            speed_ratio=speed_ratio,
            encoding="pcm",
        )
        audio_idx = 0

        async def audio_forwarder():
            nonlocal audio_idx
            # PCM 流按 16-bit 单声道 24kHz 转发；批量合并减少 WS 次数并保证 sample 对齐。
            # 16384 bytes ≈ 341ms @ 24kHz/16-bit/mono
            BATCH_BYTES = 16384
            batch = bytearray()
            sample_width = 2

            async for chunk in tts_session.get_audio_chunks():
                batch.extend(chunk)
                if len(batch) >= BATCH_BYTES:
                    aligned_size = len(batch) - (len(batch) % sample_width)
                    if aligned_size <= 0:
                        continue
                    audio_base64 = base64.b64encode(bytes(batch[:aligned_size])).decode()
                    await manager.send_personal_message(
                        {
                            "type": "tts_audio",
                            "content": audio_base64,
                            "index": audio_idx,
                            "format": "pcm_s16le",
                            "sample_rate": 24000,
                            "channels": 1,
                        },
                        websocket,
                    )
                    audio_idx += 1
                    batch = bytearray(batch[aligned_size:])

            # 刷末尾残留（最后一批通常 < BATCH_BYTES）
            if batch:
                aligned_size = len(batch) - (len(batch) % sample_width)
                if aligned_size > 0:
                    audio_base64 = base64.b64encode(bytes(batch[:aligned_size])).decode()
                    await manager.send_personal_message(
                        {
                            "type": "tts_audio",
                            "content": audio_base64,
                            "index": audio_idx,
                            "format": "pcm_s16le",
                            "sample_rate": 24000,
                            "channels": 1,
                        },
                        websocket,
                    )
                    audio_idx += 1

        async def llm_producer():
            buf = ""
            if override_messages is not None:
                messages_for_llm = override_messages
            else:
                system_prompt = config_manager.get_system_prompt()
                messages_for_llm = [{"role": "system", "content": system_prompt}] + history

            try:
                async for chunk in llm_service.chat_completion(messages_for_llm, stream=True):
                    full_response_chunks.append(chunk)
                    buf += chunk
                    await manager.send_personal_message(
                        {"type": "llm_chunk", "content": chunk}, websocket
                    )
                    # flush 条件：遇标点 或 缓冲够长
                    if FLUSH_PUNCT.search(buf) or len(buf) >= FLUSH_LEN:
                        try:
                            await tts_session.send_task(buf)
                        except Exception as e:
                            print(f"[pipeline] send_task 失败: {e}")
                        buf = ""
            except Exception as e:
                print(f"[pipeline] LLM 生成出错: {e}")

            # 刷末尾残留
            if buf.strip():
                try:
                    await tts_session.send_task(buf)
                except Exception as e:
                    print(f"[pipeline] send_task(末尾) 失败: {e}")

            # 通知 TTS session 文本已全部发完
            try:
                await tts_session.finish_session()
            except Exception as e:
                print(f"[pipeline] finish_session 失败: {e}")

        try:
            await asyncio.gather(llm_producer(), audio_forwarder())
        finally:
            await tts_session.close()

    else:
        # 降级：使用传统句子批量合成路径（非 VolcTTSService）
        task_queue: asyncio.Queue = asyncio.Queue()

        async def synthesize_one_fallback(idx: int, sentence: str):
            try:
                audio = await tts_service.synthesize_text(sentence, voice=voice_type, speed_ratio=speed_ratio)
                return audio
            except Exception as e:
                print(f"[pipeline] TTS 合成失败 idx={idx}: {e}")
                return None

        async def llm_producer_fallback():
            buffer = ""
            idx = 0
            if override_messages is not None:
                messages_for_llm = override_messages
            else:
                system_prompt = config_manager.get_system_prompt()
                messages_for_llm = [{"role": "system", "content": system_prompt}] + history
            try:
                async for chunk in llm_service.chat_completion(messages_for_llm, stream=True):
                    full_response_chunks.append(chunk)
                    buffer += chunk
                    await manager.send_personal_message(
                        {"type": "llm_chunk", "content": chunk}, websocket
                    )
                    sentences, buffer = extract_sentences(buffer)
                    for sentence in sentences:
                        task = asyncio.create_task(synthesize_one_fallback(idx, sentence))
                        await task_queue.put((idx, task))
                        idx += 1
            except Exception as e:
                print(f"[pipeline] LLM 生成出错: {e}")
                await task_queue.put(None)
                return
            if buffer.strip():
                task = asyncio.create_task(synthesize_one_fallback(idx, buffer.strip()))
                await task_queue.put((idx, task))
            await task_queue.put(None)

        async def audio_sender_fallback():
            while True:
                item = await task_queue.get()
                if item is None:
                    break
                idx, task = item
                try:
                    audio_bytes = await task
                    if audio_bytes:
                        audio_base64 = base64.b64encode(audio_bytes).decode()
                        await manager.send_personal_message(
                            {"type": "tts_audio", "content": audio_base64, "index": idx},
                            websocket,
                        )
                except Exception as e:
                    print(f"[pipeline] 发送音频失败 idx={idx}: {e}")

        await asyncio.gather(llm_producer_fallback(), audio_sender_fallback())

    # 写入对话历史
    response_text = "".join(full_response_chunks)
    history.append({"role": "assistant", "content": response_text})

    await manager.send_personal_message(
        {"type": "llm_complete", "content": response_text}, websocket
    )
    await manager.send_personal_message(
        {"type": "tts_complete", "message": "Speech synthesis complete"}, websocket
    )


async def send_tts_notice(text: str, websocket: WebSocket):
    """发送一条不写入对话历史的简短 TTS 提示。"""
    voice_type = config_manager.get_current_voice_type()
    speed_ratio = config_manager.get_speed_ratio()

    audio_bytes = await tts_service.synthesize_text(
        text,
        voice=voice_type,
        speed_ratio=speed_ratio,
    )
    audio_base64 = base64.b64encode(audio_bytes).decode()

    await manager.send_personal_message(
        {"type": "tts_audio", "content": audio_base64, "format": "mp3"},
        websocket,
    )
    await manager.send_personal_message(
        {"type": "tts_complete", "message": "Speech synthesis complete"},
        websocket,
    )


def build_openclaw_notify_messages(user_text: str, openclaw_response: str) -> list:
    """构建 OpenClaw 结果转述提示。"""
    notify_system = (
        "你是一个 Live2D AI 助手。请用第一人称，简洁地把 OpenClaw 刚刚返回的结果要点"
        "转述给用户（1句话）。语气自然口语化，不要用任何格式符号或 Markdown。"
        "你回答问题时直击要害，务实高效，让对方立刻得到有用的信息。\n\n【回答格式要求】\n你的回答将直接通过语音朗读给用户，因此必须严格遵守以下格式规则：\n1. 只使用自然爽快的中文口语表达，简洁明了，像在直接对话\n2. 不要使用任何Markdown格式，禁止出现星号、井号、横线、反引号等符号\n3. 不要用列表符号（如1. 2. 3. 或 * - 等），改用「第一步……第二步……」或「先……再……最后……」这样直接的口语\n4. 不要输出任何代码块、JSON、XML或其他程序格式\n5. 回答要简洁有力，适合语音播报，避免废话，直接给答案\n6. 保持活力感，通过语气和节奏传递能量，而非格式符号\n\n【播放行为约束】\n- 请以第一人称（“我”）来播报 OpenClaw 的结果，语气保持角色的元气与直接风格。\n- 回答必须简洁、只说重点，省略序列号、UUID、cron ID、trace ID 等无意义内部信息，只保留对用户有用的内容。\n"
    )
    notify_user = (
        f"用户说：{user_text}\n\n"
        f"OpenClaw 的回复：\n{openclaw_response}"
    )
    return [
        {"role": "system", "content": notify_system},
        {"role": "user", "content": notify_user},
    ]


async def route_user_message(user_text: str, history: list, websocket: WebSocket):
    """根据当前意图将请求路由到 OpenClaw 或普通 LLM。"""
    decision = await intent_router.decide(user_text, history)
    print(
        "[IntentRouter] "
        f"route={decision.route} intent={decision.intent_type} "
        f"confidence={decision.confidence:.2f} reason={decision.reason}"
    )

    if decision.route == OPENCLAW_ROUTE:
        await process_with_openclaw(user_text, history, websocket)
        return

    await manager.send_personal_message(
        {"type": "llm_thinking"},
        websocket,
    )
    await pipeline_llm_tts(history, websocket)


async def process_with_openclaw(user_text: str, history: list, websocket: WebSocket):
    """
    OpenClaw webhook 集成管道：
      1. 调用 OpenClaw /hooks/agent
      2. 将 OpenClaw 返回结果推送到前端（显示为 openclaw_message，不触发 TTS）
      3. 将结果交给 LLM 生成简洁口语通知，然后通过 TTS 播放
    """
    # 通知前端正在调用 OpenClaw
    await manager.send_personal_message(
        {"type": "status", "message": "正在查询 OpenClaw…"},
        websocket,
    )
    await manager.send_personal_message(
        {"type": "openclaw_thinking"},
        websocket,
    )

    openclaw_task = asyncio.create_task(openclaw_service.call_agent(user_text))

    try:
        await send_tts_notice("OpenClaw 正在处理您的任务。", websocket)
    except Exception as e:
        print(f"[OpenClaw] 处理提示播报失败: {e}")

    # 调用 OpenClaw webhook
    openclaw_response = await openclaw_task
    if not openclaw_response:
        openclaw_response = "（OpenClaw 未返回内容）"

    # 向前端推送 OpenClaw 原始结果（仅显示，不 TTS）
    await manager.send_personal_message(
        {"type": "openclaw_message", "content": openclaw_response},
        websocket,
    )

    override_messages = build_openclaw_notify_messages(user_text, openclaw_response)

    await manager.send_personal_message(
        {"type": "llm_thinking"},
        websocket,
    )

    # LLM 生成通知文本 + TTS 播放（使用 override_messages，不改 history）
    await pipeline_llm_tts(history, websocket, override_messages=override_messages)

    # 将对话写入 history：用户原文 + AI 通知（此步骤由 pipeline_llm_tts 末尾写入 assistant 部分）
    # 这里我们只写用户消息（assistant 已由 pipeline_llm_tts 写入）


def get_asr_service():
    """Get ASR service instance"""
    return asr_service


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket chat endpoint - Streaming + Buffer complete loop

    Flow: User audio stream -> VAD buffer -> Detect complete speech -> ASR -> LLM -> TTS -> Return audio

    Supported message types:
    - text: text message
    - audio_start: start sending audio stream
    - audio: audio data chunk (continuous)
    - audio_end: end sending audio stream

    Streaming ASR extra support:
    - asr_partial: partial recognition result (real-time)
    - asr_final: final recognition result
    """
    await manager.connect(websocket)
    conversation_history = []

    # Get ASR service
    asr_service_instance = get_asr_service()

    # 双向流式 ASR 状态（每次 audio_start 重置）
    _active_asr_session = None
    _asr_final_event = asyncio.Event()
    _asr_final_text: List[str] = [""]    # mutable ref
    _asr_partial_text: List[str] = [""]  # mutable ref

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()

            message_type = data.get("type")
            content = data.get("content", "")

            if message_type == "text":
                # Text message handling
                await handle_text_message(content, conversation_history, websocket)

            elif message_type == "audio_start":
                # 重置 ASR 状态
                _asr_final_event.clear()
                _asr_final_text[0] = ""
                _asr_partial_text[0] = ""
                # 关闭上次遗留的 ASR 会话
                if _active_asr_session is not None:
                    try:
                        await _active_asr_session.close()
                    except Exception:
                        pass
                    _active_asr_session = None

                # 构建 ASR 回调
                from backend.services.asr_base import ASRStreamCallback as _ASRCb

                _cb = _ASRCb()

                def _make_partial_sender(_ws):
                    def _handler(text):
                        _asr_partial_text[0] = text
                        asyncio.get_event_loop().create_task(
                            manager.send_personal_message(
                                {"type": "asr_partial", "content": text}, _ws
                            )
                        )
                    return _handler

                _cb.on_partial_result = _make_partial_sender(websocket)

                def _on_definite(text):
                    _asr_partial_text[0] = text
                    asyncio.get_event_loop().create_task(
                        manager.send_personal_message(
                            {"type": "asr_partial", "content": text}, websocket
                        )
                    )

                _cb.on_definite_sentence = _on_definite

                def _on_final(text):
                    _asr_final_text[0] = text
                    _asr_final_event.set()

                _cb.on_final_result = _on_final

                # 创建并启动 ASR 会话（bigmodel_async 双向流式）
                try:
                    _active_asr_session = await asr_service_instance.create_session(
                        session_id=str(uuid.uuid4()),
                        language="zh",
                        callback=_cb,
                    )
                    await _active_asr_session.start()
                except Exception as _e:
                    import traceback; traceback.print_exc()
                    _active_asr_session = None

                await manager.send_personal_message(
                    {"type": "status", "message": "Recording..."},
                    websocket,
                )

            elif message_type == "audio":
                # 将音频小块实时转发给 ASR WebSocket 会话（无人工延迟）
                if _active_asr_session is not None:
                    try:
                        chunk_bytes = base64.b64decode(content)
                        arr, sr = sf.read(io.BytesIO(chunk_bytes), dtype='float32')
                        if arr.ndim > 1:
                            arr = arr.mean(axis=1)
                        # 重采样到 16kHz
                        if sr != 16000:
                            try:
                                from scipy.signal import resample_poly
                                from math import gcd as _gcd
                                _g = _gcd(int(sr), 16000)
                                arr = resample_poly(arr, 16000 // _g, int(sr) // _g).astype(np.float32)
                            except ImportError:
                                _new_len = int(len(arr) * 16000 / sr)
                                arr = np.interp(np.linspace(0, len(arr) - 1, _new_len), np.arange(len(arr)), arr).astype(np.float32)
                        # 转为 PCM int16 字节
                        pcm_bytes = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                        await _active_asr_session.send_audio_chunk_raw(pcm_bytes)
                    except Exception as _e:
                        import traceback; traceback.print_exc()

            elif message_type == "audio_end":
                if _active_asr_session is None:
                    await manager.send_personal_message(
                        {"type": "status", "message": "No audio session"},
                        websocket,
                    )
                else:
                    transcribed_text = ""
                    try:
                        # 发送流结束包（负序列号信号）
                        await _active_asr_session.send_audio_chunk_raw(b"", is_last=True)
                        # 等待 ASR 最终结果（最多 10 秒）
                        try:
                            await asyncio.wait_for(_asr_final_event.wait(), timeout=10.0)
                            transcribed_text = _asr_final_text[0]
                        except asyncio.TimeoutError:
                            # 超时兜底：使用最后的部分识别结果
                            transcribed_text = _asr_partial_text[0]
                    except Exception as _e:
                        import traceback; traceback.print_exc()
                        transcribed_text = _asr_partial_text[0]
                    finally:
                        try:
                            await _active_asr_session.close()
                        except Exception:
                            pass
                        _active_asr_session = None

                    if not transcribed_text or not transcribed_text.strip():
                        await manager.send_personal_message(
                            {"type": "status", "message": "No text recognized"},
                            websocket,
                        )
                    else:
                        # 通知前端 ASR 完成
                        await manager.send_personal_message(
                            {"type": "asr_complete", "content": transcribed_text},
                            websocket,
                        )
                        conversation_history.append({"role": "user", "content": transcribed_text})
                        if config_manager.is_openclaw_enabled():
                            await route_user_message(transcribed_text, conversation_history, websocket)
                        else:
                            await manager.send_personal_message(
                                {"type": "llm_thinking"},
                                websocket,
                            )
                            await pipeline_llm_tts(conversation_history, websocket)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        await manager.send_personal_message(
            {"type": "error", "message": str(e)},
            websocket,
        )
        manager.disconnect(websocket)


# =============================================================================
# 端到端实时语音 WebSocket 端点 (VOICE_MODE=realtime_volc)
# 火山端到端模型自带 ASR，不需要单独的 ASR 服务
# =============================================================================

class RealtimeVolcCallback:
    """VolcRealtimeSession 回调，将事件转发到前端 WebSocket"""

    def __init__(self, websocket: WebSocket, session_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self.dialog_id = None

    def on_session_started(self, data: dict):
        self.dialog_id = data.get("dialog_id")
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "realtime_session_started", "dialog_id": self.dialog_id},
                self.websocket,
            )
        )

    def on_asr_response(self, text: str, is_interim: bool = False):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "asr_partial", "content": text, "is_interim": is_interim},
                self.websocket,
            )
        )

    def on_asr_ended(self):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "asr_complete"},
                self.websocket,
            )
        )

    def on_tts_response(self, audio_bytes: bytes):
        # 发送 TTS 音频 (base64 编码)
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "tts_audio", "audio": base64.b64encode(audio_bytes).decode("utf-8")},
                self.websocket,
            )
        )

    def on_tts_sentence_start(self, data: dict):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "tts_sentence_start", "data": data},
                self.websocket,
            )
        )

    def on_tts_sentence_end(self, data: dict):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "tts_sentence_end", "data": data},
                self.websocket,
            )
        )

    def on_tts_ended(self, data: dict):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "tts_complete", "data": data},
                self.websocket,
            )
        )

    def on_chat_response(self, data: dict):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "chat_response", "data": data},
                self.websocket,
            )
        )

    def on_chat_ended(self, data: dict):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "chat_complete", "data": data},
                self.websocket,
            )
        )

    def on_session_finished(self):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "realtime_session_finished"},
                self.websocket,
            )
        )

    def on_session_failed(self, error_message: str):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "error", "message": f"Session failed: {error_message}"},
                self.websocket,
            )
        )

    def on_error(self, exc: Exception):
        asyncio.get_event_loop().create_task(
            manager.send_personal_message(
                {"type": "error", "message": str(exc)},
                self.websocket,
            )
        )

    def on_close(self):
        pass


@router.websocket("/ws/realtime_volc")
async def websocket_realtime_volc(websocket: WebSocket):
    """
    WebSocket 端点 - 火山端到端实时语音模式

    端到端语音到语音对话，模型自带 ASR，不需要单独的 ASR 服务。
    Flow:
    1. audio_start -> 创建 VolcRealtimeSession
    2. audio -> 流式发送音频到服务端
    3. audio_end -> 发送 END_ASR，服务端开始处理
    4. 接收 TTS 音频流和 ASR 识别结果
    """
    import gzip

    await manager.connect(websocket)

    # 会话状态
    active_session = None
    session_id = str(uuid.uuid4())
    audio_ended_sent = False

    try:
        while True:
            data = await websocket.receive_json()
            message_type = data.get("type")
            content = data.get("content", "")

            if message_type == "audio_start":
                # 创建端到端实时语音会话
                from backend.services.realtime_service import create_realtime_service

                service = create_realtime_service("realtime_volc")
                callback = RealtimeVolcCallback(websocket, session_id)

                try:
                    active_session = await service.create_session(
                        session_id=session_id,
                        callback=callback,
                    )
                    await manager.send_personal_message(
                        {"type": "status", "message": "Recording..."},
                        websocket,
                    )
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    await manager.send_personal_message(
                        {"type": "error", "message": f"Failed to start session: {e}"},
                        websocket,
                    )

            elif message_type == "audio":
                # 流式发送音频数据
                if active_session is None:
                    continue

                try:
                    chunk_bytes = base64.b64decode(content)
                    arr, sr = sf.read(io.BytesIO(chunk_bytes), dtype='float32')
                    if arr.ndim > 1:
                        arr = arr.mean(axis=1)

                    # 重采样到 16kHz
                    if sr != 16000:
                        from scipy.signal import resample_poly
                        from math import gcd as _gcd
                        _g = _gcd(int(sr), 16000)
                        arr = resample_poly(arr, 16000 // _g, int(sr) // _g).astype(np.float32)

                    # 转为 PCM int16 字节
                    pcm_bytes = (np.clip(arr, -1.0, 1.0) * 32767).astype(np.int16).tobytes()

                    # 使用 session.send_audio() 发送音频
                    await active_session.send_audio(pcm_bytes)

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    await manager.send_personal_message(
                        {"type": "error", "message": f"Audio send error: {e}"},
                        websocket,
                    )

            elif message_type == "audio_end":
                # 全双工模式：不发送 END_ASR，只记录状态
                # (服务端根据音频流自动检测说话结束)
                audio_ended_sent = True

            elif message_type == "audio_stop":
                # 用户主动停止发送音频，但保持会话存活
                # (用于 full-duplex 模式下暂停音频输入)
                if active_session is None:
                    continue
                audio_ended_sent = True

            elif message_type == "text":
                # 文本消息（text 模式）
                if active_session is None:
                    continue

                try:
                    await active_session.send_text(content)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    await manager.send_personal_message(
                        {"type": "error", "message": f"Text send error: {e}"},
                        websocket,
                    )

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await manager.send_personal_message(
            {"type": "error", "message": str(e)},
            websocket,
        )
        manager.disconnect(websocket)
    finally:
        if active_session is not None:
            try:
                await active_session.finish_session()
            except Exception:
                pass
            try:
                await active_session.close()
            except Exception:
                pass


async def handle_text_message(text: str, history: list, websocket: WebSocket):
    """Handle text message"""
    # Add user message to history
    history.append({"role": "user", "content": text})

    try:
        if config_manager.is_openclaw_enabled():
            await route_user_message(text, history, websocket)
        else:
            await manager.send_personal_message(
                {"type": "llm_thinking"},
                websocket,
            )
            await pipeline_llm_tts(history, websocket)
    except Exception as e:
        import traceback
        traceback.print_exc()
        await manager.send_personal_message(
            {"type": "error", "message": f"Processing error: {str(e)}"},
            websocket,
        )


async def handle_audio_stream_chunk(audio_chunk_base64: str, history: list, websocket: WebSocket):
    """
    Handle streaming audio chunk

    Flow:
    1. Decode audio chunk
    2. Pass to VAD
    3. VAD detects complete speech -> ASR -> LLM -> TTS loop
    """
    try:
        # Decode base64 audio data
        audio_chunk = base64.b64decode(audio_chunk_base64)

        # Read audio
        audio_chunk_io = io.BytesIO(audio_chunk)
        audio_array, sr = sf.read(audio_chunk_io, dtype='float32')

        # Convert stereo to mono if needed
        if len(audio_array.shape) > 1:
            audio_array = audio_array.mean(axis=1)

        import sys as _sys
        _sys.stderr.write(f"[DEBUG audio_chunk] sr={sr} samples={len(audio_array)} duration={len(audio_array)/sr:.2f}s\n")
        _sys.stderr.flush()

        # Pass to VAD for processing
        complete_speech = vad_service.process_stream_chunk(audio_array, sr)

        # If VAD detects complete speech segment
        # NOTE: complete_speech is already resampled to vad_service.sample_rate (16000)
        if complete_speech is not None:
            print("VAD detected complete speech mid-stream, processing...")
            await process_complete_speech(complete_speech, vad_service.sample_rate, history, websocket)

    except Exception as e:
        import traceback
        traceback.print_exc()
        await manager.send_personal_message(
            {"type": "error", "message": f"Audio stream error: {str(e)}"},
            websocket,
        )


async def handle_audio_stream_chunk_streaming(audio_chunk_base64: str, history: list, websocket: WebSocket):
    """
    Handle streaming audio chunk (with streaming ASR)

    Flow:
    1. Decode audio chunk
    2. Pass to VAD (with streaming ASR)
    3. VAD detects complete speech -> ASR -> LLM -> TTS loop
    """
    try:
        # Decode base64 audio data
        audio_chunk = base64.b64decode(audio_chunk_base64)

        # Read audio
        audio_chunk_io = io.BytesIO(audio_chunk)
        audio_array, sr = sf.read(audio_chunk_io, dtype='float32')

        # Convert stereo to mono if needed
        if len(audio_array.shape) > 1:
            audio_array = audio_array.mean(axis=1)

        # Pass to VAD for streaming (with streaming ASR)
        complete_speech = await vad_service.process_stream_chunk_with_streaming_asr(
            audio_array, sr
        )

        # If VAD detects complete speech segment
        if complete_speech is not None:
            print("VAD detected complete speech, processing...")
            await process_complete_speech(complete_speech, sr, history, websocket)

    except Exception as e:
        import traceback
        traceback.print_exc()
        await manager.send_personal_message(
            {"type": "error", "message": f"Audio stream error: {str(e)}"},
            websocket,
        )


async def handle_audio_stream_end(history: list, websocket: WebSocket):
    """
    Handle audio stream end

    Process remaining audio in VAD buffer
    """
    try:
        # Flush VAD buffer
        remaining_speech = vad_service.flush_buffer()

        import sys as _sys
        _sys.stderr.write(f"[DEBUG audio_end] flush_buffer returned: {None if remaining_speech is None else len(remaining_speech)} samples, "
              f"vad buffer_before_flush was {'non-empty' if remaining_speech is not None else 'empty'}\n")
        _sys.stderr.flush()

        if remaining_speech is not None and len(remaining_speech) > 0:
            _sys.stderr.write(f"[DEBUG audio_end] sending {len(remaining_speech)} samples at {vad_service.sample_rate}Hz to ASR\n")
            _sys.stderr.flush()
            await process_complete_speech(remaining_speech, vad_service.sample_rate, history, websocket)
        else:
            _sys.stderr.write("[DEBUG audio_end] No audio to process (buffer was empty)\n")
            _sys.stderr.flush()
            await manager.send_personal_message(
                {"type": "status", "message": "No text recognized"},
                websocket,
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        await manager.send_personal_message(
            {"type": "error", "message": f"Audio stream end error: {str(e)}"},
            websocket,
        )


async def handle_audio_stream_end_streaming(history: list, websocket: WebSocket):
    """
    Handle audio stream end (with streaming ASR)

    Process remaining audio in VAD buffer
    """
    try:
        # End streaming ASR and get final result
        await vad_service._end_streaming_asr()

        # Flush VAD buffer
        remaining_speech = vad_service.flush_buffer()

        if remaining_speech is not None and len(remaining_speech) > 0:
            print("Processing remaining audio in buffer...")
            await process_complete_speech(remaining_speech, vad_service.sample_rate, history, websocket)

    except Exception as e:
        import traceback
        traceback.print_exc()
        await manager.send_personal_message(
            {"type": "error", "message": f"Audio stream end error: {str(e)}"},
            websocket,
        )


async def process_complete_speech(audio_array: np.ndarray, sample_rate: int, history: list, websocket: WebSocket):
    """
    Process complete speech segment

    Flow: ASR -> LLM -> TTS -> Return audio
    """
    try:
        # 1. ASR recognition
        await manager.send_personal_message(
            {"type": "status", "message": "Recognizing speech..."},
            websocket,
        )

        # DEBUG: log audio stats + save WAV for inspection
        import sys as _sys
        duration_s = len(audio_array) / sample_rate
        rms = float(np.sqrt(np.mean(audio_array ** 2)))
        _sys.stderr.write(f"[DEBUG process_complete_speech] samples={len(audio_array)} sr={sample_rate} "
              f"duration={duration_s:.2f}s rms={rms:.5f} min={audio_array.min():.4f} max={audio_array.max():.4f}\n")
        import os, time as _time
        debug_path = f"logs/debug_audio_{int(_time.time())}.wav"
        sf.write(debug_path, audio_array, sample_rate)
        _sys.stderr.write(f"[DEBUG] Saved debug WAV: {debug_path}\n")
        _sys.stderr.flush()

        # Normalize audio amplitude to target RMS (safeguard for quiet mic input)
        target_rms = 0.1
        if rms > 1e-9:  # only normalize if there's any signal at all
            gain = target_rms / rms
            # Clamp gain to prevent extreme amplification of background noise
            gain = min(gain, 50.0)
            audio_array = audio_array * gain
            # Clip to [-1, 1] to avoid WAV overflow
            audio_array = np.clip(audio_array, -1.0, 1.0)
            _sys.stderr.write(f"[DEBUG] Normalized audio: gain={gain:.1f}x → new rms={float(np.sqrt(np.mean(audio_array**2))):.5f}\n")
            _sys.stderr.flush()

        # Re-encode audio
        audio_bytes_io = io.BytesIO()
        sf.write(audio_bytes_io, audio_array, sample_rate, format='WAV')
        audio_bytes_io.seek(0)
        audio_bytes = audio_bytes_io.read()

        _sys.stderr.write(f"[DEBUG process_complete_speech] WAV bytes={len(audio_bytes)} sending to ASR...\n")
        _sys.stderr.flush()

        # Recognize audio
        transcribed_text = await asr_service.transcribe_file(audio_bytes, language="zh")

        _sys.stderr.write(f"[DEBUG process_complete_speech] ASR result: '{transcribed_text}'\n")
        _sys.stderr.flush()

        if not transcribed_text:
            await manager.send_personal_message(
                {"type": "status", "message": "No text recognized"},
                websocket,
            )
            return

        # Send ASR result
        await manager.send_personal_message(
            {"type": "asr_complete", "content": transcribed_text},
            websocket,
        )

        # Add user message to history
        history.append({"role": "user", "content": transcribed_text})

        if config_manager.is_openclaw_enabled():
            await route_user_message(transcribed_text, history, websocket)
        else:
            await manager.send_personal_message(
                {"type": "llm_thinking"},
                websocket,
            )
            await pipeline_llm_tts(history, websocket)

    except Exception as e:
        import traceback
        traceback.print_exc()
        await manager.send_personal_message(
            {"type": "error", "message": f"Speech processing error: {str(e)}"},
            websocket,
        )
